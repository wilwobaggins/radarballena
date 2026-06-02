from collections import Counter
from typing import Any


ALLOWED_DEEPENGINE_CATEGORIES = {
    "politics",
    "geopolitics",
    "macro",
    "economy",
    "crypto",
    "technology",
    "ai",
    "regulation",
    "business",
    "culture",
    "science",
    "world_events",
}

BLOCKED_DEEPENGINE_CATEGORIES = {
    "sports",
    "football",
    "soccer",
    "basketball",
    "baseball",
    "mma",
    "ufc",
    "boxing",
    "tennis",
    "fantasy",
    "player_props",
    "esports",
    "horse_racing",
}

CATEGORY_ALIASES = {
    "economics": "economy",
    "economic": "economy",
    "finance": "economy",
    "financial": "economy",
    "markets": "economy",
    "world": "world_events",
    "world event": "world_events",
    "world events": "world_events",
    "world_events": "world_events",
    "tech": "technology",
    "artificial intelligence": "ai",
    "regulations": "regulation",
    "legal": "regulation",
    "companies": "business",
    "company": "business",
    "elections": "politics",
    "election": "politics",
    "political": "politics",
}

SPORTS_KEYWORDS = {
    "sports",
    "sport",
    "football",
    "soccer",
    "basketball",
    "baseball",
    "tennis",
    "mma",
    "ufc",
    "boxing",
    "fantasy",
    "player prop",
    "player props",
    "horse racing",
    "esports",
    "e-sports",
    "nfl",
    "nba",
    "mlb",
    "nhl",
    "fifa",
    "world cup",
    "champions league",
    "premier league",
    "laliga",
    "la liga",
    "serie a",
    "bundesliga",
    "ufc",
    "wimbledon",
    "super bowl",
    "march madness",
    "playoffs",
    "tournament",
    "match",
    "game",
    "team",
    "player",
    "lineup",
    "injury",
    "score",
    "goals",
    "points",
    "touchdowns",
    "home runs",
}

ALLOWED_KEYWORDS_BY_CATEGORY = {
    "politics": {
        "trump",
        "biden",
        "president",
        "election",
        "senate",
        "congress",
        "democrat",
        "republican",
        "poll",
        "primary",
        "white house",
        "administration",
    },
    "geopolitics": {
        "war",
        "ceasefire",
        "israel",
        "iran",
        "china",
        "russia",
        "ukraine",
        "nato",
        "gaza",
        "taiwan",
        "sanctions",
        "peace deal",
        "diplomatic",
    },
    "macro": {
        "fed",
        "federal reserve",
        "interest rate",
        "rates",
        "cpi",
        "inflation",
        "recession",
        "gdp",
        "unemployment",
        "jobs report",
        "yield",
    },
    "economy": {
        "economy",
        "tariff",
        "trade deficit",
        "oil",
        "gold",
        "commodities",
        "debt",
        "treasury",
        "dollar",
        "central bank",
    },
    "crypto": {
        "bitcoin",
        "btc",
        "ethereum",
        "eth",
        "crypto",
        "stablecoin",
        "solana",
        "xrp",
        "etf",
    },
    "technology": {
        "nvidia",
        "openai",
        "microsoft",
        "google",
        "apple",
        "meta",
        "tesla",
        "semiconductor",
        "chip",
        "technology",
    },
    "ai": {
        "ai",
        "artificial intelligence",
        "openai",
        "anthropic",
        "llm",
        "chatgpt",
        "agi",
        "model",
    },
    "regulation": {
        "regulation",
        "regulatory",
        "sec",
        "ftc",
        "doj",
        "lawsuit",
        "bill",
        "ban",
        "approval",
        "court",
    },
    "business": {
        "earnings",
        "ipo",
        "merger",
        "acquisition",
        "bankruptcy",
        "company",
        "ceo",
        "stock",
        "shares",
    },
    "culture": {
        "oscars",
        "grammys",
        "movie",
        "album",
        "streaming",
        "viral",
        "culture",
        "celebrity",
    },
    "science": {
        "science",
        "space",
        "nasa",
        "spacex",
        "drug approval",
        "fda",
        "vaccine",
        "climate",
    },
    "world_events": {
        "summit",
        "referendum",
        "strike",
        "protest",
        "natural disaster",
        "public event",
        "international",
    },
}


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_category(category: Any) -> str:
    raw = normalize_text(category).replace("-", "_").replace(" ", "_")

    if not raw:
        return "category_unknown"

    if raw in BLOCKED_DEEPENGINE_CATEGORIES:
        return raw

    if raw in ALLOWED_DEEPENGINE_CATEGORIES:
        return raw

    alias_key = raw.replace("_", " ")
    if alias_key in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[alias_key]

    if raw in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[raw]

    return "category_unknown"


def market_text(market: dict[str, Any]) -> str:
    raw_payload = market.get("raw_payload") or {}

    pieces = [
        market.get("title"),
        market.get("description"),
        market.get("category"),
        raw_payload.get("question") if isinstance(raw_payload, dict) else None,
        raw_payload.get("title") if isinstance(raw_payload, dict) else None,
        raw_payload.get("description") if isinstance(raw_payload, dict) else None,
        raw_payload.get("category") if isinstance(raw_payload, dict) else None,
    ]

    outcomes = market.get("outcomes")
    if isinstance(outcomes, list):
        pieces.extend(outcomes)

    return " ".join(str(piece or "") for piece in pieces).lower()


