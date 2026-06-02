import json
from typing import Any

from services.category_filter import (
    classify_deepengine_category,
    filter_deepengine_eligible_markets,
    summarize_exclusions,
)
from services.scoring_service import (
    score_markets,
    sort_markets_by_score,
    days_to_close,
    safe_float,
)


def get_market_outcomes(market: dict[str, Any]) -> list[Any]:
    outcomes = market.get("outcomes")

    if isinstance(outcomes, list):
        return outcomes

    if isinstance(outcomes, str):
        try:
            parsed = json.loads(outcomes)
            if isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass

    raw_payload = market.get("raw_payload") or {}

    if isinstance(raw_payload, dict):
        raw_outcomes = raw_payload.get("outcomes")

        if isinstance(raw_outcomes, list):
            return raw_outcomes

        if isinstance(raw_outcomes, str):
            try:
                parsed = json.loads(raw_outcomes)
                if isinstance(parsed, list):
                    return parsed
            except json.JSONDecodeError:
                pass

    return []


def has_clear_resolution(market: dict[str, Any]) -> bool:
    title = str(market.get("title") or "").strip()
    outcomes = get_market_outcomes(market)

    if not title:
        return False

    if isinstance(outcomes, list) and len(outcomes) >= 2:
        return True

    title_lower = title.lower()

    if title_lower.startswith("will "):
        return True

    return False


def passes_basic_market_quality(
    market: dict[str, Any],
    min_liquidity: float = 500,
    min_volume: float = 1_000,
    max_days_to_close: int = 1200,
) -> bool:
    liquidity = safe_float(market.get("liquidity"))
    volume = safe_float(market.get("volume"))
    close_days = days_to_close(market)

    if liquidity < min_liquidity:
        return False

    if volume < min_volume:
        return False

    if close_days > max_days_to_close:
        return False

    if not has_clear_resolution(market):
        return False

    return True


def is_relevant_market(
    market: dict[str, Any],
    min_liquidity: float = 500,
    min_volume: float = 1_000,
    max_days_to_close: int = 1200,
    min_probability_move: float = 0.01,
) -> bool:
    """
    Relevancia para DeepEngine MVP.

    Nota:
    El filtro de categorías se aplica antes en filter_relevant_markets().
    Esta función asume que el mercado ya es elegible para DeepEngine.
    """
    classification = classify_deepengine_category(market)

    if not classification["eligible"]:
        return False

    if not passes_basic_market_quality(
        market=market,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
        max_days_to_close=max_days_to_close,
    ):
        return False

    volume = safe_float(market.get("volume"))
    probability_move = abs(safe_float(market.get("probability_change_24h")))

    has_movement = probability_move >= min_probability_move
    has_high_volume = volume >= 100_000
    has_allowed_category = bool(market.get("deepengine_eligible"))

    return has_movement or has_high_volume or has_allowed_category


def filter_relevant_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Primero excluye deportes y categorías incompatibles con DeepEngine MVP.
    Luego aplica filtros básicos de liquidez, volumen, cierre y resolución.
    """
    eligible_markets, excluded_markets = filter_deepengine_eligible_markets(markets)

    if excluded_markets:
        print(
            "DeepEngine category filter exclusions:",
            summarize_exclusions(excluded_markets),
        )

    relevant_markets = [
        market for market in eligible_markets if is_relevant_market(market)
    ]

    print(
        "DeepEngine filter:",
        {
            "input_markets": len(markets),
            "category_eligible": len(eligible_markets),
            "category_excluded": len(excluded_markets),
            "relevant_after_quality_filter": len(relevant_markets),
        },
    )

    return relevant_markets


def select_top_markets(
    markets: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    """
    Filtra mercados compatibles con DeepEngine MVP, calcula
    preliminary_radar_score y ordena por score.

    Los deportes NO entran a OpenAI ni a DeepBriefs.
    """
    relevant_markets = filter_relevant_markets(markets)
    scored_markets = score_markets(relevant_markets)
    sorted_markets = sort_markets_by_score(scored_markets)

    return sorted_markets[:limit]