import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple, Literal

import httpx
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

load_dotenv()

DATA_API = "https://data-api.polymarket.com"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# Output / worker mode
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
STATE_FILE_NAME = os.getenv("STATE_FILE_NAME", "state.json")
WHALE_FINDER_MODE = os.getenv("WHALE_FINDER_MODE", "worker").lower()  # worker | once
RUN_ON_START = os.getenv("RUN_ON_START", "true").lower() == "true"

# Cadence
ACTIVE_HEALTH_INTERVAL_SECONDS = int(os.getenv("ACTIVE_HEALTH_INTERVAL_SECONDS", "14400"))  # 4h
DISCOVERY_INTERVAL_SECONDS = int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "86400"))          # 24h
WORKER_SLEEP_SECONDS = int(os.getenv("WORKER_SLEEP_SECONDS", "300"))                       # 5min

# API / filters
MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", "250"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "168"))
MAX_CANDIDATES_FOR_AI = int(os.getenv("MAX_CANDIDATES_FOR_AI", "20"))

# Pagination: keep this conservative. Some offsets can return 400.
PAGE_LIMIT = int(os.getenv("PAGE_LIMIT", "1000"))
MAX_OFFSET = int(os.getenv("MAX_OFFSET", "4000"))
HTTP_TIMEOUT_SECONDS = int(os.getenv("HTTP_TIMEOUT_SECONDS", "25"))

# Discovery quality gates
MIN_APPROVE_TRADES = int(os.getenv("MIN_APPROVE_TRADES", "10"))
MIN_APPROVE_MARKETS = int(os.getenv("MIN_APPROVE_MARKETS", "5"))
MIN_APPROVE_VOLUME = float(os.getenv("MIN_APPROVE_VOLUME", "5000"))

# AI behavior
AI_REVIEW_ACTIVE = os.getenv("AI_REVIEW_ACTIVE", "true").lower() == "true"
AI_REVIEW_CANDIDATES = os.getenv("AI_REVIEW_CANDIDATES", "true").lower() == "true"
REQUIRE_AI_APPROVAL_FOR_REPLACEMENT = (
    os.getenv("REQUIRE_AI_APPROVAL_FOR_REPLACEMENT", "true").lower() == "true"
)
MIN_AI_REPLACEMENT_CONFIDENCE = int(os.getenv("MIN_AI_REPLACEMENT_CONFIDENCE", "70"))

ACTIVE_WALLETS = {
    "nba_volume": {
        "name": "NBA Volume Trader Theta",
        "wallet": "0x32ed517a571c01b6e9adecf61ba81ca48ff2f960",
        "min_usdc": 200,
        "profile": "sports",
    },
    "sports_arb": {
        "name": "Global Sports Arb Lambda",
        "wallet": "0x479e330b07822ee28e20bac5e504f1b7c6b591c3",
        "min_usdc": 500,
        "profile": "sports",
    },
    "global_trader": {
        "name": "Everything Trader Zeta",
        "wallet": "0x9d84ce0306f8551e02efef1680475fc0f1dc1344",
        "min_usdc": 300,
        "profile": "mixed",
    },
    "macro_economics": {
        "name": "Macro Economics Whale",
        "wallet": "0xc8ab97a9089a9ff7e6ef0688e6e591a066946418",
        "min_usdc": 150,
        "profile": "macro",
    },
    "geo_macro": {
        "name": "Geopolitical Macro Whale",
        "wallet": "0xbacd00c9080a82ded56f504ee8810af732b0ab35",
        "min_usdc": 150,
        "profile": "politics",
    },
    "sports_esports_titan": {
        "name": "Soccer Esports Titan Alpha",
        "wallet": "0x2663daca3cecf3767ca1c3b126002a8578a8ed1f",
        "min_usdc": 175,
        "profile": "sports",
    },
}

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


class AIWalletReview(BaseModel):
    recommendation: Literal["approve", "watch", "reject"]
    confidence: int = Field(description="0 to 100")
    category_guess: str
    health_verdict: Literal["healthy", "watch", "degraded", "inactive"]
    replacement_readiness: Literal["none", "watch_only", "candidate_replace"]
    risk_flags: List[str]
    strengths: List[str]
    weaknesses: List[str]
    reason: str
    suggested_action: str


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return now_utc().isoformat()