def find_keyword_matches(text: str, keywords: set[str]) -> list[str]:
    return sorted(keyword for keyword in keywords if keyword in text)


def infer_allowed_category_from_keywords(text: str) -> str:
    matches_by_category: dict[str, int] = {}

    for category, keywords in ALLOWED_KEYWORDS_BY_CATEGORY.items():
        matches = find_keyword_matches(text, keywords)
        if matches:
            matches_by_category[category] = len(matches)

    if not matches_by_category:
        return "category_unknown"

    ranked = sorted(
        matches_by_category.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
        return "category_unknown"

    return ranked[0][0]


def classify_deepengine_category(market: dict[str, Any]) -> dict[str, Any]:
    raw_category = market.get("category")
    normalized_category = normalize_category(raw_category)
    text = market_text(market)

    sports_matches = find_keyword_matches(text, SPORTS_KEYWORDS)

    if normalized_category in BLOCKED_DEEPENGINE_CATEGORIES:
        return {
            "eligible": False,
            "category": normalized_category,
            "reason": "blocked_category",
            "matched_keywords": sports_matches,
        }

    if sports_matches:
        return {
            "eligible": False,
            "category": "sports",
            "reason": "sports_keyword_match",
            "matched_keywords": sports_matches,
        }

    if normalized_category in ALLOWED_DEEPENGINE_CATEGORIES:
        return {
            "eligible": True,
            "category": normalized_category,
            "reason": "allowed_category",
            "matched_keywords": [],
        }

    inferred_category = infer_allowed_category_from_keywords(text)

    if inferred_category in ALLOWED_DEEPENGINE_CATEGORIES:
        return {
            "eligible": True,
            "category": inferred_category,
            "reason": "allowed_keyword_inference",
            "matched_keywords": [],
        }

    return {
        "eligible": False,
        "category": "category_unknown",
        "reason": "ambiguous_category",
        "matched_keywords": [],
    }


def is_deepengine_eligible(market: dict[str, Any]) -> bool:
    return bool(classify_deepengine_category(market)["eligible"])


def with_deepengine_category(market: dict[str, Any]) -> dict[str, Any]:
    classification = classify_deepengine_category(market)

    return {
        **market,
        "category": classification["category"],
        "deepengine_category": classification["category"],
        "deepengine_eligible": classification["eligible"],
        "deepengine_filter_reason": classification["reason"],
        "deepengine_filter_keywords": classification["matched_keywords"],
    }


def filter_deepengine_eligible_markets(
    markets: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    eligible: list[dict[str, Any]] = []
    excluded: list[dict[str, Any]] = []

    for market in markets:
        annotated = with_deepengine_category(market)

        if annotated["deepengine_eligible"]:
            eligible.append(annotated)
        else:
            excluded.append(annotated)

    return eligible, excluded


def summarize_exclusions(excluded_markets: list[dict[str, Any]]) -> dict[str, int]:
    counter = Counter()

    for market in excluded_markets:
        category = market.get("deepengine_category") or "category_unknown"
        reason = market.get("deepengine_filter_reason") or "unknown"
        counter[f"{category}:{reason}"] += 1

    return dict(counter)

def map_to_classifier_output_category(category: str) -> str:
    """
    Convierte categorías internas del filtro DeepEngine
    al output v1 pedido por la tarjeta.
    """
    if category in {
        "sports",
        "football",
        "soccer",
        "basketball",
        "baseball",
        "mma",
        "ufc",
        "boxing",
        "tennis",
        "fantasy",
        "player_props",
        "esports",
        "horse_racing",
    }:
        return "sports"

    if category == "politics":
        return "politics"

    if category == "geopolitics":
        return "geopolitics"

    if category in {"macro", "economy"}:
        return "macro"

    if category == "crypto":
        return "crypto"

    if category in {"technology", "ai", "regulation", "business", "science"}:
        return "technology"

    if category in {"culture", "world_events"}:
        return "culture"

    return "other"


def classify_market(market: dict[str, Any]) -> dict[str, Any]:
    """
    Clasificador v1 para DeepEngine MVP.

    Output esperado:
    {
        "category": "...",
        "isDeepEngineEligible": bool,
        "exclusionReason": str | None
    }
    """
    classification = classify_deepengine_category(market)

    output_category = map_to_classifier_output_category(
        classification.get("category", "category_unknown")
    )

    is_eligible = bool(classification.get("eligible"))

    result = {
        "category": output_category,
        "isDeepEngineEligible": is_eligible,
    }

    if not is_eligible:
        result["exclusionReason"] = classification.get("reason", "not_eligible")

    return result


def classifyMarket(market: dict[str, Any]) -> dict[str, Any]:
    """
    Alias camelCase para cumplir literalmente la tarjeta.
    En Python el uso interno recomendado sigue siendo classify_market().
    """
    return classify_market(market)