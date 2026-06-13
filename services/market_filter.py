import json
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from services.category_filter import (
    BLOCKED_DEEPENGINE_CATEGORIES,
    classify_deepengine_category,
    filter_deepengine_eligible_markets,
    market_text,
    summarize_exclusions,
)
from services.scoring_service import (
    days_to_close,
    get_market_value,
    parse_date,
    safe_float,
    score_markets,
    sort_markets_by_score,
)


CLOSE_DATE_KEYS = (
    "close_date",
    "closeDate",
    "closing_date",
    "closingDate",
    "end_date",
    "endDate",
    "endDateIso",
    "end_date_iso",
)

NOVELTY_TITLE_PATTERNS = (
    "lebron james",
    "mrbeast",
    "george clooney",
    "barack obama",
    "michelle obama",
    "hillary clinton",
    "celebrity",
)

NOVELTY_KEYWORDS = {
    "celebrity",
    "viral",
    "meme",
    "novelty",
    "gimmick",
    "influencer",
    "actor",
    "actress",
    "youtube",
}

CATALYST_KEYWORDS = {
    "earnings",
    "debate",
    "vote",
    "hearing",
    "approval",
    "decision",
    "deadline",
    "launch",
    "release",
    "meeting",
    "cpi",
    "fed",
    "fomc",
    "inflation",
    "tariff",
    "treaty",
    "ceasefire",
    "summit",
    "sanctions",
    "lawsuit",
    "ruling",
    "guidance",
    "upgrade",
    "downgrade",
    "etf",
    "conference",
    "report",
    "jobs report",
    "election",
    "primary",
    "referendum",
    "regulation",
    "bill",
    "fda",
}


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


def coerce_optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value

    if value is None or value == "":
        return None

    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        return None

    if isinstance(value, str):
        normalized = value.strip().lower()

        if normalized in {"true", "1", "yes"}:
            return True

        if normalized in {"false", "0", "no"}:
            return False

    return None


def get_market_close_date(market: dict[str, Any]) -> datetime | None:
    close_date_value = get_market_value(market, *CLOSE_DATE_KEYS)
    return parse_date(close_date_value)