def ensure_output_dir() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def output_path(filename: str) -> str:
    ensure_output_dir()
    return os.path.join(OUTPUT_DIR, filename)


def save_json(filename: str, data: Any) -> None:
    """
    Atomic-ish JSON write:
    writes to .tmp first, then replaces final file.
    This prevents half-written JSONs if the process dies mid-write.
    """
    path = output_path(filename)
    tmp_path = f"{path}.tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    os.replace(tmp_path, path)


def load_json(filename: str, default: Any) -> Any:
    path = output_path(filename)
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        print(f"Could not load {filename}: {exc}")
        return default


def load_state() -> Dict[str, Any]:
    return load_json(STATE_FILE_NAME, {})


def save_state(state: Dict[str, Any]) -> None:
    state["updated_at"] = iso_now()
    save_json(STATE_FILE_NAME, state)


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None

    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def pick_wallet(activity: Dict[str, Any]) -> Optional[str]:
    for key in ["proxyWallet", "wallet", "user", "address", "trader"]:
        value = activity.get(key)
        if isinstance(value, str) and value.startswith("0x"):
            return value.lower()
    return None


def pick_market_id(activity: Dict[str, Any]) -> Optional[str]:
    for key in ["market", "marketId", "conditionId", "condition_id"]:
        value = activity.get(key)
        if value:
            return str(value)
    return None


def pick_timestamp(activity: Dict[str, Any]) -> Optional[datetime]:
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
    """
    Excludes micro-timeframe markets like:
    - Bitcoin Up or Down - May 18, 1:20PM-1:25PM ET
    - Ethereum Up or Down...
    These are noisy for RadarBallena discovery because they often attract scalpers/hedgers.
    """
    t = title.lower()

    if "up or down" in t:
        return True

    time_window_tokens = [
        "am-", "pm-", ":00-", ":05-", ":10-", ":15-", ":20-", ":25-",
        ":30-", ":35-", ":40-", ":45-", ":50-", ":55-",
    ]

    if any(token in t for token in time_window_tokens) and (
        "bitcoin" in t or "ethereum" in t or "btc" in t or "eth" in t
    ):
        return True

    return False


def guess_category_from_title(title: str) -> str:
    t = title.lower()

    sports_terms = [
        "nba", "nfl", "mlb", "nhl", "soccer", "tennis", "open", "league",
        " vs ", "vs.", "ipl", "cricket", "ufc", "fight", "game", "match",
    ]
    crypto_terms = ["bitcoin", "btc", "ethereum", "eth", "solana", "xrp", "crypto"]
    politics_terms = ["trump", "biden", "election", "senate", "congress", "president", "poll"]
    macro_terms = ["fed", "fomc", "rate", "inflation", "cpi", "recession", "gdp"]

    if any(x in t for x in sports_terms):
        return "sports"
    if any(x in t for x in crypto_terms):
        return "crypto"
    if any(x in t for x in politics_terms):
        return "politics"
    if any(x in t for x in macro_terms):
        return "macro"

    return "unknown"


def normalize_activity(row: Dict[str, Any]) -> Optional[Dict[str, Any]]:
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


