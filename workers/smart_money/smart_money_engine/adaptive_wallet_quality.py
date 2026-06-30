from __future__ import annotations

import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

try:  # pragma: no cover - support package and script-style imports
    from .copyability_storage import sanitize_payload
    from .path_utils import resolve_output_dir
except ImportError:  # pragma: no cover
    from copyability_storage import sanitize_payload
    from path_utils import resolve_output_dir


OUTPUT_DIR = resolve_output_dir()
ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE = OUTPUT_DIR / "adaptive_signal_wallet_quality.json"

HIGH_VALUE_LABELS = {"ALTA_CONVICCION", "ACUMULACION"}
HIGH_COPYABILITY_LABELS = {"ALTA_CONVICCION"}
HIGH_COPYABILITY_STATUSES = {"high_copyability"}
WATCH_COPYABILITY_STATUSES = {"watch_copyability"}
ROUTINE_LABELS = {"ACTIVIDAD_RUTINARIA"}
NOT_COPYABLE_LABELS = {"COBERTURA_NO_COPIABLE"}
REDUCTION_LABELS = {"REDUCCION_DE_TESIS"}
STRATEGIC_CATEGORIES = {"politics", "geopolitics", "macro", "sports", "crypto", "technology", "culture_awards"}

_MICRO_MARKET_PATTERNS = (
    re.compile(r"bitcoin\s+up\s+or\s+down", re.IGNORECASE),
    re.compile(r"\bexact\s*score\b", re.IGNORECASE),
    re.compile(r"\bcorners?\b", re.IGNORECASE),
    re.compile(r"\bhalf\s*time\b", re.IGNORECASE),
    re.compile(r"\bhalftime\b", re.IGNORECASE),
    re.compile(r"\bplayer[\s_-]", re.IGNORECASE),
    re.compile(r"\b(?:shots|rebounds|assists|goals|saves|touchdowns|yards|passes|cards|fouls|stats?)\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}:\d{2}\s?(?:am|pm)\s*-\s*\d{1,2}:\d{2}\s?(?:am|pm)\b", re.IGNORECASE),
)


def _normalize_wallet(value: Any) -> str:
    return str(value or "").strip().lower()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except Exception:
        return default
    if math.isnan(result) or math.isinf(result):
        return default
    return result


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    if math.isnan(value) or math.isinf(value):
        return lower
    return max(lower, min(upper, value))


def _market_text(cluster: dict[str, Any]) -> str:
    return " ".join(
        str(cluster.get(field) or "").strip()
        for field in ("marketTitle", "category", "eventSlug", "conditionId", "asset", "outcome")
    ).strip()


def _is_micro_market(cluster: dict[str, Any]) -> bool:
    text = _market_text(cluster)
    if not text:
        return False
    if any(pattern.search(text) for pattern in _MICRO_MARKET_PATTERNS):
        return True
    duration = _safe_float(cluster.get("durationMinutes"))
    if 0 < duration <= 10:
        lowered = text.lower()
        if "up or down" in lowered or "prop" in lowered or "intraminute" in lowered:
            return True
    return False


def _is_high_copyability(cluster: dict[str, Any]) -> bool:
    status = str(cluster.get("copyabilityStatus") or "")
    label = str(cluster.get("copyabilityLabel") or "")
    return status in HIGH_COPYABILITY_STATUSES or label in HIGH_COPYABILITY_LABELS


def _is_watch_copyability(cluster: dict[str, Any]) -> bool:
    status = str(cluster.get("copyabilityStatus") or "")
    return status in WATCH_COPYABILITY_STATUSES


def _is_actionable(cluster: dict[str, Any]) -> bool:
    label = str(cluster.get("copyabilityLabel") or "")
    return _is_high_copyability(cluster) or _is_watch_copyability(cluster) or label in HIGH_VALUE_LABELS


def _is_routine(cluster: dict[str, Any]) -> bool:
    status = str(cluster.get("copyabilityStatus") or "")
    label = str(cluster.get("copyabilityLabel") or "")
    return status == "low_copyability" or label in ROUTINE_LABELS


def _is_not_copyable(cluster: dict[str, Any]) -> bool:
    status = str(cluster.get("copyabilityStatus") or "")
    label = str(cluster.get("copyabilityLabel") or "")
    return status == "not_copyable" or label in NOT_COPYABLE_LABELS


def _is_reduction_signal(cluster: dict[str, Any]) -> bool:
    status = str(cluster.get("copyabilityStatus") or "")
    label = str(cluster.get("copyabilityLabel") or "")
    return status == "reduction_signal" or label in REDUCTION_LABELS


