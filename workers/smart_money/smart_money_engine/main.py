import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

try:  # pragma: no cover - support package and script-style imports
    from .market_trail import (
        build_market_capital_trails,
        summarize_market_trails,
    )
    from .related_markets import build_estela_capital_by_market
    from .polymarket_profile_client import fetch_closed_positions
    from .storage import save_json
    from .supabase_writer import (
        fail_engine_run,
        finish_engine_run,
        start_engine_run,
        upsert_capital_trails,
        upsert_wallet_scores,
    )
    from .category_utils import guess_category_from_title
    from .wallet_skill_score import (
        compute_shadow_meta_evaluation,
        compute_wallet_skill,
    )
    from .wallet_classifier import (
        INSUFFICIENT_HISTORY,
        SIGNAL_WALLET,
        WHALE_BUT_NOISY,
    )
    from .wallet_metrics import compute_wallet_scores
except ImportError:  # pragma: no cover
    from market_trail import (
        build_market_capital_trails,
        summarize_market_trails,
    )
    from related_markets import build_estela_capital_by_market
    from polymarket_profile_client import fetch_closed_positions
    from storage import save_json
    from supabase_writer import (
        fail_engine_run,
        finish_engine_run,
        start_engine_run,
        upsert_capital_trails,
        upsert_wallet_scores,
    )
    from category_utils import guess_category_from_title
    from wallet_skill_score import (
        compute_shadow_meta_evaluation,
        compute_wallet_skill,
    )
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
SKILL_SHADOW_ENABLED = os.getenv("SKILL_SHADOW_ENABLED", "true").lower() == "true"
SKILL_MAX_WALLETS_PER_RUN = int(os.getenv("SKILL_MAX_WALLETS_PER_RUN", "25"))
SKILL_MAX_CLOSED_POSITIONS = int(os.getenv("SKILL_MAX_CLOSED_POSITIONS", "500"))
SKILL_HTTP_CONCURRENCY = int(os.getenv("SKILL_HTTP_CONCURRENCY", "4"))
SKILL_PRIORITY_WALLETS = os.getenv("SKILL_PRIORITY_WALLETS", "")


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


