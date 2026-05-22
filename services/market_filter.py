from datetime import datetime, timezone
from typing import Any


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_date(date_text: Any) -> datetime | None:
    if not date_text:
        return None

    try:
        parsed = datetime.fromisoformat(str(date_text).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def days_to_close(market: dict[str, Any]) -> int:
    close_date = parse_date(market.get("close_date"))
    if close_date is None:
        return 9999
    return max((close_date - datetime.now(timezone.utc)).days, 0)


def has_clear_resolution(market: dict[str, Any]) -> bool:
    title = str(market.get("title") or "")
    description = str(market.get("description") or "")
    outcomes = market.get("outcomes") or []

    if not title:
        return False
    if len(outcomes) < 2:
        return False
    return bool(description)


def narrative_category_score(market: dict[str, Any]) -> int:
    category = str(market.get("category") or "").lower()
    title = str(market.get("title") or "").lower()
    description = str(market.get("description") or "").lower()
    haystack = f"{category} {title} {description}"

    if category in RELEVANT_CATEGORIES:
        return 10

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

    if any(keyword in haystack for keyword in keywords):
        return 8

    return 4


def is_relevant_market(
    market: dict[str, Any],
    min_liquidity: float = 1_000,
    min_volume: float = 5_000,
    max_days_to_close: int = 90,
    min_probability_move: float = 0.01,
) -> bool:
    liquidity = safe_float(market.get("liquidity"))
    volume = safe_float(market.get("volume"))
    move = abs(safe_float(market.get("probability_change_24h")))
    days = days_to_close(market)

    if liquidity < min_liquidity:
        return False
    if volume < min_volume:
        return False
    if days > max_days_to_close:
        return False
    if not has_clear_resolution(market):
        return False

    has_movement = move >= min_probability_move
    has_high_volume = volume >= 100_000
    has_relevant_category = narrative_category_score(market) >= 8

    return has_movement or has_high_volume or has_relevant_category


def preliminary_market_score(market: dict[str, Any]) -> int:
    volume = safe_float(market.get("volume"))
    liquidity = safe_float(market.get("liquidity"))
    move = abs(safe_float(market.get("probability_change_24h")))
    days = days_to_close(market)

    score = 0
    score += min(int((move / 0.05) * 25), 25)
    score += min(int((volume / 250_000) * 20), 20)
    score += min(int((liquidity / 50_000) * 20), 20)

    if days <= 7:
        score += 8
    elif days <= 30:
        score += 15
    elif days <= 60:
        score += 12
    elif days <= 90:
        score += 8

    score += narrative_category_score(market)
    score += 10 if has_clear_resolution(market) else 0

    return max(0, min(score, 100))


def filter_relevant_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [market for market in markets if is_relevant_market(market)]


def select_top_markets(
    markets: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    relevant = filter_relevant_markets(markets)

    for market in relevant:
        market["preliminary_radar_score"] = preliminary_market_score(market)
        market["days_to_close"] = days_to_close(market)

    relevant.sort(
        key=lambda market: (
            market.get("preliminary_radar_score", 0),
            safe_float(market.get("volume")),
            safe_float(market.get("liquidity")),
        ),
        reverse=True,
    )

    return relevant[:limit]