def _is_strategic_market(cluster: dict[str, Any]) -> bool:
    if _is_micro_market(cluster):
        return False
    if _is_routine(cluster) or _is_not_copyable(cluster):
        return False
    category = str(cluster.get("category") or "unknown").strip().lower()
    duration = _safe_float(cluster.get("durationMinutes"))
    total_size = _safe_float(cluster.get("totalSizeUsd"))
    if category in STRATEGIC_CATEGORIES:
        return True
    if duration >= 15 and total_size >= 150:
        return True
    title = _market_text(cluster).lower()
    return any(token in title for token in ("election", "elections", "tournament", "macro", "politics", "geopolitics"))


def _choose_best_category(category_stats: dict[str, dict[str, float]]) -> str:
    if not category_stats:
        return "unknown"
    category, _stats = max(
        category_stats.items(),
        key=lambda item: (
            item[1].get("actionable", 0.0),
            item[1].get("score_sum", 0.0),
            item[1].get("count", 0.0),
        ),
    )
    return category


def _cluster_identity(cluster: dict[str, Any]) -> tuple[Any, ...]:
    return (
        _normalize_wallet(cluster.get("wallet")),
        str(cluster.get("clusterId") or cluster.get("tradeId") or ""),
        str(cluster.get("conditionId") or cluster.get("asset") or cluster.get("marketTitle") or ""),
        str(cluster.get("side") or ""),
        str(cluster.get("outcome") or ""),
        _safe_float(cluster.get("copyabilityAtDetectionScore")),
        _safe_float(cluster.get("totalSizeUsd")),
        str(cluster.get("validationStatus") or ""),
    )


def _wallet_display_name(wallet: str, roster_map: dict[str, dict[str, Any]], copyability_rows: dict[str, dict[str, Any]]) -> str:
    roster_row = roster_map.get(wallet) or {}
    if roster_row.get("displayName"):
        return str(roster_row.get("displayName"))
    copyability_row = copyability_rows.get(wallet) or {}
    if copyability_row.get("displayName"):
        return str(copyability_row.get("displayName"))
    return wallet


def _recommendation_for_row(row: dict[str, Any], *, benchmark_wallet: str) -> str:
    if row["wallet"] == benchmark_wallet:
        return "KEEP_BENCHMARK"

    score = _safe_float(row.get("actionableSignalScore"))
    actionable_rate = _safe_float(row.get("actionableClusterRate"))
    strategic_rate = _safe_float(row.get("strategicMarketRate"))
    micro_rate = _safe_float(row.get("microMarketClusterRate"))
    routine_rate = _safe_float(row.get("routineClusterRate"))
    hedge_rate = _safe_float(row.get("hedgeRate"))
    not_copyable_rate = _safe_float(row.get("notCopyableCount")) / max(1.0, _safe_float(row.get("clustersCount")))

    if score >= 75 and actionable_rate >= 0.40 and strategic_rate >= 0.30 and micro_rate <= 0.35 and routine_rate <= 0.45 and hedge_rate <= 0.35 and not_copyable_rate <= 0.30:
        return "KEEP_CANDIDATE"
    if score >= 50 and strategic_rate >= 0.15:
        return "WATCHLIST"
    return "REPLACE_CANDIDATE"


