from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:  # pragma: no cover - support package and script-style imports
    from .copyability_storage import sanitize_payload
    from .path_utils import resolve_output_dir
    from .trade_copyability import (
        COPYABILITY_LOOKBACK_HOURS,
        COPYABILITY_MAX_TRADES_PER_WALLET,
        build_trade_clusters,
        fetch_copyability_trades_for_wallet,
    )
except ImportError:  # pragma: no cover
    from copyability_storage import sanitize_payload
    from path_utils import resolve_output_dir
    from trade_copyability import (
        COPYABILITY_LOOKBACK_HOURS,
        COPYABILITY_MAX_TRADES_PER_WALLET,
        build_trade_clusters,
        fetch_copyability_trades_for_wallet,
    )


OUTPUT_DIR = resolve_output_dir()
ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE = OUTPUT_DIR / "adaptive_signal_candidate_pool.json"

SIGNAL_WALLET_DISCOVERY_V2_ENABLED = os.getenv("SIGNAL_WALLET_DISCOVERY_V2_ENABLED", "true").lower() == "true"
SIGNAL_WALLET_DISCOVERY_V2_MAX_CANDIDATES = int(os.getenv("SIGNAL_WALLET_DISCOVERY_V2_MAX_CANDIDATES", "200"))
SIGNAL_WALLET_DISCOVERY_V2_PREFLIGHT_TOP_N = int(os.getenv("SIGNAL_WALLET_DISCOVERY_V2_PREFLIGHT_TOP_N", "50"))
SIGNAL_WALLET_DISCOVERY_V2_MIN_RAW_TRADES = int(os.getenv("SIGNAL_WALLET_DISCOVERY_V2_MIN_RAW_TRADES", "20"))
SIGNAL_WALLET_DISCOVERY_V2_MIN_NORMALIZED_TRADES = int(os.getenv("SIGNAL_WALLET_DISCOVERY_V2_MIN_NORMALIZED_TRADES", "15"))
SIGNAL_WALLET_DISCOVERY_V2_MIN_UNIQUE_MARKETS = int(os.getenv("SIGNAL_WALLET_DISCOVERY_V2_MIN_UNIQUE_MARKETS", "2"))
SIGNAL_WALLET_DISCOVERY_V2_EXCLUDE_MICRO_MARKETS = os.getenv("SIGNAL_WALLET_DISCOVERY_V2_EXCLUDE_MICRO_MARKETS", "true").lower() == "true"

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

_STRATEGIC_CATEGORIES = {
    "geopolitics",
    "politics",
    "macro",
    "economy",
    "business",
    "regulation",
    "technology",
    "ai",
    "crypto",
}


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


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def _title_text(*parts: Any) -> str:
    return " ".join(str(part or "").strip() for part in parts).strip()


def _is_micro_market(title: str) -> bool:
    lowered = title.lower()
    if not lowered:
        return False
    if any(pattern.search(lowered) for pattern in _MICRO_MARKET_PATTERNS):
        return True
    return any(token in lowered for token in ("props", "prop", "player ", "player-", "player_", "intraminute", "intrahour"))


def _is_strategic_category(category: str) -> bool:
    return str(category or "").strip().lower() in _STRATEGIC_CATEGORIES


def _guess_source_wallet(row: dict[str, Any]) -> str:
    for key in ("wallet", "candidateWallet", "walletAddress", "address", "proxyWallet", "user"):
        wallet = _normalize_wallet(row.get(key))
        if wallet:
            return wallet
    return ""


def _load_optional_rows(base: Path, filename: str) -> list[dict[str, Any]]:
    payload = _load_json(base / filename, [])
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        rows = payload.get("candidates") or payload.get("wallets") or payload.get("walletResults") or []
        if isinstance(rows, list):
            return [row for row in rows if isinstance(row, dict)]
    return []


