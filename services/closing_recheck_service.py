from __future__ import annotations

import copy
import json
import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:  # pragma: no cover - optional dependency
    genai = None
    genai_types = None

from schemas.closing_recheck_schema import ClosingRecheckModelOutput, ClosingRecheckResult
from services.closing_recheck_prompt_builder import build_closing_recheck_prompt
from services.closing_recheck_repository import (
    compute_prompt_hash,
    get_closing_recheck_by_market_and_latest_analysis,
    get_closing_recheck_by_prompt_hash_for_market,
    get_recent_closing_recheck_for_market,
    save_closing_recheck_result,
)
from services.closing_recheck_candidate_normalizer import (
    normalize_closing_recheck_candidate,
)
from services.closing_recheck_scoring import (
    build_current_market_for_scoring,
    calculate_current_hybrid_score,
    calculate_current_preliminary_score,
)
from services.deepbrief_generator import (
    SYSTEM_INSTRUCTION,
    ProviderGenerationError,
    build_groq_response_schema,
    get_provider_model,
    get_provider_sequence,
    is_provider_configured,
    load_json_repair_prompt,
    summarize_exception,
)
from services.logger_service import get_logger
from services.market_filter import get_market_open_status
from services.scoring_service import days_to_close
from services.scoring_service import get_signal_label_for_final_score, safe_float


load_dotenv()

logger = get_logger("closing_recheck_service")


class ClosingRecheckQuotaExceeded(RuntimeError):
    pass


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_market(market: Any) -> dict[str, Any]:
    if not isinstance(market, dict):
        return {}

    closing_time = _coalesce(
        market.get("closingTime"),
        market.get("closing_time"),
        market.get("closeDate"),
        market.get("close_date"),
        market.get("endDate"),
        market.get("end_date"),
        market.get("endDateIso"),
        market.get("end_date_iso"),
    )

    normalized = {
        **market,
        "marketId": _coalesce(
            market.get("marketId"),
            market.get("market_id"),
            market.get("id"),
        ),
        "title": _clean_text(market.get("title")),
        "category": _clean_text(market.get("category")),
        "closingTime": _clean_text(closing_time),
        "close_date": _clean_text(closing_time),
        "closeDate": _clean_text(closing_time),
        "daysToClose": _as_int(
            _coalesce(market.get("daysToClose"), market.get("days_to_close"))
        ),
        "closingLabel": _clean_text(
            _coalesce(market.get("closingLabel"), market.get("closing_label"))
        ),
        "current_probability": _as_float(
            _coalesce(
                market.get("current_probability"),
                market.get("currentProbability"),
                market.get("probability"),
            )
        ),
        "previous_probability_24h": _as_float(
            _coalesce(
                market.get("previous_probability_24h"),
                market.get("previousProbability24h"),
            )
        ),
        "probability_change_24h": _as_float(
            _coalesce(
                market.get("probability_change_24h"),
                market.get("probabilityChange24h"),
            )
        ),
        "volume": _as_float(market.get("volume")),
        "liquidity": _as_float(market.get("liquidity")),
    }

    if normalized["daysToClose"] is None and normalized["closingTime"]:
        normalized["daysToClose"] = days_to_close(normalized)

    if not normalized["closingLabel"] and normalized["daysToClose"] is not None:
        normalized["closingLabel"] = f"{normalized['daysToClose']}d"

    return normalized


def _normalize_analysis(analysis: Any) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}

    return {
        **analysis,
        "analysisId": _coalesce(
            analysis.get("analysisId"),
            analysis.get("analysis_id"),
            analysis.get("id"),
        ),
        "generatedAt": _coalesce(
            analysis.get("generatedAt"),
            analysis.get("generated_at"),
            analysis.get("createdAt"),
            analysis.get("created_at"),
        ),
        "thesis": _clean_text(analysis.get("thesis")),
        "signalLabel": _clean_text(
            _coalesce(analysis.get("signalLabel"), analysis.get("signal_label"))
        ),
        "radarScore": _as_float(
            _coalesce(
                analysis.get("radarScore"),
                analysis.get("finalRadarScore"),
                analysis.get("radar_score"),
            )
        ),
        "probability": _as_float(
            _coalesce(
                analysis.get("probability"),
                analysis.get("current_probability"),
                analysis.get("predictedProbability"),
            )
        ),
    }


def _normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return normalize_closing_recheck_candidate(candidate)


def _build_deltas(candidate: dict[str, Any]) -> dict[str, Any]:
    deltas = dict(candidate.get("deltas") or {})

    previous_analysis = candidate.get("previousAnalysis") or {}
    latest_analysis = candidate.get("latestAnalysis") or {}

    if "probabilityChangeSincePreviousAnalysis" not in deltas:
        previous_probability = _as_float(previous_analysis.get("probability"))
        latest_probability = _as_float(latest_analysis.get("probability"))
        if previous_probability is not None and latest_probability is not None:
            deltas["probabilityChangeSincePreviousAnalysis"] = (
                latest_probability - previous_probability
            )

    if "radarScoreChangeSincePreviousAnalysis" not in deltas:
        previous_score = _as_float(previous_analysis.get("radarScore"))
        latest_score = _as_float(latest_analysis.get("radarScore"))
        if previous_score is not None and latest_score is not None:
            deltas["radarScoreChangeSincePreviousAnalysis"] = latest_score - previous_score

    if "probabilityChange24h" not in deltas:
        market = candidate.get("market") or {}
        if market:
            probability_change = _as_float(market.get("probability_change_24h"))
            if probability_change is not None:
                deltas["probabilityChange24h"] = probability_change

    return deltas


