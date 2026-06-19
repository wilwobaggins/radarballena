import hashlib
from typing import Any

from services.supabase_service import get_supabase_client
from schemas.closing_recheck_schema import ClosingRecheckResult


def compute_prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def save_closing_recheck_result(
    result: ClosingRecheckResult,
    provider: str | None = None,
    model: str | None = None,
    fallback_used: bool = False,
    prompt_hash: str | None = None,
    source: str = "manual_debug",
) -> dict[str, Any]:
    supabase = get_supabase_client()
    result_dump = result.model_dump()

    payload = {
        "market_id": result.marketId,
        "previous_analysis_id": result.previousAnalysisId,
        "latest_analysis_id": result.latestAnalysisId,
        "analysis_mode": result.analysisMode,
        "recheck_status": result.recheckStatus,
        "importance": result.importance,
        "recommendation": result.recommendation,
        "thesis": result.thesis,
        "confidence": result.confidence,
        "previous_radar_score": result.reevaluation.previousRadarScore,
        "new_radar_score": result.reevaluation.newRadarScore,
        "radar_score_delta": result.reevaluation.radarScoreDelta,
        "score_direction": result.reevaluation.scoreDirection,
        "score_change_magnitude": result.reevaluation.scoreChangeMagnitude,
        "provider": provider,
        "model": model,
        "fallback_used": fallback_used,
        "result": result_dump,
        "prompt_hash": prompt_hash,
        "source": source,
    }

    response = (
        supabase
        .table("closing_recheck_results")
        .insert(payload)
        .execute()
    )

    if not response.data:
        raise RuntimeError("No se pudo guardar closing recheck result")

    return response.data[0]