def _load_sources(output_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    base = Path(output_dir) if output_dir else OUTPUT_DIR
    return {
        "wallet_shadow_rankings": _load_optional_rows(base, "wallet_shadow_rankings.json"),
        "wallet_category_rankings": _load_json(base / "wallet_category_rankings.json", {}),
        "wallet_comparison_summary": _load_json(base / "wallet_comparison_summary.json", {}),
        "wallet_shadow_history": _load_jsonl(base / "wallet_shadow_history.jsonl"),
        "trade_copyability_shadow": _load_json(base / "trade_copyability_shadow.json", {}),
        "wallet_copyability_summary": _load_json(base / "wallet_copyability_summary.json", {}),
        "wallet_quality": _load_optional_rows(base, "adaptive_signal_wallet_quality.json"),
        "wallet_roster": _load_json(base / "adaptive_signal_wallet_roster.json", {}),
        "whale_global_candidates": _load_optional_rows(base, "global_candidates.json"),
        "whale_replacements": _load_optional_rows(base, "replacement_recommendations.json"),
        "whale_active_wallet_health": _load_optional_rows(base, "active_wallet_health.json"),
    }


def _ensure_candidate(candidates: dict[str, dict[str, Any]], wallet: str) -> dict[str, Any]:
    wallet = _normalize_wallet(wallet)
    candidate = candidates.get(wallet)
    if candidate is None:
        candidate = {
            "wallet": wallet,
            "discoverySources": set(),
            "sourceCount": 0,
            "seenInPreviousRoster": False,
            "previousQualityRecommendation": None,
            "previousActionableSignalScore": None,
            "previousRoutineClusterRate": None,
            "previousMicroMarketClusterRate": None,
            "previousHedgeRate": None,
            "previousBestCategory": None,
            "robustSkillScore": 0.0,
            "categorySkillScore": 0.0,
            "walletCategorySkillScore": 0.0,
            "categorySkillStatus": None,
            "recentRawTrades": 0,
            "recentNormalizedTrades": 0,
            "uniqueMarketsCount": 0,
            "totalRecentUsdc": 0.0,
            "clusterViabilityScore": 0.0,
            "strategicMarketExposureScore": 0.0,
            "microMarketExposureScore": 0.0,
            "routineRiskScore": 0.0,
            "copyabilityPotentialScore": 0.0,
            "candidateQualityScore": 0.0,
            "candidateRecommendation": "REJECT",
            "candidateReasons": [],
            "candidateRisks": [],
            "_uniqueMarkets": set(),
            "baseScore": 0.0,
            "preflightStatus": "unknown",
            "preflightReason": None,
            "preflightSource": None,
            "preflightAnalyzed": False,
        }
        candidates[wallet] = candidate
    return candidate


def _merge_non_empty(candidate: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "" or value == [] or value == {}:
        return
    current_value = candidate.get(key)
    if current_value is None or current_value == "" or current_value == [] or current_value == {}:
        candidate[key] = value


def _merge_source(candidate: dict[str, Any], source_name: str) -> None:
    candidate["discoverySources"].add(source_name)


def _merge_wallet_score(candidate: dict[str, Any], score: dict[str, Any], source_name: str = "wallet_scores") -> None:
    _merge_source(candidate, source_name)
    _merge_non_empty(candidate, "robustSkillScore", score.get("robustSkillScore") or score.get("walletQualityScore") or score.get("behaviorQualityScore"))
    _merge_non_empty(candidate, "categorySkillScore", score.get("categorySkillScore") or score.get("walletCategorySkillScore"))
    _merge_non_empty(candidate, "walletCategorySkillScore", score.get("walletCategorySkillScore") or score.get("categorySkillScore"))
    _merge_non_empty(candidate, "categorySkillStatus", score.get("categorySkillStatus"))
    _merge_non_empty(candidate, "previousBestCategory", score.get("dominantKnownCategory") or score.get("primaryCategory"))
    candidate["seenInPreviousRoster"] = bool(candidate.get("seenInPreviousRoster") or score.get("seenInPreviousRoster"))


def _merge_quality_row(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    _merge_source(candidate, "adaptive_signal_wallet_quality")
    _merge_non_empty(candidate, "previousQualityRecommendation", row.get("keepInRosterRecommendation"))
    _merge_non_empty(candidate, "previousActionableSignalScore", row.get("actionableSignalScore"))
    _merge_non_empty(candidate, "previousRoutineClusterRate", row.get("routineClusterRate"))
    _merge_non_empty(candidate, "previousMicroMarketClusterRate", row.get("microMarketClusterRate"))
    candidate["candidateRisks"].append("previous_quality_recommendation")


def _merge_roster_row(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    _merge_source(candidate, "adaptive_signal_wallet_roster")
    candidate["seenInPreviousRoster"] = True
    _merge_non_empty(candidate, "previousQualityRecommendation", row.get("previousQualityRecommendation"))
    _merge_non_empty(candidate, "previousActionableSignalScore", row.get("previousActionableSignalScore"))
    _merge_non_empty(candidate, "previousRoutineClusterRate", row.get("previousRoutineClusterRate"))
    _merge_non_empty(candidate, "previousMicroMarketClusterRate", row.get("previousMicroMarketClusterRate"))
    _merge_non_empty(candidate, "previousHedgeRate", row.get("previousHedgeRate"))
    _merge_non_empty(candidate, "previousBestCategory", row.get("primaryCategory"))


def _merge_category_row(candidate: dict[str, Any], row: dict[str, Any], category: str) -> None:
    _merge_source(candidate, "wallet_category_rankings")
    _merge_non_empty(candidate, "categorySkillStatus", row.get("categorySkillStatus"))
    _merge_non_empty(candidate, "categorySkillScore", row.get("categorySkillScore"))
    _merge_non_empty(candidate, "walletCategorySkillScore", row.get("categorySkillScore"))
    _merge_non_empty(candidate, "previousBestCategory", category)


def _merge_summary_row(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    _merge_source(candidate, "wallet_copyability_summary")
    candidate["copyabilityPotentialScore"] = max(candidate.get("copyabilityPotentialScore") or 0.0, _safe_float(row.get("actionableClusterCount")) * 3.0)
    candidate["recentRawTrades"] = max(candidate.get("recentRawTrades") or 0, int(row.get("clustersCount") or 0))
    candidate["candidateRisks"].append("copyability_summary_present")


def _merge_trade_cluster(candidate: dict[str, Any], cluster: dict[str, Any]) -> None:
    _merge_source(candidate, "trade_copyability_shadow")
    candidate["recentRawTrades"] += 1
    candidate["recentNormalizedTrades"] += 1
    market_key = _title_text(cluster.get("marketTitle"), cluster.get("eventSlug"), cluster.get("conditionId"), cluster.get("asset")).lower()
    if market_key:
        unique_markets = set(candidate.get("_uniqueMarkets") or set())
        unique_markets.add(market_key)
        candidate["_uniqueMarkets"] = unique_markets
        candidate["uniqueMarketsCount"] = len(unique_markets)
    candidate["totalRecentUsdc"] += max(0.0, _safe_float(cluster.get("totalSizeUsd")))
    label = str(cluster.get("copyabilityLabel") or "")
    status = str(cluster.get("copyabilityStatus") or "")
    hedge_probability = _safe_float((cluster.get("hedge") or {}).get("hedgeProbability"))
    if label == "ACUMULACION":
        candidate["candidateReasons"].append("accumulation_signal")
        candidate["copyabilityPotentialScore"] += 10
    if status in {"high_copyability", "watch_copyability"} or label in {"ALTA_CONVICCION"}:
        candidate["copyabilityPotentialScore"] += 8
    if status == "not_copyable" or label == "COBERTURA_NO_COPIABLE":
        candidate["candidateRisks"].append("not_copyable_cluster")
        candidate["routineRiskScore"] += 4
    if hedge_probability >= 70:
        candidate["candidateRisks"].append("high_hedge_rate")
        candidate["routineRiskScore"] += 2
    if _is_micro_market(_title_text(cluster.get("marketTitle"), cluster.get("category"), cluster.get("eventSlug"), cluster.get("outcome"))):
        candidate["microMarketExposureScore"] += 10
        candidate["candidateRisks"].append("micro_market")
    if _is_strategic_category(str(cluster.get("category") or "")) and not _is_micro_market(_title_text(cluster.get("marketTitle"), cluster.get("eventSlug"))):
        candidate["strategicMarketExposureScore"] += 8


def _merge_shadow_history(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    _merge_source(candidate, "wallet_shadow_history")
    _merge_non_empty(candidate, "robustSkillScore", row.get("robustSkillScore") or row.get("behaviorQualityScore"))
    _merge_non_empty(candidate, "previousBestCategory", row.get("shadowSkill", {}).get("dominantKnownCategory"))


def _merge_optional_wallet(candidate: dict[str, Any], row: dict[str, Any], source_name: str) -> None:
    wallet = _guess_source_wallet(row)
    if not wallet:
        return
    _merge_source(candidate, source_name)
    _merge_non_empty(candidate, "previousBestCategory", row.get("primaryCategory") or row.get("category") or row.get("bestCategory"))
    _merge_non_empty(candidate, "robustSkillScore", row.get("robustSkillScore") or row.get("walletQualityScore"))
    _merge_non_empty(candidate, "categorySkillScore", row.get("categorySkillScore"))
    _merge_non_empty(candidate, "previousQualityRecommendation", row.get("candidateRecommendation") or row.get("keepInRosterRecommendation"))


def _strategic_seed_markets(trade_copyability_shadow: dict[str, Any], copyability_seed_trades: list[dict[str, Any]] | None) -> set[str]:
    markets: set[str] = set()
    clusters = list((trade_copyability_shadow or {}).get("clusters") or [])
    for cluster in clusters:
        title = _title_text(cluster.get("marketTitle"), cluster.get("eventSlug"), cluster.get("conditionId"))
        if not title:
            continue
        category = str(cluster.get("category") or "").lower()
        label = str(cluster.get("copyabilityLabel") or "")
        status = str(cluster.get("copyabilityStatus") or "")
        total_size = _safe_float(cluster.get("totalSizeUsd"))
        if (_is_strategic_category(category) or label in {"ALTA_CONVICCION", "ACUMULACION"} or status in {"high_copyability", "watch_copyability"}) and total_size >= 150 and not _is_micro_market(title):
            markets.add(title.lower())
    for trade in copyability_seed_trades or []:
        title = _title_text(trade.get("marketTitle"), trade.get("eventSlug"), trade.get("conditionId"))
        if title and not _is_micro_market(title):
            markets.add(title.lower())
    return markets


def _score_candidate(candidate: dict[str, Any], strategic_seeds: set[str]) -> None:
    robust = _clamp(_safe_float(candidate.get("robustSkillScore")))
    category = _clamp(_safe_float(candidate.get("categorySkillScore") or candidate.get("walletCategorySkillScore")))
    raw_trades = int(candidate.get("recentRawTrades") or 0)
    normalized_trades = int(candidate.get("recentNormalizedTrades") or 0)
    unique_markets = int(candidate.get("uniqueMarketsCount") or 0)
    total_usdc = _safe_float(candidate.get("totalRecentUsdc"))
    cluster_viability = _safe_float(candidate.get("clusterViabilityScore"))
    strategic_exposure = _safe_float(candidate.get("strategicMarketExposureScore"))
    micro_exposure = _safe_float(candidate.get("microMarketExposureScore"))
    routine_risk = _safe_float(candidate.get("routineRiskScore"))
    copyability_potential = _safe_float(candidate.get("copyabilityPotentialScore"))
    previous_quality = str(candidate.get("previousQualityRecommendation") or "")
    previous_actionable = _safe_float(candidate.get("previousActionableSignalScore"), default=0.0)
    previous_routine = _safe_float(candidate.get("previousRoutineClusterRate"), default=0.0)
    previous_micro = _safe_float(candidate.get("previousMicroMarketClusterRate"), default=0.0)
    previous_hedge = _safe_float(candidate.get("previousHedgeRate"), default=0.0)
    seen_previous = bool(candidate.get("seenInPreviousRoster"))
    valid_strategy_match = 0.0
    if strategic_seeds:
        previous_best_category = str(candidate.get("previousBestCategory") or "").lower()
        if previous_best_category in _STRATEGIC_CATEGORIES:
            valid_strategy_match = 8.0

    candidate_reasons: list[str] = []
    candidate_risks: list[str] = list(dict.fromkeys(candidate.get("candidateRisks") or []))
    if raw_trades >= SIGNAL_WALLET_DISCOVERY_V2_MIN_RAW_TRADES:
        candidate_reasons.append("sufficient_recent_activity")
    if normalized_trades >= SIGNAL_WALLET_DISCOVERY_V2_MIN_NORMALIZED_TRADES:
        candidate_reasons.append("sufficient_normalized_activity")
    if unique_markets >= SIGNAL_WALLET_DISCOVERY_V2_MIN_UNIQUE_MARKETS:
        candidate_reasons.append("multi_market_activity")
    if strategic_exposure > 0 or valid_strategy_match > 0:
        candidate_reasons.append("strategic_market_exposure")
    if copyability_potential >= 10:
        candidate_reasons.append("copyability_signal_present")

    if previous_quality == "REPLACE_CANDIDATE":
        candidate_risks.append("previous_replace_candidate")
    if previous_actionable <= 0:
        candidate_risks.append("no_prior_actionable_signal")
    if previous_routine >= 0.45:
        candidate_risks.append("high_routine_rate")
    if previous_micro >= 0.25:
        candidate_risks.append("high_micro_market_rate")
    if previous_hedge >= 0.5:
        candidate_risks.append("high_hedge_rate")
    if raw_trades < SIGNAL_WALLET_DISCOVERY_V2_MIN_RAW_TRADES:
        candidate_risks.append("insufficient_live_trades")
    if normalized_trades < SIGNAL_WALLET_DISCOVERY_V2_MIN_NORMALIZED_TRADES:
        candidate_risks.append("insufficient_normalized_trades")
    if unique_markets < SIGNAL_WALLET_DISCOVERY_V2_MIN_UNIQUE_MARKETS:
        candidate_risks.append("low_unique_markets")
    if cluster_viability <= 0:
        candidate_risks.append("low_cluster_viability")
    if not candidate.get("categorySkillStatus"):
        candidate_risks.append("missing_category_status")

    strategic_bonus = (
        min(strategic_exposure, 30.0) * 0.6
        + valid_strategy_match
        + (8.0 if _is_strategic_category(str(candidate.get("previousBestCategory") or "")) else 0.0)
    )
    activity_bonus = (
        min(raw_trades, 40) * 0.9
        + min(normalized_trades, 40) * 0.7
        + min(unique_markets, 12) * 4.5
        + min(total_usdc / 1000.0, 30.0)
        + min(cluster_viability, 100.0) * 0.4
        + min(copyability_potential, 40.0) * 0.6
    )
    quality_bonus = (
        robust * 0.18
        + category * 0.14
        + (10.0 if candidate.get("candidateRecommendation") == "STRONG_CANDIDATE" else 0.0)
    )
    strategic_floor_bonus = 0.0
    strategic_category = str(candidate.get("previousBestCategory") or candidate.get("dominantKnownCategory") or "").lower()
    if (
        _is_strategic_category(strategic_category)
        and previous_quality != "REPLACE_CANDIDATE"
        and (
            previous_actionable >= 50.0
            or category >= 55.0
            or robust >= 55.0
            or copyability_potential >= 20.0
        )
    ):
        strategic_floor_bonus = 22.0
    routine_penalty = _clamp(routine_risk * 0.75 + previous_routine * 22.0)
    micro_penalty = _clamp(micro_exposure * 0.5 + previous_micro * 18.0)
    hedge_penalty = _clamp(previous_hedge * 20.0)
    replace_penalty = 18.0 if previous_quality == "REPLACE_CANDIDATE" else 0.0
    missing_penalty = 18.0 if raw_trades <= 0 and normalized_trades <= 0 and not candidate.get("categorySkillStatus") else 0.0
    weak_penalty = 12.0 if robust < 35 and category < 35 else 0.0

    base_score = quality_bonus + activity_bonus + strategic_bonus + strategic_floor_bonus
    final_score = _clamp(base_score - routine_penalty - micro_penalty - hedge_penalty - replace_penalty - missing_penalty - weak_penalty)
    if seen_previous:
        final_score = _clamp(final_score - 2.0)

    if final_score >= 75:
        recommendation = "STRONG_CANDIDATE"
    elif final_score >= 60:
        recommendation = "CANDIDATE"
    elif final_score >= 45:
        recommendation = "WATCHLIST_CANDIDATE"
    elif final_score >= 25:
        recommendation = "WEAK_CANDIDATE"
    else:
        recommendation = "REJECT"

    if SIGNAL_WALLET_DISCOVERY_V2_EXCLUDE_MICRO_MARKETS and micro_exposure >= 15 and recommendation != "REJECT":
        recommendation = "WEAK_CANDIDATE" if final_score >= 20 else "REJECT"
    if raw_trades < SIGNAL_WALLET_DISCOVERY_V2_MIN_RAW_TRADES or normalized_trades < SIGNAL_WALLET_DISCOVERY_V2_MIN_NORMALIZED_TRADES or unique_markets < SIGNAL_WALLET_DISCOVERY_V2_MIN_UNIQUE_MARKETS or cluster_viability <= 0:
        if final_score < 50:
            recommendation = "REJECT"

    candidate["candidateReasons"] = list(dict.fromkeys(candidate_reasons))
    candidate["candidateRisks"] = list(dict.fromkeys(candidate_risks))
    candidate["baseScore"] = round(base_score, 2)
    candidate["candidateQualityScore"] = round(final_score, 2)
    candidate["candidateRecommendation"] = recommendation
    candidate["sourceCount"] = len(candidate.get("discoverySources") or [])
    print(
        "SMART_MONEY_DISCOVERY_V2_CANDIDATE_SCORED "
        f"wallet={candidate['wallet']} "
        f"score={candidate['candidateQualityScore']} "
        f"recommendation={candidate['candidateRecommendation']}"
    )


def build_adaptive_signal_candidate_pool(
    *,
    wallet_scores: list[dict[str, Any]] | None = None,
    shadow_rows: list[dict[str, Any]] | None = None,
    copyability_seed_trades: list[dict[str, Any]] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    print("SMART_MONEY_DISCOVERY_V2_STARTED")
    if not SIGNAL_WALLET_DISCOVERY_V2_ENABLED:
        payload = {
            "generatedAt": datetime.now(timezone.utc).isoformat(),
            "sourceStatus": "disabled",
            "candidateCount": 0,
            "strongCandidateCount": 0,
            "watchlistCandidateCount": 0,
            "weakCandidateCount": 0,
            "rejectedCandidateCount": 0,
            "candidates": [],
            "rejectedCandidates": [],
            "reasonSummary": {},
        }
        return payload

    base = Path(output_dir) if output_dir else OUTPUT_DIR
    sources = _load_sources(base)
    source_loaded_counts = {
        "wallet_shadow_rankings": len(sources["wallet_shadow_rankings"] or []),
        "wallet_category_rankings": sum(len(rows or []) for rows in (sources["wallet_category_rankings"] or {}).values()) if isinstance(sources["wallet_category_rankings"], dict) else 0,
        "wallet_comparison_summary": len((sources["wallet_comparison_summary"] or {}).get("comparisons") or []) if isinstance(sources["wallet_comparison_summary"], dict) else 0,
        "wallet_shadow_history": len(sources["wallet_shadow_history"] or []),
        "trade_copyability_shadow": len((sources["trade_copyability_shadow"] or {}).get("clusters") or []) if isinstance(sources["trade_copyability_shadow"], dict) else 0,
        "wallet_copyability_summary": len(sources["wallet_copyability_summary"] or {}),
        "wallet_quality": len(sources["wallet_quality"] or []),
        "wallet_roster": len((sources["wallet_roster"] or {}).get("selectedWallets") or []) if isinstance(sources["wallet_roster"], dict) else 0,
        "whale_global_candidates": len(sources["whale_global_candidates"] or []),
        "whale_replacements": len(sources["whale_replacements"] or []),
        "whale_active_wallet_health": len(sources["whale_active_wallet_health"] or []),
    }
    for source_name, count in source_loaded_counts.items():
        print(f"SMART_MONEY_DISCOVERY_V2_SOURCE_LOADED source={source_name} count={count}")

    candidates: dict[str, dict[str, Any]] = {}
    strategic_seeds = _strategic_seed_markets(sources["trade_copyability_shadow"] or {}, copyability_seed_trades)

    def include(wallet: Any) -> dict[str, Any] | None:
        wallet = _normalize_wallet(wallet)
        if not wallet:
            return None
        return _ensure_candidate(candidates, wallet)

    for score in wallet_scores or []:
        wallet = _normalize_wallet(score.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_wallet_score(candidate, score, "engine_wallet_scores")

    for row in shadow_rows or []:
        wallet = _normalize_wallet(row.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_source(candidate, "engine_shadow_rows")
        _merge_non_empty(candidate, "previousBestCategory", row.get("primaryCategory") or row.get("dominantKnownCategory"))

    for row in sources["wallet_shadow_rankings"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_wallet_score(candidate, row, "wallet_shadow_rankings")

    category_rankings = sources["wallet_category_rankings"] or {}
    if isinstance(category_rankings, dict):
        for category, rows in category_rankings.items():
            for row in rows or []:
                wallet = _normalize_wallet(row.get("wallet"))
                if not wallet:
                    continue
                candidate = include(wallet)
                if candidate is None:
                    continue
                _merge_category_row(candidate, row, category)

    comparison_summary = sources["wallet_comparison_summary"] or {}
    if isinstance(comparison_summary, dict):
        for comparison in comparison_summary.get("comparisons") or []:
            wallet = _normalize_wallet(comparison.get("candidateWallet"))
            candidate = include(wallet)
            if candidate is None:
                continue
            _merge_source(candidate, "wallet_comparison_summary")
            if comparison.get("comparisonStatus") == "candidate_leads":
                candidate["copyabilityPotentialScore"] += 4.0

    for row in sources["wallet_shadow_history"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_shadow_history(candidate, row)

    trade_copyability_shadow = sources["trade_copyability_shadow"] or {}
    if isinstance(trade_copyability_shadow, dict):
        for wallet_result in trade_copyability_shadow.get("walletResults") or []:
            wallet = _normalize_wallet(wallet_result.get("wallet"))
            candidate = include(wallet)
            if candidate is None:
                continue
            _merge_source(candidate, "trade_copyability_shadow")
            candidate["recentRawTrades"] = max(candidate["recentRawTrades"], int(wallet_result.get("rawTrades") or 0))
            candidate["recentNormalizedTrades"] = max(candidate["recentNormalizedTrades"], int(wallet_result.get("normalizedTrades") or 0))
            candidate["copyabilityPotentialScore"] += _safe_float(wallet_result.get("highCopyabilityCount")) * 2.0
            candidate["copyabilityPotentialScore"] += _safe_float(wallet_result.get("watchCopyabilityCount")) * 1.2
            candidate["routineRiskScore"] += _safe_float(wallet_result.get("notCopyableCount")) * 0.8
            candidate["previousHedgeRate"] = max(_safe_float(candidate.get("previousHedgeRate")), _safe_float(wallet_result.get("hedgeRate")))
        for cluster in trade_copyability_shadow.get("clusters") or []:
            wallet = _normalize_wallet(cluster.get("wallet"))
            candidate = include(wallet)
            if candidate is None:
                continue
            _merge_trade_cluster(candidate, cluster)

    wallet_copyability_summary = sources["wallet_copyability_summary"] or {}
    if isinstance(wallet_copyability_summary, dict):
        for wallet, row in wallet_copyability_summary.items():
            candidate = include(wallet)
            if candidate is None:
                continue
            _merge_summary_row(candidate, row)

    for row in sources["wallet_quality"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_quality_row(candidate, row)

    roster_payload = sources["wallet_roster"] if isinstance(sources["wallet_roster"], dict) else {}
    for row in list((roster_payload or {}).get("selectedWallets") or []) + list((roster_payload or {}).get("explorationWallets") or []) + list((roster_payload or {}).get("rejectedWallets") or []):
        wallet = _normalize_wallet(row.get("wallet"))
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_roster_row(candidate, row)

    for row in sources["whale_global_candidates"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_optional_wallet(candidate, row, "whale_global_candidates")
    for row in sources["whale_replacements"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_optional_wallet(candidate, row, "whale_replacements")
    for row in sources["whale_active_wallet_health"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_optional_wallet(candidate, row, "whale_active_wallet_health")

    for candidate in candidates.values():
        candidate["sourceCount"] = len(candidate.get("discoverySources") or [])
        candidate["discoverySources"] = sorted(candidate.get("discoverySources") or [])
        candidate["recentRawTrades"] = int(candidate.get("recentRawTrades") or 0)
        candidate["recentNormalizedTrades"] = int(candidate.get("recentNormalizedTrades") or 0)
        candidate["uniqueMarketsCount"] = int(candidate.get("uniqueMarketsCount") or 0)
        candidate["totalRecentUsdc"] = round(_safe_float(candidate.get("totalRecentUsdc")), 2)
        candidate["strategicMarketExposureScore"] = round(_safe_float(candidate.get("strategicMarketExposureScore")), 2)
        candidate["microMarketExposureScore"] = round(_safe_float(candidate.get("microMarketExposureScore")), 2)
        candidate["routineRiskScore"] = round(_safe_float(candidate.get("routineRiskScore")), 2)
        candidate["copyabilityPotentialScore"] = round(_safe_float(candidate.get("copyabilityPotentialScore")), 2)
        candidate["previousActionableSignalScore"] = _safe_float(candidate.get("previousActionableSignalScore"), default=0.0) if candidate.get("previousActionableSignalScore") is not None else None
        candidate["previousRoutineClusterRate"] = _safe_float(candidate.get("previousRoutineClusterRate"), default=0.0) if candidate.get("previousRoutineClusterRate") is not None else None
        candidate["previousMicroMarketClusterRate"] = _safe_float(candidate.get("previousMicroMarketClusterRate"), default=0.0) if candidate.get("previousMicroMarketClusterRate") is not None else None
        candidate["previousHedgeRate"] = _safe_float(candidate.get("previousHedgeRate"), default=0.0) if candidate.get("previousHedgeRate") is not None else None
        candidate["candidateRisks"] = list(dict.fromkeys(candidate.get("candidateRisks") or []))
        candidate["candidateReasons"] = list(dict.fromkeys(candidate.get("candidateReasons") or []))
        candidate.pop("_uniqueMarkets", None)

    provisional_candidates = sorted(
        candidates.values(),
        key=lambda item: (
            _safe_float(item.get("robustSkillScore")),
            _safe_float(item.get("categorySkillScore")),
            _safe_float(item.get("copyabilityPotentialScore")),
            _safe_float(item.get("recentRawTrades")),
            _safe_float(item.get("uniqueMarketsCount")),
        ),
        reverse=True,
    )
    for candidate in provisional_candidates[: min(SIGNAL_WALLET_DISCOVERY_V2_PREFLIGHT_TOP_N, len(provisional_candidates))]:
        wallet = candidate["wallet"]
        fetch_result = asyncio.run(
            fetch_copyability_trades_for_wallet(
            wallet,
            COPYABILITY_MAX_TRADES_PER_WALLET,
            COPYABILITY_LOOKBACK_HOURS,
            return_details=True,
            )
        )
        trades = list((fetch_result or {}).get("trades") or [])
        normalized_trades = len(trades)
        raw_trades = int((fetch_result or {}).get("rawTrades") or len(trades))
        unique_markets = {
            str(trade.get("conditionId") or trade.get("asset") or trade.get("marketTitle") or trade.get("eventSlug") or "")
            for trade in trades
            if str(trade.get("conditionId") or trade.get("asset") or trade.get("marketTitle") or trade.get("eventSlug") or "").strip()
        }
        preflight_cluster_viability = 0.0
        if trades:
            clusters = build_trade_clusters(trades)
            preflight_cluster_viability = (
                len(clusters) * 18.0
                + min(len(unique_markets), 8) * 6.0
                + min(sum(max(0.0, _safe_float(trade.get("sizeUsd"))) for trade in trades) / 150.0, 20.0)
                + min(raw_trades, 30) * 1.2
            )
            if SIGNAL_WALLET_DISCOVERY_V2_EXCLUDE_MICRO_MARKETS and any(_is_micro_market(_title_text(trade.get("marketTitle"), trade.get("eventSlug"), trade.get("conditionId"))) for trade in trades):
                preflight_cluster_viability -= 18.0
        candidate["preflightAnalyzed"] = True
        candidate["preflightSource"] = "copyability_api_fetch"
        candidate["preflightStatus"] = str((fetch_result or {}).get("status") or "completed")
        candidate["preflightReason"] = str((fetch_result or {}).get("reason") or "no_valid_trades")
        candidate["recentRawTrades"] = max(candidate["recentRawTrades"], raw_trades)
        candidate["recentNormalizedTrades"] = max(candidate["recentNormalizedTrades"], normalized_trades)
        unique_market_set = set(candidate.get("_uniqueMarkets") or set())
        unique_market_set.update({market.lower() for market in unique_markets if market})
        candidate["_uniqueMarkets"] = unique_market_set
        candidate["uniqueMarketsCount"] = max(candidate["uniqueMarketsCount"], len(unique_market_set))
        candidate["clusterViabilityScore"] = max(candidate["clusterViabilityScore"], round(max(0.0, preflight_cluster_viability), 2))
        candidate["copyabilityPotentialScore"] = max(candidate["copyabilityPotentialScore"], min(40.0, raw_trades * 0.8 + len(unique_markets) * 2.0))
        candidate["strategicMarketExposureScore"] = max(candidate["strategicMarketExposureScore"], 8.0 if any(_title_text(trade.get("marketTitle"), trade.get("eventSlug"), trade.get("conditionId")).lower() in strategic_seeds for trade in trades) else 0.0)
        print(
            "SMART_MONEY_DISCOVERY_V2_PREFLIGHT "
            f"wallet={wallet} "
            f"raw={raw_trades} "
            f"normalized={normalized_trades} "
            f"markets={len(unique_markets)} "
            f"viability={candidate['clusterViabilityScore']}"
        )

    for candidate in candidates.values():
        if candidate.get("preflightAnalyzed"):
            candidate["candidateReasons"].append("preflight_validated")
        if candidate.get("preflightStatus") == "failed":
            candidate["candidateRisks"].append("preflight_failed")
        if candidate.get("previousQualityRecommendation") == "REPLACE_CANDIDATE":
            candidate["candidateRisks"].append("previous_replace_candidate")
        if not candidate.get("candidateReasons"):
            candidate["candidateReasons"].append("insufficient_signal")
        _score_candidate(candidate, strategic_seeds)

    candidates_list = sorted(
        candidates.values(),
        key=lambda item: (
            _safe_float(item.get("candidateQualityScore")),
            _safe_float(item.get("strategicMarketExposureScore")),
            _safe_float(item.get("copyabilityPotentialScore")),
            _safe_float(item.get("recentRawTrades")),
            _safe_float(item.get("uniqueMarketsCount")),
        ),
        reverse=True,
    )

    max_candidates = max(0, SIGNAL_WALLET_DISCOVERY_V2_MAX_CANDIDATES)
    selected_candidates = candidates_list[:max_candidates] if max_candidates else candidates_list
    rejected_candidates = candidates_list[max_candidates:] if max_candidates else []
    strong_count = sum(1 for row in selected_candidates if row["candidateRecommendation"] == "STRONG_CANDIDATE")
    watchlist_count = sum(1 for row in selected_candidates if row["candidateRecommendation"] == "WATCHLIST_CANDIDATE")
    weak_count = sum(1 for row in selected_candidates if row["candidateRecommendation"] == "WEAK_CANDIDATE")
    rejected_count = sum(1 for row in selected_candidates if row["candidateRecommendation"] == "REJECT") + len(rejected_candidates)

    reason_summary: dict[str, int] = defaultdict(int)
    for row in selected_candidates + rejected_candidates:
        for reason in row.get("candidateReasons") or []:
            reason_summary[reason] += 1
        for risk in row.get("candidateRisks") or []:
            reason_summary[f"risk:{risk}"] += 1

    print(
        "SMART_MONEY_DISCOVERY_V2_COMPLETED "
        f"candidates={len(selected_candidates)} "
        f"strong={strong_count} "
        f"watchlist={watchlist_count} "
        f"rejected={rejected_count}"
    )

    source_has_content = any(value > 0 for value in source_loaded_counts.values())
    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sourceStatus": "ok" if source_has_content or selected_candidates or rejected_candidates else "empty",
        "candidateCount": len(selected_candidates),
        "strongCandidateCount": strong_count,
        "watchlistCandidateCount": watchlist_count,
        "weakCandidateCount": weak_count,
        "rejectedCandidateCount": rejected_count,
        "candidates": [
            {
                "wallet": row["wallet"],
                "candidateQualityScore": row["candidateQualityScore"],
                "candidateRecommendation": row["candidateRecommendation"],
                "discoverySources": row.get("discoverySources") or [],
                "sourceCount": row.get("sourceCount") or 0,
                "seenInPreviousRoster": bool(row.get("seenInPreviousRoster")),
                "previousQualityRecommendation": row.get("previousQualityRecommendation"),
                "previousActionableSignalScore": row.get("previousActionableSignalScore"),
                "previousRoutineClusterRate": row.get("previousRoutineClusterRate"),
                "previousMicroMarketClusterRate": row.get("previousMicroMarketClusterRate"),
                "previousHedgeRate": row.get("previousHedgeRate"),
                "previousBestCategory": row.get("previousBestCategory"),
                "robustSkillScore": round(_safe_float(row.get("robustSkillScore")), 2),
                "categorySkillScore": round(_safe_float(row.get("categorySkillScore")), 2),
                "walletCategorySkillScore": round(_safe_float(row.get("walletCategorySkillScore")), 2),
                "categorySkillStatus": row.get("categorySkillStatus"),
                "recentRawTrades": int(row.get("recentRawTrades") or 0),
                "recentNormalizedTrades": int(row.get("recentNormalizedTrades") or 0),
                "uniqueMarketsCount": int(row.get("uniqueMarketsCount") or 0),
                "totalRecentUsdc": round(_safe_float(row.get("totalRecentUsdc")), 2),
                "clusterViabilityScore": round(_safe_float(row.get("clusterViabilityScore")), 2),
                "strategicMarketExposureScore": round(_safe_float(row.get("strategicMarketExposureScore")), 2),
                "microMarketExposureScore": round(_safe_float(row.get("microMarketExposureScore")), 2),
                "routineRiskScore": round(_safe_float(row.get("routineRiskScore")), 2),
                "copyabilityPotentialScore": round(_safe_float(row.get("copyabilityPotentialScore")), 2),
                "candidateReasons": row.get("candidateReasons") or [],
                "candidateRisks": row.get("candidateRisks") or [],
                "preflightStatus": row.get("preflightStatus"),
                "preflightReason": row.get("preflightReason"),
                "preflightSource": row.get("preflightSource"),
            }
            for row in selected_candidates
        ],
        "rejectedCandidates": [
            {
                "wallet": row["wallet"],
                "candidateQualityScore": row["candidateQualityScore"],
                "candidateRecommendation": row["candidateRecommendation"],
                "discoverySources": row.get("discoverySources") or [],
                "sourceCount": row.get("sourceCount") or 0,
                "candidateReasons": row.get("candidateReasons") or [],
                "candidateRisks": row.get("candidateRisks") or [],
            }
            for row in rejected_candidates
        ],
        "reasonSummary": dict(sorted(reason_summary.items(), key=lambda item: (-item[1], item[0]))),
    }
    return payload


def write_adaptive_signal_candidate_pool(payload: dict[str, Any]) -> Path:
    ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE.with_suffix(ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_payload(payload), handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE)
    print(f"SMART_MONEY_DISCOVERY_V2_WRITTEN path={ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE}")
    return ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE
