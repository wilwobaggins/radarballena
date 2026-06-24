from __future__ import annotations

from typing import Any

from services.deterministic_deepbrief_generator import (
    build_deterministic_raw_output,
    generate_deterministic_deepbrief,
)
from services.logger_service import get_logger


logger = get_logger("deterministic_deepbrief_persistence")


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _sanitize_provider_attempts(provider_attempts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for attempt in provider_attempts or []:
        if not isinstance(attempt, dict):
            continue

        sanitized.append(
            {
                "provider": attempt.get("provider"),
                "status": attempt.get("status"),
                "error_type": attempt.get("error_type"),
                "model": attempt.get("model"),
                "attempt": attempt.get("attempt"),
                "fallback_used": attempt.get("fallback_used"),
                "message": attempt.get("message"),
            }
        )

    return sanitized


def _build_recent_fallback_probe(
    *,
    db: Any,
    market_db_id: str,
    hours: int,
) -> dict[str, Any] | None:
    if not hasattr(db, "get_recent_deepbrief"):
        return None

    recent = db.get_recent_deepbrief(market_db_id=market_db_id, hours=hours)
    if not recent:
        return None

    raw_output = recent.get("rawOutput") or {}
    if raw_output.get("provider") == "deterministic" and raw_output.get("generation_mode") == "deterministic_fallback":
        return recent

    return None


def persist_deterministic_deepbrief(
    *,
    db: Any,
    market_db_id: str,
    market: dict[str, Any],
    preliminary_score: int | float,
    score_breakdown: dict[str, Any],
    selection_reason: str | None = None,
    fallback_reason: str = "all_llm_providers_unavailable",
    pipeline_run_id: str | None = None,
    provider_attempts: list[dict[str, Any]] | None = None,
    deterministic_deepbrief: Any | None = None,
) -> dict[str, Any]:
    deepbrief = (
        deterministic_deepbrief
        if deterministic_deepbrief is not None
        else generate_deterministic_deepbrief(
            market=market,
            preliminary_score=preliminary_score,
            score_breakdown=score_breakdown,
            selection_reason=selection_reason,
            fallback_reason=fallback_reason,
        )
    )

    deterministic_score = {
        "preliminary_radar_score": int(round(preliminary_score)),
        "ai_interpretive_score": None,
        "final_radar_score": int(round(preliminary_score)),
        "score_breakdown": {
            "generation_mode": "deterministic_fallback",
            "formula": "final_radar_score = preliminary_radar_score",
            "ai_component_used": False,
            "preliminary_radar_score": int(round(preliminary_score)),
            "final_radar_score": int(round(preliminary_score)),
        },
    }

    raw_output = build_deterministic_raw_output(
        market=market,
        preliminary_score=preliminary_score,
        score_breakdown=score_breakdown,
        fallback_reason=fallback_reason,
    )
    raw_output["market_input"]["selection_reason"] = selection_reason or market.get("selection_reason")
    raw_output["pipeline_run_id"] = pipeline_run_id
    raw_output["provider_attempts"] = _sanitize_provider_attempts(provider_attempts)

    deepbrief_payload = deepbrief.model_dump() if hasattr(deepbrief, "model_dump") else dict(deepbrief)
    deepbrief_payload["rawOutput"] = raw_output
    deepbrief_payload["pipelineRunId"] = pipeline_run_id
    deepbrief_payload["radar_score"] = deterministic_score["final_radar_score"]
    deepbrief_payload["radarScore"] = deterministic_score["final_radar_score"]
    deepbrief_payload["aiInterpretiveScore"] = None
    deepbrief_payload["preliminaryRadarScore"] = deterministic_score["preliminary_radar_score"]
    deepbrief_payload["finalRadarScore"] = deterministic_score["final_radar_score"]
    deepbrief_payload["hybridScoreBreakdown"] = deterministic_score["score_breakdown"]

    recent_probe = _build_recent_fallback_probe(db=db, market_db_id=market_db_id, hours=12)
    if recent_probe:
        logger.info(
            "Deterministic fallback reciente detectado | market_id=%s | deepbrief_id=%s",
            market_db_id,
            recent_probe.get("id"),
        )

    if not hasattr(db, "insert_deepbrief"):
        raise AttributeError("db debe exponer insert_deepbrief")

    saved = db.insert_deepbrief(
        market_db_id=market_db_id,
        deepbrief=deepbrief_payload,
        raw_output=raw_output,
        hybrid_score=deterministic_score,
        pipeline_run_id=pipeline_run_id,
    )

    return saved


def has_recent_deterministic_fallback(
    *,
    db: Any,
    market_db_id: str,
    hours: int = 12,
) -> bool:
    return _build_recent_fallback_probe(db=db, market_db_id=market_db_id, hours=hours) is not None