def _build_market_snapshot(candidate: dict[str, Any]) -> dict[str, Any]:
    market = dict(candidate.get("market") or {})
    market_snapshot = dict(candidate.get("marketSnapshot") or {})

    if not market_snapshot:
        market_snapshot = dict(market)

    market_snapshot.setdefault("marketId", candidate.get("marketId"))
    market_snapshot.setdefault("title", market.get("title"))
    market_snapshot.setdefault("category", market.get("category"))
    market_snapshot.setdefault("closingTime", market.get("closingTime"))
    market_snapshot.setdefault("closingLabel", market.get("closingLabel"))
    market_snapshot.setdefault("daysToClose", market.get("daysToClose"))
    market_snapshot.setdefault(
        "current_probability",
        market.get("current_probability")
        if market.get("current_probability") is not None
        else candidate.get("latestAnalysis", {}).get("probability"),
    )
    market_snapshot.setdefault(
        "previous_probability_24h",
        market.get("previous_probability_24h"),
    )
    market_snapshot.setdefault(
        "probability_change_24h",
        market.get("probability_change_24h"),
    )
    market_snapshot.setdefault("volume", market.get("volume"))
    market_snapshot.setdefault("liquidity", market.get("liquidity"))
    market_snapshot.setdefault("outcomes", market.get("outcomes"))

    return market_snapshot


def _build_recheck_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    recheck_candidate = dict(candidate.get("recheckCandidate") or {})

    if not recheck_candidate:
        recheck_candidate = {
            "recheckStatus": candidate.get("recheckStatus"),
            "recheckPriority": candidate.get("recheckPriority"),
            "recheckScore": candidate.get("recheckScore"),
        }

    recheck_candidate.setdefault("recheckStatus", candidate.get("recheckStatus"))
    recheck_candidate.setdefault("recheckPriority", candidate.get("recheckPriority"))
    recheck_candidate.setdefault("recheckScore", candidate.get("recheckScore"))

    return recheck_candidate


def _build_prompt_inputs(candidate: dict[str, Any]) -> dict[str, Any]:
    market = candidate.get("market") or {}
    market_current = candidate.get("marketCurrent") or {}
    previous_analysis = candidate.get("previousAnalysis") or {}
    latest_analysis = candidate.get("latestAnalysis") or {}

    return {
        "market": market,
        "market_current": market_current,
        "previous_analysis": previous_analysis,
        "latest_analysis": latest_analysis,
        "deltas": _build_deltas(candidate),
        "recheck_candidate": _build_recheck_candidate(candidate),
        "capital_trail": candidate.get("capitalTrail"),
        "market_snapshot": _build_market_snapshot(candidate),
    }


def _probability_scale_status(candidate: dict[str, Any]) -> str:
    market_current = candidate.get("marketCurrent") or {}
    market_snapshot = candidate.get("marketSnapshot") or {}
    market = candidate.get("market") or {}
    for source in (market_current, market_snapshot, market):
        if not isinstance(source, dict):
            continue
        scale = source.get("probabilityScale")
        if scale:
            return str(scale)
    return "unknown"


def _current_market_source_label(candidate: dict[str, Any]) -> str:
    market_current = candidate.get("marketCurrent")
    if isinstance(market_current, dict) and market_current:
        freshness = market_current.get("freshness") or {}
        status = freshness.get("status") if isinstance(freshness, dict) else None
        if status:
            return str(status)
        return "current"

    market_snapshot = candidate.get("marketSnapshot")
    if isinstance(market_snapshot, dict) and market_snapshot:
        return "historical_fallback"

    return "unknown"


def _normalize_importance(value: Any, confidence: int | None) -> str:
    normalized = str(value or "").strip().upper()
    if normalized in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        return normalized

    if confidence is None:
        return "LOW"
    return "LOW" if confidence < 50 else "MEDIUM"


def _fetch_updated_context(candidate: dict[str, Any], market_current: dict[str, Any]) -> tuple[list[dict[str, Any]], str]:
    market_id = candidate.get("marketId") or (candidate.get("marketCurrent") or {}).get("marketId")
    if market_id:
        try:
            from services.context_client import search_context

            sources = search_context(
                market={
                    **market_current,
                    "id": market_id,
                },
                max_results=3,
            )
            if sources:
                return sources, "fresh_context"
        except Exception as error:
            logger.warning("Could not fetch fresh context | marketId=%s | error=%s", market_id, error)

    latest_analysis = candidate.get("latestAnalysis") or {}
    fallback_sources = latest_analysis.get("contextSources")
    if isinstance(fallback_sources, list) and fallback_sources:
        return fallback_sources, "latest_analysis_context_fallback"

    return [], "no_context"


def _build_score_parity(
    *,
    baseline_analysis: dict[str, Any],
    previous_analysis: dict[str, Any],
    previous_preliminary: float | None,
    new_preliminary: float | None,
    previous_ai: float | None,
    new_ai: float | None,
    previous_final: float | None,
    new_final: float | None,
    previous_breakdown: dict[str, Any] | None,
    new_breakdown: dict[str, Any] | None,
    hybrid_breakdown: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "formula": "final_radar_score = 0.40 preliminary_radar_score + 0.60 ai_interpretive_score",
        "baselineAnalysisId": baseline_analysis.get("analysisId"),
        "previousPreliminaryRadarScore": previous_preliminary,
        "newPreliminaryRadarScore": new_preliminary,
        "preliminaryRadarScoreDelta": None if previous_preliminary is None or new_preliminary is None else new_preliminary - previous_preliminary,
        "previousAiInterpretiveScore": previous_ai,
        "newAiInterpretiveScore": new_ai,
        "aiInterpretiveScoreDelta": None if previous_ai is None or new_ai is None else new_ai - previous_ai,
        "previousFinalRadarScore": previous_final,
        "newFinalRadarScore": new_final,
        "finalRadarScoreDelta": None if previous_final is None or new_final is None else new_final - previous_final,
        "previousScoreBreakdown": previous_breakdown,
        "newScoreBreakdown": new_breakdown,
        "hybridScoreBreakdown": hybrid_breakdown,
    }


def _score_change_magnitude(delta: float | None) -> str:
    if delta is None:
        return "LOW"
    magnitude = abs(delta)
    if magnitude >= 20:
        return "CRITICAL"
    if magnitude >= 10:
        return "HIGH"
    if magnitude >= 5:
        return "MEDIUM"
    return "LOW"


