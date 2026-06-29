from __future__ import annotations

import asyncio
import hashlib
import math
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, median
from typing import Any

import httpx

try:  # pragma: no cover - support package and script-style imports
    from .category_utils import guess_skill_category_from_title
    from .copyability_storage import (
        append_trade_copyability_history,
        read_trade_copyability_state,
        sanitize_payload,
        write_trade_copyability_backtest,
        write_trade_copyability_shadow,
        write_trade_copyability_state,
        write_wallet_copyability_summary,
    )
    from .polymarket_price_history_client import (
        fetch_batch_price_history,
        find_nearest_price_point,
    )
    from .time_utils import to_unix_seconds, to_utc_datetime, to_utc_iso
except ImportError:  # pragma: no cover
    from category_utils import guess_skill_category_from_title
    from copyability_storage import (
        append_trade_copyability_history,
        read_trade_copyability_state,
        sanitize_payload,
        write_trade_copyability_backtest,
        write_trade_copyability_shadow,
        write_trade_copyability_state,
        write_wallet_copyability_summary,
    )
    from polymarket_price_history_client import (
        fetch_batch_price_history,
        find_nearest_price_point,
    )
    from time_utils import to_unix_seconds, to_utc_datetime, to_utc_iso


COPYABILITY_SHADOW_ENABLED = os.getenv("COPYABILITY_SHADOW_ENABLED", "false").lower() == "true"
COPYABILITY_MAX_WALLETS_PER_RUN = int(os.getenv("COPYABILITY_MAX_WALLETS_PER_RUN", "3"))
COPYABILITY_MAX_TRADES_PER_WALLET = int(os.getenv("COPYABILITY_MAX_TRADES_PER_WALLET", "200"))
COPYABILITY_LOOKBACK_HOURS = int(os.getenv("COPYABILITY_LOOKBACK_HOURS", "168"))
COPYABILITY_CLUSTER_GAP_MINUTES = int(os.getenv("COPYABILITY_CLUSTER_GAP_MINUTES", "30"))
COPYABILITY_CLUSTER_MAX_HOURS = int(os.getenv("COPYABILITY_CLUSTER_MAX_HOURS", "6"))
COPYABILITY_MIN_CLUSTER_USD = float(os.getenv("COPYABILITY_MIN_CLUSTER_USD", "0"))
COPYABILITY_HTTP_CONCURRENCY = int(os.getenv("COPYABILITY_HTTP_CONCURRENCY", "4"))
COPYABILITY_HTTP_TIMEOUT_SECONDS = float(os.getenv("COPYABILITY_HTTP_TIMEOUT_SECONDS", "25"))
COPYABILITY_PRICE_HISTORY_ENABLED = os.getenv("COPYABILITY_PRICE_HISTORY_ENABLED", "true").lower() == "true"
COPYABILITY_PRICE_HISTORY_BATCH_ENABLED = os.getenv("COPYABILITY_PRICE_HISTORY_BATCH_ENABLED", "true").lower() == "true"
COPYABILITY_PRICE_FIDELITY_MINUTES = int(os.getenv("COPYABILITY_PRICE_FIDELITY_MINUTES", "5"))
COPYABILITY_PRICE_HORIZONS_HOURS = tuple(
    int(part.strip())
    for part in os.getenv("COPYABILITY_PRICE_HORIZONS_HOURS", "1,6,24").split(",")
    if part.strip()
)
COPYABILITY_PRICE_LOOKBACK_HOURS = int(os.getenv("COPYABILITY_PRICE_LOOKBACK_HOURS", "2"))
COPYABILITY_PRICE_POINT_TOLERANCE_MINUTES = int(os.getenv("COPYABILITY_PRICE_POINT_TOLERANCE_MINUTES", "15"))
COPYABILITY_PRICE_CACHE_ENABLED = os.getenv("COPYABILITY_PRICE_CACHE_ENABLED", "true").lower() == "true"
COPYABILITY_HEDGE_LOOKBACK_HOURS = int(os.getenv("COPYABILITY_HEDGE_LOOKBACK_HOURS", "24"))
COPYABILITY_RAPID_ROUNDTRIP_HOURS = int(os.getenv("COPYABILITY_RAPID_ROUNDTRIP_HOURS", "2"))
COPYABILITY_HISTORY_ENABLED = os.getenv("COPYABILITY_HISTORY_ENABLED", "true").lower() == "true"
COPYABILITY_STATE_ENABLED = os.getenv("COPYABILITY_STATE_ENABLED", "true").lower() == "true"
COPYABILITY_BACKTEST_ENABLED = os.getenv("COPYABILITY_BACKTEST_ENABLED", "true").lower() == "true"

WALLET_RE = __import__("re").compile(r"^0x[a-fA-F0-9]{40}$")

COPYABILITY_ACTIVITY_CACHE: dict[str, list[dict[str, Any]]] = {}


def _normalize_wallet(value: Any) -> str:
    return str(value or "").strip().lower()


def _valid_wallet(value: str) -> bool:
    return bool(WALLET_RE.match(value or ""))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except Exception:
        return default
    if math.isnan(number) or math.isinf(number):
        return default
    return number


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    if math.isnan(value) or math.isinf(value):
        return lower
    return max(lower, min(upper, value))


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_iso_now() -> str:
    return to_utc_iso(_utc_now()) or datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    return to_utc_datetime(value)


def _timestamp_iso(ts: datetime | None) -> str | None:
    return to_utc_iso(ts)


def _normalize_price(value: Any) -> float | None:
    price = _safe_float(value, default=float("nan"))
    if price != price or math.isinf(price) or price < 0 or price > 1:
        return None
    return round(price, 6)


def _normalize_nonnegative(value: Any) -> float:
    number = _safe_float(value, default=0.0)
    if number < 0 or math.isnan(number) or math.isinf(number):
        return 0.0
    return round(number, 6)


