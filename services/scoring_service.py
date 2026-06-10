from datetime import datetime, timezone
from typing import Any

from services.category_filter import (
    ALLOWED_DEEPENGINE_CATEGORIES,
    classify_deepengine_category,
)
from services.logger_service import get_logger


logger = get_logger("scoring_service")


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(value, max_value))


def parse_date(value: Any) -> datetime | None:
    if not value:
        return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))

        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)

        return parsed
    except ValueError:
        return None


def get_market_value(market: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = market.get(key)

        if value not in (None, ""):
            return value

    raw_payload = market.get("raw_payload") or {}

    if isinstance(raw_payload, dict):
        for key in keys:
            value = raw_payload.get(key)

            if value not in (None, ""):
                return value

    return None


def days_to_close(market: dict[str, Any]) -> int:
    close_date_value = get_market_value(
        market,
        "close_date",
        "closeDate",
        "closing_date",
        "closingDate",
        "end_date",
        "endDate",
        "endDateIso",
        "end_date_iso",
    )

    close_date = parse_date(close_date_value)

    if close_date is None:
        return 9999

    return max((close_date - datetime.now(timezone.utc)).days, 0)


def calculate_volume_score(market: dict[str, Any]) -> int:
    """
    0-20 pts.
    """
    volume = safe_float(market.get("volume"))
    return int(clamp((volume / 250_000) * 20, 0, 20))


def calculate_liquidity_score(market: dict[str, Any]) -> int:
    """
    0-20 pts.
    """
    liquidity = safe_float(market.get("liquidity"))
    return int(clamp((liquidity / 50_000) * 20, 0, 20))


def calculate_time_to_close_score(market: dict[str, Any]) -> int:
    """
    0-15 pts.
    Premia cierre relativamente cercano, pero no demasiado inmediato.
    """
    days = days_to_close(market)

    if days <= 0:
        return 0
    if days <= 7:
        return 8
    if days <= 30:
        return 15
    if days <= 60:
        return 12
    if days <= 90:
        return 8

    return 0


def calculate_probability_movement_score(market: dict[str, Any]) -> int:
    """
    0-25 pts.
    Requiere probability_change_24h.
    Si no existe, regresa 0.
    """
    movement = abs(safe_float(market.get("probability_change_24h")))
    return int(clamp((movement / 0.05) * 25, 0, 25))


def calculate_resolution_score(market: dict[str, Any]) -> int:
    """
    0-10 pts.
    Evalua claridad basica.
    """
    title = str(market.get("title") or "").strip()
    description = str(market.get("description") or "").strip()
    outcomes = market.get("outcomes") or []

    if not title:
        return 0

    score = 4

    if description:
        score += 3

    if isinstance(outcomes, list) and len(outcomes) >= 2:
        score += 3

    return int(clamp(score, 0, 10))


def calculate_narrative_score(market: dict[str, Any]) -> int:
    """
    0-10 pts.
    Solo premia categorias compatibles con DeepEngine MVP.
    Deportes y categorias ambiguas reciben 0.
    """
    classification = classify_deepengine_category(market)

    if not classification["eligible"]:
        return 0

    category = classification["category"]

    if category in ALLOWED_DEEPENGINE_CATEGORIES:
        return 10

    return 4


def calculate_preliminary_radar_score(market: dict[str, Any]) -> dict[str, Any]:
    volume_score = calculate_volume_score(market)
    liquidity_score = calculate_liquidity_score(market)
    time_to_close_score = calculate_time_to_close_score(market)
    probability_movement_score = calculate_probability_movement_score(market)
    resolution_score = calculate_resolution_score(market)
    narrative_score = calculate_narrative_score(market)

    total = (
        volume_score
        + liquidity_score
        + time_to_close_score
        + probability_movement_score
        + resolution_score
        + narrative_score
    )

    preliminary_radar_score = int(clamp(total, 0, 100))

    return {
        "preliminary_radar_score": preliminary_radar_score,
        "score_breakdown": {
            "volume_score": volume_score,
            "liquidity_score": liquidity_score,
            "time_to_close_score": time_to_close_score,
            "probability_movement_score": probability_movement_score,
            "resolution_score": resolution_score,
            "narrative_score": narrative_score,
        },
    }


def score_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    scored = []

    for market in markets:
        score_result = calculate_preliminary_radar_score(market)

        scored_market = {
            **market,
            **score_result,
        }

        scored.append(scored_market)

    return scored


def sort_markets_by_score(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        markets,
        key=lambda market: market.get("preliminary_radar_score", 0),
        reverse=True,
    )


def calculate_hybrid_radar_score(
    preliminary_radar_score: int | float | None,
    ai_interpretive_score: int | float | None,
) -> dict:
    """
    Score hibrido:
    final_radar_score = 0.40 preliminary + 0.60 ai_interpretive
    """
    preliminary = safe_float(preliminary_radar_score)
    ai_score = safe_float(ai_interpretive_score)

    preliminary = int(clamp(preliminary, 0, 100))
    ai_score = int(clamp(ai_score, 0, 100))

    final_score = round((0.40 * preliminary) + (0.60 * ai_score))
    final_score = int(clamp(final_score, 0, 100))

    logger.info(
        "Hybrid score formula usada | formula=%s | preliminary=%s | ai=%s | final=%s",
        "final_radar_score = 0.40 preliminary_radar_score + 0.60 ai_interpretive_score",
        preliminary,
        ai_score,
        final_score,
    )

    return {
        "preliminary_radar_score": preliminary,
        "ai_interpretive_score": ai_score,
        "final_radar_score": final_score,
        "score_breakdown": {
            "formula": "final_radar_score = 0.40 preliminary_radar_score + 0.60 ai_interpretive_score",
            "weights": {
                "preliminary_radar_score": 0.40,
                "ai_interpretive_score": 0.60,
            },
            "inputs": {
                "preliminary_radar_score": preliminary,
                "ai_interpretive_score": ai_score,
            },
            "output": {
                "final_radar_score": final_score,
            },
        },
    }