def get_market_open_status(
    market: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    reference_now = now or datetime.now(timezone.utc)
    reasons: list[str] = []
    flags: dict[str, Any] = {}

    close_date = get_market_close_date(market)
    if close_date is not None and close_date <= reference_now:
        reasons.append("closed_by_date")
        flags["close_date"] = close_date.isoformat()

    closed_flag = coerce_optional_bool(get_market_value(market, "closed"))
    if closed_flag is True:
        reasons.append("closed_by_flag")
        flags["closed"] = True

    archived_flag = coerce_optional_bool(get_market_value(market, "archived"))
    if archived_flag is True:
        reasons.append("closed_by_flag")
        flags["archived"] = True

    active_flag = coerce_optional_bool(get_market_value(market, "active"))
    if active_flag is False:
        reasons.append("inactive_market_excluded")
        flags["active"] = False

    accepting_orders_flag = coerce_optional_bool(
        get_market_value(market, "acceptingOrders")
    )
    if accepting_orders_flag is False:
        reasons.append("closed_by_flag")
        flags["acceptingOrders"] = False

    deduped_reasons = sorted(set(reasons))

    return {
        "is_open": not deduped_reasons,
        "reasons": deduped_reasons,
        "flags": flags,
    }


def is_market_open(
    market: dict[str, Any],
    now: datetime | None = None,
) -> bool:
    return bool(get_market_open_status(market=market, now=now)["is_open"])


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
    if not is_market_open(market):
        return False

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


def get_market_text(market: dict[str, Any]) -> str:
    return market_text(market)


def is_novelty_market(market: dict[str, Any]) -> bool:
    text = get_market_text(market)

    if any(pattern in text for pattern in NOVELTY_TITLE_PATTERNS):
        return True

    return any(keyword in text for keyword in NOVELTY_KEYWORDS)


def has_catalyst_context(market: dict[str, Any]) -> bool:
    text = get_market_text(market)
    return any(keyword in text for keyword in CATALYST_KEYWORDS)


def has_strong_movement(
    market: dict[str, Any],
    min_probability_move: float,
) -> bool:
    probability_move = abs(safe_float(market.get("probability_change_24h")))
    return probability_move >= max(min_probability_move * 2, 0.03)


def assess_market_relevance(
    market: dict[str, Any],
    min_liquidity: float = 500,
    min_volume: float = 1_000,
    max_days_to_close: int = 1200,
    min_probability_move: float = 0.01,
) -> dict[str, Any]:
    classification = classify_deepengine_category(market)

    if not classification["eligible"]:
        return {
            "is_relevant": False,
            "reasons": [],
            "exclusion_reason": "ineligible_category",
            "is_novelty": False,
        }

    if not passes_basic_market_quality(
        market=market,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
        max_days_to_close=max_days_to_close,
    ):
        return {
            "is_relevant": False,
            "reasons": [],
            "exclusion_reason": "basic_quality_failed",
            "is_novelty": is_novelty_market(market),
        }

    volume = safe_float(market.get("volume"))
    liquidity = safe_float(market.get("liquidity"))
    probability_move = abs(safe_float(market.get("probability_change_24h")))
    category = classification["category"]
    novelty_market = is_novelty_market(market)
    catalyst_context = has_catalyst_context(market)

    reasons: list[str] = []

    if probability_move >= min_probability_move:
        reasons.append("probability_move")

    if volume >= 100_000:
        reasons.append("high_volume")

    if liquidity >= 25_000 and volume >= 25_000:
        reasons.append("liquidity_and_volume")

    if category in {
        "politics",
        "macro",
        "geopolitics",
        "crypto",
        "technology",
        "ai",
        "regulation",
        "business",
        "culture",
        "science",
        "world_events",
        "economy",
    } and catalyst_context:
        reasons.append("strategic_context")

    strong_movement = has_strong_movement(
        market=market,
        min_probability_move=min_probability_move,
    )

    if novelty_market and not strong_movement:
        return {
            "is_relevant": False,
            "reasons": reasons,
            "exclusion_reason": "novelty_without_catalyst",
            "is_novelty": True,
        }

    if not reasons:
        return {
            "is_relevant": False,
            "reasons": [],
            "exclusion_reason": "no_real_interest_signal",
            "is_novelty": novelty_market,
        }

    return {
        "is_relevant": True,
        "reasons": reasons,
        "exclusion_reason": None,
        "is_novelty": novelty_market,
    }


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
    El filtro de categorias se aplica antes en filter_relevant_markets().
    Esta funcion asume que el mercado ya es elegible para DeepEngine.
    """
    relevance = assess_market_relevance(
        market=market,
        min_liquidity=min_liquidity,
        min_volume=min_volume,
        max_days_to_close=max_days_to_close,
        min_probability_move=min_probability_move,
    )
    return bool(relevance["is_relevant"])


def summarize_open_market_exclusions(
    excluded_markets: list[dict[str, Any]],
) -> dict[str, int]:
    counter = Counter(
        {
            "closed_market_excluded": 0,
            "closed_by_date": 0,
            "closed_by_flag": 0,
            "inactive_market_excluded": 0,
        }
    )

    for market in excluded_markets:
        counter["closed_market_excluded"] += 1

        for reason in set(market.get("market_open_exclusion_reasons") or []):
            counter[reason] += 1

    return dict(counter)


def summarize_category_buckets(excluded_markets: list[dict[str, Any]]) -> dict[str, int]:
    sports_excluded = 0
    unknown_excluded = 0

    for market in excluded_markets:
        category = market.get("deepengine_category") or "category_unknown"
        reason = market.get("deepengine_filter_reason") or "unknown"

        if category in BLOCKED_DEEPENGINE_CATEGORIES or category == "sports":
            sports_excluded += 1
        elif category == "category_unknown" or reason == "ambiguous_category":
            unknown_excluded += 1

    return {
        "sports_market_excluded": sports_excluded,
        "unknown_market_excluded": unknown_excluded,
    }


def filter_relevant_markets_with_stats(
    markets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Primero excluye deportes y categorias incompatibles con DeepEngine MVP.
    Luego excluye mercados cerrados/inactivos y por ultimo aplica
    filtros basicos de liquidez, volumen, cierre y resolucion.
    """
    eligible_markets, category_excluded_markets = filter_deepengine_eligible_markets(
        markets
    )

    if category_excluded_markets:
        print(
            "DeepEngine category filter exclusions:",
            summarize_exclusions(category_excluded_markets),
        )

    open_markets: list[dict[str, Any]] = []
    closed_or_inactive_markets: list[dict[str, Any]] = []
    relevance_excluded_markets: list[dict[str, Any]] = []
    relevant_markets: list[dict[str, Any]] = []

    for market in eligible_markets:
        open_status = get_market_open_status(market)

        if open_status["is_open"]:
            open_markets.append(market)
            continue

        closed_or_inactive_markets.append(
            {
                **market,
                "market_open_exclusion_reasons": open_status["reasons"],
                "market_open_exclusion_flags": open_status["flags"],
            }
        )

    for market in open_markets:
        relevance = assess_market_relevance(market)

        if relevance["is_relevant"]:
            relevant_markets.append(
                {
                    **market,
                    "relevance_reasons": relevance["reasons"],
                    "novelty_market": relevance["is_novelty"],
                }
            )
            continue

        relevance_excluded_markets.append(
            {
                **market,
                "relevance_exclusion_reason": relevance["exclusion_reason"],
                "relevance_reasons": relevance["reasons"],
                "novelty_market": relevance["is_novelty"],
            }
        )

    open_market_summary = summarize_open_market_exclusions(closed_or_inactive_markets)
    category_bucket_summary = summarize_category_buckets(category_excluded_markets)
    relevance_exclusion_summary = Counter(
        market.get("relevance_exclusion_reason") or "unknown"
        for market in relevance_excluded_markets
    )
    quality_excluded = len(relevance_excluded_markets)
    stats = {
        "input_markets": len(markets),
        "category_eligible": len(eligible_markets),
        "category_excluded": len(category_excluded_markets),
        **category_bucket_summary,
        **open_market_summary,
        "quality_market_excluded": quality_excluded,
        "novelty_market_excluded": sum(
            1 for market in relevance_excluded_markets if market.get("novelty_market")
        ),
        "relevance_exclusion_summary": dict(relevance_exclusion_summary),
        "eligible_after_filters": len(relevant_markets),
    }

    if closed_or_inactive_markets:
        print("DeepEngine open-market exclusions:", open_market_summary)

    novelty_exclusions = [
        market.get("title")
        for market in relevance_excluded_markets
        if market.get("novelty_market")
    ]
    if novelty_exclusions:
        print("DeepEngine novelty exclusions:", novelty_exclusions[:10])

    print("DeepEngine filter:", stats)

    return relevant_markets, stats


def filter_relevant_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    relevant_markets, _stats = filter_relevant_markets_with_stats(markets)
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