def _string_value(raw: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = raw.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _trade_type(raw: dict[str, Any]) -> str | None:
    for key in ("type", "eventType", "action", "kind"):
        value = str(raw.get(key) or "").strip().upper()
        if value:
            return value
    return None


def _normalize_side(value: Any) -> str | None:
    side = str(value or "").strip().upper()
    if side in {"BUY", "SELL"}:
        return side
    return None


def _deterministic_id(*parts: Any) -> str:
    payload = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def normalize_copyability_trade(raw: dict[str, Any], wallet: str) -> dict[str, Any] | None:
    wallet = _normalize_wallet(wallet)
    if not _valid_wallet(wallet):
        return None
    if not isinstance(raw, dict):
        return None

    trade_type = _trade_type(raw)
    if trade_type and trade_type not in {"TRADE", "BUY", "SELL", "MATCH"}:
        return None

    timestamp = to_utc_datetime(
        raw.get("timestamp")
        or raw.get("time")
        or raw.get("createdAt")
        or raw.get("executedAt")
        or raw.get("ts")
    )
    if timestamp is None:
        return None

    side = _normalize_side(raw.get("side") or raw.get("tradeSide") or raw.get("action"))
    if side is None:
        return None

    market_title = _string_value(raw, "marketTitle", "title", "question", "slug", "name")
    condition_id = _string_value(raw, "conditionId", "condition_id", "marketId", "market_id")
    asset = _string_value(raw, "asset", "tokenId", "token_id", "outcomeTokenId", "token")
    if not asset and condition_id:
        asset = condition_id

    price = _normalize_price(raw.get("price") or raw.get("avgPrice") or raw.get("executionPrice"))
    if price is None:
        return None

    shares = _normalize_nonnegative(raw.get("shares") or raw.get("quantity") or raw.get("amount"))
    size_usd = _normalize_nonnegative(
        raw.get("sizeUsd")
        or raw.get("usdcSize")
        or raw.get("size")
        or raw.get("value")
        or raw.get("usdSize")
    )

    if size_usd == 0.0 and shares == 0.0:
        return None

    transaction_hash = _string_value(raw, "transactionHash", "txHash", "hash")
    trade_id = _string_value(raw, "tradeId", "id", "trade_id")
    event_slug = _string_value(raw, "eventSlug", "slug")
    outcome = _string_value(raw, "outcome", "answer", "outcomeName")
    category = guess_skill_category_from_title(market_title or event_slug or condition_id or asset)

    if transaction_hash:
        dedupe_key = _deterministic_id(
            transaction_hash.lower(),
            asset.lower(),
            side,
            f"{size_usd:.6f}",
            f"{timestamp.timestamp():.0f}",
        )
    elif trade_id:
        dedupe_key = _deterministic_id(trade_id.lower())
    else:
        dedupe_key = _deterministic_id(
            wallet,
            condition_id.lower(),
            asset.lower(),
            side,
            f"{price:.6f}",
            f"{size_usd:.6f}",
            f"{timestamp.timestamp():.0f}",
        )

    normalized = {
        "tradeId": trade_id or transaction_hash or dedupe_key,
        "dedupeKey": dedupe_key,
        "transactionHash": transaction_hash or None,
        "wallet": wallet,
        "timestamp": to_unix_seconds(timestamp),
        "timestampIso": _timestamp_iso(timestamp),
        "conditionId": condition_id or None,
        "asset": asset or None,
        "marketTitle": market_title or condition_id or asset or None,
        "eventSlug": event_slug or None,
        "outcome": outcome or None,
        "side": side,
        "price": price,
        "shares": shares,
        "sizeUsd": size_usd,
        "category": category or "unknown",
        "rawSource": str(raw.get("rawSource") or raw.get("source") or "activity"),
    }
    return normalized


def dedupe_copyability_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for trade in trades:
        key = str(trade.get("dedupeKey") or "")
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(trade)
    return deduped


async def fetch_copyability_trades_for_wallet(
    wallet: str,
    limit: int,
    lookback_hours: int,
    *,
    client: httpx.AsyncClient | None = None,
    semaphore: asyncio.Semaphore | None = None,
    wallet_trade_cache: dict[str, list[dict[str, Any]]] | None = None,
    return_details: bool = False,
) -> list[dict[str, Any]] | dict[str, Any]:
    wallet = _normalize_wallet(wallet)
    if not _valid_wallet(wallet):
        if return_details:
            return {
                "wallet": wallet,
                "status": "failed",
                "reason": "invalid_wallet",
                "rawTrades": 0,
                "normalizedTrades": 0,
                "trades": [],
                "error": "invalid_wallet",
            }
        return []

    if wallet_trade_cache and wallet in wallet_trade_cache:
        cached = list(wallet_trade_cache[wallet])
        if return_details:
            return {
                "wallet": wallet,
                "status": "completed",
                "reason": "cache_hit",
                "rawTrades": len(cached),
                "normalizedTrades": len(cached),
                "trades": cached,
                "error": None,
            }
        return cached
    if wallet in COPYABILITY_ACTIVITY_CACHE:
        cached = list(COPYABILITY_ACTIVITY_CACHE[wallet])
        if return_details:
            return {
                "wallet": wallet,
                "status": "completed",
                "reason": "cache_hit",
                "rawTrades": len(cached),
                "normalizedTrades": len(cached),
                "trades": cached,
                "error": None,
            }
        return cached

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=COPYABILITY_HTTP_TIMEOUT_SECONDS)
        close_client = True

    collected: list[dict[str, Any]] = []
    error_message: str | None = None
    status = "completed"
    reason = "no_valid_trades"
    cutoff = _utc_now() - timedelta(hours=lookback_hours)
    try:
        for offset in range(0, limit, 50):
            params = {
                "user": wallet,
                "limit": min(50, limit - offset),
                "offset": offset,
                "takerOnly": False,
            }
            if semaphore is not None:
                async with semaphore:
                    response = await client.get("https://data-api.polymarket.com/trades", params=params)
            else:
                response = await client.get("https://data-api.polymarket.com/trades", params=params)
            response.raise_for_status()
            data = response.json()
            if isinstance(data, dict):
                items = data.get("data") or data.get("items") or data.get("trades") or []
            else:
                items = data
            if not isinstance(items, list) or not items:
                    break
            for raw in items:
                if not isinstance(raw, dict):
                    continue
                if _trade_type(raw) and _trade_type(raw) not in {"TRADE", "BUY", "SELL", "MATCH"}:
                    continue
                trade = normalize_copyability_trade(raw, wallet)
                if trade is None:
                    continue
                trade_ts = to_utc_datetime(trade.get("timestamp"))
                if trade_ts is None or trade_ts < cutoff:
                    continue
                collected.append(trade)
            if len(items) < 50:
                break
    except Exception:
        collected = []
        status = "failed"
        reason = "network_failure"
        error_message = "network_failure"
    finally:
        if close_client:
            await client.aclose()

    deduped = dedupe_copyability_trades(collected)
    deduped.sort(key=lambda item: to_unix_seconds(item.get("timestamp")) or 0)
    deduped = deduped[:limit]
    COPYABILITY_ACTIVITY_CACHE[wallet] = list(deduped)
    if wallet_trade_cache is not None:
        wallet_trade_cache[wallet] = list(deduped)
    if status != "failed" and not deduped:
        reason = "no_valid_trades"
    if return_details:
        return {
            "wallet": wallet,
            "status": status,
            "reason": reason,
            "rawTrades": len(collected),
            "normalizedTrades": len(deduped),
            "trades": deduped,
            "error": error_message,
        }
    return deduped


def build_trade_clusters(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        wallet = _normalize_wallet(trade.get("wallet"))
        condition_id = str(trade.get("conditionId") or "")
        asset = str(trade.get("asset") or "")
        side = str(trade.get("side") or "").upper()
        outcome = str(trade.get("outcome") or "").strip().lower()
        if not wallet or not condition_id or not asset or side not in {"BUY", "SELL"}:
            continue
        grouped[(wallet, condition_id, asset, side, outcome)].append(trade)

    clusters: list[dict[str, Any]] = []
    max_gap = timedelta(minutes=COPYABILITY_CLUSTER_GAP_MINUTES)
    max_duration = timedelta(hours=COPYABILITY_CLUSTER_MAX_HOURS)

    for (wallet, condition_id, asset, side, outcome), wallet_trades in grouped.items():
        ordered = sorted(wallet_trades, key=lambda item: to_unix_seconds(item.get("timestamp")) or 0)
        if not ordered:
            continue

        current: list[dict[str, Any]] = [ordered[0]]
        for trade in ordered[1:]:
            prev_ts = to_utc_datetime(current[-1].get("timestamp"))
            trade_ts = to_utc_datetime(trade.get("timestamp"))
            first_ts = to_utc_datetime(current[0].get("timestamp"))
            if prev_ts is None or trade_ts is None or first_ts is None:
                continue
            if trade_ts - prev_ts <= max_gap and trade_ts - first_ts <= max_duration:
                current.append(trade)
            else:
                clusters.append(_build_cluster(current, wallet, condition_id, asset, side, outcome))
                current = [trade]
        clusters.append(_build_cluster(current, wallet, condition_id, asset, side, outcome))

    if COPYABILITY_MIN_CLUSTER_USD > 0:
        clusters = [cluster for cluster in clusters if float(cluster.get("totalSizeUsd") or 0.0) >= COPYABILITY_MIN_CLUSTER_USD]

    clusters.sort(key=lambda item: (item["wallet"], item["conditionId"], item["asset"], item["side"], item["firstTradeAt"]))
    return clusters


def _build_cluster(
    trades: list[dict[str, Any]],
    wallet: str,
    condition_id: str,
    asset: str,
    side: str,
    outcome: str,
) -> dict[str, Any]:
    first_ts = to_utc_datetime(trades[0].get("timestamp")) or _utc_now()
    last_ts = to_utc_datetime(trades[-1].get("timestamp")) or first_ts
    trade_ids = [str(trade.get("tradeId") or trade.get("dedupeKey")) for trade in trades]
    total_size = sum(_safe_float(trade.get("sizeUsd")) for trade in trades)
    total_shares = sum(_safe_float(trade.get("shares")) for trade in trades)
    prices = [_safe_float(trade.get("price")) for trade in trades]
    weighted_prices = []
    weights = []
    if any(_safe_float(trade.get("shares")) > 0 for trade in trades):
        for trade in trades:
            shares = _safe_float(trade.get("shares"))
            if shares > 0:
                weighted_prices.append(_safe_float(trade.get("price")) * shares)
                weights.append(shares)
    elif any(_safe_float(trade.get("sizeUsd")) > 0 for trade in trades):
        for trade in trades:
            size_usd = _safe_float(trade.get("sizeUsd"))
            if size_usd > 0:
                weighted_prices.append(_safe_float(trade.get("price")) * size_usd)
                weights.append(size_usd)

    if weights:
        vwap = sum(weighted_prices) / sum(weights)
    else:
        vwap = mean(prices) if prices else 0.0

    sizes = [_safe_float(trade.get("sizeUsd")) for trade in trades]
    sizes_increasing = all(a < b for a, b in zip(sizes, sizes[1:])) if len(sizes) > 1 else False
    cluster_id = hashlib.sha1(
        "|".join(
            [
                wallet,
                condition_id,
                asset,
                side,
                outcome,
                first_ts.isoformat(),
                last_ts.isoformat(),
                ",".join(trade_ids),
            ]
        ).encode("utf-8")
    ).hexdigest()
    return {
        "clusterId": cluster_id,
        "wallet": wallet,
        "conditionId": condition_id,
        "asset": asset,
        "side": side,
        "outcome": outcome or None,
        "marketTitle": trades[0].get("marketTitle"),
        "category": trades[0].get("category") or "unknown",
        "tradeCount": len(trades),
        "firstTradeAt": first_ts.astimezone(timezone.utc).isoformat(),
        "lastTradeAt": last_ts.astimezone(timezone.utc).isoformat(),
        "durationMinutes": round((last_ts - first_ts).total_seconds() / 60.0, 2),
        "totalSizeUsd": round(total_size, 6),
        "totalShares": round(total_shares, 6),
        "vwapPrice": round(vwap, 6),
        "tradeIds": trade_ids,
        "sizesIncreasing": sizes_increasing,
        "tradeTs": [to_unix_seconds(trade.get("timestamp")) for trade in trades],
        "tradePrices": prices,
        "tradeSizes": sizes,
    }


def compute_wallet_cluster_baseline(clusters: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        wallet = _normalize_wallet(cluster.get("wallet"))
        if wallet:
            by_wallet[wallet].append(cluster)

    result: dict[str, dict[str, Any]] = {}
    for wallet, wallet_clusters in by_wallet.items():
        sizes = sorted(_safe_float(cluster.get("totalSizeUsd")) for cluster in wallet_clusters)
        if not sizes:
            continue
        result[wallet] = {
            "wallet": wallet,
            "clusterCount": len(wallet_clusters),
            "clusterSizes": sizes,
            "medianClusterSizeUsd": round(median(sizes), 6),
            "averageClusterSizeUsd": round(mean(sizes), 6),
            "p75ClusterSizeUsd": round(_percentile(sizes, 75), 6),
            "p90ClusterSizeUsd": round(_percentile(sizes, 90), 6),
            "maxClusterSizeUsd": round(max(sizes), 6),
        }
    return result


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    k = (len(ordered) - 1) * (percentile / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return ordered[int(k)]
    return ordered[f] * (c - k) + ordered[c] * (k - f)


def score_relative_conviction(cluster: dict[str, Any], wallet_baseline: dict[str, Any]) -> dict[str, Any]:
    cluster_sizes = list(wallet_baseline.get("clusterSizes") or [])
    total_size = _safe_float(cluster.get("totalSizeUsd"))
    median_size = _safe_float(wallet_baseline.get("medianClusterSizeUsd"))
    relative_size_ratio = total_size / median_size if median_size > 0 else None
    size_percentile = 0.0
    if cluster_sizes:
        smaller_or_equal = sum(1 for size in cluster_sizes if size <= total_size)
        size_percentile = (smaller_or_equal / len(cluster_sizes)) * 100.0
    relative_conviction_score = _clamp(20.0 + 0.80 * size_percentile)
    return {
        "relativeSizeRatio": round(relative_size_ratio, 6) if relative_size_ratio is not None else None,
        "sizePercentile": round(size_percentile, 2),
        "relativeConvictionScore": round(relative_conviction_score, 2),
    }


def score_accumulation(cluster: dict[str, Any], relative_size_ratio: float | None) -> dict[str, Any]:
    trade_count = int(cluster.get("tradeCount") or 0)
    if trade_count <= 1:
        base = 20
    elif trade_count == 2:
        base = 50
    elif trade_count == 3:
        base = 70
    else:
        base = 85

    bonus = 0
    if relative_size_ratio is not None and relative_size_ratio >= 2:
        bonus += 10
    if cluster.get("sizesIncreasing"):
        bonus += 5

    score = _clamp(base + bonus)
    return {
        "accumulationScore": round(score, 2),
        "tradeCount": trade_count,
    }


def score_hedge_probability(clusters: list[dict[str, Any]], target_cluster: dict[str, Any]) -> dict[str, Any]:
    wallet = _normalize_wallet(target_cluster.get("wallet"))
    condition_id = str(target_cluster.get("conditionId") or "")
    target_ts = _parse_timestamp(target_cluster.get("lastTradeAt")) or _utc_now()
    window_start = target_ts - timedelta(hours=COPYABILITY_HEDGE_LOOKBACK_HOURS)
    rapid_start = target_ts - timedelta(hours=COPYABILITY_RAPID_ROUNDTRIP_HOURS)
    same_wallet_condition = [
        cluster
        for cluster in clusters
        if _normalize_wallet(cluster.get("wallet")) == wallet
        and str(cluster.get("conditionId") or "") == condition_id
        and (cluster_ts := _parse_timestamp(cluster.get("lastTradeAt"))) is not None
        and window_start <= cluster_ts <= target_ts
    ]

    gross_buy_usd = sum(_safe_float(cluster.get("totalSizeUsd")) for cluster in same_wallet_condition if cluster.get("side") == "BUY")
    gross_sell_usd = sum(_safe_float(cluster.get("totalSizeUsd")) for cluster in same_wallet_condition if cluster.get("side") == "SELL")
    dominant_outcome = str(target_cluster.get("outcome") or "").strip().lower()
    dominant_outcome_buy_usd = sum(
        _safe_float(cluster.get("totalSizeUsd"))
        for cluster in same_wallet_condition
        if cluster.get("side") == "BUY" and str(cluster.get("outcome") or "").strip().lower() == dominant_outcome
    )
    opposing_outcome_buy_usd = sum(
        _safe_float(cluster.get("totalSizeUsd"))
        for cluster in same_wallet_condition
        if cluster.get("side") == "BUY" and str(cluster.get("outcome") or "").strip().lower() not in {dominant_outcome, ""}
    )

    net_directional_exposure_usd = gross_buy_usd - gross_sell_usd
    gross_total = gross_buy_usd + gross_sell_usd
    net_directional_ratio = abs(net_directional_exposure_usd) / gross_total if gross_total > 0 else 0.0

    rapid_roundtrip = any(
        cluster.get("asset") == target_cluster.get("asset")
        and cluster.get("side") != target_cluster.get("side")
        and (cluster_ts := _parse_timestamp(cluster.get("lastTradeAt"))) is not None
        and rapid_start <= cluster_ts <= target_ts
        for cluster in same_wallet_condition
    )
    rapid_roundtrip_ratio = 1.0 if rapid_roundtrip else 0.0

    hedge_probability = 0.0
    hedge_reasons: list[str] = []
    if opposing_outcome_buy_usd > 0:
        hedge_probability += 40
        hedge_reasons.append("opposing_outcome_buy")
    if gross_buy_usd > 0 and opposing_outcome_buy_usd >= 0.25 * gross_buy_usd:
        hedge_probability += 20
        hedge_reasons.append("opposing_buy_ge_25pct")
    if gross_buy_usd > 0 and opposing_outcome_buy_usd >= 0.50 * gross_buy_usd:
        hedge_probability += 20
        hedge_reasons.append("opposing_buy_ge_50pct")
    if rapid_roundtrip:
        hedge_probability += 35
        hedge_reasons.append("rapid_roundtrip")
    if net_directional_ratio < 0.40:
        hedge_probability += 30
        hedge_reasons.append("low_directional_ratio")

    hedge_probability = min(100.0, hedge_probability)
    if hedge_probability >= 80:
        hedge_label = "likely_hedge_or_arbitrage"
    elif hedge_probability >= 35:
        hedge_label = "possible_hedge"
    else:
        hedge_label = "low_hedge_probability"

    return {
        "grossBuyUsd": round(gross_buy_usd, 6),
        "grossSellUsd": round(gross_sell_usd, 6),
        "dominantOutcomeBuyUsd": round(dominant_outcome_buy_usd, 6),
        "opposingOutcomeBuyUsd": round(opposing_outcome_buy_usd, 6),
        "netDirectionalExposureUsd": round(net_directional_exposure_usd, 6),
        "netDirectionalRatio": round(net_directional_ratio, 6),
        "rapidRoundTripRatio": round(rapid_roundtrip_ratio, 6),
        "hedgeProbability": round(hedge_probability, 2),
        "hedgeReasons": hedge_reasons,
        "directionalityScore": round(100.0 - hedge_probability, 2),
        "hedgeLabel": hedge_label,
    }


def resolve_wallet_category_skill(wallet_shadow: dict[str, Any] | None, category: str) -> dict[str, Any]:
    category = str(category or "unknown").strip().lower()
    if not wallet_shadow:
        return {
            "marketCategory": category,
            "categorySkillStatus": "unknown_wallet_skill",
            "categorySkillScore": None,
            "walletCategorySkillScore": 50,
            "skillSource": "neutral_fallback",
            "robustSkillScore": None,
        }

    shadow_skill = wallet_shadow.get("shadowSkill") or {}
    shadow_robust = wallet_shadow.get("shadowRobustEvaluation") or {}
    category_scores = shadow_skill.get("categorySkillScores") or {}
    category_score = category_scores.get(category) or {}
    category_skill_status = str(category_score.get("skillStatus") or "unknown")
    category_skill_value = category_score.get("skillScore") if category_score else None
    category_skill_score = _safe_float(category_skill_value, default=0.0) if category_skill_value is not None else None
    robust_skill_value = shadow_robust.get("robustSkillScore") if shadow_robust else None
    robust_skill_score = _safe_float(robust_skill_value, default=0.0) if robust_skill_value is not None else None

    if category_skill_status == "sufficient" and category_skill_score is not None:
        wallet_category_skill_score = category_skill_score
        skill_source = "category_sufficient"
    elif category_skill_status == "limited" and category_skill_score is not None and robust_skill_score is not None:
        wallet_category_skill_score = 0.70 * category_skill_score + 0.30 * robust_skill_score
        skill_source = "category_limited_blended"
    elif robust_skill_score is not None:
        wallet_category_skill_score = robust_skill_score
        skill_source = "wallet_robust_fallback"
    else:
        wallet_category_skill_score = 50.0
        skill_source = "neutral_fallback"

    return {
        "marketCategory": category,
        "categorySkillStatus": category_skill_status,
        "categorySkillScore": round(category_skill_score, 2) if category_skill_score is not None else None,
        "robustSkillScore": round(robust_skill_score, 2) if robust_skill_score is not None else None,
        "walletCategorySkillScore": round(wallet_category_skill_score, 2),
        "skillSource": skill_source,
    }


def build_entry_context(cluster: dict[str, Any], price_history: list[dict[str, Any]] | None) -> dict[str, Any]:
    first_trade_at = _parse_timestamp(cluster.get("firstTradeAt")) or _utc_now()
    entry_vwap_price = _safe_float(cluster.get("vwapPrice"))
    price_before = None
    status = "available"
    if price_history:
        before_target = first_trade_at - timedelta(hours=1)
        point = find_nearest_price_point(price_history, before_target, tolerance_minutes=COPYABILITY_PRICE_POINT_TOLERANCE_MINUTES)
        if point is not None:
            price_before = _safe_float(point.get("price"))
        else:
            status = "insufficient_pretrade_history"
    else:
        status = "insufficient_pretrade_history"

    if price_before is None:
        return {
            "priceBefore1h": None,
            "entryVwapPrice": round(entry_vwap_price, 6),
            "sideAdjustedPreTradeMove1h": None,
            "chasePenalty": None,
            "entryContextScore": 50,
            "entryContextStatus": "insufficient_pretrade_history",
        }

    if str(cluster.get("side") or "") == "BUY":
        side_adjusted = entry_vwap_price - price_before
    else:
        side_adjusted = price_before - entry_vwap_price
    chase_penalty = _clamp(max(0.0, side_adjusted) * 400.0, 0.0, 40.0)
    return {
        "priceBefore1h": round(price_before, 6),
        "entryVwapPrice": round(entry_vwap_price, 6),
        "sideAdjustedPreTradeMove1h": round(side_adjusted, 6),
        "chasePenalty": round(chase_penalty, 2),
        "entryContextScore": round(_clamp(70.0 - chase_penalty), 2),
        "entryContextStatus": status,
    }


def build_liquidity_context(cluster: dict[str, Any], orderbook_snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if not orderbook_snapshot:
        return {
            "spread": None,
            "spreadScore": None,
            "depthUsd": None,
            "depthCoverageRatio": None,
            "depthCoverageScore": None,
            "liquidityScore": None,
            "liquidityStatus": "unavailable",
            "liquiditySnapshotAt": None,
        }

    best_bid = _safe_float(orderbook_snapshot.get("bestBid"))
    best_ask = _safe_float(orderbook_snapshot.get("bestAsk"))
    midpoint = _safe_float(orderbook_snapshot.get("midpoint"))
    if best_bid > 0 and best_ask > 0:
        spread = max(0.0, best_ask - best_bid)
    elif midpoint > 0 and _safe_float(orderbook_snapshot.get("spread")) > 0:
        spread = _safe_float(orderbook_snapshot.get("spread"))
    else:
        spread = None

    if spread is None:
        return {
            "spread": None,
            "spreadScore": None,
            "depthUsd": None,
            "depthCoverageRatio": None,
            "depthCoverageScore": None,
            "liquidityScore": None,
            "liquidityStatus": "unavailable",
            "liquiditySnapshotAt": orderbook_snapshot.get("snapshotAt"),
        }

    if spread <= 0.02:
        spread_score = 100
    elif spread <= 0.04:
        spread_score = 75
    elif spread <= 0.08:
        spread_score = 50
    else:
        spread_score = 20

    depth_usd = orderbook_snapshot.get("depthUsd")
    if depth_usd is None:
        return {
            "spread": round(spread, 6),
            "spreadScore": spread_score,
            "depthUsd": None,
            "depthCoverageRatio": None,
            "depthCoverageScore": None,
            "liquidityScore": spread_score,
            "liquidityStatus": "spread_only",
            "liquiditySnapshotAt": orderbook_snapshot.get("snapshotAt"),
        }

    depth_usd_value = _safe_float(depth_usd)
    total_size_usd = _safe_float(cluster.get("totalSizeUsd"))
    depth_coverage_ratio = depth_usd_value / total_size_usd if total_size_usd > 0 else None
    if depth_coverage_ratio is None:
        depth_coverage_score = 15
    elif depth_coverage_ratio >= 5:
        depth_coverage_score = 100
    elif depth_coverage_ratio >= 2:
        depth_coverage_score = 80
    elif depth_coverage_ratio >= 1:
        depth_coverage_score = 60
    elif depth_coverage_ratio >= 0.5:
        depth_coverage_score = 35
    else:
        depth_coverage_score = 15

    liquidity_score = 0.70 * spread_score + 0.30 * depth_coverage_score
    return {
        "spread": round(spread, 6),
        "spreadScore": spread_score,
        "depthUsd": round(depth_usd_value, 6),
        "depthCoverageRatio": round(depth_coverage_ratio, 6) if depth_coverage_ratio is not None else None,
        "depthCoverageScore": depth_coverage_score,
        "liquidityScore": round(liquidity_score, 2),
        "liquidityStatus": "available",
        "liquiditySnapshotAt": orderbook_snapshot.get("snapshotAt"),
    }


def score_copyability_at_detection(
    cluster: dict[str, Any],
    wallet_shadow: dict[str, Any] | None,
    wallet_baseline: dict[str, Any] | None,
    all_clusters: list[dict[str, Any]],
    price_context: dict[str, Any] | None,
    liquidity_context: dict[str, Any] | None,
) -> dict[str, Any]:
    wallet_category_skill = resolve_wallet_category_skill(wallet_shadow, str(cluster.get("category") or "unknown"))
    baseline = wallet_baseline or {}
    relative = score_relative_conviction(cluster, baseline) if baseline else {
        "relativeSizeRatio": None,
        "sizePercentile": 0.0,
        "relativeConvictionScore": 20.0,
    }
    accumulation = score_accumulation(cluster, relative.get("relativeSizeRatio"))
    hedge = score_hedge_probability(all_clusters, cluster)
    entry = price_context or {
        "entryContextScore": None,
        "entryContextStatus": "unavailable",
        "chasePenalty": None,
    }
    liquidity = liquidity_context or {
        "liquidityScore": None,
        "liquidityStatus": "unavailable",
    }

    factors = [
        ("walletCategorySkillScore", _safe_float(wallet_category_skill["walletCategorySkillScore"], default=50.0), 30.0, True),
        ("relativeConvictionScore", _safe_float(relative.get("relativeConvictionScore"), default=50.0), 25.0, True),
        ("accumulationScore", _safe_float(accumulation.get("accumulationScore"), default=50.0), 20.0, True),
        ("entryContextScore", _safe_float(entry.get("entryContextScore"), default=50.0), 15.0, True),
        ("liquidityScore", liquidity.get("liquidityScore"), 10.0, liquidity.get("liquidityScore") is not None),
    ]
    available_weight = 0.0
    weighted_total = 0.0
    for _name, value, weight, available in factors:
        if not available or value is None:
            continue
        available_weight += weight
        weighted_total += value * weight
    factor_availability_score = (available_weight / 100.0) * 100.0
    base_score = weighted_total / available_weight if available_weight > 0 else 0.0
    score = _clamp(base_score - (_safe_float(hedge.get("hedgeProbability")) * 0.35))

    side = str(cluster.get("side") or "").upper()
    status = "low_copyability"
    if factor_availability_score < 60:
        status = "insufficient_data"
    elif _safe_float(hedge.get("hedgeProbability")) >= 70:
        status = "not_copyable"
        score = min(score, 35)
    elif side == "SELL":
        status = "reduction_signal"
        score = min(score, 55)
    elif score >= 75 and factor_availability_score >= 70 and _safe_float(hedge.get("hedgeProbability")) < 35 and side == "BUY":
        status = "high_copyability"
    elif 60 <= score < 75:
        status = "watch_copyability"

    return {
        "walletCategorySkillScore": round(_safe_float(wallet_category_skill["walletCategorySkillScore"], default=50.0), 2),
        "relativeConvictionScore": relative.get("relativeConvictionScore"),
        "accumulationScore": accumulation.get("accumulationScore"),
        "entryContextScore": entry.get("entryContextScore"),
        "liquidityScore": liquidity.get("liquidityScore"),
        "factorAvailabilityScore": round(factor_availability_score, 2),
        "copyabilityDetectionBaseScore": round(base_score, 2),
        "hedgePenalty": round(_safe_float(hedge.get("hedgeProbability")) * 0.35, 2),
        "copyabilityAtDetectionScore": round(score, 2),
        "copyabilityStatus": status,
        "walletCategorySkill": wallet_category_skill,
        "relativeConviction": relative,
        "accumulation": accumulation,
        "hedge": hedge,
        "entryContext": entry,
        "liquidityContext": liquidity,
        "sizePercentile": relative.get("sizePercentile"),
    }


def assign_copyability_label(scored_cluster: dict[str, Any]) -> str:
    hedge_probability = _safe_float((scored_cluster.get("hedge") or {}).get("hedgeProbability"))
    side = str(scored_cluster.get("side") or "").upper()
    status = str(scored_cluster.get("copyabilityStatus") or "")
    size_percentile = _safe_float(scored_cluster.get("sizePercentile"))
    trade_count = int(scored_cluster.get("tradeCount") or 0)
    accumulation_score = _safe_float(scored_cluster.get("accumulationScore"))
    validation_status = str(scored_cluster.get("validationStatus") or "pending")

    if hedge_probability >= 70:
        return "COBERTURA_NO_COPIABLE"
    if side == "SELL":
        return "REDUCCION_DE_TESIS"
    if status == "high_copyability" and size_percentile >= 85:
        return "ALTA_CONVICCION"
    if trade_count >= 3 or accumulation_score >= 70:
        return "ACUMULACION"
    if validation_status in {"pending", "partial"} and _safe_float(scored_cluster.get("copyabilityAtDetectionScore")) >= 70:
        return "PENDIENTE_VALIDACION"
    if validation_status == "complete" and side == "BUY" and _safe_float(scored_cluster.get("postTradeFollowthroughScore")) >= 70 and _safe_float(scored_cluster.get("chasePenalty")) <= 10 and hedge_probability < 35:
        return "ENTRADA_TEMPRANA"
    return "ACTIVIDAD_RUTINARIA"


def validate_cluster_retrospectively(
    cluster: dict[str, Any],
    price_history: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    price_history = price_history or []
    entry_ts = _parse_timestamp(cluster.get("lastTradeAt")) or _utc_now()
    now_ts = _utc_now()
    horizons = list(COPYABILITY_PRICE_HORIZONS_HOURS)
    available: dict[int, float] = {}
    mature_horizons = [hour for hour in horizons if now_ts >= entry_ts + timedelta(hours=hour)]
    if not price_history:
        return {
            "priceAfter1h": None,
            "priceAfter6h": None,
            "priceAfter24h": None,
            "followthrough1h": None,
            "followthrough6h": None,
            "followthrough24h": None,
            "postTradeFollowthroughScore": None,
            "validationStatus": "pending",
            "validationReason": "empty_history",
            "priceHistoryStatus": "empty_history",
            "copyabilityValidatedScore": None,
        }

    if not mature_horizons:
        return {
            "priceAfter1h": None,
            "priceAfter6h": None,
            "priceAfter24h": None,
            "followthrough1h": None,
            "followthrough6h": None,
            "followthrough24h": None,
            "postTradeFollowthroughScore": None,
            "validationStatus": "pending",
            "validationReason": "horizons_not_mature",
            "priceHistoryStatus": "horizons_not_mature",
            "copyabilityValidatedScore": None,
        }

    for hour in mature_horizons:
        target_ts = entry_ts + timedelta(hours=hour)
        point = find_nearest_price_point(price_history, target_ts, tolerance_minutes=COPYABILITY_PRICE_POINT_TOLERANCE_MINUTES)
        if point is not None:
            available[hour] = _safe_float(point.get("price"))

    if not available:
        return {
            "priceAfter1h": None,
            "priceAfter6h": None,
            "priceAfter24h": None,
            "followthrough1h": None,
            "followthrough6h": None,
            "followthrough24h": None,
            "postTradeFollowthroughScore": None,
            "validationStatus": "pending",
            "validationReason": "missing_price_point",
            "priceHistoryStatus": "missing_price_point",
            "copyabilityValidatedScore": None,
        }

    entry_price = _safe_float(cluster.get("vwapPrice"))
    side = str(cluster.get("side") or "").upper()
    followthrough: dict[int, float | None] = {}
    for hour, future_price in available.items():
        if side == "SELL":
            followthrough[hour] = entry_price - future_price
        else:
            followthrough[hour] = future_price - entry_price

    weights = {1: 0.20, 6: 0.30, 24: 0.50}
    weight_sum = sum(weights[hour] for hour in available if hour in weights)
    weighted_followthrough = sum(followthrough[hour] * weights[hour] for hour in available if hour in weights) / weight_sum
    post_trade_score = _clamp(50.0 + weighted_followthrough * 500.0)
    copyability_validated_score = 0.70 * _safe_float(cluster.get("copyabilityAtDetectionScore")) + 0.30 * post_trade_score
    if len(available) < len(mature_horizons):
        validation_status = "partial"
        validation_reason = "missing_price_point"
        price_history_status = "missing_price_point"
    else:
        validation_status = "complete"
        validation_reason = "ok"
        price_history_status = "ok"

    result = {
        "priceAfter1h": available.get(1),
        "priceAfter6h": available.get(6),
        "priceAfter24h": available.get(24),
        "followthrough1h": followthrough.get(1),
        "followthrough6h": followthrough.get(6),
        "followthrough24h": followthrough.get(24),
        "postTradeFollowthroughScore": round(post_trade_score, 2),
        "validationStatus": validation_status,
        "validationReason": validation_reason,
        "priceHistoryStatus": price_history_status,
        "copyabilityValidatedScore": round(copyability_validated_score, 2),
    }

    if validation_status == "pending":
        result["copyabilityValidatedScore"] = None
    return result


def deep_engine_relevance_score_for_category(category: str) -> int:
    mapping = {
        "politics": 100,
        "geopolitics": 100,
        "macro": 100,
        "crypto": 90,
        "technology": 90,
        "culture_awards": 75,
        "sports": 40,
        "esports": 40,
        "unknown": 25,
    }
    return mapping.get(str(category or "unknown").strip().lower(), 25)


def build_wallet_copyability_summary(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        wallet = _normalize_wallet(cluster.get("wallet"))
        if wallet:
            by_wallet[wallet].append(cluster)

    summary: dict[str, Any] = {}
    for wallet, wallet_clusters in by_wallet.items():
        detection_scores = [_safe_float(cluster.get("copyabilityAtDetectionScore")) for cluster in wallet_clusters]
        validated_scores = [
            _safe_float(cluster.get("copyabilityValidatedScore"))
            for cluster in wallet_clusters
            if cluster.get("copyabilityValidatedScore") is not None
        ]
        follow1 = [cluster.get("followthrough1h") for cluster in wallet_clusters if cluster.get("followthrough1h") is not None]
        follow6 = [cluster.get("followthrough6h") for cluster in wallet_clusters if cluster.get("followthrough6h") is not None]
        follow24 = [cluster.get("followthrough24h") for cluster in wallet_clusters if cluster.get("followthrough24h") is not None]
        best_category = None
        if wallet_clusters:
            best_category = max(
                wallet_clusters,
                key=lambda cluster: _safe_float(cluster.get("copyabilityValidatedScore"), default=_safe_float(cluster.get("copyabilityAtDetectionScore"))),
            ).get("category")

        hedge_count_70 = 0
        possible_hedge_count_60 = 0
        for cluster in wallet_clusters:
            hedge_probability = _safe_float((cluster.get("hedge") or {}).get("hedgeProbability"))
            copyability_status = str(cluster.get("copyabilityStatus") or "")
            copyability_label = str(cluster.get("copyabilityLabel") or "")
            hedge_label = str((cluster.get("hedge") or {}).get("hedgeLabel") or "")

            is_hedge_70 = hedge_probability >= 70 or copyability_status == "not_copyable" or copyability_label == "COBERTURA_NO_COPIABLE"
            is_possible_hedge_60 = hedge_probability >= 60 or hedge_label in {"possible_hedge", "likely_hedge_or_arbitrage"}

            hedge_count_70 += 1 if is_hedge_70 else 0
            possible_hedge_count_60 += 1 if is_possible_hedge_60 else 0

        summary[wallet] = {
            "wallet": wallet,
            "clustersCount": len(wallet_clusters),
            "buyClusters": sum(1 for cluster in wallet_clusters if cluster.get("side") == "BUY"),
            "sellClusters": sum(1 for cluster in wallet_clusters if cluster.get("side") == "SELL"),
            "highCopyabilityCount": sum(1 for cluster in wallet_clusters if cluster.get("copyabilityStatus") == "high_copyability"),
            "watchCopyabilityCount": sum(1 for cluster in wallet_clusters if cluster.get("copyabilityStatus") == "watch_copyability"),
            "notCopyableCount": sum(1 for cluster in wallet_clusters if cluster.get("copyabilityStatus") == "not_copyable"),
            "reductionSignalCount": sum(1 for cluster in wallet_clusters if cluster.get("copyabilityStatus") == "reduction_signal"),
            "accumulationCount": sum(1 for cluster in wallet_clusters if cluster.get("copyabilityLabel") == "ACUMULACION"),
            "averageDetectionScore": round(mean(detection_scores), 2) if detection_scores else None,
            "medianDetectionScore": round(median(detection_scores), 2) if detection_scores else None,
            "averageValidatedScore": round(mean(validated_scores), 2) if validated_scores else None,
            "positiveFollowthroughRate1h": round(sum(1 for x in follow1 if x and x > 0) / len(follow1), 4) if follow1 else None,
            "positiveFollowthroughRate6h": round(sum(1 for x in follow6 if x and x > 0) / len(follow6), 4) if follow6 else None,
            "positiveFollowthroughRate24h": round(sum(1 for x in follow24 if x and x > 0) / len(follow24), 4) if follow24 else None,
            "hedgeCount70": hedge_count_70,
            "possibleHedgeCount60": possible_hedge_count_60,
            "hedgeRate70": round(hedge_count_70 / len(wallet_clusters), 4) if wallet_clusters else 0.0,
            "possibleHedgeRate60": round(possible_hedge_count_60 / len(wallet_clusters), 4) if wallet_clusters else 0.0,
            "hedgeRate": round(hedge_count_70 / len(wallet_clusters), 4) if wallet_clusters else 0.0,
            "bestCategory": best_category,
            "generatedAt": _utc_iso_now(),
        }
    return summary


def build_trade_copyability_backtest(clusters: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        label = str(cluster.get("copyabilityLabel") or "ACTIVIDAD_RUTINARIA")
        detection_status = str(cluster.get("copyabilityStatus") or "low_copyability")
        groups[
            (
                _normalize_wallet(cluster.get("wallet")),
                str(cluster.get("category") or "unknown"),
                label,
                detection_status,
            )
        ].append(cluster)

    backtest: list[dict[str, Any]] = []
    for (wallet, category, label, detection_status), rows in groups.items():
        sample_count = len(rows)
        follow1 = [cluster.get("followthrough1h") for cluster in rows if cluster.get("followthrough1h") is not None]
        follow6 = [cluster.get("followthrough6h") for cluster in rows if cluster.get("followthrough6h") is not None]
        follow24 = [cluster.get("followthrough24h") for cluster in rows if cluster.get("followthrough24h") is not None]
        mature1h = len(follow1)
        mature6h = len(follow6)
        mature24h = len(follow24)
        sample_reliability_status = "insufficient_sample" if sample_count < 5 else "adequate"
        mature_total = mature1h + mature6h + mature24h
        if mature_total == 0:
            validation_reliability_status = "pending_validation"
        elif mature1h > 0 and mature6h > 0 and mature24h > 0:
            validation_reliability_status = "complete_validation"
        elif sample_reliability_status == "insufficient_sample":
            validation_reliability_status = "insufficient_mature_horizons"
        else:
            validation_reliability_status = "partial_validation"
        backtest.append(
            {
                "wallet": wallet,
                "category": category,
                "label": label,
                "detectionStatus": detection_status,
                "sampleCount": sample_count,
                "mature1hCount": mature1h,
                "mature6hCount": mature6h,
                "mature24hCount": mature24h,
                "averageFollowthrough1h": round(mean(follow1), 6) if follow1 else None,
                "averageFollowthrough6h": round(mean(follow6), 6) if follow6 else None,
                "averageFollowthrough24h": round(mean(follow24), 6) if follow24 else None,
                "positiveFollowthroughRate1h": round(sum(1 for x in follow1 if x > 0) / len(follow1), 4) if follow1 else None,
                "positiveFollowthroughRate6h": round(sum(1 for x in follow6 if x > 0) / len(follow6), 4) if follow6 else None,
                "positiveFollowthroughRate24h": round(sum(1 for x in follow24 if x > 0) / len(follow24), 4) if follow24 else None,
                "averageDetectionScore": round(mean(_safe_float(cluster.get("copyabilityAtDetectionScore")) for cluster in rows), 2),
                "averageValidatedScore": round(mean(_safe_float(cluster.get("copyabilityValidatedScore")) for cluster in rows if cluster.get("copyabilityValidatedScore") is not None), 2)
                if any(cluster.get("copyabilityValidatedScore") is not None for cluster in rows)
                else None,
                "sampleReliabilityStatus": sample_reliability_status,
                "validationReliabilityStatus": validation_reliability_status,
                "reliabilityStatus": sample_reliability_status,
            }
        )

    return {"groups": backtest}


def _wallet_display(wallet_row: dict[str, Any], fallback: str) -> str:
    return str(wallet_row.get("displayName") or fallback)


def _wallet_profiles(wallet_row: dict[str, Any]) -> list[str]:
    return list(wallet_row.get("profiles") or [])


def _wallet_roles(wallet_row: dict[str, Any]) -> list[str]:
    return list(wallet_row.get("roles") or [])


async def run_trade_copyability_shadow(
    *,
    run_id: str,
    wallet_scores: list[dict[str, Any]],
    shadow_phase: dict[str, Any] | None,
    deduped_trades: list[dict[str, Any]],
    price_history_client: Any | None = None,
) -> dict[str, Any]:
    selected_wallet_rows = list((shadow_phase or {}).get("cohort") or [])
    if not selected_wallet_rows:
        selected_wallet_rows = [
            {
                "wallet": item.get("wallet"),
                "displayName": item.get("wallet"),
                "roles": [],
                "profiles": [],
                "sources": [],
                "classification": item.get("classification"),
                "behaviorQualityScore": item.get("walletQualityScore"),
                "shadowSkill": item.get("shadowSkill"),
                "shadowMetaEvaluation": item.get("shadowMetaEvaluation"),
                "shadowRobustEvaluation": item.get("shadowRobustEvaluation"),
            }
            for item in wallet_scores[:COPYABILITY_MAX_WALLETS_PER_RUN]
        ]

    selected_wallet_rows = selected_wallet_rows[:COPYABILITY_MAX_WALLETS_PER_RUN]
    print(
        "SMART_MONEY_COPYABILITY_STARTED "
        f"wallets={len(selected_wallet_rows)} "
        f"lookback_hours={COPYABILITY_LOOKBACK_HOURS}"
    )

    wallet_score_map = {
        _normalize_wallet(score.get("wallet")): score
        for score in wallet_scores
        if score.get("wallet")
    }
    shadow_row_map: dict[str, dict[str, Any]] = {}
    if shadow_phase:
        for row in list(shadow_phase.get("shadow_rows") or []) + list(shadow_phase.get("cohort") or []):
            wallet = _normalize_wallet(row.get("wallet"))
            if wallet and wallet not in shadow_row_map:
                shadow_row_map[wallet] = row
    wallet_trade_cache: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in deduped_trades:
        wallet = _normalize_wallet(trade.get("wallet"))
        if wallet:
            wallet_trade_cache[wallet].append(trade)
    for wallet in list(wallet_trade_cache.keys()):
        wallet_trade_cache[wallet].sort(key=lambda item: to_unix_seconds(item.get("timestamp")) or 0)

    cluster_rows: list[dict[str, Any]] = []
    wallet_results: list[dict[str, Any]] = []
    failed_wallets = 0
    skipped_wallets = 0
    semaphore = asyncio.Semaphore(max(1, COPYABILITY_HTTP_CONCURRENCY))
    price_history_requests = 0
    price_history_cache_hits = 0

    for wallet_row in selected_wallet_rows:
        wallet = _normalize_wallet(wallet_row.get("wallet"))
        if not _valid_wallet(wallet):
            skipped_wallets += 1
            wallet_results.append(
                {
                    "wallet": wallet,
                    "status": "skipped",
                    "rawTrades": 0,
                    "normalizedTrades": 0,
                    "clusters": 0,
                    "reason": "invalid_wallet",
                }
            )
            print(f"SMART_MONEY_COPYABILITY_WALLET_SKIPPED wallet={wallet} reason=invalid_wallet")
            continue
        try:
            fetch_result: dict[str, Any]
            raw_trades = list(wallet_trade_cache.get(wallet) or [])
            if raw_trades:
                fetch_result = {
                    "wallet": wallet,
                    "status": "completed",
                    "reason": "cache_hit",
                    "rawTrades": len(raw_trades),
                    "normalizedTrades": len(raw_trades),
                    "trades": raw_trades,
                    "error": None,
                }
            else:
                fetch_result = await fetch_copyability_trades_for_wallet(
                    wallet,
                    COPYABILITY_MAX_TRADES_PER_WALLET,
                    COPYABILITY_LOOKBACK_HOURS,
                    semaphore=semaphore,
                    wallet_trade_cache=wallet_trade_cache,
                    return_details=True,
                )
                if not isinstance(fetch_result, dict):
                    fetch_result = {
                        "wallet": wallet,
                        "status": "completed",
                        "reason": "cache_hit",
                        "rawTrades": len(fetch_result),
                        "normalizedTrades": len(fetch_result),
                        "trades": list(fetch_result),
                        "error": None,
                    }
            normalized = list(fetch_result.get("trades") or [])
            raw_trade_count = int(fetch_result.get("rawTrades") or len(raw_trades) or len(normalized))
            normalized_trade_count = int(fetch_result.get("normalizedTrades") or len(normalized))
            clusters = build_trade_clusters(normalized)
            cluster_rows.extend(clusters)
            if str(fetch_result.get("status") or "") == "failed":
                failed_wallets += 1
                reason = str(fetch_result.get("reason") or "network_failure")
                wallet_results.append(
                    {
                        "wallet": wallet,
                        "status": "failed",
                        "rawTrades": raw_trade_count,
                        "normalizedTrades": normalized_trade_count,
                        "clusters": len(clusters),
                        "reason": reason,
                    }
                )
                print(
                    "SMART_MONEY_COPYABILITY_WALLET_FAILED "
                    f"wallet={wallet} "
                    f"reason={reason} "
                    f"raw_trades={raw_trade_count} "
                    f"normalized={normalized_trade_count} "
                    f"clusters={len(clusters)}"
                )
                continue
            if normalized_trade_count == 0:
                reason = "no_valid_trades"
            elif not clusters:
                reason = "no_clusters_after_filters"
            else:
                reason = "clusters_generated"
            wallet_results.append(
                {
                    "wallet": wallet,
                    "status": "completed",
                    "rawTrades": raw_trade_count,
                    "normalizedTrades": normalized_trade_count,
                    "clusters": len(clusters),
                    "reason": reason,
                }
            )
            print(
                "SMART_MONEY_COPYABILITY_WALLET_FETCHED "
                f"wallet={wallet} "
                f"raw_trades={raw_trade_count} "
                f"normalized={normalized_trade_count} "
                f"clusters={len(clusters)}"
            )
        except Exception as error:
            failed_wallets += 1
            reason = "network_failure" if isinstance(error, httpx.HTTPError) else "unexpected_error"
            wallet_results.append(
                {
                    "wallet": wallet,
                    "status": "failed",
                    "rawTrades": 0,
                    "normalizedTrades": 0,
                    "clusters": 0,
                    "reason": reason,
                    "error": error.__class__.__name__,
                }
            )
            print(
                "SMART_MONEY_COPYABILITY_WALLET_FAILED "
                f"wallet={wallet} "
                f"reason={reason} "
                f"error={error.__class__.__name__}"
            )

    clusters_by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cluster in cluster_rows:
        clusters_by_wallet[_normalize_wallet(cluster.get("wallet"))].append(cluster)

    baselines = compute_wallet_cluster_baseline(cluster_rows)
    orderbook_snapshots: dict[str, dict[str, Any]] = {}
    if COPYABILITY_PRICE_HISTORY_BATCH_ENABLED and COPYABILITY_PRICE_HISTORY_ENABLED:
        token_ids = [str(cluster.get("asset") or "") for cluster in cluster_rows if cluster.get("asset")]
        price_history_requests = len({token for token in token_ids if token})
        start_candidates = [
            _parse_timestamp(cluster.get("firstTradeAt")) - timedelta(hours=1)
            for cluster in cluster_rows
            if _parse_timestamp(cluster.get("firstTradeAt")) is not None
        ]
        end_candidates = [
            _parse_timestamp(cluster.get("lastTradeAt")) + timedelta(hours=max(COPYABILITY_PRICE_HORIZONS_HOURS))
            for cluster in cluster_rows
            if _parse_timestamp(cluster.get("lastTradeAt")) is not None
        ]
        start_timestamp = min(start_candidates) if start_candidates else None
        end_timestamp = max(end_candidates) if end_candidates else None
        batch_histories = await fetch_batch_price_history(
            token_ids,
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            fidelity=str(COPYABILITY_PRICE_FIDELITY_MINUTES),
            cache_enabled=COPYABILITY_PRICE_CACHE_ENABLED,
        )
        price_history_cache_hits = max(0, len(token_ids) - price_history_requests)
        resolved_points = sum(len(points or []) for points in batch_histories.values())
        missing_points = max(0, price_history_requests - sum(1 for points in batch_histories.values() if points))
        print(
            "SMART_MONEY_COPYABILITY_PRICE_HISTORY_BATCH "
            f"tokens={len(set(token_ids))} "
            f"requests={price_history_requests} "
            f"cache_hits={price_history_cache_hits} "
            f"resolved_points={resolved_points} "
            f"missing_points={missing_points}"
        )
    else:
        batch_histories = {}
        print("SMART_MONEY_COPYABILITY_PRICE_HISTORY_BATCH tokens=0 requests=0 cache_hits=0 resolved_points=0 missing_points=0")

    scored_clusters: list[dict[str, Any]] = []
    for cluster in cluster_rows:
        wallet = _normalize_wallet(cluster.get("wallet"))
        wallet_row = next((row for row in selected_wallet_rows if _normalize_wallet(row.get("wallet")) == wallet), None)
        wallet_shadow = shadow_row_map.get(wallet) or wallet_score_map.get(wallet)
        baseline = baselines.get(wallet) or {}
        price_history = []
        if COPYABILITY_PRICE_HISTORY_ENABLED and cluster.get("asset"):
            price_history = batch_histories.get(str(cluster.get("asset") or ""), [])
        entry_context = build_entry_context(cluster, price_history)
        liquidity_context = build_liquidity_context(cluster, orderbook_snapshots.get(str(cluster.get("asset") or "")))
        detection = score_copyability_at_detection(
            cluster,
            wallet_shadow,
            baseline,
            cluster_rows,
            entry_context,
            liquidity_context,
        )
        validation = validate_cluster_retrospectively(cluster, price_history if COPYABILITY_PRICE_HISTORY_ENABLED else [])
        price_history_status = validation.get("priceHistoryStatus")
        validation_reason = validation.get("validationReason")
        if not cluster.get("asset"):
            price_history_status = "token_unresolved"
            validation_reason = "token_unresolved"
            validation["validationStatus"] = "pending"
            validation["copyabilityValidatedScore"] = None
        scored_cluster = {
            **cluster,
            "displayName": _wallet_display(wallet_row or {}, wallet),
            "roles": _wallet_roles(wallet_row or {}),
            "profiles": _wallet_profiles(wallet_row or {}),
            "walletCategorySkillScore": detection["walletCategorySkillScore"],
            "categorySkillStatus": detection["walletCategorySkill"]["categorySkillStatus"],
            "categorySkillScore": detection["walletCategorySkill"]["categorySkillScore"],
            "robustSkillScore": detection["walletCategorySkill"]["robustSkillScore"],
            "skillSource": detection["walletCategorySkill"]["skillSource"],
            "relativeConvictionScore": detection["relativeConvictionScore"],
            "accumulationScore": detection["accumulationScore"],
            "hedgeProbability": detection["hedge"]["hedgeProbability"],
            "directionalityScore": detection["hedge"]["directionalityScore"],
            "hedgeLabel": detection["hedge"]["hedgeLabel"],
            "entryContextScore": detection["entryContextScore"],
            "entryContextStatus": detection["entryContext"]["entryContextStatus"],
            "chasePenalty": detection["entryContext"]["chasePenalty"],
            "liquidityScore": detection["liquidityScore"],
            "liquidityStatus": detection["liquidityContext"]["liquidityStatus"],
            "factorAvailabilityScore": detection["factorAvailabilityScore"],
            "copyabilityAtDetectionScore": detection["copyabilityAtDetectionScore"],
            "copyabilityStatus": detection["copyabilityStatus"],
            "copyabilityLabel": assign_copyability_label(
                {
                    **cluster,
                    **detection,
                    **validation,
                    "chasePenalty": detection["entryContext"]["chasePenalty"],
                }
            ),
            "validationStatus": validation["validationStatus"],
            "priceAfter1h": validation["priceAfter1h"],
            "priceAfter6h": validation["priceAfter6h"],
            "priceAfter24h": validation["priceAfter24h"],
            "followthrough1h": validation["followthrough1h"],
            "followthrough6h": validation["followthrough6h"],
            "followthrough24h": validation["followthrough24h"],
            "postTradeFollowthroughScore": validation["postTradeFollowthroughScore"],
            "copyabilityValidatedScore": validation["copyabilityValidatedScore"],
            "validationReason": validation_reason,
            "priceHistoryStatus": price_history_status,
            "deepEngineRelevanceScore": deep_engine_relevance_score_for_category(cluster.get("category")),
            "deepEngineCopyabilityScore": round(
                detection["copyabilityAtDetectionScore"] * deep_engine_relevance_score_for_category(cluster.get("category")) / 100.0,
                2,
            ),
            "generatedAt": _utc_iso_now(),
        }
        scored_clusters.append(scored_cluster)
        print(
            "SMART_MONEY_COPYABILITY_CLUSTER_SCORED "
            f"cluster={cluster.get('clusterId')} "
            f"wallet={wallet} "
            f"detection={scored_cluster['copyabilityAtDetectionScore']} "
            f"status={scored_cluster['copyabilityStatus']} "
            f"label={scored_cluster['copyabilityLabel']} "
            f"hedge={scored_cluster['hedgeProbability']}"
        )
        print(
            "SMART_MONEY_COPYABILITY_VALIDATED "
            f"cluster={cluster.get('clusterId')} "
            f"status={scored_cluster['validationStatus']} "
            f"reason={scored_cluster.get('validationReason')} "
            f"validated_score={scored_cluster['copyabilityValidatedScore']}"
        )

    scored_clusters.sort(
        key=lambda item: (
            _safe_float(item.get("copyabilityAtDetectionScore")),
            _safe_float(item.get("totalSizeUsd")),
            _parse_timestamp(item.get("lastTradeAt")) or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )

    state = read_trade_copyability_state() if COPYABILITY_STATE_ENABLED else {}
    for cluster in scored_clusters:
        state[str(cluster.get("clusterId"))] = {
            "clusterId": cluster.get("clusterId"),
            "wallet": cluster.get("wallet"),
            "validationStatus": cluster.get("validationStatus"),
            "copyabilityValidatedScore": cluster.get("copyabilityValidatedScore"),
            "copyabilityAtDetectionScore": cluster.get("copyabilityAtDetectionScore"),
            "updatedAt": cluster.get("generatedAt"),
        }

    history_path = None
    if COPYABILITY_HISTORY_ENABLED:
        history_path = append_trade_copyability_history(
            [
                {
                    "runId": run_id,
                    "clusterId": cluster.get("clusterId"),
                    "wallet": cluster.get("wallet"),
                    "validationStatus": cluster.get("validationStatus"),
                    "copyabilityLabel": cluster.get("copyabilityLabel"),
                    "copyabilityStatus": cluster.get("copyabilityStatus"),
                    "copyabilityAtDetectionScore": cluster.get("copyabilityAtDetectionScore"),
                    "copyabilityValidatedScore": cluster.get("copyabilityValidatedScore"),
                    "deepEngineCopyabilityScore": cluster.get("deepEngineCopyabilityScore"),
                    "generatedAt": cluster.get("generatedAt"),
                    "category": cluster.get("category"),
                    "side": cluster.get("side"),
                    "priceAfter1h": cluster.get("priceAfter1h"),
                    "priceAfter6h": cluster.get("priceAfter6h"),
                    "priceAfter24h": cluster.get("priceAfter24h"),
                }
                for cluster in scored_clusters
            ]
        )
    if COPYABILITY_STATE_ENABLED:
        write_trade_copyability_state(state)

    summary = build_wallet_copyability_summary(scored_clusters)
    backtest = build_trade_copyability_backtest(scored_clusters)
    shadow_payload = {
        "runId": run_id,
        "generatedAt": _utc_iso_now(),
        "phase": "2_full_shadow",
        "walletsRequested": len(selected_wallet_rows),
        "walletsCompleted": len({cluster["wallet"] for cluster in scored_clusters}),
        "walletsFailed": failed_wallets,
        "walletsSkipped": skipped_wallets,
        "walletResults": sanitize_payload(wallet_results),
        "clusters": sanitize_payload(scored_clusters),
    }

    shadow_path = write_trade_copyability_shadow(shadow_payload)
    summary_path = write_wallet_copyability_summary(summary)
    state_path = write_trade_copyability_state(state) if COPYABILITY_STATE_ENABLED else None
    backtest_path = write_trade_copyability_backtest(backtest)

    print(
        "SMART_MONEY_COPYABILITY_WRITTEN "
        f"shadow={shadow_path} "
        f"summary={summary_path} "
        f"history={history_path} "
        f"state={state_path} "
        f"backtest={backtest_path} "
        f"clusters={len(scored_clusters)}"
    )
    print(
        "SMART_MONEY_COPYABILITY_COMPLETED "
        f"wallets={len(selected_wallet_rows)} "
        f"clusters={len(scored_clusters)} "
        f"high={sum(1 for cluster in scored_clusters if cluster.get('copyabilityStatus') == 'high_copyability')} "
        f"watch={sum(1 for cluster in scored_clusters if cluster.get('copyabilityStatus') == 'watch_copyability')} "
        f"not_copyable={sum(1 for cluster in scored_clusters if cluster.get('copyabilityStatus') == 'not_copyable')} "
        f"failed={failed_wallets}"
    )

    return {
        "shadow": shadow_payload,
        "summary": summary,
        "backtest": backtest,
        "state": state,
        "clusters": scored_clusters,
        "history_path": history_path,
        "shadow_path": shadow_path,
        "summary_path": summary_path,
        "backtest_path": backtest_path,
        "state_path": state_path,
        "price_history_requests": price_history_requests,
        "price_history_cache_hits": price_history_cache_hits,
    }