def _score_wallet_row(row: dict[str, Any], *, benchmark_wallet: str) -> dict[str, Any]:
    clusters = list(row.get("_clusters") or [])
    cluster_count = len(clusters)
    detection_scores = [_safe_float(cluster.get("copyabilityAtDetectionScore")) for cluster in clusters]
    valid_detection_scores = [score for score in detection_scores if not math.isnan(score)]
    total_size_usd = sum(max(0.0, _safe_float(cluster.get("totalSizeUsd"))) for cluster in clusters)

    high_copyability_count = 0
    watch_copyability_count = 0
    accumulation_count = 0
    reduction_signal_count = 0
    routine_activity_count = 0
    not_copyable_count = 0
    hedge_count = 0
    actionable_cluster_count = 0
    micro_market_cluster_count = 0
    strategic_market_cluster_count = 0
    unknown_category_count = 0

    category_stats: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0.0, "score_sum": 0.0, "actionable": 0.0})
    seen_cluster_identities: set[tuple[Any, ...]] = set()

    for cluster in clusters:
        identity = _cluster_identity(cluster)
        if identity in seen_cluster_identities:
            continue
        seen_cluster_identities.add(identity)

        category = str(cluster.get("category") or "unknown").strip().lower() or "unknown"
        category_stats[category]["count"] += 1.0
        category_stats[category]["score_sum"] += _safe_float(cluster.get("copyabilityAtDetectionScore"))

        is_micro = _is_micro_market(cluster)
        is_actionable = _is_actionable(cluster)
        is_high = _is_high_copyability(cluster)
        is_routine = _is_routine(cluster)
        is_not_copyable = _is_not_copyable(cluster)
        is_reduction = _is_reduction_signal(cluster)
        hedge_probability = _safe_float(cluster.get("hedgeProbability"))
        is_hedge = hedge_probability >= 70 or is_not_copyable
        is_strategic = _is_strategic_market(cluster)

        if category == "unknown":
            unknown_category_count += 1
        if is_micro:
            micro_market_cluster_count += 1
        if is_strategic:
            strategic_market_cluster_count += 1
        if is_high:
            high_copyability_count += 1
        if _is_watch_copyability(cluster):
            watch_copyability_count += 1
        if str(cluster.get("copyabilityLabel") or "") == "ACUMULACION":
            accumulation_count += 1
        if is_reduction:
            reduction_signal_count += 1
        if is_routine:
            routine_activity_count += 1
        if is_not_copyable:
            not_copyable_count += 1
        if is_hedge:
            hedge_count += 1
        if is_actionable:
            actionable_cluster_count += 1
            category_stats[category]["actionable"] += 1.0

    best_category = _choose_best_category(category_stats) if clusters else "unknown"
    actionable_rate = actionable_cluster_count / cluster_count if cluster_count else 0.0
    routine_rate = routine_activity_count / cluster_count if cluster_count else 0.0
    micro_rate = micro_market_cluster_count / cluster_count if cluster_count else 0.0
    strategic_rate = strategic_market_cluster_count / cluster_count if cluster_count else 0.0
    hedge_rate = hedge_count / cluster_count if cluster_count else 0.0
    not_copyable_rate = not_copyable_count / cluster_count if cluster_count else 0.0
    unknown_rate = unknown_category_count / cluster_count if cluster_count else 0.0

    average_detection = round(mean(valid_detection_scores), 2) if valid_detection_scores else None
    median_detection = round(median(valid_detection_scores), 2) if valid_detection_scores else None

    actionable_signal_score = 0.0
    if cluster_count:
        actionable_signal_score = (
            actionable_rate * 55.0
            + (_safe_float(average_detection) * 0.24 if average_detection is not None else 0.0)
            + strategic_rate * 18.0
            + min(12.0, high_copyability_count * 2.5)
            + min(8.0, accumulation_count * 2.5)
            + min(4.0, watch_copyability_count * 1.0)
        )

        micro_penalty = (micro_rate * 34.0) + (micro_market_cluster_count * 0.5)
        routine_penalty = (routine_rate * 30.0) + max(0.0, routine_activity_count - actionable_cluster_count) * 1.2
        hedge_penalty = (hedge_rate * 24.0) + (not_copyable_count * 1.5)
        unknown_penalty = (unknown_rate * 18.0) + (8.0 if best_category == "unknown" else 0.0)
        actionable_signal_score -= micro_penalty + routine_penalty + hedge_penalty + unknown_penalty
    else:
        micro_penalty = 0.0
        routine_penalty = 0.0
        hedge_penalty = 0.0
        unknown_penalty = 0.0

    actionable_signal_score = round(_clamp(actionable_signal_score), 2)
    micro_penalty = round(micro_penalty, 2)
    routine_penalty = round(routine_penalty, 2)
    hedge_penalty = round(hedge_penalty, 2)
    unknown_penalty = round(unknown_penalty, 2)

    row = {
        "wallet": row["wallet"],
        "displayName": row["displayName"],
        "clustersCount": cluster_count,
        "highCopyabilityCount": high_copyability_count,
        "watchCopyabilityCount": watch_copyability_count,
        "accumulationCount": accumulation_count,
        "reductionSignalCount": reduction_signal_count,
        "routineActivityCount": routine_activity_count,
        "notCopyableCount": not_copyable_count,
        "hedgeRate": round(hedge_rate, 4),
        "averageCopyabilityAtDetectionScore": average_detection,
        "medianCopyabilityAtDetectionScore": median_detection,
        "bestCategory": best_category,
        "actionableClusterCount": actionable_cluster_count,
        "actionableClusterRate": round(actionable_rate, 4),
        "routineClusterRate": round(routine_rate, 4),
        "microMarketClusterCount": micro_market_cluster_count,
        "microMarketClusterRate": round(micro_rate, 4),
        "strategicMarketClusterCount": strategic_market_cluster_count,
        "strategicMarketRate": round(strategic_rate, 4),
        "microMarketPenalty": micro_penalty,
        "routinePenalty": routine_penalty,
        "hedgePenalty": hedge_penalty,
        "unknownCategoryPenalty": unknown_penalty,
        "actionableSignalScore": actionable_signal_score,
        "keepInRosterRecommendation": _recommendation_for_row(
            {
                "wallet": row["wallet"],
                "actionableSignalScore": actionable_signal_score,
                "actionableClusterRate": actionable_rate,
                "strategicMarketRate": strategic_rate,
                "microMarketClusterRate": micro_rate,
                "routineClusterRate": routine_rate,
                "hedgeRate": hedge_rate,
                "notCopyableCount": not_copyable_count,
                "clustersCount": cluster_count,
            },
            benchmark_wallet=benchmark_wallet,
        ),
        "totalRecentUsdc": round(total_size_usd, 2),
        "copyabilityRows": cluster_count,
    }
    return row


