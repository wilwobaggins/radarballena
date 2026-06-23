from __future__ import annotations

from typing import Any

from services.scoring_service import calculate_hybrid_radar_score, calculate_preliminary_radar_score


def _infer_probability_scale(*values: Any) -> str | None:
    numeric_values: list[float] = []
    for value in values:
        if value is None or value == "":
            continue
        try:
            numeric_values.append(float(value))
        except (TypeError, ValueError):
            continue

    if not numeric_values:
        return None

    if any(value > 1 for value in numeric_values):
        return "percent_0_100"

    return "fraction_0_1"


def build_current_market_for_scoring(candidate: dict[str, Any]) -> dict[str, Any]:
    market_current = candidate.get("marketCurrent")
    if not isinstance(market_current, dict):
        market_current = {}

    market_snapshot = candidate.get("marketSnapshot")
    if not isinstance(market_snapshot, dict):
        market_snapshot = {}

    market = candidate.get("market")
    if not isinstance(market, dict):
        market = {}

    source = market_current or market_snapshot or market

    probability_scale = source.get("probabilityScale") or candidate.get("probabilityScale")
    if probability_scale is None:
        probability_scale = _infer_probability_scale(
            source.get("currentProbability"),
            source.get("current_probability"),
            source.get("previousProbability24h"),
            source.get("previous_probability_24h"),
            source.get("probabilityChange24h"),
            source.get("probability_change_24h"),
            candidate.get("probabilityScale"),
        )
    if probability_scale not in {"fraction_0_1", "percent_0_100"}:
        raise ValueError(f"Unsupported probabilityScale: {probability_scale or 'unknown'}")

    current_probability = source.get("currentProbability")
    if current_probability is None:
        current_probability = source.get("current_probability")
    previous_probability_24h = source.get("previousProbability24h")
    if previous_probability_24h is None:
        previous_probability_24h = source.get("previous_probability_24h")
    probability_change_24h = source.get("probabilityChange24h")
    if probability_change_24h is None:
        probability_change_24h = source.get("probability_change_24h")

    return {
        "title": source.get("title") or market.get("title"),
        "description": source.get("description") or market.get("description"),
        "category": source.get("category") or market.get("category"),
        "url": source.get("url") or market.get("url"),
        "close_date": source.get("closingTime") or source.get("close_date") or source.get("closeDate") or market.get("closingTime") or market.get("close_date") or market.get("closeDate"),
        "current_probability": current_probability,
        "previous_probability_24h": previous_probability_24h,
        "probability_change_24h": probability_change_24h,
        "volume": source.get("volume"),
        "liquidity": source.get("liquidity"),
        "outcomes": source.get("outcomes") or market.get("outcomes"),
        "probabilityScale": probability_scale,
        "dataSource": source.get("dataSource") or candidate.get("dataSource") or "unknown",
        "freshness": source.get("freshness") or candidate.get("freshness"),
    }


def calculate_current_preliminary_score(candidate: dict[str, Any]) -> dict[str, Any]:
    current_market = build_current_market_for_scoring(candidate)
    return calculate_preliminary_radar_score(current_market)


def calculate_current_hybrid_score(
    *,
    preliminary_radar_score: int | float | None,
    ai_interpretive_score: int | float | None,
) -> dict[str, Any]:
    return calculate_hybrid_radar_score(
        preliminary_radar_score=preliminary_radar_score,
        ai_interpretive_score=ai_interpretive_score,
    )
