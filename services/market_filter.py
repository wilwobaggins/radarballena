from typing import Any

from services.scoring_service import (
    score_markets,
    sort_markets_by_score,
    days_to_close,
    safe_float,
)


RELEVANT_CATEGORIES = {
    "politics",
    "macro",
    "economics",
    "crypto",
    "technology",
    "geopolitics",
    "entertainment",
    "sports",
    "commodities",
}


def has_clear_resolution(market: dict[str, Any]) -> bool:
    title = str(market.get("title") or "").strip()
    description = str(market.get("description") or "").strip()
    outcomes = market.get("outcomes") or []

    if not title:
        return False

    if not description:
        return False

    if not isinstance(outcomes, list) or len(outcomes) < 2:
        return False

    return True


def has_relevant_category(market: dict[str, Any]) -> bool:
    category = str(market.get("category") or "").lower()
    title = str(market.get("title") or "").lower()
    description = str(market.get("description") or "").lower()

    if category in RELEVANT_CATEGORIES:
        return True

    keywords = [
        "trump",
        "president",
        "election",
        "bitcoin",
        "btc",
        "ethereum",
        "fed",
        "inflation",
        "war",
        "ceasefire",
        "ai",
        "openai",
        "nvidia",
        "gta",
        "rockstar",
        "oil",
        "gold",
        "nba",
        "nfl",
    ]

    text = f"{title} {description}"

    return any(keyword in text for keyword in keywords)


def is_relevant_market(
    market: dict[str, Any],
    min_liquidity: float = 1_000,
    min_volume: float = 5_000,
    max_days_to_close: int = 90,
    min_probability_move: float = 0.01,
) -> bool:
    liquidity = safe_float(market.get("liquidity"))
    volume = safe_float(market.get("volume"))
    probability_move = abs(safe_float(market.get("probability_change_24h")))
    close_days = days_to_close(market)

    if liquidity < min_liquidity:
        return False

    if volume < min_volume:
        return False

    if close_days > max_days_to_close:
        return False

    if not has_clear_resolution(market):
        return False

    has_movement = probability_move >= min_probability_move
    has_high_volume = volume >= 100_000
    category_relevant = has_relevant_category(market)

    return has_movement or has_high_volume or category_relevant


def filter_relevant_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [market for market in markets if is_relevant_market(market)]


def select_top_markets(
    markets: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Filtra mercados relevantes, calcula preliminary_radar_score
    usando scoring_service.py y ordena por score.
    """
    relevant_markets = filter_relevant_markets(markets)
    scored_markets = score_markets(relevant_markets)
    sorted_markets = sort_markets_by_score(scored_markets)

    return sorted_markets[:limit]