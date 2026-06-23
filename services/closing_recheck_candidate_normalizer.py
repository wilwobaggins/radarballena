from __future__ import annotations

from typing import Any


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _build_market_from_flat(candidate: dict[str, Any]) -> dict[str, Any]:
    closing_time = _coalesce(
        candidate.get("closingTime"),
        candidate.get("closing_time"),
        candidate.get("closeDate"),
        candidate.get("close_date"),
        candidate.get("endDate"),
        candidate.get("end_date"),
        candidate.get("endDateIso"),
        candidate.get("end_date_iso"),
    )

    days_to_close = _coalesce(candidate.get("daysToClose"), candidate.get("days_to_close"))
    closing_label = _coalesce(candidate.get("closingLabel"), candidate.get("closing_label"))
    if not closing_label and days_to_close is not None:
        closing_label = f"{_as_int(days_to_close)}d"

    return {
        "marketId": _coalesce(candidate.get("marketId"), candidate.get("market_id")),
        "title": _clean_text(candidate.get("title")),
        "category": _clean_text(candidate.get("category")),
        "closingTime": _clean_text(closing_time),
        "close_date": _clean_text(closing_time),
        "closeDate": _clean_text(closing_time),
        "closingLabel": _clean_text(closing_label),
        "daysToClose": _as_int(days_to_close),
        "current_probability": _as_float(_coalesce(candidate.get("latestProbability"))),
        "previous_probability_24h": _as_float(
            _coalesce(
                candidate.get("previousProbability24h"),
                candidate.get("previousProbability"),
                candidate.get("previousAnalysisProbability"),
            )
        ),
        "probability_change_24h": _as_float(candidate.get("probabilityChange24h")),
        "volume": _as_float(candidate.get("volume")),
        "liquidity": _as_float(candidate.get("liquidity")),
    }


def _build_market(candidate: dict[str, Any]) -> dict[str, Any]:
    market = candidate.get("market")
    if isinstance(market, dict):
        normalized = {**market}
    else:
        market_snapshot = candidate.get("marketSnapshot")
        normalized = {**market_snapshot} if isinstance(market_snapshot, dict) else {}

    if not normalized:
        normalized = _build_market_from_flat(candidate)
    else:
        closing_time = _coalesce(
            normalized.get("closingTime"),
            normalized.get("closing_time"),
            normalized.get("closeDate"),
            normalized.get("close_date"),
            normalized.get("endDate"),
            normalized.get("end_date"),
            normalized.get("endDateIso"),
            normalized.get("end_date_iso"),
            candidate.get("closingTime"),
            candidate.get("close_date"),
            candidate.get("closeDate"),
        )
        normalized = {
            **normalized,
            "marketId": _coalesce(
                normalized.get("marketId"),
                normalized.get("market_id"),
                normalized.get("id"),
                candidate.get("marketId"),
                candidate.get("market_id"),
            ),
            "title": _clean_text(_coalesce(normalized.get("title"), candidate.get("title"))),
            "category": _clean_text(
                _coalesce(normalized.get("category"), candidate.get("category"))
            ),
            "closingTime": _clean_text(closing_time),
            "close_date": _clean_text(closing_time),
            "closeDate": _clean_text(closing_time),
            "closingLabel": _clean_text(
                _coalesce(normalized.get("closingLabel"), candidate.get("closingLabel"))
            ),
            "daysToClose": _as_int(
                _coalesce(normalized.get("daysToClose"), candidate.get("daysToClose"))
            ),
            "current_probability": _as_float(
                _coalesce(
                    normalized.get("current_probability"),
                    normalized.get("currentProbability"),
                    normalized.get("probability"),
                    candidate.get("latestProbability"),
                )
            ),
            "previous_probability_24h": _as_float(
                _coalesce(
                    normalized.get("previous_probability_24h"),
                    normalized.get("previousProbability24h"),
                    candidate.get("previousAnalysisProbability"),
                )
            ),
            "probability_change_24h": _as_float(
                _coalesce(
                    normalized.get("probability_change_24h"),
                    normalized.get("probabilityChange24h"),
                    candidate.get("probabilityChange24h"),
                )
            ),
            "volume": _as_float(_coalesce(normalized.get("volume"), candidate.get("volume"))),
            "liquidity": _as_float(
                _coalesce(normalized.get("liquidity"), candidate.get("liquidity"))
            ),
        }

    if normalized.get("daysToClose") is None and normalized.get("closingTime"):
        normalized["daysToClose"] = _as_int(candidate.get("daysToClose"))

    if not normalized.get("closingLabel") and normalized.get("daysToClose") is not None:
        normalized["closingLabel"] = f"{normalized['daysToClose']}d"

    return normalized


def _build_previous_analysis(candidate: dict[str, Any]) -> dict[str, Any]:
    analysis = candidate.get("previousAnalysis")
    if isinstance(analysis, dict):
        normalized = {**analysis}
    else:
        normalized = {}

    normalized = {
        **normalized,
        "analysisId": _coalesce(
            normalized.get("analysisId"),
            normalized.get("analysis_id"),
            candidate.get("previousAnalysisId"),
            candidate.get("previous_analysis_id"),
        ),
        "generatedAt": _coalesce(
            normalized.get("generatedAt"),
            normalized.get("generated_at"),
            candidate.get("previousAnalysisGeneratedAt"),
        ),
        "thesis": _clean_text(
            _coalesce(normalized.get("thesis"), candidate.get("previousThesis"))
        ),
        "signalLabel": _clean_text(
            _coalesce(normalized.get("signalLabel"), candidate.get("signalLabel"))
        ),
        "radarScore": _as_float(
            _coalesce(
                normalized.get("radarScore"),
                normalized.get("finalRadarScore"),
                candidate.get("previousAnalysisRadarScore"),
            )
        ),
        "probability": _as_float(
            _coalesce(
                normalized.get("probability"),
                candidate.get("previousAnalysisProbability"),
            )
        ),
    }

    return normalized