async def fetch_recent_activity() -> List[Dict[str, Any]]:
    """
    Fetches recent trades from Polymarket Data API.

    Notes:
    - /trades supports limit, offset and takerOnly.
    - Some high offsets can return 400. We stop instead of crashing.
    - takerOnly=false includes maker fills too, which is better for discovery.
    """
    all_items: List[Dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        for offset in range(0, MAX_OFFSET, PAGE_LIMIT):
            params = {
                "limit": PAGE_LIMIT,
                "offset": offset,
                "takerOnly": False,
            }

            res = await http.get(f"{DATA_API}/trades", params=params)

            if res.status_code == 400:
                print(f"Stopping pagination: 400 at offset={offset}")
                break

            res.raise_for_status()
            data = res.json()

            if isinstance(data, dict):
                items = data.get("data") or data.get("items") or data.get("trades") or []
            else:
                items = data

            print(f"offset={offset} raw_items={len(items)}")

            if not items:
                break

            if offset == 0 and items:
                print("\nSample raw trade keys:")
                print(list(items[0].keys()))
                print()

            all_items.extend(items)

    print(f"Raw trades fetched: {len(all_items)}")

    normalized: List[Dict[str, Any]] = []
    cutoff = now_utc() - timedelta(hours=LOOKBACK_HOURS)

    dropped_old = 0
    dropped_small = 0
    dropped_invalid = 0

    for item in all_items:
        row = normalize_activity(item)
        if not row:
            dropped_invalid += 1
            continue

        if row["timestamp"] and row["timestamp"] < cutoff:
            dropped_old += 1
            continue

        if row["size_usd"] < MIN_TRADE_USD:
            dropped_small += 1
            continue

        normalized.append(row)

    print(f"Dropped invalid/noise: {dropped_invalid}")
    print(f"Dropped old: {dropped_old}")
    print(f"Dropped small: {dropped_small}")

    return normalized


async def fetch_wallet_trades(wallet: str, min_trade_usd: Optional[float] = None) -> List[Dict[str, Any]]:
    all_items: List[Dict[str, Any]] = []
    min_trade = MIN_TRADE_USD if min_trade_usd is None else float(min_trade_usd)

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as http:
        for offset in range(0, MAX_OFFSET, PAGE_LIMIT):
            params = {
                "user": wallet,
                "limit": PAGE_LIMIT,
                "offset": offset,
                "takerOnly": False,
            }

            res = await http.get(f"{DATA_API}/trades", params=params)

            if res.status_code == 400:
                print(f"Stopping wallet pagination: wallet={wallet} offset={offset}")
                break

            res.raise_for_status()
            data = res.json()

            if isinstance(data, dict):
                items = data.get("data") or data.get("items") or data.get("trades") or []
            else:
                items = data

            if not items:
                break

            all_items.extend(items)

    normalized: List[Dict[str, Any]] = []
    cutoff = now_utc() - timedelta(hours=LOOKBACK_HOURS)

    for item in all_items:
        row = normalize_activity(item)
        if not row:
            continue
        if row["timestamp"] and row["timestamp"] < cutoff:
            continue
        if row["size_usd"] < min_trade:
            continue
        normalized.append(row)

    return normalized


def count_opposing_outcome_markets(g: pd.DataFrame) -> Tuple[int, List[str]]:
    """
    Counts markets where the same wallet traded more than one outcome.
    This is a strong hedge/arb/noise signal.
    """
    bad_markets: List[str] = []

    for market_id, mg in g.groupby("market_id"):
        outcomes = set(str(x).lower() for x in mg["outcome"].dropna().unique())
        if len(outcomes) >= 2:
            bad_markets.append(str(market_id))

    return len(bad_markets), bad_markets


def dominant_category(g: pd.DataFrame) -> str:
    values = [x for x in g["category_guess"].dropna().tolist() if x and x != "unknown"]
    if not values:
        return "unknown"

    counts = pd.Series(values).value_counts()
    return str(counts.index[0])


def compute_wallet_metrics(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not trades:
        return []

    df = pd.DataFrame(trades)

    grouped: List[Dict[str, Any]] = []

    for wallet, g in df.groupby("wallet"):
        trade_count = len(g)
        total_volume = float(g["size_usd"].sum())
        avg_size = float(g["size_usd"].mean())
        max_size = float(g["size_usd"].max())

        unique_markets = int(g["market_id"].nunique(dropna=True))

        prices_without_zero = g["price"].replace(0, pd.NA).dropna()
        avg_price = float(prices_without_zero.mean()) if len(prices_without_zero) else 0.0

        early_entries = int(((g["price"] > 0.05) & (g["price"] < 0.65)).sum())
        late_entries = int((g["price"] >= 0.85).sum())
        late_entry_ratio = late_entries / trade_count if trade_count else 0.0

        low_price_trades = int((g["price"] <= 0.05).sum())
        low_price_ratio = low_price_trades / trade_count if trade_count else 0.0

        sell_trades = int((g["side"].astype(str).str.upper() == "SELL").sum())
        sell_ratio = sell_trades / trade_count if trade_count else 0.0

        extreme_price_volume = float(
            g[(g["price"] <= 0.05) | (g["price"] >= 0.95)]["size_usd"].sum()
        )
        extreme_price_volume_ratio = extreme_price_volume / total_volume if total_volume else 0.0

        market_repeats = trade_count - unique_markets
        concentration = max_size / total_volume if total_volume > 0 else 0.0
        opposing_market_count, opposing_markets = count_opposing_outcome_markets(g)
        opposing_market_ratio = opposing_market_count / unique_markets if unique_markets else 0.0
        category = dominant_category(g)

        score = 0.0

        # Positive signals
        score += min(25, total_volume / 1000)
        score += min(20, trade_count * 2)
        score += min(15, avg_size / 400)
        score += min(15, early_entries * 2.5)
        score += min(10, unique_markets * 1.5)

        if unique_markets >= 3:
            score += min(10, market_repeats * 1.5)

        # Penalties
        if late_entries >= max(2, trade_count * 0.4):
            score -= 15

        if late_entry_ratio > 0.65:
            score -= 20

        if concentration > 0.85 and trade_count < 5:
            score -= 20

        if unique_markets <= 1:
            score -= 20

        if trade_count < 4:
            score -= 15

        if opposing_market_count > 0:
            score -= min(30, opposing_market_count * 15)

        if opposing_market_count >= 3 or opposing_market_ratio > 0.15:
            score -= 20

        if low_price_ratio > 0.65:
            score -= 10

        if sell_ratio > 0.8:
            score -= 5

        if extreme_price_volume_ratio > 0.7:
            score -= 10
        elif extreme_price_volume_ratio > 0.5:
            score -= 5

        score = max(0, min(100, round(score)))

        hard_flags: List[str] = []

        if trade_count < MIN_APPROVE_TRADES:
            hard_flags.append("low_trade_count")
        if unique_markets < MIN_APPROVE_MARKETS:
            hard_flags.append("low_market_diversity")
        if total_volume < MIN_APPROVE_VOLUME:
            hard_flags.append("low_total_volume")
        if opposing_market_count > 0:
            hard_flags.append("opposing_outcomes_detected")
        if opposing_market_count >= 3 or opposing_market_ratio > 0.15:
            hard_flags.append("heavy_opposing_outcomes")
        if late_entry_ratio > 0.65:
            hard_flags.append("mostly_late_entries")
        if low_price_ratio > 0.65:
            hard_flags.append("mostly_low_price_trades")
        if extreme_price_volume_ratio > 0.7:
            hard_flags.append("extreme_price_volume_heavy")
        elif extreme_price_volume_ratio > 0.5:
            hard_flags.append("extreme_price_volume_warning")
        if sell_ratio > 0.8:
            hard_flags.append("mostly_sells")

        disqualifying_flags = {
            "heavy_opposing_outcomes",
            "mostly_late_entries",
        }

        if score >= 75 and not any(f in hard_flags for f in disqualifying_flags):
            tier = "candidate_high"
        elif score >= 60 and not any(f in hard_flags for f in disqualifying_flags):
            tier = "candidate_watch"
        elif score >= 35:
            tier = "weak_candidate"
        else:
            tier = "reject"

        sample_trades = (
            g.sort_values("size_usd", ascending=False)
            .head(6)[["market_id", "title", "category_guess", "side", "outcome", "size_usd", "price"]]
            .to_dict(orient="records")
        )

        grouped.append({
            "wallet": wallet,
            "score": score,
            "tier": tier,
            "category_guess": category,
            "trade_count": trade_count,
            "total_volume": round(total_volume, 2),
            "avg_size": round(avg_size, 2),
            "max_size": round(max_size, 2),
            "unique_markets": unique_markets,
            "avg_price": round(avg_price, 4),
            "early_entries": early_entries,
            "late_entries": late_entries,
            "late_entry_ratio": round(late_entry_ratio, 3),
            "low_price_trades": low_price_trades,
            "low_price_ratio": round(low_price_ratio, 3),
            "sell_trades": sell_trades,
            "sell_ratio": round(sell_ratio, 3),
            "extreme_price_volume": round(extreme_price_volume, 2),
            "extreme_price_volume_ratio": round(extreme_price_volume_ratio, 3),
            "opposing_market_count": opposing_market_count,
            "opposing_market_ratio": round(opposing_market_ratio, 3),
            "opposing_markets": opposing_markets[:5],
            "concentration": round(concentration, 3),
            "hard_flags": hard_flags,
            "sample_trades": sample_trades,
        })

    return sorted(grouped, key=lambda x: x["score"], reverse=True)


def dedupe_trades(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    clean: List[Dict[str, Any]] = []

    for t in trades:
        key = (
            t.get("wallet"),
            t.get("market_id"),
            t.get("side"),
            t.get("outcome"),
            round(float(t.get("size_usd") or 0), 4),
            round(float(t.get("price") or 0), 6),
        )

        if key in seen:
            continue

        seen.add(key)
        clean.append(t)

    return clean


async def enrich_candidates_with_wallet_history(initial_candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []

    # Only enrich wallets worth reviewing.
    wallets_to_check = [
        c["wallet"]
        for c in initial_candidates
        if (
            c["score"] >= 10
            or c["total_volume"] >= 1000
            or c["trade_count"] >= 3
        )
    ][:MAX_CANDIDATES_FOR_AI]

    print(f"Wallets to enrich: {len(wallets_to_check)}")

    for idx, wallet in enumerate(wallets_to_check, start=1):
        print(f"[{idx}/{len(wallets_to_check)}] Fetching wallet history: {wallet}")

        wallet_trades = await fetch_wallet_trades(wallet, min_trade_usd=MIN_TRADE_USD)
        wallet_trades = dedupe_trades(wallet_trades)

        if not wallet_trades:
            continue

        wallet_metrics = compute_wallet_metrics(wallet_trades)

        if not wallet_metrics:
            continue

        final_candidate = wallet_metrics[0]
        final_candidate["source"] = "wallet_history"
        final_candidate["global_pre_score"] = next(
            (c["score"] for c in initial_candidates if c["wallet"] == wallet),
            None,
        )

        enriched.append(final_candidate)

    return sorted(enriched, key=lambda x: x["score"], reverse=True)


def classify_active_wallet(metric: Dict[str, Any]) -> str:
    flags = set(metric.get("hard_flags", []))

    if metric.get("trade_count", 0) == 0:
        return "inactive"

    bad_flags = {
        "heavy_opposing_outcomes",
        "mostly_late_entries",
    }

    if metric["score"] >= 65 and not flags.intersection(bad_flags):
        return "healthy"

    if metric["score"] >= 45 and not flags.intersection(bad_flags):
        return "watch"

    return "degraded"


async def run_active_health_check() -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []

    for whale_id, cfg in ACTIVE_WALLETS.items():
        wallet = cfg["wallet"].lower()
        min_usdc = float(cfg.get("min_usdc", MIN_TRADE_USD))

        print(f"Checking active wallet: {whale_id} {wallet}")

        try:
            trades = await fetch_wallet_trades(wallet, min_trade_usd=min_usdc)
            trades = dedupe_trades(trades)
            metrics = compute_wallet_metrics(trades)
        except Exception as exc:
            print(f"Active wallet check failed: whale_id={whale_id} error={exc}")
            results.append({
                "whale_id": whale_id,
                "name": cfg["name"],
                "wallet": wallet,
                "profile": cfg.get("profile", "mixed"),
                "status": "error",
                "score": 0,
                "reason": str(exc),
                "source": "active_wallet_health",
                "checked_at": iso_now(),
            })
            continue

        if not metrics:
            results.append({
                "whale_id": whale_id,
                "name": cfg["name"],
                "wallet": wallet,
                "profile": cfg.get("profile", "mixed"),
                "status": "inactive",
                "score": 0,
                "reason": "No recent qualifying trades",
                "source": "active_wallet_health",
                "checked_at": iso_now(),
            })
            continue

        metric = metrics[0]
        metric["whale_id"] = whale_id
        metric["name"] = cfg["name"]
        metric["profile"] = cfg.get("profile", "mixed")
        metric["status"] = classify_active_wallet(metric)
        metric["source"] = "active_wallet_health"
        metric["checked_at"] = iso_now()

        results.append(metric)

    return results


def ai_review_wallet(wallet_data: Dict[str, Any], review_type: str) -> Optional[Dict[str, Any]]:
    if not client:
        return None

    prompt = f"""
Evalúa esta wallet de Polymarket para RadarBallena.

Tipo de revisión:
{review_type}

Reglas:
- No inventes datos.
- El score algorítmico ya existe; úsalo como input, no como verdad absoluta.
- Distingue entre:
  - BUY Yes + BUY No = señal fuerte de hedge/opposing outcome.
  - BUY outcome + SELL same outcome = puede ser salida, cierre, market making o arb.
- No apruebes si hay poca muestra.
- No apruebes si el patrón parece market-making, farming, scalping o arbitraje.
- Para wallets activas, no recomiendes reemplazo por una sola mala corrida.
- Para candidatas, solo recomienda approve si el patrón es direccional y limpio.
- Sé crítico y breve.

Wallet JSON:
{json.dumps(wallet_data, ensure_ascii=False)}
"""

    try:
        response = client.responses.parse(
            model=OPENAI_MODEL,
            input=[
                {
                    "role": "system",
                    "content": "Eres analista cuantitativo de wallets de Polymarket para un sistema de whale alerts. Evalúas calidad de señal, riesgo, continuidad y posible reemplazo.",
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            text_format=AIWalletReview,
        )

        parsed: AIWalletReview = response.output_parsed
        return parsed.model_dump()
    except Exception as exc:
        print(f"AI review failed: {exc}")
        return {
            "recommendation": "watch",
            "confidence": 0,
            "category_guess": wallet_data.get("category_guess", "unknown"),
            "health_verdict": "watch",
            "replacement_readiness": "none",
            "risk_flags": ["ai_review_error"],
            "strengths": [],
            "weaknesses": [str(exc)],
            "reason": "AI review failed. Using algorithmic metrics only.",
            "suggested_action": "review_manually",
        }


def ai_review_active_wallets(active_health: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    reviewed: List[Dict[str, Any]] = []

    for wallet in active_health:
        review = ai_review_wallet(wallet, review_type="active_wallet_health")
        wallet["ai_review"] = review
        reviewed.append(wallet)

    return reviewed


def candidate_is_usable(candidate: Dict[str, Any]) -> bool:
    if candidate.get("tier") not in ["candidate_high", "candidate_watch"]:
        return False

    if candidate.get("score", 0) < 60:
        return False

    flags = set(candidate.get("hard_flags", []))
    if "heavy_opposing_outcomes" in flags or "mostly_late_entries" in flags:
        return False

    if REQUIRE_AI_APPROVAL_FOR_REPLACEMENT:
        review = candidate.get("ai_review") or {}
        if review.get("recommendation") != "approve":
            return False
        if int(review.get("confidence", 0)) < MIN_AI_REPLACEMENT_CONFIDENCE:
            return False

    return True


def compare_active_vs_candidates(
    active_health: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    recommendations: List[Dict[str, Any]] = []
    usable_candidates = [c for c in candidates if candidate_is_usable(c)]

    for active in active_health:
        if active.get("status") not in ["degraded", "inactive", "watch", "error"]:
            continue

        profile = active.get("profile", "mixed")

        same_profile = [
            c for c in usable_candidates
            if c.get("category_guess") == profile or profile == "mixed"
        ]

        same_profile = sorted(same_profile, key=lambda x: x.get("score", 0), reverse=True)
        best = same_profile[0] if same_profile else None

        recommendations.append({
            "active_whale_id": active.get("whale_id"),
            "active_name": active.get("name"),
            "active_wallet": active.get("wallet"),
            "active_profile": profile,
            "active_status": active.get("status"),
            "active_score": active.get("score", 0),
            "active_flags": active.get("hard_flags", []),
            "recommended_action": "replace_candidate_found" if best else "keep_watch_no_replacement",
            "replacement_candidate": best,
            "generated_at": iso_now(),
        })

    return recommendations


async def run_active_cycle() -> List[Dict[str, Any]]:
    print("\n" + "=" * 80)
    print("Running active wallet health check...")
    print("=" * 80)

    active_health = await run_active_health_check()

    if AI_REVIEW_ACTIVE:
        active_health = ai_review_active_wallets(active_health)

    save_json("active_wallet_health.json", active_health)

    print(f"Active wallets checked: {len(active_health)}")
    return active_health


async def run_discovery_cycle() -> List[Dict[str, Any]]:
    print("\n" + "=" * 80)
    print("Running global wallet discovery...")
    print("=" * 80)

    trades = await fetch_recent_activity()
    print(f"Global trades after filters: {len(trades)}")

    trades = dedupe_trades(trades)
    print(f"Global trades after dedupe: {len(trades)}")

    initial_candidates = compute_wallet_metrics(trades)
    print(f"Initial wallets scored: {len(initial_candidates)}")

    save_json("all_scored_wallets_global.json", initial_candidates)

    enriched_candidates = await enrich_candidates_with_wallet_history(initial_candidates)
    print(f"Enriched wallets scored: {len(enriched_candidates)}")

    save_json("all_scored_wallets_enriched.json", enriched_candidates)

    candidates_for_ai = [
        c for c in enriched_candidates
        if c.get("tier") in ["candidate_high", "candidate_watch"] or c.get("score", 0) >= 60
    ]

    top = candidates_for_ai[:MAX_CANDIDATES_FOR_AI]
    print(f"Candidates for AI/manual review: {len(top)}")

    if AI_REVIEW_CANDIDATES:
        for idx, candidate in enumerate(top, start=1):
            review = ai_review_wallet(candidate, review_type="candidate_discovery")
            candidate["ai_review"] = review

            print("\n" + "=" * 80)
            print(f"{idx}. {candidate['wallet']}")
            print(f"score={candidate['score']} tier={candidate['tier']} category={candidate['category_guess']}")
            print(f"global_pre_score={candidate.get('global_pre_score')}")
            print(f"trades={candidate['trade_count']} volume=${candidate['total_volume']} avg=${candidate['avg_size']}")
            print(f"markets={candidate['unique_markets']} early={candidate['early_entries']} late={candidate['late_entries']}")
            print(f"opposing_markets={candidate['opposing_market_count']} hard_flags={candidate['hard_flags']}")

            if review:
                print(f"AI: {review.get('recommendation')} | {review.get('category_guess')}")
                print(f"confidence: {review.get('confidence')}")
                print(f"flags: {', '.join(review.get('risk_flags', []))}")
                print(f"reason: {review.get('reason')}")

    save_json("global_candidates.json", top)
    save_json("candidates.json", top)

    return top


def run_recommendations_cycle(
    active_health: Optional[List[Dict[str, Any]]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    print("\n" + "=" * 80)
    print("Running replacement recommendations...")
    print("=" * 80)

    if active_health is None:
        active_health = load_json("active_wallet_health.json", [])

    if candidates is None:
        candidates = load_json("global_candidates.json", [])

    recommendations = compare_active_vs_candidates(active_health, candidates)
    save_json("replacement_recommendations.json", recommendations)

    print(f"Replacement recommendations saved: {len(recommendations)}")
    return recommendations


def save_run_summary(
    active_health: Optional[List[Dict[str, Any]]] = None,
    candidates: Optional[List[Dict[str, Any]]] = None,
    recommendations: Optional[List[Dict[str, Any]]] = None,
    status: str = "success",
    error: Optional[str] = None,
) -> None:
    summary = {
        "status": status,
        "error": error,
        "generated_at": iso_now(),
        "mode": WHALE_FINDER_MODE,
        "lookback_hours": LOOKBACK_HOURS,
        "min_trade_usd": MIN_TRADE_USD,
        "active_wallets_checked": len(active_health or []),
        "candidates_count": len(candidates or []),
        "recommendations_count": len(recommendations or []),
        "active_interval_seconds": ACTIVE_HEALTH_INTERVAL_SECONDS,
        "discovery_interval_seconds": DISCOVERY_INTERVAL_SECONDS,
    }

    save_json("run_summary.json", summary)


async def run_once() -> None:
    active_health = await run_active_cycle()
    candidates = await run_discovery_cycle()
    recommendations = run_recommendations_cycle(active_health, candidates)
    save_run_summary(active_health, candidates, recommendations)


async def worker_loop() -> None:
    ensure_output_dir()

    state = load_state()
    last_active_run = parse_datetime(state.get("last_active_run"))
    last_discovery_run = parse_datetime(state.get("last_discovery_run"))

    if RUN_ON_START:
        print("RUN_ON_START=true. Running full cycle first...")
        try:
            await run_once()
            now = now_utc()
            state["last_active_run"] = now.isoformat()
            state["last_discovery_run"] = now.isoformat()
            state["last_success"] = now.isoformat()
            state["last_error"] = None
            save_state(state)
            last_active_run = now
            last_discovery_run = now
        except Exception as exc:
            state["last_error"] = str(exc)
            state["last_error_at"] = iso_now()
            save_state(state)
            save_run_summary(status="error", error=str(exc))
            print(f"Initial full cycle failed: {exc}")

    while True:
        now = now_utc()

        should_run_active = (
            last_active_run is None
            or (now - last_active_run).total_seconds() >= ACTIVE_HEALTH_INTERVAL_SECONDS
        )

        should_run_discovery = (
            last_discovery_run is None
            or (now - last_discovery_run).total_seconds() >= DISCOVERY_INTERVAL_SECONDS
        )

        active_health: Optional[List[Dict[str, Any]]] = None
        candidates: Optional[List[Dict[str, Any]]] = None
        recommendations: Optional[List[Dict[str, Any]]] = None

        try:
            if should_run_active:
                active_health = await run_active_cycle()
                last_active_run = now_utc()
                state["last_active_run"] = last_active_run.isoformat()

            if should_run_discovery:
                candidates = await run_discovery_cycle()
                last_discovery_run = now_utc()
                state["last_discovery_run"] = last_discovery_run.isoformat()

            if active_health is not None or candidates is not None:
                if active_health is None:
                    active_health = load_json("active_wallet_health.json", [])

                if candidates is None:
                    candidates = load_json("global_candidates.json", [])

                recommendations = run_recommendations_cycle(active_health, candidates)
                save_run_summary(active_health, candidates, recommendations)

                state["last_success"] = iso_now()
                state["last_error"] = None
                save_state(state)

        except Exception as exc:
            print(f"Worker cycle failed: {exc}")
            state["last_error"] = str(exc)
            state["last_error_at"] = iso_now()
            save_state(state)
            save_run_summary(
                active_health=active_health,
                candidates=candidates,
                recommendations=recommendations,
                status="error",
                error=str(exc),
            )

        print(f"Sleeping {WORKER_SLEEP_SECONDS}s...")
        await asyncio.sleep(WORKER_SLEEP_SECONDS)


async def main() -> None:
    print("Starting whale-finder")
    print(f"mode={WHALE_FINDER_MODE}")
    print(f"output_dir={OUTPUT_DIR}")
    print(f"lookback_hours={LOOKBACK_HOURS}")
    print(f"active_interval_seconds={ACTIVE_HEALTH_INTERVAL_SECONDS}")
    print(f"discovery_interval_seconds={DISCOVERY_INTERVAL_SECONDS}")

    if WHALE_FINDER_MODE == "once":
        await run_once()
        return

    await worker_loop()


if __name__ == "__main__":
    asyncio.run(main())
