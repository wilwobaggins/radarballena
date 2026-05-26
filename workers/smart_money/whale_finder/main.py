import os
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import Literal

load_dotenv()

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output"))

if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = BASE_DIR / OUTPUT_DIR

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_json(filename: str, data: Any) -> None:
    path = OUTPUT_DIR / filename

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    print(f"Saved {path}")

DATA_API = "https://data-api.polymarket.com"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

# DEBUG / LOCAL DEFAULTS
MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", "250"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "168"))
MAX_CANDIDATES_FOR_AI = int(os.getenv("MAX_CANDIDATES_FOR_AI", "20"))

# Pagination: keep this conservative. Some offsets can return 400.
PAGE_LIMIT = int(os.getenv("PAGE_LIMIT", "1000"))
MAX_OFFSET = int(os.getenv("MAX_OFFSET", "4000"))

# Discovery quality gates
MIN_APPROVE_TRADES = int(os.getenv("MIN_APPROVE_TRADES", "10"))
MIN_APPROVE_MARKETS = int(os.getenv("MIN_APPROVE_MARKETS", "5"))
MIN_APPROVE_VOLUME = float(os.getenv("MIN_APPROVE_VOLUME", "5000"))

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

    # Detect obvious minute windows: 1:20PM-1:25PM, 13:20-13:25, etc.
    time_window_tokens = [
        "am-", "pm-", ":00-", ":05-", ":10-", ":15-", ":20-", ":25-",
        ":30-", ":35-", ":40-", ":45-", ":50-", ":55-"
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
        " vs ", "vs.", "ipl", "cricket", "ufc", "fight", "game", "match"
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

    async with httpx.AsyncClient(timeout=25) as http:
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
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

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

async def fetch_wallet_trades(wallet: str, limit: int = 1000):
    all_items = []

    async with httpx.AsyncClient(timeout=25) as http:
        for offset in range(0, MAX_OFFSET, PAGE_LIMIT):
            params = {
                "user": wallet,
                "limit": PAGE_LIMIT,
                "offset": offset,
                "takerOnly": False,
            }

            res = await http.get(f"{DATA_API}/trades", params=params)

            if res.status_code == 400:
                break

            res.raise_for_status()
            data = res.json()

            items = data.get("data") or data.get("items") or data.get("trades") or data if isinstance(data, dict) else data

            if not items:
                break

            all_items.extend(items)

    normalized = []
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


def count_opposing_outcome_markets(g: pd.DataFrame) -> Tuple[int, List[str]]:
    """
    Counts markets where the same wallet traded more than one outcome.
    This is a strong hedge/arb/noise signal.
    """
    bad_markets = []

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

    grouped = []
    for wallet, g in df.groupby("wallet"):
        trade_count = len(g)
        total_volume = float(g["size_usd"].sum())
        avg_size = float(g["size_usd"].mean())
        max_size = float(g["size_usd"].max())

        unique_markets = int(g["market_id"].nunique(dropna=True))
        avg_price = float(g["price"].replace(0, pd.NA).dropna().mean() or 0)

        early_entries = int(((g["price"] > 0.05) & (g["price"] < 0.65)).sum())
        late_entries = int((g["price"] >= 0.85).sum())
        late_entry_ratio = late_entries / trade_count if trade_count else 0

        # NUEVO: detectar estrategia de precios muy bajos / mostly sells
        low_price_trades = int((g["price"] <= 0.05).sum())
        low_price_ratio = low_price_trades / trade_count if trade_count else 0

        sell_trades = int((g["side"].astype(str).str.upper() == "SELL").sum())
        sell_ratio = sell_trades / trade_count if trade_count else 0

        extreme_price_volume = float(
            g[(g["price"] <= 0.05) | (g["price"] >= 0.95)]["size_usd"].sum()
        )

        extreme_price_volume_ratio = (
            extreme_price_volume / total_volume if total_volume else 0
        )

        market_repeats = trade_count - unique_markets
        concentration = max_size / total_volume if total_volume > 0 else 0
        opposing_market_count, opposing_markets = count_opposing_outcome_markets(g)
        opposing_market_ratio = opposing_market_count / unique_markets if unique_markets else 0
        category = dominant_category(g)

        score = 0.0

        # señales positivas
        score += min(25, total_volume / 1000)
        score += min(20, trade_count * 2)
        score += min(15, avg_size / 400)
        score += min(15, early_entries * 2.5)
        score += min(10, unique_markets * 1.5)

        if unique_markets >= 3:
            score += min(10, market_repeats * 1.5)

        # penalizaciones
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

        # NUEVO: penalización suave
        if low_price_ratio > 0.65:
            score -= 10

        if sell_ratio > 0.8:
            score -= 5

        if extreme_price_volume_ratio > 0.7:
            score -= 10

        elif extreme_price_volume_ratio > 0.5:
            score -= 5

        score = max(0, min(100, round(score)))

        hard_flags = []

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

            #  métricas visibles
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

def dedupe_trades(trades):
    seen = set()
    clean = []

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

async def enrich_candidates_with_wallet_history(initial_candidates):
    enriched = []

    # Solo enriquecemos wallets que valen la pena revisar.
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

        wallet_trades = await fetch_wallet_trades(wallet)
        wallet_trades = dedupe_trades(wallet_trades)

        if not wallet_trades:
            continue

        wallet_metrics = compute_wallet_metrics(wallet_trades)

        if not wallet_metrics:
            continue

        # compute_wallet_metrics regresa lista, pero aquí debería ser una sola wallet.
        final_candidate = wallet_metrics[0]
        final_candidate["source"] = "wallet_history"
        final_candidate["global_pre_score"] = next(
            (c["score"] for c in initial_candidates if c["wallet"] == wallet),
            None
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
    results = []

    for whale_id, cfg in ACTIVE_WALLETS.items():
        wallet = cfg["wallet"].lower()

        print(f"Checking active wallet: {whale_id} {wallet}")

        trades = await fetch_wallet_trades(wallet)
        trades = dedupe_trades(trades)

        metrics = compute_wallet_metrics(trades)

        if not metrics:
            results.append({
                "whale_id": whale_id,
                "name": cfg["name"],
                "wallet": wallet,
                "profile": cfg.get("profile", "mixed"),
                "status": "inactive",
                "score": 0,
                "reason": "No recent qualifying trades",
            })
            continue

        metric = metrics[0]
        metric["whale_id"] = whale_id
        metric["name"] = cfg["name"]
        metric["profile"] = cfg.get("profile", "mixed")
        metric["status"] = classify_active_wallet(metric)
        metric["source"] = "active_wallet_health"

        results.append(metric)

    return results

def ai_review_active_wallets(active_health: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    reviewed = []

    for wallet in active_health:
        review = ai_review_wallet(wallet, review_type="active_wallet_health")
        wallet["ai_review"] = review
        reviewed.append(wallet)

    return reviewed

def compare_active_vs_candidates(
    active_health: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    recommendations = []

    usable_candidates = [
    c for c in candidates
    if c["tier"] in ["candidate_high", "candidate_watch"]
    and c["score"] >= 60
    and "heavy_opposing_outcomes" not in c.get("hard_flags", [])
    and "mostly_late_entries" not in c.get("hard_flags", [])
    and c.get("ai_review", {}).get("recommendation") == "approve"
    and c.get("ai_review", {}).get("confidence", 0) >= 70
]

    for active in active_health:
        if active["status"] not in ["degraded", "inactive", "watch"]:
            continue

        profile = active.get("profile")

        same_profile = [
            c for c in usable_candidates
            if c.get("category_guess") == profile or profile == "mixed"
        ]

        same_profile = sorted(
            same_profile,
            key=lambda x: x["score"],
            reverse=True,
        )

        best = same_profile[0] if same_profile else None

        recommendations.append({
            "active_whale_id": active["whale_id"],
            "active_name": active["name"],
            "active_wallet": active["wallet"],
            "active_status": active["status"],
            "active_score": active.get("score", 0),
            "active_flags": active.get("hard_flags", []),
            "recommended_action": "replace_candidate_found" if best else "keep_watch_no_replacement",
            "replacement_candidate": best,
        })

    return recommendations

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


async def main():
    print(f"Output dir: {OUTPUT_DIR}")

    print("Running active wallet health check...")

    active_health = await run_active_health_check()

    if os.getenv("AI_REVIEW_ACTIVE", "true").lower() == "true":
        active_health = ai_review_active_wallets(active_health)

    save_json("active_wallet_health.json", active_health)

    print(f"Active wallets checked: {len(active_health)}")

    print("Fetching recent Polymarket activity...")

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
        if (
            c["tier"] in ["candidate_high", "candidate_watch"]
            or c["score"] >= 60
        )
    ]

    top = candidates_for_ai[:MAX_CANDIDATES_FOR_AI]

    print(f"Candidates for AI: {len(top)}")

    for idx, candidate in enumerate(top, start=1):
        review = ai_review_wallet(candidate, review_type="candidate_discovery")
        candidate["ai_review"] = review

        print("\n" + "=" * 80)
        print(f"{idx}. {candidate['wallet']}")
        print(
            f"score={candidate['score']} "
            f"tier={candidate['tier']} "
            f"category={candidate['category_guess']}"
        )
        print(f"global_pre_score={candidate.get('global_pre_score')}")
        print(
            f"trades={candidate['trade_count']} "
            f"volume=${candidate['total_volume']} "
            f"avg=${candidate['avg_size']}"
        )
        print(
            f"markets={candidate['unique_markets']} "
            f"early={candidate['early_entries']} "
            f"late={candidate['late_entries']}"
        )
        print(
            f"opposing_markets={candidate['opposing_market_count']} "
            f"hard_flags={candidate['hard_flags']}"
        )

        if review:
            print(f"AI: {review['recommendation']} | {review['category_guess']}")
            print(f"flags: {', '.join(review['risk_flags'])}")
            print(f"reason: {review['reason']}")

    save_json("global_candidates.json", top)
    save_json("candidates.json", top)

    recommendations = compare_active_vs_candidates(active_health, top)

    save_json("replacement_recommendations.json", recommendations)

    print("\nWhale finder terminado.")
    print(f"Active wallets checked: {len(active_health)}")
    print(f"Initial wallets scored: {len(initial_candidates)}")
    print(f"Enriched wallets scored: {len(enriched_candidates)}")
    print(f"Candidates reviewed by AI: {len(top)}")
    print(f"Recommendations: {len(recommendations)}")

if __name__ == "__main__":
    asyncio.run(main())
