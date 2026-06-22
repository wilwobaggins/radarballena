from __future__ import annotations

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

from schemas.closing_recheck_schema import ClosingRecheckResult
from services.closing_recheck_prompt_builder import build_closing_recheck_prompt
from services.closing_recheck_repository import (
    compute_prompt_hash,
    get_closing_recheck_by_market_and_latest_analysis,
    get_closing_recheck_by_prompt_hash_for_market,
    get_recent_closing_recheck_for_market,
    save_closing_recheck_result,
)
from services.deepbrief_generator import (
    SYSTEM_INSTRUCTION,
    ProviderGenerationError,
    get_provider_model,
    get_provider_sequence,
    is_provider_configured,
    load_json_repair_prompt,
    summarize_exception,
)
from services.logger_service import get_logger
from services.market_filter import get_market_open_status
from services.scoring_service import days_to_close


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
    market = _normalize_market(
        _coalesce(candidate.get("market"), candidate.get("marketSnapshot"))
    )
    if not market:
        market = _normalize_market(candidate)

    previous_analysis = _normalize_analysis(
        _coalesce(candidate.get("previousAnalysis"), candidate.get("previous_analysis"))
    )
    latest_analysis = _normalize_analysis(
        _coalesce(candidate.get("latestAnalysis"), candidate.get("latest_analysis"))
    )

    recheck_candidate = candidate.get("recheckCandidate")
    if not isinstance(recheck_candidate, dict):
        recheck_candidate = {}

    deltas = candidate.get("deltas")
    if not isinstance(deltas, dict):
        deltas = {}

    market_snapshot = candidate.get("marketSnapshot")
    if not isinstance(market_snapshot, dict):
        market_snapshot = market or {}

    capital_trail = candidate.get("capitalTrail")

    recheck_priority = _clean_text(
        _coalesce(
            candidate.get("recheckPriority"),
            recheck_candidate.get("recheckPriority"),
            candidate.get("priority"),
        )
    )
    recheck_status = _clean_text(
        _coalesce(
            candidate.get("recheckStatus"),
            recheck_candidate.get("recheckStatus"),
        )
    )
    recheck_score = _coalesce(
        candidate.get("recheckScore"),
        recheck_candidate.get("recheckScore"),
    )

    return {
        **candidate,
        "marketId": _coalesce(
            candidate.get("marketId"),
            candidate.get("market_id"),
            market.get("marketId"),
            latest_analysis.get("analysisId"),
        ),
        "previousAnalysisId": _coalesce(
            candidate.get("previousAnalysisId"),
            candidate.get("previous_analysis_id"),
            previous_analysis.get("analysisId"),
        ),
        "latestAnalysisId": _coalesce(
            candidate.get("latestAnalysisId"),
            candidate.get("latest_analysis_id"),
            latest_analysis.get("analysisId"),
        ),
        "market": market,
        "previousAnalysis": previous_analysis,
        "latestAnalysis": latest_analysis,
        "deltas": deltas,
        "recheckCandidate": {
            **recheck_candidate,
            "recheckPriority": recheck_priority,
            "recheckStatus": recheck_status,
            "recheckScore": _as_float(recheck_score),
        },
        "capitalTrail": capital_trail,
        "marketSnapshot": market_snapshot,
        "recheckPriority": recheck_priority,
        "recheckStatus": recheck_status,
        "recheckScore": _as_float(recheck_score),
    }


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
    previous_analysis = candidate.get("previousAnalysis") or {}
    latest_analysis = candidate.get("latestAnalysis") or {}

    return {
        "market": market,
        "previous_analysis": previous_analysis,
        "latest_analysis": latest_analysis,
        "deltas": _build_deltas(candidate),
        "recheck_candidate": _build_recheck_candidate(candidate),
        "capital_trail": candidate.get("capitalTrail"),
        "market_snapshot": _build_market_snapshot(candidate),
    }


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


def _is_json_repair_needed(error: Exception) -> bool:
    message = summarize_exception(error).lower()
    return "json" in message or "schema" in message or "parse" in message


def _build_model_prompt(
    candidate: dict[str, Any],
    *,
    repair_note: str | None = None,
) -> tuple[str, str]:
    prompt_input = _build_prompt_inputs(candidate)
    prompt, prompt_source = build_closing_recheck_prompt(
        market=prompt_input["market"],
        previous_analysis=prompt_input["previous_analysis"],
        latest_analysis=prompt_input["latest_analysis"],
        deltas=prompt_input["deltas"],
        recheck_candidate=prompt_input["recheck_candidate"],
        capital_trail=prompt_input["capital_trail"],
        market_snapshot=prompt_input["market_snapshot"],
        repair_note=repair_note,
    )
    return prompt, prompt_source


def call_closing_recheck_model_with_provider_sequence(
    *,
    candidate: dict[str, Any],
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
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    prior_attempts=attempts,
                )
            else:
                deepbrief, raw_output = _call_openai_model(
                    candidate=candidate,
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

        prompt, prompt_source = _build_model_prompt(candidate, repair_note=repair_note)

        try:
            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": prompt},
                ],
                text_format=ClosingRecheckResult,
            )

            parsed = response.output_parsed
            if parsed is None:
                raise RuntimeError("El modelo no devolvio un ClosingRecheckResult valido")

            validated = ClosingRecheckResult.model_validate(parsed.model_dump())
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

    for attempt in range(1, max_retries + 2):
        repair_note = None
        if attempt > 1:
            repair_note = load_json_repair_prompt()
            if last_error:
                repair_note += f"\n\nError anterior:\n{last_error}"

        prompt, prompt_source = _build_model_prompt(candidate, repair_note=repair_note)

        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=ClosingRecheckResult,
                ),
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

            validated = ClosingRecheckResult.model_validate(payload)
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

    prompt, prompt_source = _build_model_prompt(normalized)
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
            max_retries=max_retries,
        )
    except ClosingRecheckQuotaExceeded:
        raise

    validated = ClosingRecheckResult.model_validate(result_payload)

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
