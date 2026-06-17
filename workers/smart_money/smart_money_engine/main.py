import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

from market_trail import (
    build_market_capital_trails,
    summarize_market_trails,
)
from related_markets import build_estela_capital_by_market
from storage import save_json
from wallet_classifier import (
    INSUFFICIENT_HISTORY,
    SIGNAL_WALLET,
    WHALE_BUT_NOISY,
)
from wallet_metrics import compute_wallet_scores


load_dotenv()

DATA_API = "https://data-api.polymarket.com"
MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", "250"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "168"))
PAGE_LIMIT = int(os.getenv("PAGE_LIMIT", "1000"))
MAX_OFFSET = int(os.getenv("MAX_OFFSET", "4000"))


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def pick_wallet(activity: dict[str, Any]) -> Optional[str]:
    for key in ["proxyWallet", "wallet", "user", "address", "trader"]:
        value = activity.get(key)
        if isinstance(value, str) and value.startswith("0x"):
            return value.lower()
    return None


def pick_market_id(activity: dict[str, Any]) -> Optional[str]:
    for key in ["market", "marketId", "conditionId", "condition_id"]:
        value = activity.get(key)
        if value:
            return str(value)
    return None


def pick_timestamp(activity: dict[str, Any]) -> Optional[datetime]:
    value = activity.get("timestamp") or activity.get("time") or activity.get("createdAt")
    if value is None:
        return None

    try:
        if isinstance(value, (int, float)):
            if value > 10_000_000_000:
                value = value / 1000
            return datetime.fromtimestamp(value, tz=timezone.utc)

        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None

    return None


def normalize_title(title: Optional[str]) -> str:
    return (title or "").strip()


def is_short_term_noise_market(title: str) -> bool:
    lowered = title.lower()

    if "up or down" in lowered:
        return True

    time_window_tokens = [
        "am-",
        "pm-",
        ":00-",
        ":05-",
        ":10-",
        ":15-",
        ":20-",
        ":25-",
        ":30-",
        ":35-",
        ":40-",
        ":45-",
        ":50-",
        ":55-",
    ]

    if any(token in lowered for token in time_window_tokens) and (
        "bitcoin" in lowered or "ethereum" in lowered or "btc" in lowered or "eth" in lowered
    ):
        return True

    return False


def guess_category_from_title(title: str) -> str:
    lowered = title.lower()

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


def normalize_activity(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    wallet = pick_wallet(row)
    if not wallet:
        return None

    size_usd = (
        parse_float(row.get("usdcSize"))
        or parse_float(row.get("size"))
        or parse_float(row.get("amount"))
        or parse_float(row.get("value"))
    )

    price = parse_float(row.get("price"), default=0.0)
    timestamp = pick_timestamp(row)
    title = normalize_title(row.get("title") or row.get("marketTitle") or row.get("slug"))

    if is_short_term_noise_market(title):
        return None

    return {
        "wallet": wallet,
        "market_id": pick_market_id(row),
        "side": row.get("side") or row.get("type") or row.get("action"),
        "outcome": row.get("outcome") or row.get("answer"),
        "title": title,
        "category_guess": guess_category_from_title(title),
        "size_usd": size_usd,
        "price": price,
        "timestamp": timestamp,
        "raw": row,
    }


async def fetch_recent_activity() -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=25) as http:
        for offset in range(0, MAX_OFFSET, PAGE_LIMIT):
            params = {
                "limit": PAGE_LIMIT,
                "offset": offset,
                "takerOnly": False,
            }

            try:
                response = await http.get(f"{DATA_API}/trades", params=params)
            except httpx.HTTPError as exc:
                print(f"Stopping pagination: request error at offset={offset}: {exc}")
                break

            if response.status_code == 400:
                print(f"Stopping pagination: 400 at offset={offset}")
                break

            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"Stopping pagination: response error at offset={offset}: {exc}")
                break
            data = response.json()

            if isinstance(data, dict):
                items = data.get("data") or data.get("items") or data.get("trades") or []
            else:
                items = data

            print(f"offset={offset} raw_items={len(items)}")

            if not items:
                break

            all_items.extend(items)

    normalized: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    for item in all_items:
        row = normalize_activity(item)
        if not row:
            continue
        if row["timestamp"] and row["timestamp"] < cutoff:
            continue
        if row["size_usd"] < MIN_TRADE_USD:
            continue
        normalized.append(row)

    return normalized