def _score_direction(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "UNCHANGED"
    return "UP" if delta > 0 else "DOWN"


def _validate_candidate(candidate: dict[str, Any]) -> None:
    required_keys = [
        "marketId",
        "previousAnalysisId",
        "latestAnalysisId",
    ]
    missing = [key for key in required_keys if not candidate.get(key)]
    if missing:
        raise ValueError("Candidate missing required fields: " + ", ".join(missing))

    if candidate["previousAnalysisId"] == candidate["latestAnalysisId"]:
        raise ValueError("previousAnalysisId and latestAnalysisId must be different")

    market = candidate.get("market") or {}
    previous_analysis = candidate.get("previousAnalysis") or {}
    latest_analysis = candidate.get("latestAnalysis") or {}

    if not market.get("title"):
        raise ValueError("Candidate missing market title")
    if not previous_analysis.get("analysisId"):
        raise ValueError("Candidate missing previous analysis")
    if not latest_analysis.get("analysisId"):
        raise ValueError("Candidate missing latest analysis")

    if not previous_analysis.get("thesis"):
        raise ValueError("Candidate missing previous thesis")
    if not latest_analysis.get("thesis"):
        raise ValueError("Candidate missing latest thesis")

    if market.get("closingTime") is None and market.get("daysToClose") is None:
        raise ValueError("Candidate missing closing context")


def _is_rate_limit_error(error: Exception) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code == 429:
        return True

    response = getattr(error, "response", None)
    if getattr(response, "status_code", None) == 429:
        return True

    message = summarize_exception(error).lower()
    markers = (
        "429",
        "rate limit",
        "too many requests",
        "insufficient_quota",
        "quota",
        "resource_exhausted",
    )
    return any(marker in message for marker in markers)


def _is_rate_limit_message(message: str) -> bool:
    normalized = message.lower()
    markers = (
        "429",
        "rate limit",
        "too many requests",
        "insufficient_quota",
        "quota",
        "resource_exhausted",
    )
    return any(marker in normalized for marker in markers)


def _provider_error_is_quota_related(error: ProviderGenerationError) -> bool:
    if _is_rate_limit_message(error.message):
        return True

    for attempt in error.attempts:
        if _is_rate_limit_message(str(attempt.get("error", ""))):
            return True

    return False


def classify_closing_recheck_provider_errors(provider_errors: list[str]) -> str:
    normalized = [str(item).lower() for item in provider_errors if item]
    if not normalized:
        return "all_providers_failed"

    quota_count = sum(
        1
        for item in normalized
        if "quota" in item or "insufficient_quota" in item or "rate limit" in item or "too many requests" in item
    )
    schema_count = sum(
        1
        for item in normalized
        if "schema" in item or "additional_properties" in item or "invalid_argument" in item
    )
    auth_count = sum(
        1
        for item in normalized
        if "auth" in item or "unauthorized" in item or "api key" in item or "permission" in item
    )
    transient_count = sum(
        1
        for item in normalized
        if "timeout" in item or "network" in item or "connection" in item or "temporary" in item
    )

    if quota_count and quota_count == len(normalized):
        return "all_providers_quota_exhausted"
    if schema_count:
        return "provider_schema_error"
    if auth_count:
        return "provider_auth_error"
    if transient_count:
        return "provider_transient_error"
    return "all_providers_failed"


def _is_json_repair_needed(error: Exception) -> bool:
    message = summarize_exception(error).lower()
    return "json" in message or "schema" in message or "parse" in message


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def build_gemini_response_schema(model_type: type[Any]) -> dict[str, Any]:
    schema = copy.deepcopy(model_type.model_json_schema(mode="validation"))

    def _clean(node: Any) -> Any:
        if isinstance(node, dict):
            cleaned: dict[str, Any] = {}
            for key, value in node.items():
                if key in {"additionalProperties", "additional_properties", "title", "default", "examples", "unevaluatedProperties"}:
                    continue
                if key == "propertyOrdering":
                    continue
                if key == "$defs":
                    cleaned[key] = {name: _clean(definition) for name, definition in value.items()}
                    continue
                if key == "$ref":
                    cleaned[key] = value
                    continue
                cleaned[key] = _clean(value)
            return cleaned
        if isinstance(node, list):
            return [_clean(item) for item in node]
        return node

    return _clean(schema)


def _is_gemini_schema_compatibility_error(error: Exception) -> bool:
    message = summarize_exception(error).lower()
    markers = (
        "invalid_argument",
        "unknown name",
        "additional_properties",
        "additionalproperties",
        "response_schema",
        "schema",
    )
    return any(marker in message for marker in markers)


def _classify_provider_error(error: Exception) -> str:
    status_code = getattr(error, "status_code", None) or getattr(
        getattr(error, "response", None),
        "status_code",
        None,
    )
    message = summarize_exception(error).lower()

    if status_code in {401, 403} or "unauthorized" in message or "api key" in message:
        return "provider_auth_error"
    if status_code == 429 or any(marker in message for marker in ("quota", "insufficient_quota", "rate limit", "too many requests", "resource_exhausted")):
        return "provider_quota_error" if "quota" in message or "insufficient_quota" in message or "resource_exhausted" in message else "provider_rate_limit"
    if status_code in {400, 422} or any(marker in message for marker in ("response_schema", "json_schema", "schema", "additional_properties", "additionalproperties", "invalid_argument")):
        return "provider_schema_error" if any(marker in message for marker in ("response_schema", "json_schema", "schema", "additional_properties", "additionalproperties", "invalid_argument")) else "provider_invalid_response"
    if status_code in {500, 502, 503, 504} or any(marker in message for marker in ("timeout", "network", "connection", "transient")):
        return "provider_timeout" if "timeout" in message else "provider_transient_error"
    if "json" in message and any(marker in message for marker in ("invalid", "parse", "decode")):
        return "provider_invalid_response"
    return "provider_transient_error"


def _build_model_prompt(
    candidate: dict[str, Any],
    *,
    new_preliminary: dict[str, Any],
    score_parity: dict[str, Any] | None = None,
    context_source: str | None = None,
    repair_note: str | None = None,
) -> tuple[str, str]:
    prompt_input = _build_prompt_inputs(candidate)
    prompt, prompt_source = build_closing_recheck_prompt(
        market_current=prompt_input["market_current"] or build_current_market_for_scoring(candidate),
        new_preliminary_radar_score=new_preliminary["preliminary_radar_score"],
        new_preliminary_score_breakdown=new_preliminary["score_breakdown"],
        previous_analysis=prompt_input["previous_analysis"],
        latest_analysis=prompt_input["latest_analysis"],
        deltas=prompt_input["deltas"],
        recheck_candidate=prompt_input["recheck_candidate"],
        capital_trail=prompt_input["capital_trail"],
        market_snapshot=prompt_input["market_snapshot"],
        score_parity=score_parity,
        context_source=context_source,
        repair_note=repair_note,
    )
    return prompt, prompt_source


def call_closing_recheck_model_with_provider_sequence(
    *,
    candidate: dict[str, Any],
    new_preliminary: dict[str, Any],
    score_parity: dict[str, Any] | None,
    context_source: str | None,
    max_retries: int,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    primary_provider, provider_sequence = get_provider_sequence()
    attempts: list[dict[str, Any]] = []
    provider_errors: list[str] = []
    quota_related_failures = 0
    attempted_providers = 0

    for index, provider in enumerate(provider_sequence):
        configured, reason = is_provider_configured(provider)
        is_fallback = index > 0
        provider_model = get_provider_model(provider)

        if not configured:
            provider_errors.append(f"{provider}: {reason}")
            continue

        attempted_providers += 1

        try:
            if provider == "gemini":
                deepbrief, raw_output = _call_gemini_model(
                    candidate=candidate,
                    new_preliminary=new_preliminary,
                    score_parity=score_parity,
                    context_source=context_source,
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    prior_attempts=attempts,
                )
            elif provider == "groq":
                deepbrief, raw_output = _call_groq_model(
                    candidate=candidate,
                    new_preliminary=new_preliminary,
                    score_parity=score_parity,
                    context_source=context_source,
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    prior_attempts=attempts,
                )
            else:
                deepbrief, raw_output = _call_openai_model(
                    candidate=candidate,
                    new_preliminary=new_preliminary,
                    score_parity=score_parity,
                    context_source=context_source,
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    prior_attempts=attempts,
                )

            return deepbrief, raw_output, provider, provider_model
        except ProviderGenerationError as error:
            attempts = list(error.attempts)
            provider_errors.append(f"{provider}: {error.message}")
            if _provider_error_is_quota_related(error):
                quota_related_failures += 1
        except Exception as error:
            provider_errors.append(f"{provider}: {summarize_exception(error)}")
            if _is_rate_limit_error(error):
                quota_related_failures += 1

    combined_error = " | ".join(provider_errors) or "No providers configured"
    if attempted_providers and quota_related_failures >= attempted_providers:
        raise ClosingRecheckQuotaExceeded(combined_error)

    raise RuntimeError(f"All providers failed: {combined_error}")


def _call_openai_model(
    *,
    candidate: dict[str, Any],
    new_preliminary: dict[str, Any],
    score_parity: dict[str, Any] | None,
    context_source: str | None,
    max_retries: int,
    primary_provider: str,
    fallback_used: bool,
    prior_attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = get_provider_model("openai")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    attempts = list(prior_attempts or [])
    last_error = None

    for attempt in range(1, max_retries + 2):
        repair_note = None
        if attempt > 1:
            repair_note = load_json_repair_prompt()
            if last_error:
                repair_note += f"\n\nError anterior:\n{last_error}"

        prompt, prompt_source = _build_model_prompt(
            candidate,
            new_preliminary=new_preliminary,
            score_parity=score_parity,
            context_source=context_source,
            repair_note=repair_note,
        )

        try:
            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                text_format=ClosingRecheckModelOutput,
            )

            parsed = response.output_parsed
            if parsed is None:
                raise RuntimeError("El modelo no devolvio un ClosingRecheckModelOutput valido")

            validated = ClosingRecheckModelOutput.model_validate(parsed.model_dump())
            attempts.append(
                {
                    "provider": "openai",
                    "attempt": attempt,
                    "status": "ok",
                    "model": model,
                }
            )

            raw_output = {
                "status": "ok",
                "provider": "openai",
                "model": model,
                "fallback_used": fallback_used,
                "primary_provider": primary_provider,
                "attempts": attempts,
                "prompt_source": prompt_source,
                "prompt": prompt,
                "parsed_output": validated.model_dump(),
                "response_id": getattr(response, "id", None),
            }

            return validated.model_dump(), raw_output
        except Exception as error:
            last_error = summarize_exception(error)
            attempts.append(
                {
                    "provider": "openai",
                    "attempt": attempt,
                    "status": "failed",
                    "model": model,
                    "error": last_error,
                }
            )

            if attempt >= max_retries + 1:
                raise ProviderGenerationError(
                    provider="openai",
                    model=model,
                    message=f"OpenAI failed after retries: {last_error}",
                    attempts=attempts,
                ) from error

    raise ProviderGenerationError(
        provider="openai",
        model=model,
        message="OpenAI failed unexpectedly",
        attempts=attempts,
    )


def _call_gemini_model(
    *,
    candidate: dict[str, Any],
    new_preliminary: dict[str, Any],
    score_parity: dict[str, Any] | None,
    context_source: str | None,
    max_retries: int,
    primary_provider: str,
    fallback_used: bool,
    prior_attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if genai is None or genai_types is None:  # pragma: no cover - optional dependency
        raise RuntimeError("SDK google-genai no instalado")

    model = get_provider_model("gemini")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    attempts = list(prior_attempts or [])
    last_error = None
    schema = build_gemini_response_schema(ClosingRecheckModelOutput)
    structured_schema_rejected = False

    for attempt in range(1, max_retries + 2):
        repair_note = None
        if attempt > 1:
            repair_note = load_json_repair_prompt()
            if last_error:
                repair_note += f"\n\nError anterior:\n{last_error}"

        prompt, prompt_source = _build_model_prompt(
            candidate,
            new_preliminary=new_preliminary,
            score_parity=score_parity,
            context_source=context_source,
            repair_note=repair_note,
        )

        try:
            config_kwargs: dict[str, Any] = {
                "system_instruction": SYSTEM_INSTRUCTION,
                "response_mime_type": "application/json",
            }
            if not structured_schema_rejected:
                config_kwargs["response_schema"] = schema

            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(**config_kwargs),
            )

            parsed_candidate = getattr(response, "parsed", None)
            if parsed_candidate is not None:
                if hasattr(parsed_candidate, "model_dump"):
                    payload = parsed_candidate.model_dump()
                else:
                    payload = parsed_candidate
            else:
                response_text = getattr(response, "text", None)
                if not response_text:
                    raise RuntimeError("Gemini no devolvio texto JSON")
                import json

                payload = json.loads(response_text)

            validated = ClosingRecheckModelOutput.model_validate(payload)
            attempts.append(
                {
                    "provider": "gemini",
                    "attempt": attempt,
                    "status": "ok",
                    "model": model,
                }
            )

            raw_output = {
                "status": "ok",
                "provider": "gemini",
                "model": model,
                "fallback_used": fallback_used,
                "primary_provider": primary_provider,
                "attempts": attempts,
                "prompt_source": prompt_source,
                "prompt": prompt,
                "parsed_output": validated.model_dump(),
                "response_id": getattr(response, "response_id", None),
            }

            return validated.model_dump(), raw_output
        except Exception as error:
            if not structured_schema_rejected and _is_gemini_schema_compatibility_error(error):
                structured_schema_rejected = True
                logger.warning(
                    "[CLOSING_RECHECK_GEMINI_SCHEMA] structured_schema_rejected=true retrying_without_response_schema=true"
                )
                continue

            last_error = summarize_exception(error)
            attempts.append(
                {
                    "provider": "gemini",
                    "attempt": attempt,
                    "status": "failed",
                    "model": model,
                    "error": last_error,
                }
            )

            if attempt >= max_retries + 1:
                raise ProviderGenerationError(
                    provider="gemini",
                    model=model,
                    message=f"Gemini failed after retries: {last_error}",
                    attempts=attempts,
                ) from error

    raise ProviderGenerationError(
        provider="gemini",
        model=model,
        message="Gemini failed unexpectedly",
        attempts=attempts,
    )


def _call_groq_model(
    *,
    candidate: dict[str, Any],
    new_preliminary: dict[str, Any],
    score_parity: dict[str, Any] | None,
    context_source: str | None,
    max_retries: int,
    primary_provider: str,
    fallback_used: bool,
    prior_attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = get_provider_model("groq")
    client = OpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    )
    attempts = list(prior_attempts or [])
    last_error: str | None = None
    schema = build_groq_response_schema(ClosingRecheckModelOutput)
    structured_schema_rejected = False

    for attempt in range(1, max_retries + 2):
        repair_note = None
        if attempt > 1:
            repair_note = load_json_repair_prompt()
            if last_error:
                repair_note += f"\n\nError anterior:\n{last_error}"

        prompt, prompt_source = _build_model_prompt(
            candidate,
            new_preliminary=new_preliminary,
            score_parity=score_parity,
            context_source=context_source,
            repair_note=repair_note,
        )

        try:
            config_kwargs: dict[str, Any] = {
                "response_mime_type": "application/json",
            }
            if not structured_schema_rejected:
                config_kwargs["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "closing_recheck",
                        "strict": False,
                        "schema": schema,
                        },
                    }
            else:
                config_kwargs["response_format"] = {"type": "json_object"}

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                extra_body={
                    "reasoning_effort": "low",
                    "include_reasoning": False,
                },
                **config_kwargs,
            )

            response_text = getattr(response.choices[0].message, "content", None)
            if not response_text:
                raise RuntimeError("Groq no devolvio contenido JSON")

            payload = json.loads(_strip_code_fences(response_text))
            validated = ClosingRecheckModelOutput.model_validate(payload)
            attempts.append(
                {
                    "provider": "groq",
                    "attempt": attempt,
                    "status": "ok",
                    "model": model,
                }
            )

            usage = getattr(response, "usage", None)
            raw_output = {
                "status": "ok",
                "provider": "groq",
                "model": model,
                "fallback_used": fallback_used,
                "primary_provider": primary_provider,
                "attempts": attempts,
                "prompt_source": prompt_source,
                "prompt": prompt,
                "parsed_output": validated.model_dump(),
                "response_id": getattr(response, "id", None),
                "usage": {
                    "input_tokens": getattr(usage, "prompt_tokens", None) if usage else None,
                    "output_tokens": getattr(usage, "completion_tokens", None) if usage else None,
                    "total_tokens": getattr(usage, "total_tokens", None) if usage else None,
                },
            }
            return validated.model_dump(), raw_output
        except Exception as error:
            if not structured_schema_rejected and _is_gemini_schema_compatibility_error(error):
                structured_schema_rejected = True
                logger.warning(
                    "[CLOSING_RECHECK_GROQ_SCHEMA] structured_schema_rejected=true retrying_without_response_schema=true"
                )
                continue

            last_error = summarize_exception(error)
            attempts.append(
                {
                    "provider": "groq",
                    "attempt": attempt,
                    "status": "failed",
                    "model": model,
                    "error": last_error,
                    "error_type": _classify_provider_error(error),
                }
            )

            if attempt >= max_retries + 1:
                raise ProviderGenerationError(
                    provider="groq",
                    model=model,
                    message=f"Groq failed after retries: {last_error}",
                    attempts=attempts,
                ) from error

    raise ProviderGenerationError(
        provider="groq",
        model=model,
        message="Groq failed unexpectedly",
        attempts=attempts,
    )