def build_adaptive_signal_wallet_quality(
    *,
    copyability_phase: dict[str, Any],
    wallet_roster: dict[str, Any] | list[dict[str, Any]] | None = None,
    benchmark_wallet: str,
    output_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    del output_dir

    clusters = list((copyability_phase or {}).get("clusters") or [])
    copyability_rows = {}
    for item in list((copyability_phase or {}).get("walletResults") or []):
        wallet = _normalize_wallet(item.get("wallet"))
        if wallet and wallet not in copyability_rows:
            copyability_rows[wallet] = item

    roster_rows: list[dict[str, Any]]
    if isinstance(wallet_roster, dict):
        roster_rows = list(wallet_roster.get("selectedWallets") or [])
    elif isinstance(wallet_roster, list):
        roster_rows = list(wallet_roster)
    else:
        roster_rows = []

    roster_map: dict[str, dict[str, Any]] = {}
    for row in roster_rows:
        wallet = _normalize_wallet(row.get("wallet"))
        if wallet and wallet not in roster_map:
            roster_map[wallet] = row

    wallet_order: list[str] = []
    for row in roster_rows:
        wallet = _normalize_wallet(row.get("wallet"))
        if wallet and wallet not in wallet_order:
            wallet_order.append(wallet)
    for cluster in clusters:
        wallet = _normalize_wallet(cluster.get("wallet"))
        if wallet and wallet not in wallet_order:
            wallet_order.append(wallet)
    for wallet in copyability_rows.keys():
        if wallet not in wallet_order:
            wallet_order.append(wallet)

    clusters_by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for cluster in clusters:
        wallet = _normalize_wallet(cluster.get("wallet"))
        if wallet:
            clusters_by_wallet[wallet].append(cluster)

    rows: list[dict[str, Any]] = []
    for wallet in wallet_order:
        wallet_clusters = clusters_by_wallet.get(wallet) or []
        roster_row = roster_map.get(wallet) or {}
        quality_row = {
            "wallet": wallet,
            "displayName": _wallet_display_name(wallet, roster_map, copyability_rows),
            "_clusters": wallet_clusters,
        }
        if roster_row.get("isBenchmark"):
            benchmark_wallet = wallet
        row = _score_wallet_row(quality_row, benchmark_wallet=_normalize_wallet(benchmark_wallet))
        row["displayName"] = quality_row["displayName"]
        rows.append(row)

    rows.sort(
        key=lambda item: (
            0 if item["wallet"] == _normalize_wallet(benchmark_wallet) else 1,
            -_safe_float(item.get("actionableSignalScore")),
            -_safe_float(item.get("strategicMarketRate")) * 100.0,
            -_safe_float(item.get("actionableClusterRate")) * 100.0,
            _normalize_wallet(item.get("wallet")),
        )
    )

    for index, row in enumerate(rows, start=1):
        if row["wallet"] == _normalize_wallet(benchmark_wallet):
            row["keepInRosterRecommendation"] = "KEEP_BENCHMARK"
        row["rank"] = index
        print(
            "SMART_MONEY_WALLET_QUALITY_SUMMARY "
            f"wallet={row['wallet']} "
            f"actionableScore={row['actionableSignalScore']} "
            f"actionableRate={row['actionableClusterRate']} "
            f"microRate={row['microMarketClusterRate']} "
            f"routineRate={row['routineClusterRate']} "
            f"recommendation={row['keepInRosterRecommendation']}"
        )

    payload = {
        "runId": (copyability_phase or {}).get("runId"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "benchmarkWallet": _normalize_wallet(benchmark_wallet),
        "walletCount": len(rows),
        "wallets": sanitize_payload(rows),
        "walletQualityRows": sanitize_payload(rows),
        "walletResults": sanitize_payload(rows),
    }
    return payload


def write_adaptive_signal_wallet_quality(payload: dict[str, Any]) -> Path:
    ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE.with_suffix(ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE.suffix + ".tmp")
    payload = dict(payload)
    canonical_rows = payload.get("wallets") or payload.get("walletQualityRows") or payload.get("walletResults") or []
    payload["wallets"] = canonical_rows
    payload["walletQualityRows"] = payload.get("walletQualityRows") or canonical_rows
    payload["walletResults"] = payload.get("walletResults") or canonical_rows
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_payload(payload), handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE)
    print(f"SMART_MONEY_WALLET_QUALITY_WRITTEN path={ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE}")
    print(
        "SMART_MONEY_WALLET_QUALITY_COMPLETED "
        f"rows={len(payload.get('walletQualityRows') or payload.get('walletResults') or [])}"
    )
    return ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE
