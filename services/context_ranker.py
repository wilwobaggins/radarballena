from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


OFFICIAL_DOMAINS = {
    "fifa.com",
    "nba.com",
    "nfl.com",
    "nhl.com",
    "mlb.com",
    "whitehouse.gov",
    "congress.gov",
    "federalreserve.gov",
    "sec.gov",
    "cftc.gov",
    "treasury.gov",
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bloomberg.com",
    "ft.com",
}


LOW_QUALITY_DOMAINS = {
    "reddit.com",
    "x.com",
    "twitter.com",
    "facebook.com",
    "tiktok.com",
    "pinterest.com",
}


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_text(value: Any) -> str:
    return str(value or "").lower().strip()


def get_domain(url: str | None) -> str:
    if not url:
        return ""

    parsed = urlparse(url)
    domain = parsed.netloc.lower()

    if domain.startswith("www."):
        domain = domain[4:]

    return domain


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


def days_old(source: dict[str, Any]) -> int | None:
    published = parse_date(
        source.get("published_date")
        or source.get("publishedDate")
    )

    if published is None:
        return None

    return max((datetime.now(timezone.utc) - published).days, 0)


def tokenize(text: str) -> set[str]:
    stopwords = {
        "the",
        "a",
        "an",
        "will",
        "win",
        "before",
        "after",
        "by",
        "in",
        "on",
        "of",
        "for",
        "to",
        "and",
        "or",
        "market",
        "prediction",
        "latest",
        "context",
    }

    clean = (
        text.lower()
        .replace("?", " ")
        .replace(",", " ")
        .replace(".", " ")
        .replace(":", " ")
        .replace("-", " ")
        .replace("/", " ")
    )

    return {
        token
        for token in clean.split()
        if len(token) >= 3 and token not in stopwords
    }


def semantic_overlap_score(market: dict[str, Any], source: dict[str, Any]) -> float:
    market_text = " ".join(
        [
            str(market.get("title") or ""),
            str(market.get("description") or ""),
            str(market.get("category") or ""),
        ]
    )

    source_text = " ".join(
        [
            str(source.get("source_title") or source.get("sourceTitle") or source.get("title") or ""),
            str(source.get("summary") or ""),
            str(source.get("source_url") or source.get("sourceUrl") or source.get("url") or ""),
        ]
    )

    market_tokens = tokenize(market_text)
    source_tokens = tokenize(source_text)

    if not market_tokens or not source_tokens:
        return 0.0

    overlap = market_tokens.intersection(source_tokens)

    return len(overlap) / len(market_tokens)


def official_source_bonus(source: dict[str, Any]) -> float:
    url = source.get("source_url") or source.get("sourceUrl") or source.get("url")
    domain = get_domain(url)

    if not domain:
        return 0.0

    if domain in OFFICIAL_DOMAINS:
        return 0.20

    if any(domain.endswith(f".{official}") for official in OFFICIAL_DOMAINS):
        return 0.20

    return 0.0


def low_quality_penalty(source: dict[str, Any]) -> float:
    url = source.get("source_url") or source.get("sourceUrl") or source.get("url")
    domain = get_domain(url)

    if not domain:
        return -0.10

    if domain in LOW_QUALITY_DOMAINS:
        return -0.25

    if any(domain.endswith(f".{bad}") for bad in LOW_QUALITY_DOMAINS):
        return -0.25

    return 0.0


def recency_score(source: dict[str, Any]) -> float:
    age = days_old(source)

    if age is None:
        return 0.05

    if age <= 7:
        return 0.20

    if age <= 30:
        return 0.15

    if age <= 90:
        return 0.08

    if age <= 365:
        return 0.03

    return -0.10


def source_base_score(source: dict[str, Any]) -> float:
    return safe_float(
        source.get("relevance_score")
        or source.get("relevanceScore")
        or source.get("score"),
        0.50,
    )


def calculate_source_relevance_score(
    market: dict[str, Any],
    source: dict[str, Any],
) -> float:
    base = source_base_score(source)
    semantic = semantic_overlap_score(market, source)
    recency = recency_score(source)
    official = official_source_bonus(source)
    low_quality = low_quality_penalty(source)

    final_score = (
        0.45 * base
        + 0.30 * semantic
        + recency
        + official
        + low_quality
    )

    return round(max(0.0, min(final_score, 1.0)), 4)


def source_key(source: dict[str, Any]) -> str:
    url = (
        source.get("source_url")
        or source.get("sourceUrl")
        or source.get("url")
        or ""
    )

    title = (
        source.get("source_title")
        or source.get("sourceTitle")
        or source.get("title")
        or ""
    )

    if url:
        return normalize_text(url)

    return normalize_text(title)


def dedupe_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    clean = []

    for source in sources:
        key = source_key(source)

        if not key:
            continue

        if key in seen:
            continue

        seen.add(key)
        clean.append(source)

    return clean


def rank_context_sources(
    market: dict[str, Any],
    sources: list[dict[str, Any]],
    limit: int = 3,
) -> list[dict[str, Any]]:
    unique_sources = dedupe_sources(sources)

    ranked = []

    for source in unique_sources:
        score = calculate_source_relevance_score(market, source)

        source_copy = dict(source)
        source_copy["relevance_score"] = score
        source_copy["relevanceScore"] = score

        ranked.append(source_copy)

    ranked.sort(
        key=lambda item: item.get("relevance_score", 0),
        reverse=True,
    )

    return ranked[:limit]