def _build_prompt_hash(prompt: str) -> str:
    return compute_prompt_hash(prompt)


def run_closing_recheck_for_candidate(
    candidate: dict[str, Any],
    *,
    freshness_hours: int = 12,
    max_retries: int = 2,
    source: str = "automatic_worker",
    persist: bool = True,
) -> dict[str, Any]:
    normalized = _normalize_candidate(candidate)
    _validate_candidate(normalized)

    market_id = normalized["marketId"]
    latest_analysis_id = normalized["latestAnalysisId"]
    current_market = build_current_market_for_scoring(normalized)
    probability_scale = _probability_scale_status(normalized)
    freshness_status = _current_market_source_label(normalized)
    logger.info(
        "[CLOSING_RECHECK_SCORING] marketId=%s freshness=%s probabilityScale=%s",
        market_id,
        freshness_status,
        probability_scale,
    )
    new_preliminary = calculate_current_preliminary_score(normalized)

    latest_analysis = normalized.get("latestAnalysis") or {}
    previous_analysis = normalized.get("previousAnalysis") or {}
    latest_preliminary = _as_float(latest_analysis.get("preliminaryRadarScore"))
    if latest_preliminary is None:
        latest_preliminary = _as_float(latest_analysis.get("preliminary_radar_score"))
    latest_ai = _as_float(latest_analysis.get("aiInterpretiveScore"))
    if latest_ai is None:
        latest_ai = _as_float(latest_analysis.get("ai_interpretive_score"))
    latest_final = _as_float(latest_analysis.get("finalRadarScore"))
    if latest_final is None:
        latest_final = _as_float(latest_analysis.get("radarScore"))
    if latest_final is None:
        latest_final = _as_float(latest_analysis.get("final_radar_score"))

    previous_preliminary = _as_float(previous_analysis.get("preliminaryRadarScore"))
    if previous_preliminary is None:
        previous_preliminary = _as_float(previous_analysis.get("preliminary_radar_score"))
    previous_ai = _as_float(previous_analysis.get("aiInterpretiveScore"))
    if previous_ai is None:
        previous_ai = _as_float(previous_analysis.get("ai_interpretive_score"))
    previous_final = _as_float(previous_analysis.get("finalRadarScore"))
    if previous_final is None:
        previous_final = _as_float(previous_analysis.get("radarScore"))
    if previous_final is None:
        previous_final = _as_float(previous_analysis.get("final_radar_score"))

    context_sources, context_source_label = _fetch_updated_context(normalized, current_market)
    if not context_sources and context_source_label == "no_context":
        context_sources = []

    existing_same_analysis = get_closing_recheck_by_market_and_latest_analysis(
        market_id=market_id,
        latest_analysis_id=latest_analysis_id,
    )
    if existing_same_analysis:
        return {
            "status": "skipped",
            "reason": "already_processed_latest_analysis",
            "marketId": market_id,
            "latestAnalysisId": latest_analysis_id,
            "existing": existing_same_analysis,
        }

    recent_recheck = get_recent_closing_recheck_for_market(
        market_id=market_id,
        hours=freshness_hours,
    )
    if recent_recheck:
        return {
            "status": "skipped",
            "reason": "recent_recheck",
            "marketId": market_id,
            "latestAnalysisId": latest_analysis_id,
            "existing": recent_recheck,
        }

    score_parity_preview = _build_score_parity(
        baseline_analysis=latest_analysis or previous_analysis,
        previous_analysis=previous_analysis,
        previous_preliminary=latest_preliminary,
        new_preliminary=new_preliminary.get("preliminary_radar_score"),
        previous_ai=latest_ai,
        new_ai=None,
        previous_final=latest_final,
        new_final=None,
        previous_breakdown=latest_analysis.get("score_breakdown"),
        new_breakdown=new_preliminary.get("score_breakdown"),
        hybrid_breakdown=None,
    )

    prompt, prompt_source = _build_model_prompt(
        normalized,
        new_preliminary=new_preliminary,
        score_parity=score_parity_preview,
        context_source=context_source_label,
    )
    prompt_hash = _build_prompt_hash(prompt)

    existing_same_prompt = get_closing_recheck_by_prompt_hash_for_market(
        market_id=market_id,
        prompt_hash=prompt_hash,
    )
    if existing_same_prompt:
        return {
            "status": "skipped",
            "reason": "duplicate_prompt_hash",
            "marketId": market_id,
            "latestAnalysisId": latest_analysis_id,
            "existing": existing_same_prompt,
            "prompt_hash": prompt_hash,
            "prompt_source": prompt_source,
        }

    try:
        result_payload, raw_output, provider, model = call_closing_recheck_model_with_provider_sequence(
            candidate=normalized,
            new_preliminary=new_preliminary,
            score_parity=score_parity_preview,
            context_source=context_source_label,
            max_retries=max_retries,
        )
    except ClosingRecheckQuotaExceeded:
        raise

    model_output = ClosingRecheckModelOutput.model_validate(result_payload)

    new_hybrid = calculate_current_hybrid_score(
        preliminary_radar_score=new_preliminary.get("preliminary_radar_score"),
        ai_interpretive_score=model_output.newAiInterpretiveScore,
    )
    new_final = new_hybrid["final_radar_score"]
    score_parity = _build_score_parity(
        baseline_analysis=latest_analysis or previous_analysis,
        previous_analysis=previous_analysis,
        previous_preliminary=latest_preliminary,
        new_preliminary=new_preliminary.get("preliminary_radar_score"),
        previous_ai=latest_ai,
        new_ai=model_output.newAiInterpretiveScore,
        previous_final=latest_final,
        new_final=new_final,
        previous_breakdown=latest_analysis.get("score_breakdown"),
        new_breakdown=new_preliminary.get("score_breakdown"),
        hybrid_breakdown=new_hybrid["score_breakdown"],
    )

    previous_radar_score = latest_final
    radar_score_delta = None if previous_radar_score is None else new_final - previous_radar_score
    score_direction = _score_direction(radar_score_delta)
    score_change_magnitude = _score_change_magnitude(radar_score_delta)
    new_signal_label = get_signal_label_for_final_score(new_final)

    reevaluation = {
        "previousRadarScore": previous_radar_score,
        "newRadarScore": new_final,
        "radarScoreDelta": radar_score_delta,
        "previousSignalLabel": latest_analysis.get("signalLabel") or previous_analysis.get("signalLabel"),
        "newSignalLabel": new_signal_label,
        "scoreDirection": score_direction,
        "scoreChangeMagnitude": score_change_magnitude,
        "scoreChangeReasons": model_output.whatChanged or [model_output.recommendation],
    }

    comparison = {
        "previousThesis": latest_analysis.get("thesis") or previous_analysis.get("thesis"),
        "latestThesis": latest_analysis.get("thesis"),
        "newThesis": model_output.updatedThesis,
        "whatChanged": model_output.whatChanged,
        "whatStayedTheSame": model_output.whatStayedTheSame,
        "contradictionDetected": model_output.recheckStatus == "CONTRADICTED",
        "contradictionExplanation": next((flag for flag in model_output.riskFlags if "contrad" in flag.lower()), None),
        "probabilityChangeSincePreviousAnalysis": _as_float(
            (normalized.get("deltas") or {}).get("probabilityChangeSincePreviousAnalysis")
        ),
        "radarScoreChangeSincePreviousAnalysis": _as_float(
            (normalized.get("deltas") or {}).get("radarScoreChangeSincePreviousAnalysis")
        ),
    }

    metric_breakdown = {
        "signalStrength": {
            "score": new_hybrid["ai_interpretive_score"],
            "reason": "Derived from the model AI interpretive score.",
        },
        "informationQuality": {
            "score": new_preliminary["score_breakdown"].get("resolution_score"),
            "reason": "Derived from code using resolution score.",
        },
        "marketConsistency": {
            "score": new_preliminary["score_breakdown"].get("narrative_score"),
            "reason": "Derived from code using narrative score.",
        },
        "timingAndClosureRisk": {
            "score": new_preliminary["score_breakdown"].get("time_to_close_score"),
            "reason": "Derived from code using time-to-close score.",
        },
        "noiseRisk": {
            "score": new_preliminary["score_breakdown"].get("liquidity_score"),
            "reason": "Derived from code using liquidity score as a noise proxy.",
        },
        "capitalTrailImpact": {
            "score": None,
            "reason": "No capital trail score computed.",
        },
    }

    validated = ClosingRecheckResult.model_validate(
        {
            "analysisMode": "closing_recheck",
            "marketId": market_id,
            "previousAnalysisId": normalized["previousAnalysisId"],
            "latestAnalysisId": latest_analysis_id,
            "closingContext": {
                "daysToClose": current_market.get("daysToClose"),
                "closingTime": current_market.get("close_date") or current_market.get("closeDate") or current_market.get("closingTime"),
            },
            "reevaluation": reevaluation,
            "metricBreakdown": metric_breakdown,
            "comparison": comparison,
            "recheckStatus": model_output.recheckStatus,
            "importance": _normalize_importance(normalized.get("recheckPriority"), model_output.confidence),
            "recommendation": model_output.recommendation,
            "thesis": model_output.updatedThesis,
            "confidence": model_output.confidence,
            "riskFlags": model_output.riskFlags,
            "scoreParity": score_parity,
        }
    )

    saved_row = None
    if persist:
        saved_row = save_closing_recheck_result(
            validated,
            provider=provider,
            model=model,
            fallback_used=bool(raw_output.get("fallback_used", False)),
            prompt_hash=prompt_hash,
            source=source,
        )

    return {
        "status": "saved" if persist else "validated",
        "marketId": market_id,
        "latestAnalysisId": latest_analysis_id,
        "previousAnalysisId": normalized["previousAnalysisId"],
        "prompt_hash": prompt_hash,
        "prompt_source": prompt_source,
        "provider": provider,
        "model": model,
        "fallback_used": bool(raw_output.get("fallback_used", False)),
        "result": validated.model_dump(),
        "saved_row": saved_row,
        "raw_output": raw_output,
    }


def should_skip_due_to_open_market(candidate: dict[str, Any]) -> bool:
    market = _normalize_market(candidate.get("market") or candidate.get("marketSnapshot"))
    if not market:
        return True
    return not bool(get_market_open_status(market)["is_open"])