def dedupe_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    clean: list[dict[str, Any]] = []

    for trade in trades:
        key = (
            trade.get("wallet"),
            trade.get("market_id"),
            trade.get("side"),
            trade.get("outcome"),
            round(float(trade.get("size_usd") or 0.0), 4),
            round(float(trade.get("price") or 0.0), 6),
        )

        if key in seen:
            continue

        seen.add(key)
        clean.append(trade)

    return clean


async def run() -> list[dict]:
    trades = await fetch_recent_activity()
    deduped_trades = dedupe_trades(trades)
    wallet_scores = compute_wallet_scores(deduped_trades)
    save_json("wallet_scores.json", wallet_scores)
    noise_scores = [
        {
            "wallet": score["wallet"],
            "noiseScore": score.get("noiseScore", 0),
            "noiseLevel": score.get("noiseLevel", "LOW_NOISE"),
            "riskFlags": score.get("riskFlags", []),
            "generatedAt": score.get("generatedAt"),
        }
        for score in wallet_scores
    ]
    save_json("noise_scores.json", noise_scores)
    market_trails = build_market_capital_trails(
        trades=deduped_trades,
        wallet_scores=wallet_scores,
    )
    save_json("market_capital_trails.json", market_trails)
    estela_capital = build_estela_capital_by_market(
        trades=deduped_trades,
        market_trails=market_trails,
        wallet_scores=wallet_scores,
    )
    save_json("estela_capital_by_market.json", estela_capital)
    return wallet_scores


def log_summary(wallet_scores: list[dict]) -> None:
    counts = Counter(score["classification"] for score in wallet_scores)
    noise_counts = Counter(score.get("noiseLevel", "LOW_NOISE") for score in wallet_scores)
    print("wallets_scored:", len(wallet_scores))
    print("wallets_noise_scored:", len(wallet_scores))
    print("low_noise:", noise_counts.get("LOW_NOISE", 0))
    print("medium_noise:", noise_counts.get("MEDIUM_NOISE", 0))
    print("high_noise:", noise_counts.get("HIGH_NOISE", 0))
    print("signal_wallets:", counts.get(SIGNAL_WALLET, 0))
    print("noisy_wallets:", counts.get(WHALE_BUT_NOISY, 0))
    print("insufficient_history:", counts.get(INSUFFICIENT_HISTORY, 0))


def log_market_trail_summary(market_trails: list[dict]) -> None:
    summary = summarize_market_trails(market_trails)
    print("markets_scored:", summary["markets_scored"])
    print("direct_strong:", summary["direct_strong"])
    print("direct_weak:", summary["direct_weak"])
    print("contradictory_flow:", summary["contradictory_flow"])
    print("no_reliable_trail:", summary["no_reliable_trail"])


async def main() -> None:
    trades = await fetch_recent_activity()
    deduped_trades = dedupe_trades(trades)
    wallet_scores = compute_wallet_scores(deduped_trades)
    save_json("wallet_scores.json", wallet_scores)
    noise_scores = [
        {
            "wallet": score["wallet"],
            "noiseScore": score.get("noiseScore", 0),
            "noiseLevel": score.get("noiseLevel", "LOW_NOISE"),
            "riskFlags": score.get("riskFlags", []),
            "generatedAt": score.get("generatedAt"),
        }
        for score in wallet_scores
    ]
    save_json("noise_scores.json", noise_scores)
    market_trails = build_market_capital_trails(
        trades=deduped_trades,
        wallet_scores=wallet_scores,
    )
    save_json("market_capital_trails.json", market_trails)
    estela_capital = build_estela_capital_by_market(
        trades=deduped_trades,
        market_trails=market_trails,
        wallet_scores=wallet_scores,
    )
    save_json("estela_capital_by_market.json", estela_capital)
    log_summary(wallet_scores)
    log_market_trail_summary(market_trails)


if __name__ == "__main__":
    asyncio.run(main())