def _normalize_wallet(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_priority_wallets() -> list[str]:
    seen: set[str] = set()
    wallets: list[str] = []
    for wallet in SKILL_PRIORITY_WALLETS.split(","):
        normalized = _normalize_wallet(wallet)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        wallets.append(normalized)
    return wallets


def _score_wallet_selection_key(score: dict[str, Any]) -> tuple[float, float]:
    metrics = score.get("metrics") or {}
    return (
        float(score.get("walletQualityScore") or 0),
        float(metrics.get("totalVolume") or 0),
    )


def select_shadow_wallets(wallet_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not wallet_scores:
        return []

    by_wallet = {_normalize_wallet(score.get("wallet")): score for score in wallet_scores if score.get("wallet")}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for wallet in _parse_priority_wallets():
        score = by_wallet.get(wallet)
        if score and wallet not in seen:
            selected.append(score)
            seen.add(wallet)

    remaining = [
        score
        for score in wallet_scores
        if _normalize_wallet(score.get("wallet")) not in seen
    ]
    remaining.sort(key=_score_wallet_selection_key, reverse=True)

    for score in remaining:
        if len(selected) >= SKILL_MAX_WALLETS_PER_RUN:
            break
        wallet = _normalize_wallet(score.get("wallet"))
        if wallet in seen:
            continue
        selected.append(score)
        seen.add(wallet)

    return selected[:SKILL_MAX_WALLETS_PER_RUN]


def build_shadow_wallet_targets(wallet_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_wallet = {
        _normalize_wallet(score.get("wallet")): score
        for score in wallet_scores
        if score.get("wallet")
    }
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()

    for wallet in _parse_priority_wallets():
        if wallet in seen:
            continue
        seen.add(wallet)
        score = by_wallet.get(wallet)
        if score:
            targets.append(
                {
                    "wallet": wallet,
                    "source": "global_wallet_scores",
                    "walletScore": score,
                }
            )
        else:
            print(
                "SMART_MONEY_SKILL_PRIORITY_TARGETED "
                f"wallet={wallet} "
                "reason=missing_from_global_wallet_scores"
            )
            targets.append(
                {
                    "wallet": wallet,
                    "source": "targeted_wallet_activity",
                    "walletScore": None,
                }
            )

    remaining_budget = max(0, SKILL_MAX_WALLETS_PER_RUN - len(targets))
    if remaining_budget <= 0:
        return targets[:SKILL_MAX_WALLETS_PER_RUN]

    remaining = [
        score
        for score in wallet_scores
        if _normalize_wallet(score.get("wallet")) not in seen
    ]
    remaining.sort(key=_score_wallet_selection_key, reverse=True)

    for score in remaining:
        if len(targets) >= SKILL_MAX_WALLETS_PER_RUN:
            break
        wallet = _normalize_wallet(score.get("wallet"))
        if wallet in seen:
            continue
        seen.add(wallet)
        targets.append(
            {
                "wallet": wallet,
                "source": "global_wallet_scores",
                "walletScore": score,
            }
        )

    return targets[:SKILL_MAX_WALLETS_PER_RUN]


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        message = error.__class__.__name__
    return " ".join(message.split())[:240]


async def _fetch_shadow_positions(
    selected_wallets: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not selected_wallets:
        return {}

    print(f"SMART_MONEY_SKILL_SHADOW_STARTED wallets={len(selected_wallets)}")
    semaphore = asyncio.Semaphore(max(1, SKILL_HTTP_CONCURRENCY))
    results: dict[str, dict[str, Any]] = {}
    selected_wallet_set = {_normalize_wallet(score.get("wallet")) for score in selected_wallets}

    async def _load_one(score: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        wallet = _normalize_wallet(score.get("wallet"))
        try:
            async with semaphore:
                positions = await fetch_closed_positions(wallet, max_positions=SKILL_MAX_CLOSED_POSITIONS)
            print(f"SMART_MONEY_SKILL_FETCHED wallet={wallet} closed_positions={len(positions)}")
            return wallet, {
                "wallet": wallet,
                "closed_positions": positions,
            }
        except Exception as error:
            print(
                "SMART_MONEY_SKILL_FAILED "
                f"wallet={wallet} "
                f"error={_safe_error_message(error)}"
            )
            return wallet, {
                "wallet": wallet,
                "closed_positions": [],
                "error": _safe_error_message(error),
            }

    tasks = [asyncio.create_task(_load_one(score)) for score in selected_wallets]
    for task in asyncio.as_completed(tasks):
        wallet, payload = await task
        results[wallet] = payload

    # keep a stable map for wallets we never selected
    for wallet in selected_wallet_set:
        results.setdefault(wallet, {"wallet": wallet, "closed_positions": []})

    return results


async def _fetch_targeted_activity_for_wallet(wallet: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_events: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=float(os.getenv("SKILL_HTTP_TIMEOUT_SECONDS", "25"))) as http:
        for offset in range(0, SKILL_MAX_CLOSED_POSITIONS, 50):
            response = await http.get(
                f"{DATA_API}/trades",
                params={
                    "user": wallet,
                    "limit": 50,
                    "offset": offset,
                    "takerOnly": False,
                },
            )
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                items = data.get("data") or data.get("items") or data.get("trades") or []
            else:
                items = data
            if not isinstance(items, list) or not items:
                break
            raw_events.extend(item for item in items if isinstance(item, dict))
            if len(items) < 50:
                break

    normalized = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for item in raw_events:
        row = normalize_activity(item)
        if not row:
            continue
        if row["timestamp"] and row["timestamp"] < cutoff:
            continue
        if row["size_usd"] < MIN_TRADE_USD:
            continue
        normalized.append(row)

    return raw_events, dedupe_trades(normalized)


async def _fetch_targeted_wallet_behaviors(
    target_wallets: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not target_wallets:
        return {}

    semaphore = asyncio.Semaphore(max(1, SKILL_HTTP_CONCURRENCY))
    results: dict[str, dict[str, Any]] = {}

    async def _load_one(target: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        wallet = _normalize_wallet(target.get("wallet"))
        async with semaphore:
            raw_events, normalized_trades = await _fetch_targeted_activity_for_wallet(wallet)
        print(
            "SMART_MONEY_SKILL_TARGETED_ACTIVITY_FETCHED "
            f"wallet={wallet} "
            f"events={len(raw_events)} "
            f"normalized_trades={len(normalized_trades)}"
        )
        if not normalized_trades:
            return wallet, {
                "wallet": wallet,
                "behaviorStatus": "insufficient_recent_activity",
                "walletScore": None,
                "rawEvents": raw_events,
                "normalizedTrades": normalized_trades,
            }

        temp_scores = compute_wallet_scores(normalized_trades)
        temp_score = next(
            (
                score
                for score in temp_scores
                if _normalize_wallet(score.get("wallet")) == wallet
            ),
            None,
        )
        if temp_score is None:
            return wallet, {
                "wallet": wallet,
                "behaviorStatus": "insufficient_recent_activity",
                "walletScore": None,
                "rawEvents": raw_events,
                "normalizedTrades": normalized_trades,
            }

        return wallet, {
            "wallet": wallet,
            "behaviorStatus": "sufficient",
            "walletScore": temp_score,
            "rawEvents": raw_events,
            "normalizedTrades": normalized_trades,
        }

    tasks = [asyncio.create_task(_load_one(target)) for target in target_wallets]
    for task in asyncio.as_completed(tasks):
        wallet, payload = await task
        results[wallet] = payload

    return results


def _attach_shadow_outputs(
    wallet_scores: list[dict[str, Any]],
    shadow_targets: list[dict[str, Any]],
    shadow_positions: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    shadow_rows: list[dict[str, Any]] = []
    wallet_score_map = {
        _normalize_wallet(score.get("wallet")): score
        for score in wallet_scores
        if score.get("wallet")
    }

    for target in shadow_targets:
        wallet = _normalize_wallet(target.get("wallet"))
        shadow_source = target.get("source") or "global_wallet_scores"
        score = target.get("walletScore") or wallet_score_map.get(wallet)
        shadow_payload = shadow_positions.get(wallet)
        if shadow_payload is None:
            continue

        closed_positions = shadow_payload.get("closed_positions") or []
        shadow_error = shadow_payload.get("error")
        behavior_status = target.get("behaviorStatus") or "sufficient"
        if shadow_error:
            shadow_skill = {
                "wallet": wallet,
                "skillStatus": "error",
                "error": shadow_error,
            }
            shadow_rows.append(
                {
                    "wallet": wallet,
                    "walletQualityScore": score.get("walletQualityScore") if score else None,
                    "classification": score.get("classification") if score else None,
                    "shadowSource": shadow_source,
                    "shadowSkill": shadow_skill,
                    "shadowMetaEvaluation": None,
                    "behaviorStatus": "error",
                    "generatedAt": (score.get("generatedAt") if score else None) or datetime.now(timezone.utc).isoformat(),
                }
            )
            continue

        if not closed_positions:
            shadow_skill = {"skillStatus": "insufficient"}
            shadow_meta = None if shadow_source == "targeted_wallet_activity" or score is None else compute_shadow_meta_evaluation(int(score.get("walletQualityScore") or 0), shadow_skill)
            behavior_status = target.get("behaviorStatus") or (
                "insufficient_recent_activity" if shadow_source == "targeted_wallet_activity" else "insufficient"
            )
        else:
            try:
                shadow_skill = compute_wallet_skill(wallet, closed_positions)
            except Exception as error:
                shadow_skill = {
                    "wallet": wallet,
                    "skillStatus": "error",
                    "error": _safe_error_message(error),
                }
                shadow_meta = None
                behavior_status = "error"
            else:
                behavior_score = int(score.get("walletQualityScore") or 0) if score else 0
                shadow_meta = compute_shadow_meta_evaluation(behavior_score, shadow_skill) if score is not None or shadow_source == "global_wallet_scores" else None
                behavior_status = target.get("behaviorStatus") or ("sufficient" if shadow_skill.get("skillStatus") == "sufficient" else "limited")

        shadow_rows.append(
            {
                "wallet": wallet,
                "walletQualityScore": score.get("walletQualityScore") if score else None,
                "classification": score.get("classification") if score else None,
                "shadowSource": shadow_source,
                "shadowSkill": shadow_skill,
                "shadowMetaEvaluation": shadow_meta,
                "behaviorStatus": behavior_status,
                "generatedAt": (score.get("generatedAt") if score else None) or datetime.now(timezone.utc).isoformat(),
            }
        )

    return wallet_scores, shadow_rows


def build_noise_scores(wallet_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "wallet": score["wallet"],
            "noiseScore": score.get("noiseScore", 0),
            "noiseLevel": score.get("noiseLevel", "LOW_NOISE"),
            "riskFlags": score.get("riskFlags", []),
            "generatedAt": score.get("generatedAt"),
        }
        for score in wallet_scores
    ]


def build_run_summary(
    *,
    trades_fetched: int,
    trades_deduped: int,
    wallet_scores: list[dict[str, Any]],
    market_trails: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "tradesFetched": trades_fetched,
        "tradesDeduped": trades_deduped,
        "walletsScored": len(wallet_scores),
        "marketsScored": len(market_trails),
    }
    summary["rawSummary"] = {
        "walletsScored": len(wallet_scores),
        "marketsScored": len(market_trails),
        "walletClassificationCounts": dict(Counter(score["classification"] for score in wallet_scores)),
        "marketStatusCounts": dict(Counter(item["status"] for item in market_trails)),
    }
    return summary


async def execute_engine() -> dict[str, Any]:
    trades = await fetch_recent_activity()
    deduped_trades = dedupe_trades(trades)
    wallet_scores = compute_wallet_scores(deduped_trades)
    save_json("wallet_scores.json", wallet_scores)

    noise_scores = build_noise_scores(wallet_scores)
    save_json("noise_scores.json", noise_scores)

    shadow_rows: list[dict[str, Any]] = []
    if SKILL_SHADOW_ENABLED:
        shadow_targets = build_shadow_wallet_targets(wallet_scores)
        targeted_wallets = [target for target in shadow_targets if target.get("source") == "targeted_wallet_activity"]
        targeted_behaviors = await _fetch_targeted_wallet_behaviors(targeted_wallets)
        for target in shadow_targets:
            wallet = _normalize_wallet(target.get("wallet"))
            if target.get("source") == "targeted_wallet_activity":
                targeted_payload = targeted_behaviors.get(wallet) or {}
                target["behaviorStatus"] = targeted_payload.get("behaviorStatus") or "insufficient_recent_activity"
                target["walletScore"] = targeted_payload.get("walletScore")
            else:
                target["behaviorStatus"] = "sufficient"

        selected_wallets = shadow_targets
        shadow_positions = await _fetch_shadow_positions(selected_wallets)
        wallet_scores, shadow_rows = _attach_shadow_outputs(wallet_scores, selected_wallets, shadow_positions)
        save_json("wallet_scores.json", wallet_scores)
        save_json("wallet_skill_shadow.json", shadow_rows)
        scored_count = sum(1 for row in shadow_rows if row.get("shadowMetaEvaluation") is not None)
        failed_count = sum(1 for row in shadow_rows if (row.get("shadowSkill") or {}).get("skillStatus") == "error")
        print(
            "SMART_MONEY_SKILL_SHADOW_COMPLETED "
            f"requested={len(selected_wallets)} "
            f"scored={scored_count} "
            f"failed={failed_count}"
        )

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

    return {
        "trades": trades,
        "deduped_trades": deduped_trades,
        "wallet_scores": wallet_scores,
        "noise_scores": noise_scores,
        "shadow_rows": shadow_rows,
        "market_trails": market_trails,
        "estela_capital": estela_capital,
    }


async def run() -> list[dict]:
    result = await execute_engine()
    return result["wallet_scores"]


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
    run_id = start_engine_run()

    try:
        result = await execute_engine()
        wallet_scores = result["wallet_scores"]
        market_trails = result["market_trails"]
        summary = build_run_summary(
            trades_fetched=len(result["trades"]),
            trades_deduped=len(result["deduped_trades"]),
            wallet_scores=wallet_scores,
            market_trails=market_trails,
        )
        upsert_wallet_scores(run_id, wallet_scores)
        upsert_capital_trails(run_id, result["estela_capital"])
        finish_engine_run(run_id, summary)
        log_summary(wallet_scores)
        log_market_trail_summary(market_trails)
    except Exception as exc:
        fail_engine_run(run_id, str(exc))
        raise


if __name__ == "__main__":
    asyncio.run(main())
