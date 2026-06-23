from __future__ import annotations

import os
from typing import Any

import requests

from services.closing_recheck_candidate_normalizer import (
    normalize_closing_recheck_candidate,
)


DEFAULT_BACKEND_URL = "https://app.radarballena.com"


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


def get_backend_url() -> str:
    return (
        os.getenv("BACKEND_URL")
        or os.getenv("BACKEND_DEEPSIGNAL_ENDPOINT")
        or DEFAULT_BACKEND_URL
    ).rstrip("/")


def get_request_timeout_seconds(default: int = 30) -> int:
    return _as_int(os.getenv("CLOSING_RECHECK_REQUEST_TIMEOUT_SECONDS"), default) or default


def build_candidate_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    api_key = _coalesce(
        os.getenv("BACKEND_INTERNAL_API_KEY"),
        os.getenv("INTERNAL_API_KEY"),
    )

    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    return headers


def _extract_payload_list(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in ("candidates", "data", "results", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    return []


def _normalize_analysis(analysis: Any) -> dict[str, Any]:
    if not isinstance(analysis, dict):
        return {}

    analysis_id = _coalesce(
        analysis.get("analysisId"),
        analysis.get("analysis_id"),
        analysis.get("id"),
    )

    probability = _coalesce(
        analysis.get("probability"),
        analysis.get("current_probability"),
        analysis.get("predictedProbability"),
    )

    radar_score = _coalesce(
        analysis.get("radarScore"),
        analysis.get("finalRadarScore"),
        analysis.get("radar_score"),
    )

    return {
        **analysis,
        "analysisId": analysis_id,
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
        "radarScore": _as_float(radar_score),
        "probability": _as_float(probability),
    }


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

    days_to_close = _coalesce(
        market.get("daysToClose"),
        market.get("days_to_close"),
    )

    return {
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
        "closingLabel": _clean_text(
            _coalesce(market.get("closingLabel"), market.get("closing_label"))
        ),
        "daysToClose": _as_int(days_to_close),
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


def _normalize_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    market = _normalize_market(
        _coalesce(candidate.get("marketCurrent"), candidate.get("market"), candidate.get("marketSnapshot"))
        if isinstance(candidate, dict)
        else {}
    )
    previous_analysis = _normalize_analysis(
        _coalesce(candidate.get("previousAnalysis"), candidate.get("previous_analysis"))
    )
    latest_analysis = _normalize_analysis(
        _coalesce(candidate.get("latestAnalysis"), candidate.get("latest_analysis"))
    )

    recheck_candidate = candidate.get("recheckCandidate")
    if not isinstance(recheck_candidate, dict):
        recheck_candidate = {}

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

    if not market and isinstance(candidate.get("marketSnapshot"), dict):
        market = _normalize_market(candidate["marketSnapshot"])

    if not market and isinstance(candidate, dict):
        market = _normalize_market(candidate)

    deltas = candidate.get("deltas")
    if not isinstance(deltas, dict):
        deltas = {}

    capital_trail = candidate.get("capitalTrail")
    if capital_trail is None and isinstance(candidate.get("deepbrief"), dict):
        capital_trail = candidate["deepbrief"].get("capitalTrail")

    market_snapshot = candidate.get("marketSnapshot")
    if not isinstance(market_snapshot, dict):
        market_snapshot = market or {}

    return {
        **candidate,
        "marketId": _coalesce(
            candidate.get("marketId"),
            candidate.get("market_id"),
            market.get("marketId"),
            latest_analysis.get("marketId"),
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
        "marketCurrent": candidate.get("marketCurrent") if isinstance(candidate.get("marketCurrent"), dict) else market,
        "probabilityScale": _coalesce(
            candidate.get("probabilityScale"),
            market.get("probabilityScale"),
        ),
        "previousAnalysis": previous_analysis,
        "latestAnalysis": latest_analysis,
        "deltas": deltas,
        "recheckCandidate": {
            **recheck_candidate,
            "recheckStatus": recheck_status,
            "recheckPriority": recheck_priority,
            "recheckScore": _as_float(recheck_score),
        },
        "capitalTrail": capital_trail,
        "marketSnapshot": market_snapshot,
        "recheckPriority": recheck_priority,
        "recheckStatus": recheck_status,
        "recheckScore": _as_float(recheck_score),
    }


def normalize_closing_recheck_candidates(payload: Any) -> list[dict[str, Any]]:
    return [normalize_closing_recheck_candidate(item) for item in _extract_payload_list(payload)]


def fetch_closing_recheck_candidates(
    *,
    days: int | None = None,
    limit: int | None = None,
    max_per_category: int | None = None,
    timeout_seconds: int | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {}

    if days is not None:
        params["days"] = days
    if limit is not None:
        params["limit"] = limit
    if max_per_category is not None:
        params["maxPerCategory"] = max_per_category

    response = requests.get(
        f"{get_backend_url()}/api/deepsignal/closing-recheck-candidates",
        params=params,
        headers=build_candidate_headers(),
        timeout=timeout_seconds or get_request_timeout_seconds(),
    )
    response.raise_for_status()

    try:
        payload = response.json()
    except ValueError as error:
        raise RuntimeError("Closing recheck candidates response is not JSON") from error

    if isinstance(payload, dict) and payload.get("ok") is False:
        message = _clean_text(
            _coalesce(
                payload.get("error"),
                payload.get("message"),
                payload.get("detail"),
            )
        )
        raise RuntimeError(message or "Backend rejected closing recheck candidates request")

    return normalize_closing_recheck_candidates(payload)
