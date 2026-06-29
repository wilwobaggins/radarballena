from __future__ import annotations

import re
import unicodedata


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


def _normalize_skill_title(title: str) -> str:
    text = unicodedata.normalize("NFKD", str(title or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"([a-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([a-z])", r"\1 \2", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split()).strip()


def _contains_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def guess_skill_category_from_title(title: str) -> str:
    normalized = _normalize_skill_title(title)
    if not normalized:
        return "unknown"

    word_text = f" {normalized} "
    punctuation_text = f" {normalized.replace(' ', ' ')} "

    esports_patterns = [
        r"\bcounter strike\b",
        r"\bcs2\b",
        r"\bdota\b",
        r"\bvalorant\b",
        r"\bleague of legends\b",
        r"\besports\b",
        r"\bbo1\b",
        r"\bbo3\b",
        r"\bbo5\b",
        r"\bmap 1 winner\b",
        r"\bmap 2 winner\b",
    ]
    sports_patterns = [
        r"\bnba\b",
        r"\bnfl\b",
        r"\bmlb\b",
        r"\bnhl\b",
        r"\bfifa\b",
        r"\bpremier league\b",
        r"\bchampions league\b",
        r"\btennis\b",
        r"\bwimbledon\b",
        r"\batp\b",
        r"\bwta\b",
        r"\bufc\b",
        r"\bboxing\b",
        r"\bspread\b",
        r"\bmoneyline\b",
        r"\bexact score\b",
        r"\bhalftime\b",
        r"\bcorners\b",
        r"\bboth teams to score\b",
        r"\bo\s*\/\s*u\b",
    ]
    politics_patterns = [
        r"\belection\b",
        r"\bpresidential\b",
        r"\bpresident\b",
        r"\bprime minister\b",
        r"\bsenate\b",
        r"\bcongress\b",
        r"\bgov(?:ernor)?\b",
        r"\bnomination\b",
        r"\bcandidate\b",
        r"\bpolitical party\b",
        r"\bapproval rating\b",
        r"\bcabinet\b",
    ]
    geopolitics_patterns = [
        r"\bwar\b",
        r"\bceasefire\b",
        r"\binvasion\b",
        r"\bmilitary strike\b",
        r"\bairstrike\b",
        r"\bsanctions\b",
        r"\bnato\b",
        r"\bnuclear deal\b",
        r"\bregime change\b",
        r"\biran\b",
        r"\bisrael\b",
        r"\bgaza\b",
        r"\bukraine\b",
        r"\brussia\b",
        r"\btaiwan\b",
        r"\bstrait of hormuz\b",
        r"\bmilitary clash\b",
    ]
    macro_patterns = [
        r"\bfed\b",
        r"\bfomc\b",
        r"\binterest rate\b",
        r"\brate cut\b",
        r"\brate hike\b",
        r"\binflation\b",
        r"\bcpi\b",
        r"\bgdp\b",
        r"\brecession\b",
        r"\bunemployment\b",
        r"\bjobs report\b",
        r"\btreasury\b",
        r"\bcrude oil\b",
        r"\bgold\b",
        r"\beconomic growth\b",
    ]
    crypto_patterns = [
        r"\bbitcoin\b",
        r"\bbtc\b",
        r"\bethereum\b",
        r"\beth\b",
        r"\bsolana\b",
        r"\bxrp\b",
        r"\bcrypto\b",
    ]
    culture_patterns = [
        r"\boscars\b",
        r"\bacademy awards\b",
        r"\bemmy\b",
        r"\bgrammy\b",
        r"\bgolden globes\b",
        r"\bbafta\b",
        r"\bbest picture\b",
        r"\bbest actor\b",
        r"\bbest actress\b",
        r"\balbum of the year\b",
        r"\bawards\b",
    ]
    tech_patterns = [
        r"\bopenai\b",
        r"\bchatgpt\b",
        r"\bgemini\b",
        r"\banthropic\b",
        r"\bclaude\b",
        r"\bapple\b",
        r"\bmicrosoft\b",
        r"\bgoogle\b",
        r"\bnvidia\b",
        r"\bartificial intelligence\b",
        r"\bai model\b",
        r"\bmodel release\b",
        r"\btechnology ipo\b",
    ]

    if _contains_any(normalized, geopolitics_patterns):
        return "geopolitics"
    if _contains_any(normalized, esports_patterns):
        return "esports"
    if _contains_any(normalized, sports_patterns) or " vs " in word_text:
        return "sports"
    if _contains_any(normalized, politics_patterns):
        return "politics"
    if _contains_any(normalized, macro_patterns):
        return "macro"
    if _contains_any(normalized, crypto_patterns):
        return "crypto"
    if _contains_any(normalized, culture_patterns):
        return "culture_awards"
    if _contains_any(normalized, tech_patterns):
        return "technology"

    return "unknown"
