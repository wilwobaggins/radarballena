from __future__ import annotations


def guess_category_from_title(title: str) -> str:
    lowered = (title or "").lower()

    sports_terms = [
        "nba",
        "nfl",
        "mlb",
        "nhl",
        "soccer",
        "tennis",
        "open",
        "league",
        " vs ",
        "vs.",
        "ipl",
        "cricket",
        "ufc",
        "fight",
        "game",
        "match",
    ]
    crypto_terms = ["bitcoin", "btc", "ethereum", "eth", "solana", "xrp", "crypto"]
    politics_terms = ["trump", "biden", "election", "senate", "congress", "president", "poll"]
    macro_terms = ["fed", "fomc", "rate", "inflation", "cpi", "recession", "gdp"]

    if any(term in lowered for term in sports_terms):
        return "sports"
    if any(term in lowered for term in crypto_terms):
        return "crypto"
    if any(term in lowered for term in politics_terms):
        return "politics"
    if any(term in lowered for term in macro_terms):
        return "macro"

    return "unknown"