def _build_latest_analysis(candidate: dict[str, Any]) -> dict[str, Any]:
    analysis = candidate.get("latestAnalysis")
    if isinstance(analysis, dict):
        normalized = {**analysis}
    else:
        normalized = {}

    normalized = {
        **normalized,
        "analysisId": _coalesce(
            normalized.get("analysisId"),
            normalized.get("analysis_id"),
            candidate.get("latestAnalysisId"),
            candidate.get("latest_analysis_id"),
        ),
        "generatedAt": _coalesce(
            normalized.get("generatedAt"),
            normalized.get("generated_at"),
            candidate.get("latestAnalysisGeneratedAt"),
        ),
        "thesis": _clean_text(_coalesce(normalized.get("thesis"), candidate.get("thesis"))),
        "signalLabel": _clean_text(
            _coalesce(normalized.get("signalLabel"), candidate.get("signalLabel"))
        ),
        "radarScore": _as_float(
            _coalesce(
                normalized.get("radarScore"),
                normalized.get("finalRadarScore"),
                candidate.get("latestRadarScore"),
            )
        ),
        "probability": _as_float(
            _coalesce(normalized.get("probability"), candidate.get("latestProbability"))
        ),
    }

    return normalized


def _build_deltas(candidate: dict[str, Any]) -> dict[str, Any]:
    deltas = candidate.get("deltas")
    if isinstance(deltas, dict):
        normalized = {**deltas}
    else:
        normalized = {}

    if "probabilityChange24h" not in normalized:
        normalized["probabilityChange24h"] = _as_float(candidate.get("probabilityChange24h"))

    if "probabilityChangeSincePreviousAnalysis" not in normalized:
        probability_change = _as_float(candidate.get("probabilityChangeSincePreviousAnalysis"))
        if probability_change is None:
            probability_change = _as_float(candidate.get("probabilityChange24h"))
        normalized["probabilityChangeSincePreviousAnalysis"] = probability_change

    if "radarScoreChangeSincePreviousAnalysis" not in normalized:
        radar_change = _as_float(candidate.get("radarScoreChangeSincePreviousAnalysis"))
        if radar_change is None:
            latest_score = _as_float(candidate.get("latestRadarScore"))
            previous_score = _as_float(candidate.get("previousAnalysisRadarScore"))
            if latest_score is not None and previous_score is not None:
                radar_change = latest_score - previous_score
        normalized["radarScoreChangeSincePreviousAnalysis"] = radar_change

    return normalized


def normalize_closing_recheck_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    market = _build_market(candidate)
    market_current = candidate.get("marketCurrent")
    if not isinstance(market_current, dict):
        market_current = {}
    previous_analysis = _build_previous_analysis(candidate)
    latest_analysis = _build_latest_analysis(candidate)

    recheck_candidate = candidate.get("recheckCandidate")
    if not isinstance(recheck_candidate, dict):
        recheck_candidate = {}

    recheck_priority = _clean_text(
        _coalesce(
            candidate.get("recheckPriority"),
            recheck_candidate.get("recheckPriority"),
        )
    )
    recheck_status = _clean_text(
        _coalesce(candidate.get("recheckStatus"), recheck_candidate.get("recheckStatus"))
    )
    recheck_score = _as_float(
        _coalesce(candidate.get("recheckScore"), recheck_candidate.get("recheckScore"))
    )

    return {
        **candidate,
        "marketId": _coalesce(candidate.get("marketId"), market.get("marketId")),
        "previousAnalysisId": _coalesce(
            candidate.get("previousAnalysisId"), previous_analysis.get("analysisId")
        ),
        "latestAnalysisId": _coalesce(
            candidate.get("latestAnalysisId"), latest_analysis.get("analysisId")
        ),
        "market": market,
        "marketCurrent": market_current,
        "probabilityScale": _coalesce(
            candidate.get("probabilityScale"),
            market_current.get("probabilityScale"),
            market.get("probabilityScale"),
            candidate.get("marketSnapshot", {}).get("probabilityScale")
            if isinstance(candidate.get("marketSnapshot"), dict)
            else None,
        ),
        "previousAnalysis": previous_analysis,
        "latestAnalysis": latest_analysis,
        "deltas": _build_deltas(candidate),
        "capitalTrail": candidate.get("capitalTrail"),
        "marketSnapshot": candidate.get("marketSnapshot") if isinstance(candidate.get("marketSnapshot"), dict) else market,
        "recheckCandidate": {
            **recheck_candidate,
            "recheckPriority": recheck_priority,
            "recheckStatus": recheck_status,
            "recheckScore": recheck_score,
        },
        "recheckPriority": recheck_priority,
        "recheckStatus": recheck_status,
        "recheckScore": recheck_score,
    }
