from __future__ import annotations

import asyncio
import inspect
import json
import math
import os
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
        COPYABILITY_MAX_WALLETS_PER_RUN,
        build_trade_clusters,
        fetch_copyability_trades_for_wallet,
    )
    from .time_utils import to_utc_datetime
    from .wallet_shadow_cohort import parse_wallet_specifiers
except ImportError:  # pragma: no cover
    from copyability_storage import sanitize_payload
    from path_utils import resolve_output_dir
    from trade_copyability import (
        COPYABILITY_LOOKBACK_HOURS,
        COPYABILITY_MAX_TRADES_PER_WALLET,
        COPYABILITY_MAX_WALLETS_PER_RUN,
        build_trade_clusters,
        fetch_copyability_trades_for_wallet,
    )
    from time_utils import to_utc_datetime
    from wallet_shadow_cohort import parse_wallet_specifiers


OUTPUT_DIR = resolve_output_dir()
ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE = OUTPUT_DIR / "adaptive_signal_wallet_roster.json"
SIGNAL_WALLET_DIAGNOSTIC_PREFLIGHT_TOP_N = int(os.getenv("SIGNAL_WALLET_DIAGNOSTIC_PREFLIGHT_TOP_N", "0"))
SIGNAL_WALLET_DISCOVERY_V2_ENABLED = os.getenv("SIGNAL_WALLET_DISCOVERY_V2_ENABLED", "true").lower() == "true"


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


def _first_from_collection(value: Any, default: str = "mixed") -> str:
    if isinstance(value, set):
        items = sorted(value)
    elif isinstance(value, (list, tuple)):
        items = list(value)
    elif value in {None, "", []}:
        items = []
    else:
        return str(value)
    for item in items:
        if item not in {None, ""}:
            return str(item)
    return default


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


async def _call_fetch_copyability_trades_for_wallet(
    wallet: str,
    limit: int,
    lookback_hours: int,
    *,
    return_details: bool = False,
) -> Any:
    result = fetch_copyability_trades_for_wallet(
        wallet,
        limit,
        lookback_hours,
        return_details=return_details,
    )
    if inspect.isawaitable(result):
        return await result
    return result


def load_adaptive_signal_roster_sources(output_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    base = Path(output_dir) if output_dir else OUTPUT_DIR
    quality_payload = _load_json(base / "adaptive_signal_wallet_quality.json", {})
    if isinstance(quality_payload, dict):
        quality_rows = (
            quality_payload.get("wallets")
            or quality_payload.get("walletQualityRows")
            or quality_payload.get("walletResults")
            or []
        )
    else:
        quality_rows = []
    return {
        "wallet_shadow_rankings": _load_json(base / "wallet_shadow_rankings.json", []),
        "wallet_category_rankings": _load_json(base / "wallet_category_rankings.json", {}),
        "wallet_comparison_summary": _load_json(base / "wallet_comparison_summary.json", {}),
        "wallet_shadow_history": _load_jsonl(base / "wallet_shadow_history.jsonl"),
        "trade_copyability_shadow": _load_json(base / "trade_copyability_shadow.json", {}),
        "wallet_copyability_summary": _load_json(base / "wallet_copyability_summary.json", {}),
        "wallet_quality": quality_rows,
        "candidate_pool": _load_json(base / "adaptive_signal_candidate_pool.json", {}),
    }


def _ensure_candidate(candidates: dict[str, dict[str, Any]], wallet: str) -> dict[str, Any]:
    wallet = _normalize_wallet(wallet)
    candidate = candidates.get(wallet)
    if candidate is None:
        candidate = {
            "wallet": wallet,
            "displayName": wallet,
            "roles": set(),
            "profiles": set(),
            "sources": set(),
            "classification": None,
            "priority": False,
            "benchmark": False,
            "generalRank": None,
            "behaviorQualityScore": None,
            "walletQualityScore": None,
            "longitudinalComparisonScore": None,
            "comparisonConfidence": None,
            "runCount": 0,
            "stabilityScore": None,
            "scoreTrend": None,
            "dominantKnownCategory": None,
            "knownCategoryCoverageScore": None,
            "pnlConcentrationLevel": None,
            "recommendation": None,
            "categorySkillScore": None,
            "categorySkillStatus": None,
            "closedPositionsCount": 0,
            "categoryCount": 0,
            "latestGeneratedAt": None,
            "historyRunCount": 0,
            "copyabilityClustersCount": 0,
            "highCopyabilityCount": 0,
            "watchCopyabilityCount": 0,
            "notCopyableCount": 0,
            "reductionSignalCount": 0,
            "accumulationCount": 0,
            "hedgeCount70": 0,
            "possibleHedgeCount60": 0,
            "hedgeRate70": 0.0,
            "possibleHedgeRate60": 0.0,
            "comparisonLeadCount": 0,
            "previousActionableSignalScore": None,
            "previousQualityRecommendation": None,
            "previousRoutineClusterRate": None,
            "previousMicroMarketClusterRate": None,
            "discoveryV2CandidateRecommendation": None,
            "discoveryV2CandidateQualityScore": None,
            "discoveryV2CandidateReasons": [],
            "discoveryV2CandidateRisks": [],
            "discoveryV2DiscoverySources": [],
            "qualityPenaltyApplied": 0.0,
        }
        candidates[wallet] = candidate
    return candidate


def _merge_non_empty(candidate: dict[str, Any], key: str, value: Any) -> None:
    if value is None or value == "" or value == [] or value == {}:
        return
    current_value = candidate.get(key)
    if current_value is None or current_value == "" or current_value == [] or current_value == {}:
        candidate[key] = value


def _merge_wallet_score(candidate: dict[str, Any], score: dict[str, Any]) -> None:
    candidate["sources"].add("wallet_scores")
    candidate["roles"].update(score.get("roles") or [])
    candidate["profiles"].update(score.get("profiles") or [])
    _merge_non_empty(candidate, "displayName", score.get("displayName") or score.get("name"))
    _merge_non_empty(candidate, "classification", score.get("classification"))
    _merge_non_empty(candidate, "behaviorQualityScore", score.get("behaviorQualityScore") or score.get("walletQualityScore"))
    _merge_non_empty(candidate, "walletQualityScore", score.get("walletQualityScore"))


def _merge_general_ranking(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    candidate["sources"].add("wallet_shadow_rankings")
    candidate["roles"].update(row.get("roles") or [])
    candidate["profiles"].update(row.get("profiles") or [])
    _merge_non_empty(candidate, "displayName", row.get("displayName"))
    _merge_non_empty(candidate, "classification", row.get("classification"))
    _merge_non_empty(candidate, "behaviorQualityScore", row.get("behaviorQualityScore"))
    _merge_non_empty(candidate, "walletQualityScore", row.get("behaviorQualityScore"))
    _merge_non_empty(candidate, "generalRank", row.get("rank"))
    _merge_non_empty(candidate, "longitudinalComparisonScore", row.get("longitudinalComparisonScore"))
    _merge_non_empty(candidate, "comparisonConfidence", row.get("comparisonConfidence"))
    candidate["runCount"] = max(candidate.get("runCount") or 0, int(row.get("runCount") or 0))
    _merge_non_empty(candidate, "stabilityScore", row.get("stabilityScore"))
    _merge_non_empty(candidate, "scoreTrend", row.get("scoreTrend"))
    _merge_non_empty(candidate, "dominantKnownCategory", row.get("dominantKnownCategory"))
    _merge_non_empty(candidate, "knownCategoryCoverageScore", row.get("knownCategoryCoverageScore"))
    _merge_non_empty(candidate, "pnlConcentrationLevel", row.get("pnlConcentrationLevel"))
    _merge_non_empty(candidate, "recommendation", row.get("recommendation"))
    _merge_non_empty(candidate, "robustSkillScore", row.get("robustSkillScore"))
    _merge_non_empty(candidate, "shadowRobustMetaScore", row.get("shadowRobustMetaScore"))


def _merge_shadow_row(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    candidate["sources"].add("wallet_shadow_history")
    candidate["roles"].update(row.get("roles") or [])
    candidate["profiles"].update(row.get("profiles") or [])
    _merge_non_empty(candidate, "displayName", row.get("displayName"))
    _merge_non_empty(candidate, "classification", row.get("classification"))
    _merge_non_empty(candidate, "behaviorQualityScore", row.get("behaviorQualityScore"))
    shadow_skill = row.get("shadowSkill") or {}
    shadow_robust = row.get("shadowRobustEvaluation") or {}
    if shadow_skill.get("categorySkillScores"):
        candidate["categoryCount"] = max(candidate.get("categoryCount") or 0, len(shadow_skill.get("categorySkillScores") or {}))
    _merge_non_empty(candidate, "dominantKnownCategory", shadow_skill.get("dominantKnownCategory"))
    _merge_non_empty(candidate, "categorySkillStatus", shadow_skill.get("skillStatus"))
    _merge_non_empty(candidate, "categorySkillScore", shadow_skill.get("skillScore"))
    _merge_non_empty(candidate, "robustSkillScore", shadow_robust.get("robustSkillScore"))
    _merge_non_empty(candidate, "pnlConcentrationLevel", shadow_robust.get("pnlConcentrationLevel"))
    _merge_non_empty(candidate, "latestGeneratedAt", row.get("generatedAt"))
    candidate["historyRunCount"] = max(candidate.get("historyRunCount") or 0, 1)


def _merge_category_rankings(candidate: dict[str, Any], category_rankings: dict[str, list[dict[str, Any]]]) -> None:
    best_category = candidate.get("dominantKnownCategory")
    best_category_score = _safe_float(candidate.get("categorySkillScore"), default=-1.0)
    category_count = candidate.get("categoryCount") or 0
    for category, rows in category_rankings.items():
        if category == "unknown":
            continue
        for row in rows or []:
            if _normalize_wallet(row.get("wallet")) != candidate["wallet"]:
                continue
            category_count += 1
            category_score = _safe_float(row.get("categorySkillScore"), default=0.0)
            if category_score >= best_category_score:
                best_category = category
                best_category_score = category_score
            _merge_non_empty(candidate, "categorySkillStatus", row.get("categorySkillStatus"))
            candidate["closedPositionsCount"] = max(candidate.get("closedPositionsCount") or 0, int(row.get("closedPositionsCount") or 0))
    candidate["categoryCount"] = max(candidate.get("categoryCount") or 0, category_count)
    _merge_non_empty(candidate, "dominantKnownCategory", best_category)
    if best_category_score >= 0:
        candidate["categorySkillScore"] = max(_safe_float(candidate.get("categorySkillScore"), default=0.0), best_category_score)


def _merge_copyability_summary(candidate: dict[str, Any], summary: dict[str, Any]) -> None:
    row = summary.get(candidate["wallet"]) if isinstance(summary, dict) else None
    if not isinstance(row, dict):
        return
    candidate["sources"].add("wallet_copyability_summary")
    candidate["copyabilityClustersCount"] = max(candidate.get("copyabilityClustersCount") or 0, int(row.get("clustersCount") or 0))
    candidate["highCopyabilityCount"] = max(candidate.get("highCopyabilityCount") or 0, int(row.get("highCopyabilityCount") or 0))
    candidate["watchCopyabilityCount"] = max(candidate.get("watchCopyabilityCount") or 0, int(row.get("watchCopyabilityCount") or 0))
    candidate["notCopyableCount"] = max(candidate.get("notCopyableCount") or 0, int(row.get("notCopyableCount") or 0))
    candidate["reductionSignalCount"] = max(candidate.get("reductionSignalCount") or 0, int(row.get("reductionSignalCount") or 0))
    candidate["accumulationCount"] = max(candidate.get("accumulationCount") or 0, int(row.get("accumulationCount") or 0))
    candidate["hedgeCount70"] = max(candidate.get("hedgeCount70") or 0, int(row.get("hedgeCount70") or 0))
    candidate["possibleHedgeCount60"] = max(candidate.get("possibleHedgeCount60") or 0, int(row.get("possibleHedgeCount60") or 0))
    candidate["hedgeRate70"] = max(candidate.get("hedgeRate70") or 0.0, _safe_float(row.get("hedgeRate70")))
    candidate["possibleHedgeRate60"] = max(candidate.get("possibleHedgeRate60") or 0.0, _safe_float(row.get("possibleHedgeRate60")))


def _merge_copyability_shadow(candidate: dict[str, Any], shadow_payload: dict[str, Any]) -> None:
    if not isinstance(shadow_payload, dict):
        return
    candidate["sources"].add("trade_copyability_shadow")
    clusters = shadow_payload.get("clusters") or []
    wallet_results = shadow_payload.get("walletResults") or []
    for entry in wallet_results:
        if _normalize_wallet(entry.get("wallet")) != candidate["wallet"]:
            continue
        candidate["copyabilityClustersCount"] = max(candidate.get("copyabilityClustersCount") or 0, int(entry.get("clusters") or 0))
        candidate["highCopyabilityCount"] = max(candidate.get("highCopyabilityCount") or 0, int(entry.get("highCopyabilityCount") or 0))
        candidate["watchCopyabilityCount"] = max(candidate.get("watchCopyabilityCount") or 0, int(entry.get("watchCopyabilityCount") or 0))
        candidate["notCopyableCount"] = max(candidate.get("notCopyableCount") or 0, int(entry.get("notCopyableCount") or 0))
        break
    for cluster in clusters:
        if _normalize_wallet(cluster.get("wallet")) != candidate["wallet"]:
            continue
        candidate["copyabilityClustersCount"] = max(candidate.get("copyabilityClustersCount") or 0, 1)
        if str(cluster.get("copyabilityStatus") or "") == "not_copyable":
            candidate["notCopyableCount"] = max(candidate.get("notCopyableCount") or 0, 1)
        if str(cluster.get("copyabilityStatus") or "") == "high_copyability":
            candidate["highCopyabilityCount"] = max(candidate.get("highCopyabilityCount") or 0, 1)
        if str(cluster.get("copyabilityStatus") or "") == "watch_copyability":
            candidate["watchCopyabilityCount"] = max(candidate.get("watchCopyabilityCount") or 0, 1)
        hedge_probability = _safe_float((cluster.get("hedge") or {}).get("hedgeProbability"))
        if hedge_probability >= 70:
            candidate["hedgeCount70"] = max(candidate.get("hedgeCount70") or 0, 1)
        if hedge_probability >= 60:
            candidate["possibleHedgeCount60"] = max(candidate.get("possibleHedgeCount60") or 0, 1)


def _merge_quality_feedback(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    candidate["sources"].add("wallet_quality")
    candidate["previousActionableSignalScore"] = _safe_float(row.get("actionableSignalScore"), default=None) if row.get("actionableSignalScore") is not None else candidate.get("previousActionableSignalScore")
    candidate["previousQualityRecommendation"] = str(row.get("keepInRosterRecommendation") or candidate.get("previousQualityRecommendation") or "") or None
    candidate["previousRoutineClusterRate"] = _safe_float(row.get("routineClusterRate"), default=None) if row.get("routineClusterRate") is not None else candidate.get("previousRoutineClusterRate")
    candidate["previousMicroMarketClusterRate"] = _safe_float(row.get("microMarketClusterRate"), default=None) if row.get("microMarketClusterRate") is not None else candidate.get("previousMicroMarketClusterRate")
    recommendation = str(candidate.get("previousQualityRecommendation") or "")
    actionable_score = _safe_float(candidate.get("previousActionableSignalScore"), default=0.0)
    routine_rate = _safe_float(candidate.get("previousRoutineClusterRate"), default=0.0)
    micro_rate = _safe_float(candidate.get("previousMicroMarketClusterRate"), default=0.0)
    quality_penalty = 0.0
    if recommendation == "REPLACE_CANDIDATE":
        quality_penalty += 18.0
    if actionable_score and actionable_score < 50:
        quality_penalty += 8.0
    if routine_rate >= 0.45:
        quality_penalty += 6.0
    if micro_rate >= 0.25:
        quality_penalty += 6.0
    candidate["qualityPenaltyApplied"] = round(quality_penalty, 2)


def _merge_candidate_pool(candidate: dict[str, Any], row: dict[str, Any]) -> None:
    candidate["sources"].add("discovery_v2_candidate_pool")
    discovery_sources = row.get("discoverySources") or []
    if isinstance(discovery_sources, list):
        merged_sources = set(candidate.get("discoveryV2DiscoverySources") or [])
        merged_sources.update(str(item) for item in discovery_sources if item)
        candidate["discoveryV2DiscoverySources"] = sorted(merged_sources)
    _merge_non_empty(candidate, "discoveryV2CandidateRecommendation", row.get("candidateRecommendation"))
    _merge_non_empty(candidate, "discoveryV2CandidateQualityScore", row.get("candidateQualityScore"))
    reasons = list(candidate.get("discoveryV2CandidateReasons") or [])
    for reason in row.get("candidateReasons") or []:
        if reason not in reasons:
            reasons.append(reason)
    candidate["discoveryV2CandidateReasons"] = reasons
    risks = list(candidate.get("discoveryV2CandidateRisks") or [])
    for risk in row.get("candidateRisks") or []:
        if risk not in risks:
            risks.append(risk)
    candidate["discoveryV2CandidateRisks"] = risks
    candidate["seenInPreviousRoster"] = bool(candidate.get("seenInPreviousRoster") or row.get("seenInPreviousRoster"))
    if row.get("previousQualityRecommendation") is not None:
        candidate["previousQualityRecommendation"] = row.get("previousQualityRecommendation")
    if row.get("previousActionableSignalScore") is not None:
        candidate["previousActionableSignalScore"] = _safe_float(row.get("previousActionableSignalScore"), default=None)
    if row.get("previousRoutineClusterRate") is not None:
        candidate["previousRoutineClusterRate"] = _safe_float(row.get("previousRoutineClusterRate"), default=None)
    if row.get("previousMicroMarketClusterRate") is not None:
        candidate["previousMicroMarketClusterRate"] = _safe_float(row.get("previousMicroMarketClusterRate"), default=None)
    if row.get("previousHedgeRate") is not None:
        candidate["previousHedgeRate"] = _safe_float(row.get("previousHedgeRate"), default=None)
    if row.get("previousBestCategory") is not None:
        candidate["previousBestCategory"] = row.get("previousBestCategory")
    _merge_non_empty(candidate, "robustSkillScore", row.get("robustSkillScore"))
    _merge_non_empty(candidate, "categorySkillScore", row.get("categorySkillScore"))
    _merge_non_empty(candidate, "categorySkillStatus", row.get("categorySkillStatus"))
    _merge_non_empty(candidate, "recentRawTrades", row.get("recentRawTrades"))
    _merge_non_empty(candidate, "recentNormalizedTrades", row.get("recentNormalizedTrades"))
    _merge_non_empty(candidate, "uniqueMarketsCount", row.get("uniqueMarketsCount"))
    _merge_non_empty(candidate, "totalRecentUsdc", row.get("totalRecentUsdc"))
    _merge_non_empty(candidate, "clusterViabilityScore", row.get("clusterViabilityScore"))
    _merge_non_empty(candidate, "strategicMarketExposureScore", row.get("strategicMarketExposureScore"))
    _merge_non_empty(candidate, "microMarketExposureScore", row.get("microMarketExposureScore"))
    _merge_non_empty(candidate, "routineRiskScore", row.get("routineRiskScore"))
    _merge_non_empty(candidate, "copyabilityPotentialScore", row.get("copyabilityPotentialScore"))


def _merge_comparison_summary(candidate: dict[str, Any], comparison_summary: dict[str, Any]) -> None:
    comparisons = comparison_summary.get("comparisons") if isinstance(comparison_summary, dict) else None
    if not isinstance(comparisons, list):
        return
    lead_count = candidate.get("comparisonLeadCount") or 0
    for comparison in comparisons:
        if _normalize_wallet(comparison.get("candidateWallet")) != candidate["wallet"]:
            continue
        if comparison.get("comparisonStatus") == "candidate_leads":
            lead_count += 1
    candidate["comparisonLeadCount"] = lead_count


def _latest_wallet_seen_at(candidate: dict[str, Any], shadow_history: list[dict[str, Any]]) -> None:
    latest: datetime | None = None
    for row in shadow_history:
        if _normalize_wallet(row.get("wallet")) != candidate["wallet"]:
            continue
        parsed = to_utc_datetime(row.get("generatedAt"))
        if parsed is None:
            continue
        if latest is None or parsed > latest:
            latest = parsed
    if latest is not None:
        candidate["latestGeneratedAt"] = latest.isoformat()


def _recent_activity_profile(latest_generated_at: Any) -> tuple[str, float, float]:
    latest = to_utc_datetime(latest_generated_at)
    if latest is None:
        return "unknown", 45.0, 6.0
    now = datetime.now(timezone.utc)
    age_days = max(0.0, (now - latest).total_seconds() / 86400.0)
    if age_days <= 7:
        return "recent", 100.0, 0.0
    if age_days <= 30:
        return "recent", 82.0, 4.0
    if age_days <= 90:
        return "stale_verified", 60.0, 12.0
    return "stale_verified", 35.0, 18.0


def _build_reason(candidate: dict[str, Any]) -> str:
    if candidate.get("benchmark"):
        return "benchmark wallet"

    reasons: list[str] = []
    if _safe_float(candidate.get("robustSkillScore")) >= 80:
        reasons.append("strong robust skill score")
    if _safe_float(candidate.get("categorySkillScore")) >= 75:
        reasons.append("strong category skill")
    if _safe_float(candidate.get("recentActivityScore")) >= 70:
        reasons.append("recent activity")
    if _safe_float(candidate.get("marketDiversityScore")) >= 60:
        reasons.append("market diversity")
    if _safe_float(candidate.get("usefulAccumulationScore")) >= 55:
        reasons.append("useful accumulation")
    if _safe_float(candidate.get("reductionSignalQualityScore")) >= 55:
        reasons.append("reduction signal quality")
    if _safe_float(candidate.get("copyabilityScore")) >= 60:
        reasons.append("good copyability")
    if _safe_float(candidate.get("lowHedgeScore")) >= 60:
        reasons.append("low hedge rate")
    if candidate.get("priority"):
        reasons.append("priority wallet")
    if not reasons:
        reasons.append("signal wallet roster candidate")
    return ", ".join(reasons[:4])


def _build_rejection_reason(candidate: dict[str, Any]) -> str:
    if candidate.get("benchmark"):
        return "benchmark included"

    hedge_rate = _safe_float(candidate.get("hedgeRate70"))
    not_copyable = int(candidate.get("notCopyableCount") or 0)
    stale_penalty = _safe_float(candidate.get("staleActivityPenalty"))
    insufficient_penalty = _safe_float(candidate.get("insufficientSamplePenalty"))
    concentration_penalty = _safe_float(candidate.get("concentrationPenalty"))
    recent_status = str(candidate.get("recentActivityStatus") or "unknown")

    if not _normalize_wallet(candidate.get("wallet")):
        return "invalid wallet"
    if hedge_rate >= 0.9 and not_copyable >= 8:
        return "extreme hedge risk"
    if stale_penalty >= 16 and recent_status == "stale_verified":
        return "stale activity verified"
    if insufficient_penalty >= 12 and _safe_float(candidate.get("signalWalletRosterScore")) < 20:
        return "insufficient sample"
    if concentration_penalty >= 24:
        return "high concentration penalty"
    if _safe_float(candidate.get("copyabilityScore")) < 40:
        return "low copyability"
    return "lower signal score than selected roster"


def _has_live_diagnostic_metrics(candidate: dict[str, Any]) -> bool:
    return any(
        (
            int(candidate.get("recentRawTrades") or 0) > 0,
            int(candidate.get("recentNormalizedTrades") or 0) > 0,
            int(candidate.get("uniqueMarketsCount") or 0) > 0,
            _safe_float(candidate.get("clusterViabilityScore")) > 0,
        )
    )


def _collect_rejection_reasons(candidate: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    score = _safe_float(candidate.get("signalWalletRosterScore"))
    robust = _safe_float(candidate.get("robustSkillScore"))
    category = _safe_float(candidate.get("categorySkillScore"))
    raw_trades = int(candidate.get("recentRawTrades") or 0)
    normalized_trades = int(candidate.get("recentNormalizedTrades") or 0)
    unique_markets = int(candidate.get("uniqueMarketsCount") or 0)
    cluster_viability = _safe_float(candidate.get("clusterViabilityScore"))
    previous_quality = str(candidate.get("previousQualityRecommendation") or "")
    previous_actionable = candidate.get("previousActionableSignalScore")
    previous_routine = candidate.get("previousRoutineClusterRate")
    previous_micro = candidate.get("previousMicroMarketClusterRate")
    quality_penalty = _safe_float(candidate.get("qualityPenaltyApplied"))
    hedge_rate = _safe_float(candidate.get("hedgeRate70"))
    hedge_penalty = _safe_float(candidate.get("hedgePenalty"))
    copyability_clusters = int(candidate.get("copyabilityClustersCount") or 0)
    has_quality_feedback = previous_quality == "REPLACE_CANDIDATE" or previous_actionable is not None or quality_penalty > 0
    has_live_metrics = _has_live_diagnostic_metrics(candidate)
    has_any_metrics = any(
        (
            raw_trades > 0,
            normalized_trades > 0,
            unique_markets > 0,
            cluster_viability > 0,
            copyability_clusters > 0,
            _safe_float(candidate.get("recentActivityScore")) > 0,
            robust > 0,
            category > 0,
        )
    )

    if not _normalize_wallet(candidate.get("wallet")):
        reasons.append("invalid_wallet")
    if previous_quality == "REPLACE_CANDIDATE":
        reasons.append("previous_replace_candidate")
    if not has_quality_feedback and not has_live_metrics:
        reasons.append("unknown_quality_no_preflight")
    if not has_any_metrics:
        reasons.append("missing_required_metrics")
    if score < 45:
        reasons.append("low_actionable_score")
    if robust < 55 or category < 45 or score < 35:
        reasons.append("low_skill_score")
    if raw_trades and raw_trades < 10:
        reasons.append("insufficient_live_trades")
    if normalized_trades and normalized_trades < 10:
        reasons.append("insufficient_normalized_trades")
    if unique_markets and unique_markets < 2:
        reasons.append("low_unique_markets")
    if cluster_viability <= 0 or (cluster_viability < 25 and has_live_metrics):
        reasons.append("low_cluster_viability")
    if previous_routine is not None and _safe_float(previous_routine) >= 0.45:
        reasons.append("high_routine_rate")
    if previous_micro is not None and _safe_float(previous_micro) >= 0.25:
        reasons.append("high_micro_market_rate")
    if hedge_rate >= 0.5 or hedge_penalty >= 20:
        reasons.append("high_hedge_rate")

    seen: set[str] = set()
    deduped: list[str] = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        deduped.append(reason)
    return deduped


def _build_rejection_breakdown(candidate: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
    quality_penalty = _safe_float(candidate.get("qualityPenaltyApplied"))
    previous_replace_penalty = 18.0 if str(candidate.get("previousQualityRecommendation") or "") == "REPLACE_CANDIDATE" else 0.0
    previous_routine = _safe_float(candidate.get("previousRoutineClusterRate"), default=0.0)
    previous_micro = _safe_float(candidate.get("previousMicroMarketClusterRate"), default=0.0)
    routine_penalty = 6.0 if previous_routine >= 0.45 else 0.0
    micro_market_penalty = 6.0 if previous_micro >= 0.25 else 0.0
    return {
        "baseScore": round(_safe_float(candidate.get("signalWalletRosterScore")) + quality_penalty, 2),
        "qualityPenalty": round(quality_penalty, 2),
        "routinePenalty": round(routine_penalty, 2),
        "microMarketPenalty": round(micro_market_penalty, 2),
        "hedgePenalty": round(_safe_float(candidate.get("hedgePenalty")), 2),
        "previousReplacePenalty": round(previous_replace_penalty, 2),
        "liveActivityScore": round(_safe_float(candidate.get("recentActivityScore")), 2),
        "clusterViabilityScore": round(_safe_float(candidate.get("clusterViabilityScore")), 2),
        "finalScore": round(_safe_float(candidate.get("signalWalletRosterScore")), 2),
        "rejectionReason": reasons[0] if reasons else "low_actionable_score",
        "rejectionReasons": reasons,
    }


def _validate_candidate(candidate: dict[str, Any]) -> str | None:
    wallet = _normalize_wallet(candidate.get("wallet"))
    if not wallet or not wallet.startswith("0x") or len(wallet) != 42:
        return "invalid wallet"
    if _safe_float(candidate.get("signalWalletRosterScore")) <= 0 and not candidate.get("sources"):
        return "missing_required_metrics"
    hedge_rate = _safe_float(candidate.get("hedgeRate70"))
    not_copyable = int(candidate.get("notCopyableCount") or 0)
    clusters_count = max(0, int(candidate.get("copyabilityClustersCount") or 0))
    if clusters_count >= 5 and hedge_rate >= 0.95 and not_copyable >= 8:
        return "extreme hedge risk"
    return None


def _is_micro_prop_trade(trade: dict[str, Any]) -> bool:
    text = " ".join(
        str(trade.get(field) or "")
        for field in ("marketTitle", "eventSlug", "category", "conditionId", "asset", "outcome")
    ).lower()
    if not text.strip():
        return False
    return any(
        token in text
        for token in [
            "exact score",
            "exact-score",
            "corners",
            "corner",
            "halftime",
            "half time",
            "player ",
            "player-",
            "player_",
            "stats",
            "stat ",
            "shots",
            "rebounds",
            "assists",
            "goals",
            "saves",
            "touchdowns",
            "yards",
            "passes",
            "cards",
            "fouls",
        ]
    )


def _build_preflight_profile(trades: list[dict[str, Any]], prior_score: float) -> dict[str, Any]:
    recent_raw_trades = len(trades)
    recent_normalized_trades = len(trades)
    unique_markets = {
        str(trade.get("conditionId") or trade.get("asset") or trade.get("marketTitle") or trade.get("eventSlug") or "")
        for trade in trades
        if str(trade.get("conditionId") or trade.get("asset") or trade.get("marketTitle") or trade.get("eventSlug") or "").strip()
    }
    unique_markets_count = len(unique_markets)
    total_recent_usdc = round(sum(max(0.0, _safe_float(trade.get("sizeUsd"))) for trade in trades), 2)
    category_hints: dict[str, int] = defaultdict(int)
    micro_prop_count = 0
    for trade in trades:
        category = str(trade.get("category") or "unknown").lower()
        category_hints[category] += 1
        if _is_micro_prop_trade(trade):
            micro_prop_count += 1
    dominant_category = max(category_hints.items(), key=lambda item: item[1])[0] if category_hints else "unknown"
    sports_only = bool(trades) and all(str(trade.get("category") or "").lower() in {"sports", "esports"} for trade in trades)
    sports_only_penalty = 28.0 if sports_only else (12.0 if category_hints.get("sports", 0) and category_hints.get("sports", 0) >= sum(category_hints.values()) * 0.7 else 0.0)
    micro_bet_penalty = 20.0 if trades and total_recent_usdc < 250 else (10.0 if total_recent_usdc < 750 else 0.0)
    exact_score_prop_penalty = 18.0 if micro_prop_count and micro_prop_count >= max(1, int(len(trades) * 0.6)) else (8.0 if micro_prop_count else 0.0)
    insufficient_recent_trades_penalty = 22.0 if recent_raw_trades < 5 else (14.0 if recent_raw_trades < 10 else (6.0 if recent_raw_trades < 20 else 0.0))
    clusters = build_trade_clusters(trades)
    no_cluster_viability_penalty = 0.0
    if not clusters:
        no_cluster_viability_penalty += 30.0
    if unique_markets_count < 2:
        no_cluster_viability_penalty += 18.0
    cluster_viability_score = (
        (len(clusters) * 18.0)
        + (min(unique_markets_count, 8) * 6.0)
        + (min(total_recent_usdc / 150.0, 20.0))
        + (min(recent_raw_trades, 30) * 1.2)
        + (prior_score * 0.15)
    )
    cluster_viability_score -= sports_only_penalty + micro_bet_penalty + exact_score_prop_penalty + insufficient_recent_trades_penalty + no_cluster_viability_penalty
    cluster_viability_score = round(max(0.0, cluster_viability_score), 2)
    return {
        "recentRawTrades": recent_raw_trades,
        "recentNormalizedTrades": recent_normalized_trades,
        "estimatedTradeCount": max(recent_raw_trades, recent_normalized_trades),
        "totalRecentUsdc": total_recent_usdc,
        "uniqueMarketsCount": unique_markets_count,
        "categoryHints": dict(sorted(category_hints.items())),
        "sportsOnlyPenalty": round(sports_only_penalty, 2),
        "microBetPenalty": round(micro_bet_penalty, 2),
        "exactScorePropPenalty": round(exact_score_prop_penalty, 2),
        "noClusterViabilityPenalty": round(no_cluster_viability_penalty, 2),
        "insufficientRecentTradesPenalty": round(insufficient_recent_trades_penalty, 2),
        "clusterViabilityScore": cluster_viability_score,
        "dominantCategoryHint": dominant_category,
        "clustersGenerated": len(clusters),
    }


def _score_candidate(candidate: dict[str, Any]) -> None:
    robust = _clamp(_safe_float(candidate.get("robustSkillScore"), default=_safe_float(candidate.get("walletQualityScore"))))
    category = _clamp(_safe_float(candidate.get("categorySkillScore"), default=0.0))
    recent_status, recent, stale_penalty = _recent_activity_profile(candidate.get("latestGeneratedAt"))
    category_count = max(0, int(candidate.get("categoryCount") or 0))
    profiles_count = len(candidate.get("profiles") or [])
    market_diversity = _clamp(min(100.0, category_count * 20.0 + profiles_count * 10.0))

    clusters_count = max(0, int(candidate.get("copyabilityClustersCount") or 0))
    high_copy = max(0, int(candidate.get("highCopyabilityCount") or 0))
    watch_copy = max(0, int(candidate.get("watchCopyabilityCount") or 0))
    not_copyable = max(0, int(candidate.get("notCopyableCount") or 0))
    reduction = max(0, int(candidate.get("reductionSignalCount") or 0))
    accumulation = max(0, int(candidate.get("accumulationCount") or 0))
    hedge_rate70 = _clamp(_safe_float(candidate.get("hedgeRate70")) * 100.0)
    possible_hedge_rate60 = _clamp(_safe_float(candidate.get("possibleHedgeRate60")) * 100.0)

    if clusters_count > 0:
        high_ratio = high_copy / clusters_count
        watch_ratio = watch_copy / clusters_count
        not_copyable_ratio = not_copyable / clusters_count
    else:
        high_ratio = watch_ratio = not_copyable_ratio = 0.0

    useful_accumulation = _clamp(min(100.0, accumulation * 14.0 + high_copy * 8.0 + watch_copy * 4.0))
    reduction_quality = _clamp(min(100.0, reduction * 4.0 + max(0.0, 18.0 - not_copyable * 2.0) + high_copy * 3.0))
    copyability_score = _clamp(
        min(
            100.0,
            100.0
            * (
                0.52 * high_ratio
                + 0.28 * watch_ratio
                + 0.20 * max(0.0, 1.0 - not_copyable_ratio)
            ),
        )
    )
    low_hedge = _clamp(max(0.0, 100.0 - hedge_rate70 - (possible_hedge_rate60 * 0.30)))
    hedge_penalty = _clamp(
        (hedge_rate70 * 0.18)
        + (possible_hedge_rate60 * 0.08)
        + (6.0 if not_copyable >= 5 else 0.0)
    )

    pnl_level = str(candidate.get("pnlConcentrationLevel") or "").lower()
    concentration_penalty_map = {
        "low": 0.0,
        "moderate": 8.0,
        "high": 18.0,
        "extreme": 30.0,
    }
    concentration_penalty = concentration_penalty_map.get(pnl_level, 6.0 if pnl_level else 0.0)
    if not_copyable >= 5:
        concentration_penalty += 6.0

    insufficient_sample_penalty = 0.0
    sample_size = max(clusters_count, int(candidate.get("closedPositionsCount") or 0), int(candidate.get("runCount") or 0))
    if sample_size <= 0:
        insufficient_sample_penalty = 10.0
    elif sample_size < 5:
        insufficient_sample_penalty = 8.0
    elif sample_size < 10:
        insufficient_sample_penalty = 4.0

    category_concentration_penalty = 0.0
    if category_count <= 1 and len(candidate.get("profiles") or []) <= 1 and not candidate.get("benchmark"):
        category_concentration_penalty = 4.0
    coverage = _safe_float(candidate.get("knownCategoryCoverageScore"))
    if coverage and coverage < 45:
        category_concentration_penalty += 4.0

    priority_boost = 10.0 if candidate.get("priority") else 0.0
    behavior_quality = _clamp(_safe_float(candidate.get("behaviorQualityScore")))

    weighted_score = (
        0.22 * robust
        + 0.16 * category
        + 0.12 * recent
        + 0.08 * market_diversity
        + 0.09 * useful_accumulation
        + 0.09 * reduction_quality
        + 0.14 * copyability_score
        + 0.08 * low_hedge
        + 0.04 * behavior_quality
        + priority_boost
    )
    weighted_score -= concentration_penalty + insufficient_sample_penalty + category_concentration_penalty + stale_penalty + hedge_penalty * 0.25

    candidate["robustSkillScore"] = round(robust, 2)
    candidate["categorySkillScore"] = round(category, 2)
    candidate["recentActivityStatus"] = recent_status
    candidate["recentActivityScore"] = round(recent, 2)
    candidate["marketDiversityScore"] = round(market_diversity, 2)
    candidate["usefulAccumulationScore"] = round(useful_accumulation, 2)
    candidate["reductionSignalQualityScore"] = round(reduction_quality, 2)
    candidate["copyabilityScore"] = round(copyability_score, 2)
    candidate["lowHedgeScore"] = round(low_hedge, 2)
    candidate["hedgePenalty"] = round(hedge_penalty, 2)
    candidate["concentrationPenalty"] = round(concentration_penalty, 2)
    candidate["staleActivityPenalty"] = round(stale_penalty, 2)
    candidate["insufficientSamplePenalty"] = round(insufficient_sample_penalty, 2)
    candidate["categoryConcentrationPenalty"] = round(category_concentration_penalty, 2)
    candidate["signalWalletRosterScore"] = round(_clamp(weighted_score), 2)

    if candidate.get("latestGeneratedAt"):
        candidate["latestGeneratedAt"] = to_utc_datetime(candidate["latestGeneratedAt"]).isoformat() if to_utc_datetime(candidate["latestGeneratedAt"]) else candidate["latestGeneratedAt"]
    candidate["primaryCategory"] = candidate.get("dominantKnownCategory") or _first_from_collection(candidate.get("profiles")) or "mixed"
    candidate["reason"] = _build_reason(candidate)
    candidate["scoreBreakdown"] = {
        "robustSkillScore": candidate["robustSkillScore"],
        "categorySkillScore": candidate["categorySkillScore"],
        "recentActivityStatus": candidate["recentActivityStatus"],
        "recentActivityScore": candidate["recentActivityScore"],
        "marketDiversityScore": candidate["marketDiversityScore"],
        "usefulAccumulationScore": candidate["usefulAccumulationScore"],
        "reductionSignalQualityScore": candidate["reductionSignalQualityScore"],
        "copyabilityScore": candidate["copyabilityScore"],
        "lowHedgeScore": candidate["lowHedgeScore"],
        "hedgePenalty": candidate["hedgePenalty"],
        "concentrationPenalty": candidate["concentrationPenalty"],
        "staleActivityPenalty": candidate["staleActivityPenalty"],
        "insufficientSamplePenalty": candidate["insufficientSamplePenalty"],
        "categoryConcentrationPenalty": candidate["categoryConcentrationPenalty"],
    }


def _prepare_candidates(
    *,
    benchmark_wallet: str,
    target_roster_size: int,
    priority_wallets: str | list[str] | None,
    wallet_scores: list[dict[str, Any]] | None,
    shadow_rows: list[dict[str, Any]] | None,
    output_dir: str | os.PathLike[str] | None,
) -> dict[str, Any]:
    sources = load_adaptive_signal_roster_sources(output_dir)
    benchmark_wallet = _normalize_wallet(benchmark_wallet)
    priority_wallet_set = {_normalize_wallet(wallet) for wallet, _alias in parse_wallet_specifiers(priority_wallets)}
    priority_wallet_set.discard("")

    candidates: dict[str, dict[str, Any]] = {}

    def include(wallet: Any) -> dict[str, Any] | None:
        normalized = _normalize_wallet(wallet)
        if not normalized:
            return None
        return _ensure_candidate(candidates, normalized)

    for score in wallet_scores or []:
        wallet = _normalize_wallet(score.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_wallet_score(candidate, score)

    for row in sources["wallet_shadow_rankings"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_general_ranking(candidate, row)

    for row in shadow_rows or []:
        wallet = _normalize_wallet(row.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_shadow_row(candidate, row)

    for row in sources["wallet_shadow_history"] or []:
        wallet = _normalize_wallet(row.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_shadow_row(candidate, row)

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
                candidate["categoryCount"] = max(candidate.get("categoryCount") or 0, 1)
                candidate["closedPositionsCount"] = max(candidate.get("closedPositionsCount") or 0, int(row.get("closedPositionsCount") or 0))
                _merge_non_empty(candidate, "categorySkillStatus", row.get("categorySkillStatus"))
                current_score = _safe_float(candidate.get("categorySkillScore"), default=0.0)
                category_score = _safe_float(row.get("categorySkillScore"), default=0.0)
                if category_score >= current_score:
                    candidate["categorySkillScore"] = category_score
                    candidate["dominantKnownCategory"] = category
                    _merge_non_empty(candidate, "primaryCategory", category)

    _merge_copyability_summary_map = sources["wallet_copyability_summary"] or {}
    if isinstance(_merge_copyability_summary_map, dict):
        for wallet in list(_merge_copyability_summary_map.keys()):
            candidate = include(wallet)
            if candidate is None:
                continue
            _merge_copyability_summary(candidate, _merge_copyability_summary_map)

    wallet_quality_rows = sources.get("wallet_quality") or []
    quality_rows_by_wallet: dict[str, dict[str, Any]] = {}
    for row in wallet_quality_rows or []:
        wallet = _normalize_wallet(row.get("wallet"))
        if not wallet or wallet in quality_rows_by_wallet:
            continue
        quality_rows_by_wallet[wallet] = row
    print(f"SMART_MONEY_WALLET_ROSTER_QUALITY_FEEDBACK_LOADED rows={len(quality_rows_by_wallet)}")
    for wallet, row in quality_rows_by_wallet.items():
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_quality_feedback(candidate, row)
        print(
            "SMART_MONEY_WALLET_ROSTER_QUALITY_PENALTY "
            f"wallet={wallet} "
            f"recommendation={candidate.get('previousQualityRecommendation') or 'unknown'} "
            f"penalty={candidate.get('qualityPenaltyApplied')}"
        )

    trade_copyability_shadow = sources["trade_copyability_shadow"] or {}
    if isinstance(trade_copyability_shadow, dict):
        for wallet in list({*_merge_copyability_summary_map.keys(), *[row.get("wallet") for row in trade_copyability_shadow.get("walletResults") or []]}):
            if not wallet:
                continue
            candidate = include(wallet)
            if candidate is None:
                continue
            _merge_copyability_shadow(candidate, trade_copyability_shadow)

    candidate_pool = sources.get("candidate_pool") or {}
    candidate_pool_rows = []
    candidate_pool_source_status = "missing"
    if isinstance(candidate_pool, dict):
        candidate_pool_rows = list(candidate_pool.get("candidates") or [])
        candidate_pool_source_status = str(candidate_pool.get("sourceStatus") or "ok")
    print(f"SMART_MONEY_WALLET_ROSTER_DISCOVERY_V2_LOADED candidates={len(candidate_pool_rows)}")
    for row in candidate_pool_rows:
        wallet = _normalize_wallet(row.get("wallet"))
        if not wallet:
            continue
        candidate = include(wallet)
        if candidate is None:
            continue
        _merge_candidate_pool(candidate, row)
        print(
            "SMART_MONEY_WALLET_ROSTER_DISCOVERY_V2_USED "
            f"wallet={wallet} "
            f"score={row.get('candidateQualityScore')} "
            f"recommendation={row.get('candidateRecommendation')}"
        )

    comparison_summary = sources["wallet_comparison_summary"] or {}
    if isinstance(comparison_summary, dict):
        for wallet in list(candidates.keys()):
            _merge_comparison_summary(candidates[wallet], comparison_summary)

    for wallet in list(candidates.keys()):
        _latest_wallet_seen_at(candidates[wallet], sources["wallet_shadow_history"] or [])
        if wallet in priority_wallet_set:
            candidates[wallet]["priority"] = True
            candidates[wallet]["sources"].add("priority_wallets")

    if benchmark_wallet:
        benchmark_candidate = include(benchmark_wallet)
        if benchmark_candidate is not None:
            benchmark_candidate["benchmark"] = True
            benchmark_candidate["priority"] = True
            benchmark_candidate["signalWalletRosterScore"] = 100.0
            benchmark_candidate["reason"] = "benchmark wallet"
            benchmark_candidate["primaryCategory"] = benchmark_candidate.get("dominantKnownCategory") or _first_from_collection(benchmark_candidate.get("profiles")) or "mixed"
            benchmark_candidate["recentActivityStatus"] = benchmark_candidate.get("recentActivityStatus") or "recent"
            benchmark_candidate["probationaryCandidate"] = False
            benchmark_candidate["selectionReason"] = "benchmark wallet"
            benchmark_candidate["scoreBreakdown"] = {
                "robustSkillScore": _safe_float(benchmark_candidate.get("robustSkillScore")),
                "categorySkillScore": _safe_float(benchmark_candidate.get("categorySkillScore")),
                "recentActivityStatus": benchmark_candidate.get("recentActivityStatus"),
                "recentActivityScore": _safe_float(benchmark_candidate.get("recentActivityScore")),
                "marketDiversityScore": _safe_float(benchmark_candidate.get("marketDiversityScore")),
                "usefulAccumulationScore": _safe_float(benchmark_candidate.get("usefulAccumulationScore")),
                "reductionSignalQualityScore": _safe_float(benchmark_candidate.get("reductionSignalQualityScore")),
                "copyabilityScore": _safe_float(benchmark_candidate.get("copyabilityScore")),
                "lowHedgeScore": _safe_float(benchmark_candidate.get("lowHedgeScore")),
                "hedgePenalty": _safe_float(benchmark_candidate.get("hedgePenalty")),
                "concentrationPenalty": _safe_float(benchmark_candidate.get("concentrationPenalty")),
                "staleActivityPenalty": _safe_float(benchmark_candidate.get("staleActivityPenalty")),
                "insufficientSamplePenalty": _safe_float(benchmark_candidate.get("insufficientSamplePenalty")),
                "categoryConcentrationPenalty": _safe_float(benchmark_candidate.get("categoryConcentrationPenalty")),
            }

    for candidate in candidates.values():
        if candidate.get("benchmark"):
            continue
        _score_candidate(candidate)
        discovery_bonus = _safe_float(candidate.get("discoveryV2CandidateQualityScore")) * 0.12
        if str(candidate.get("discoveryV2CandidateRecommendation") or "") == "STRONG_CANDIDATE":
            discovery_bonus += 6.0
        elif str(candidate.get("discoveryV2CandidateRecommendation") or "") == "CANDIDATE":
            discovery_bonus += 4.0
        elif str(candidate.get("discoveryV2CandidateRecommendation") or "") == "WATCHLIST_CANDIDATE":
            discovery_bonus += 2.0
        elif str(candidate.get("discoveryV2CandidateRecommendation") or "") == "WEAK_CANDIDATE":
            discovery_bonus += 0.5
        if discovery_bonus:
            candidate["signalWalletRosterScore"] = round(_clamp(_safe_float(candidate.get("signalWalletRosterScore")) + discovery_bonus), 2)
            candidate["scoreBreakdown"]["discoveryV2Bonus"] = round(discovery_bonus, 2)
        quality_penalty = _safe_float(candidate.get("qualityPenaltyApplied"))
        if quality_penalty:
            candidate["signalWalletRosterScore"] = round(_clamp(_safe_float(candidate.get("signalWalletRosterScore")) - quality_penalty), 2)
            candidate["scoreBreakdown"]["qualityPenaltyApplied"] = round(quality_penalty, 2)
        hard_reject_reason = _validate_candidate(candidate)
        candidate["hardRejectReason"] = hard_reject_reason

    print(f"SMART_MONEY_WALLET_ROSTER_DISCOVERY_STARTED benchmark={benchmark_wallet}")
    print(f"SMART_MONEY_WALLET_ROSTER_CANDIDATES_FOUND count={len(candidates)}")

    return {
        "benchmarkWallet": benchmark_wallet,
        "targetRosterSize": target_roster_size,
        "candidates": candidates,
        "candidatePool": candidate_pool_rows,
        "candidatePoolSourceStatus": candidate_pool_source_status,
    }


async def _prefetch_fallback_activity(
    candidates: list[dict[str, Any]],
    *,
    copyability_seed_trades: list[dict[str, Any]] | None,
    output_dir: str | os.PathLike[str] | None,
) -> dict[str, dict[str, Any]]:
    del output_dir
    profiles: dict[str, dict[str, Any]] = {}
    seed_trade_map: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for trade in copyability_seed_trades or []:
        wallet = _normalize_wallet(trade.get("wallet"))
        if wallet:
            seed_trade_map[wallet].append(trade)
    if not candidates:
        return profiles
    print(f"SMART_MONEY_WALLET_ROSTER_PREFLIGHT_STARTED candidates={len(candidates)}")
    for candidate in candidates:
        wallet = _normalize_wallet(candidate.get("wallet"))
        if not wallet or wallet in profiles:
            continue
        prior_score = _safe_float(candidate.get("signalWalletRosterScore"))
        if wallet in seed_trade_map and seed_trade_map[wallet]:
            trades = list(seed_trade_map[wallet])
            fetch_result = {
                "wallet": wallet,
                "status": "completed",
                "reason": "seed_cache_hit",
                "rawTrades": len(trades),
                "normalizedTrades": len(trades),
                "trades": trades,
                "error": None,
                "fetchSource": "copyability_seed_trades",
            }
        else:
            fetch_result = await _call_fetch_copyability_trades_for_wallet(
                wallet,
                COPYABILITY_MAX_TRADES_PER_WALLET,
                COPYABILITY_LOOKBACK_HOURS,
                return_details=True,
            )
            trades = list((fetch_result or {}).get("trades") or [])
        profile = _build_preflight_profile(trades, prior_score)
        profile["wallet"] = wallet
        profile["fetchStatus"] = str((fetch_result or {}).get("status") or "completed")
        profile["fetchReason"] = str((fetch_result or {}).get("reason") or "no_valid_trades")
        profile["fetchError"] = (fetch_result or {}).get("error")
        profile["preflightSource"] = str((fetch_result or {}).get("fetchSource") or ("copyability_seed_trades" if wallet in seed_trade_map and seed_trade_map[wallet] else "copyability_api_fetch"))
        print(
            "SMART_MONEY_WALLET_ROSTER_PREFLIGHT_SOURCE "
            f"source={profile['preflightSource']} "
            f"wallet={wallet}"
        )
        print(
            "SMART_MONEY_WALLET_ROSTER_PREFLIGHT_COPYABILITY_PARITY "
            f"wallet={wallet} "
            f"preflightRaw={profile['recentRawTrades']} "
            f"copyabilityRawEstimate={int((fetch_result or {}).get('rawTrades') or len(trades))}"
        )
        profile["livePreflightRejected"] = (
            profile["fetchStatus"] == "failed"
            or profile["clusterViabilityScore"] <= 0
            or profile["uniqueMarketsCount"] < 2
            or profile["sportsOnlyPenalty"] >= 20
            or profile["microBetPenalty"] >= 20
            or profile["exactScorePropPenalty"] >= 18
        )
        profiles[wallet] = profile
        print(
            "SMART_MONEY_WALLET_ROSTER_PREFLIGHT_WALLET "
            f"wallet={wallet} "
            f"rawTrades={profile['recentRawTrades']} "
            f"uniqueMarkets={profile['uniqueMarketsCount']} "
            f"totalUsdc={profile['totalRecentUsdc']} "
            f"clusterViability={profile['clusterViabilityScore']} "
            f"penalties=sports:{profile['sportsOnlyPenalty']},micro:{profile['microBetPenalty']},exact:{profile['exactScorePropPenalty']},insufficient:{profile['insufficientRecentTradesPenalty']},no_cluster:{profile['noClusterViabilityPenalty']}"
        )
        if profile["livePreflightRejected"]:
            print(f"SMART_MONEY_WALLET_ROSTER_PREFLIGHT_REJECTED wallet={wallet} reason=not_cluster_viable")
    return profiles


def _apply_preflight_profile(candidate: dict[str, Any], profile: dict[str, Any], *, diagnostic: bool = False) -> None:
    candidate["recentRawTrades"] = profile["recentRawTrades"]
    candidate["recentNormalizedTrades"] = profile["recentNormalizedTrades"]
    candidate["estimatedTradeCount"] = profile["estimatedTradeCount"]
    candidate["totalRecentUsdc"] = profile["totalRecentUsdc"]
    candidate["uniqueMarketsCount"] = profile["uniqueMarketsCount"]
    candidate["categoryHints"] = profile["categoryHints"]
    candidate["sportsOnlyPenalty"] = profile["sportsOnlyPenalty"]
    candidate["microBetPenalty"] = profile["microBetPenalty"]
    candidate["exactScorePropPenalty"] = profile["exactScorePropPenalty"]
    candidate["noClusterViabilityPenalty"] = profile["noClusterViabilityPenalty"]
    candidate["insufficientRecentTradesPenalty"] = profile["insufficientRecentTradesPenalty"]
    candidate["clusterViabilityScore"] = profile["clusterViabilityScore"]
    candidate["livePreflightRejected"] = profile.get("livePreflightRejected")
    if diagnostic:
        candidate["diagnosticPreflightAnalyzed"] = True


async def _diagnostic_prefetch_rejected_activity(
    candidates: list[dict[str, Any]],
    *,
    top_n: int,
) -> dict[str, dict[str, Any]]:
    if top_n <= 0 or not candidates:
        return {}
    print(f"SMART_MONEY_WALLET_ROSTER_DIAGNOSTIC_PREFLIGHT_STARTED topN={top_n}")
    profiles: dict[str, dict[str, Any]] = {}
    analyzed = 0
    for candidate in candidates[:top_n]:
        wallet = _normalize_wallet(candidate.get("wallet"))
        if not wallet or wallet in profiles:
            continue
        fetch_result = await _call_fetch_copyability_trades_for_wallet(
            wallet,
            COPYABILITY_MAX_TRADES_PER_WALLET,
            COPYABILITY_LOOKBACK_HOURS,
            return_details=True,
        )
        trades = list((fetch_result or {}).get("trades") or [])
        profile = _build_preflight_profile(trades, _safe_float(candidate.get("signalWalletRosterScore")))
        profile["wallet"] = wallet
        profile["fetchStatus"] = str((fetch_result or {}).get("status") or "completed")
        profile["fetchReason"] = str((fetch_result or {}).get("reason") or "no_valid_trades")
        profile["fetchError"] = (fetch_result or {}).get("error")
        profile["preflightSource"] = "diagnostic_copyability_api_fetch"
        profiles[wallet] = profile
        analyzed += 1
        print(
            "SMART_MONEY_WALLET_ROSTER_DIAGNOSTIC_PREFLIGHT_WALLET "
            f"wallet={wallet} "
            f"raw={profile['recentRawTrades']} "
            f"normalized={profile['recentNormalizedTrades']} "
            f"markets={profile['uniqueMarketsCount']} "
            f"viability={profile['clusterViabilityScore']}"
        )
    print(f"SMART_MONEY_WALLET_ROSTER_DIAGNOSTIC_PREFLIGHT_COMPLETED analyzed={analyzed}")
    return profiles


async def _build_adaptive_signal_wallet_roster_async(
    *,
    benchmark_wallet: str,
    target_roster_size: int = 6,
    priority_wallets: str | list[str] | None = None,
    wallet_scores: list[dict[str, Any]] | None = None,
    shadow_rows: list[dict[str, Any]] | None = None,
    copyability_seed_trades: list[dict[str, Any]] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    prepared = _prepare_candidates(
        benchmark_wallet=benchmark_wallet,
        target_roster_size=target_roster_size,
        priority_wallets=priority_wallets,
        wallet_scores=wallet_scores,
        shadow_rows=shadow_rows,
        output_dir=output_dir,
    )

    candidates = prepared["candidates"]
    benchmark_wallet = prepared["benchmarkWallet"]
    target_roster_size = int(prepared["targetRosterSize"] or 0)
    candidate_pool_rows = list(prepared.get("candidatePool") or [])
    candidate_pool_source_status = str(prepared.get("candidatePoolSourceStatus") or "missing")

    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    benchmark_candidate = candidates.get(benchmark_wallet)
    if benchmark_candidate is None:
        benchmark_candidate = {
            "wallet": benchmark_wallet,
            "displayName": benchmark_wallet,
            "primaryCategory": "mixed",
            "signalWalletRosterScore": 100.0,
            "reason": "benchmark wallet",
            "benchmark": True,
            "priority": True,
            "scoreBreakdown": {
                "robustSkillScore": 0.0,
                "categorySkillScore": 0.0,
                "recentActivityScore": 0.0,
                "marketDiversityScore": 0.0,
                "usefulAccumulationScore": 0.0,
                "reductionSignalQualityScore": 0.0,
                "copyabilityScore": 0.0,
                "lowHedgeScore": 0.0,
                "concentrationPenalty": 0.0,
                "staleActivityPenalty": 0.0,
                "insufficientSamplePenalty": 0.0,
                "categoryConcentrationPenalty": 0.0,
            },
        }
        candidates[benchmark_wallet] = benchmark_candidate

    benchmark_candidate["isBenchmark"] = True
    benchmark_candidate["probationaryCandidate"] = False
    selected.append(benchmark_candidate)
    selected_categories = {str(benchmark_candidate.get("primaryCategory") or "mixed")}

    remaining_candidates = [
        candidate
        for wallet, candidate in candidates.items()
        if wallet != benchmark_wallet and not candidate.get("hardRejectReason")
    ]
    remaining_candidates.sort(
        key=lambda item: (
            _safe_float(item.get("signalWalletRosterScore")),
            _safe_float(item.get("robustSkillScore")),
            _safe_float(item.get("categorySkillScore")),
            _safe_float(item.get("recentActivityScore")),
            _safe_float(item.get("copyabilityScore")),
            _safe_float(item.get("lowHedgeScore")),
            _safe_float(item.get("marketDiversityScore")),
        ),
        reverse=True,
    )

    min_qualifying_score = 35.0
    replacement_candidates = [
        candidate
        for candidate in remaining_candidates
        if str(candidate.get("previousQualityRecommendation") or "") == "REPLACE_CANDIDATE"
    ]
    preferred_candidates = [candidate for candidate in remaining_candidates if candidate not in replacement_candidates]
    for candidate in replacement_candidates:
        print(f"SMART_MONEY_WALLET_ROSTER_REPLACE_CANDIDATE_SKIPPED wallet={candidate['wallet']}")

    def _select_from_pool(pool: list[dict[str, Any]], *, reuse_replacement: bool = False) -> bool:
        made_selection = False
        while pool and len(selected) < target_roster_size:
            best_index = 0
            best_effective = -10_000.0
            for index, candidate in enumerate(pool):
                category = str(candidate.get("primaryCategory") or "mixed")
                novelty_bonus = 8.0 if category not in selected_categories else 0.0
                priority_bonus = 6.0 if candidate.get("priority") else 0.0
                quality_bonus = 0.0
                if _safe_float(candidate.get("previousActionableSignalScore"), default=100.0) < 50:
                    quality_bonus -= 4.0
                if _safe_float(candidate.get("previousRoutineClusterRate"), default=0.0) >= 0.45:
                    quality_bonus -= 3.0
                if _safe_float(candidate.get("previousMicroMarketClusterRate"), default=0.0) >= 0.25:
                    quality_bonus -= 3.0
                effective_score = _safe_float(candidate.get("signalWalletRosterScore")) + novelty_bonus + priority_bonus + quality_bonus
                if effective_score > best_effective:
                    best_effective = effective_score
                    best_index = index
            chosen = pool.pop(best_index)
            chosen["rank"] = len(selected) + 1
            chosen["isBenchmark"] = False
            chosen["probationaryCandidate"] = bool(chosen.get("recentActivityStatus") != "recent")
            if reuse_replacement:
                chosen["probationaryCandidate"] = True
                chosen["selectionReason"] = "fallback reused despite previous REPLACE_CANDIDATE"
            else:
                chosen["selectionReason"] = chosen.get("reason") or _build_reason(chosen)
            selected.append(chosen)
            selected_categories.add(str(chosen.get("primaryCategory") or "mixed"))
            made_selection = True
        return made_selection

    preferred_pool = [
        candidate
        for candidate in preferred_candidates
        if _safe_float(candidate.get("signalWalletRosterScore")) >= min_qualifying_score
    ]
    _select_from_pool(preferred_pool)

    selected_before_fallback = len(selected)
    selected_wallets = {row["wallet"] for row in selected}
    preflight_candidates = [
        candidate
        for candidate in preferred_candidates
        if candidate["wallet"] not in selected_wallets and candidate not in preferred_pool
    ]
    preflight_profiles = await _prefetch_fallback_activity(
        preflight_candidates,
        copyability_seed_trades=copyability_seed_trades,
        output_dir=output_dir,
    )
    fallback_pool: list[dict[str, Any]] = []
    for candidate in preflight_candidates:
        wallet = candidate["wallet"]
        profile = preflight_profiles.get(wallet)
        if not profile:
            continue
        candidate["recentRawTrades"] = profile["recentRawTrades"]
        candidate["recentNormalizedTrades"] = profile["recentNormalizedTrades"]
        candidate["estimatedTradeCount"] = profile["estimatedTradeCount"]
        candidate["totalRecentUsdc"] = profile["totalRecentUsdc"]
        candidate["uniqueMarketsCount"] = profile["uniqueMarketsCount"]
        candidate["categoryHints"] = profile["categoryHints"]
        candidate["sportsOnlyPenalty"] = profile["sportsOnlyPenalty"]
        candidate["microBetPenalty"] = profile["microBetPenalty"]
        candidate["exactScorePropPenalty"] = profile["exactScorePropPenalty"]
        candidate["noClusterViabilityPenalty"] = profile["noClusterViabilityPenalty"]
        candidate["insufficientRecentTradesPenalty"] = profile["insufficientRecentTradesPenalty"]
        candidate["clusterViabilityScore"] = profile["clusterViabilityScore"]
        candidate["livePreflightRejected"] = profile["livePreflightRejected"]
        prior_score = _safe_float(candidate.get("signalWalletRosterScore"))
        live_bonus = (
            min(candidate["recentRawTrades"], 30) * 1.1
            + min(candidate["recentNormalizedTrades"], 30) * 0.8
            + min(candidate["uniqueMarketsCount"], 10) * 5.0
            + min(candidate["totalRecentUsdc"] / 150.0, 20.0)
            + min(candidate["clusterViabilityScore"], 100.0) * 0.6
        )
        live_penalty = (
            candidate["sportsOnlyPenalty"]
            + candidate["microBetPenalty"]
            + candidate["exactScorePropPenalty"]
            + candidate["noClusterViabilityPenalty"]
            + candidate["insufficientRecentTradesPenalty"]
        )
        candidate["signalWalletRosterScore"] = round(_clamp(prior_score + live_bonus - live_penalty), 2)
        if not candidate["livePreflightRejected"] and candidate["clusterViabilityScore"] > 0 and candidate["signalWalletRosterScore"] >= 25:
            fallback_pool.append(candidate)
    fallback_pool.sort(
        key=lambda item: (
            _safe_float(item.get("clusterViabilityScore")),
            _safe_float(item.get("signalWalletRosterScore")),
            _safe_float(item.get("recentRawTrades")),
            _safe_float(item.get("totalRecentUsdc")),
            _safe_float(item.get("uniqueMarketsCount")),
        ),
        reverse=True,
    )
    fallback_used = False
    if fallback_pool and len(selected) < target_roster_size:
        fallback_used = _select_from_pool(fallback_pool)

    replacement_pool = [
        candidate
        for candidate in replacement_candidates
        if candidate["wallet"] not in {row["wallet"] for row in selected}
    ]
    replacement_pool.sort(
        key=lambda item: (
            _safe_float(item.get("clusterViabilityScore")),
            _safe_float(item.get("signalWalletRosterScore")),
            _safe_float(item.get("recentRawTrades")),
            _safe_float(item.get("totalRecentUsdc")),
            _safe_float(item.get("uniqueMarketsCount")),
        ),
        reverse=True,
    )
    if replacement_pool and len(selected) < target_roster_size:
        fallback_used = _select_from_pool(replacement_pool, reuse_replacement=True) or fallback_used

    if fallback_used:
        print(
            "SMART_MONEY_WALLET_ROSTER_FALLBACK_USED "
            f"selected_before={selected_before_fallback} "
            f"selected_after={len(selected)} "
            f"target={target_roster_size}"
        )

    if len(selected) < target_roster_size and not fallback_pool:
        print(
            "SMART_MONEY_WALLET_ROSTER_INSUFFICIENT_LIVE_QUALITY "
            f"selected={len(selected)} "
            f"target={target_roster_size} "
            f"reason=no cluster-viable candidates"
        )

    if len(selected) < target_roster_size:
        remaining_reason = "insufficient qualifying wallets after scoring"
        print(
            "SMART_MONEY_WALLET_ROSTER_INSUFFICIENT_CANDIDATES "
            f"selected={len(selected)} "
            f"target={target_roster_size} "
            f"reason={remaining_reason}"
        )

    for index, wallet_row in enumerate(selected, start=1):
        wallet_row["rank"] = index
        wallet_row["signalWalletRosterScore"] = round(_safe_float(wallet_row.get("signalWalletRosterScore")), 2)
        wallet_row["scoreBreakdown"] = sanitize_payload(wallet_row.get("scoreBreakdown") or {})
        wallet_row["reason"] = wallet_row.get("reason") or _build_reason(wallet_row)
        wallet_row["selectionReason"] = wallet_row.get("selectionReason") or wallet_row["reason"]
        wallet_row["probationaryCandidate"] = bool(wallet_row.get("probationaryCandidate"))

    selected_wallet_rows: list[dict[str, Any]] = []
    exploration_wallet_rows: list[dict[str, Any]] = []
    for wallet_row in selected:
        is_exploration = (
            str(wallet_row.get("previousQualityRecommendation") or "") == "REPLACE_CANDIDATE"
            or str(wallet_row.get("selectionReason") or "") == "fallback reused despite previous REPLACE_CANDIDATE"
        )
        if wallet_row.get("isBenchmark") or not is_exploration:
            selected_wallet_rows.append(wallet_row)
        else:
            exploration_wallet_rows.append(wallet_row)

    for index, wallet_row in enumerate(selected_wallet_rows, start=1):
        wallet_row["rank"] = index
        print(
            "SMART_MONEY_WALLET_ROSTER_SELECTED_WALLET "
            f"wallet={wallet_row['wallet']} "
            f"rank={index} "
            f"score={wallet_row['signalWalletRosterScore']} "
            f"probationary={'true' if wallet_row['probationaryCandidate'] else 'false'} "
            f"reason={wallet_row['selectionReason']}"
        )

    for index, wallet_row in enumerate(exploration_wallet_rows, start=1):
        print(
            "SMART_MONEY_WALLET_ROSTER_EXPLORATION_WALLET "
            f"wallet={wallet_row['wallet']} "
            f"rank={index} "
            f"score={wallet_row['signalWalletRosterScore']} "
            f"probationary={'true' if wallet_row['probationaryCandidate'] else 'false'} "
            f"reason={wallet_row['selectionReason']}"
        )

    wallets_for_copyability = list(selected[:COPYABILITY_MAX_WALLETS_PER_RUN])
    selected_wallet_set = {row["wallet"] for row in selected}
    rejected_candidates = [
        candidate
        for candidate in candidates.values()
        if candidate["wallet"] not in selected_wallet_set
    ]
    rejected_candidates.sort(
        key=lambda item: (
            _safe_float(item.get("signalWalletRosterScore")),
            _safe_float(item.get("robustSkillScore")),
            _safe_float(item.get("categorySkillScore")),
            _safe_float(item.get("recentActivityScore")),
            _safe_float(item.get("copyabilityScore")),
            _safe_float(item.get("lowHedgeScore")),
            _safe_float(item.get("marketDiversityScore")),
        ),
        reverse=True,
    )
    diagnostic_profiles = await _diagnostic_prefetch_rejected_activity(
        rejected_candidates,
        top_n=SIGNAL_WALLET_DIAGNOSTIC_PREFLIGHT_TOP_N,
    )
    for wallet, profile in diagnostic_profiles.items():
        candidate = candidates.get(wallet)
        if candidate is None:
            continue
        _apply_preflight_profile(candidate, profile, diagnostic=True)

    for candidate in candidates.values():
        if candidate["wallet"] in selected_wallet_set:
            continue
        rejection_reasons = _collect_rejection_reasons(candidate)
        rejection_breakdown = _build_rejection_breakdown(candidate, rejection_reasons)
        rejection_reason = candidate.get("hardRejectReason") or (rejection_reasons[0] if rejection_reasons else _build_rejection_reason(candidate))
        rejected.append(
            {
                "wallet": candidate["wallet"],
                "primaryCategory": candidate.get("primaryCategory") or "mixed",
                "signalWalletRosterScore": round(_safe_float(candidate.get("signalWalletRosterScore")), 2),
                "rejectionReason": rejection_reason,
                "reason": rejection_reason,
                "rejectionReasons": rejection_reasons,
                "rejectionBreakdown": rejection_breakdown,
                "scoreBreakdown": rejection_breakdown,
                "recentActivityStatus": candidate.get("recentActivityStatus") or "unknown",
                "robustSkillScore": round(_safe_float(candidate.get("robustSkillScore")), 2),
                "categorySkillScore": round(_safe_float(candidate.get("categorySkillScore")), 2),
                "recentActivityScore": round(_safe_float(candidate.get("recentActivityScore")), 2),
                "recentRawTrades": int(candidate.get("recentRawTrades") or 0),
                "recentNormalizedTrades": int(candidate.get("recentNormalizedTrades") or 0),
                "uniqueMarketsCount": int(candidate.get("uniqueMarketsCount") or 0),
                "totalRecentUsdc": round(_safe_float(candidate.get("totalRecentUsdc")), 2),
                "clusterViabilityScore": round(_safe_float(candidate.get("clusterViabilityScore")), 2),
                "previousQualityRecommendation": candidate.get("previousQualityRecommendation"),
                "previousActionableSignalScore": _safe_float(candidate.get("previousActionableSignalScore"), default=0.0) if candidate.get("previousActionableSignalScore") is not None else None,
                "previousRoutineClusterRate": _safe_float(candidate.get("previousRoutineClusterRate"), default=0.0) if candidate.get("previousRoutineClusterRate") is not None else None,
                "previousMicroMarketClusterRate": _safe_float(candidate.get("previousMicroMarketClusterRate"), default=0.0) if candidate.get("previousMicroMarketClusterRate") is not None else None,
                "qualityPenaltyApplied": round(_safe_float(candidate.get("qualityPenaltyApplied")), 2),
                "diagnosticPreflightAnalyzed": bool(candidate.get("diagnosticPreflightAnalyzed")),
                "staleActivityPenalty": round(_safe_float(candidate.get("staleActivityPenalty")), 2),
                "insufficientSamplePenalty": round(_safe_float(candidate.get("insufficientSamplePenalty")), 2),
                "hedgePenalty": round(_safe_float(candidate.get("hedgePenalty")), 2),
                "concentrationPenalty": round(_safe_float(candidate.get("concentrationPenalty")), 2),
            }
        )

    selected_count = len(selected_wallet_rows)
    exploration_count = len(exploration_wallet_rows)
    wallets_for_copyability_count = len(wallets_for_copyability)
    needs_more_discovery = selected_count < target_roster_size
    discovery_v2_used_wallets = {
        row["wallet"]
        for row in selected_wallet_rows + exploration_wallet_rows
        if row.get("discoveryV2CandidateRecommendation")
    }
    print(f"SMART_MONEY_WALLET_ROSTER_SELECTED_VALID count={selected_count}")
    print(f"SMART_MONEY_WALLET_ROSTER_EXPLORATION_SELECTED count={exploration_count}")
    print(f"SMART_MONEY_WALLET_ROSTER_COPYABILITY_WALLETS count={wallets_for_copyability_count}")
    print(f"SMART_MONEY_WALLET_ROSTER_SELECTED count={selected_count}")
    if needs_more_discovery:
        print("SMART_MONEY_WALLET_ROSTER_NEEDS_MORE_DISCOVERY reason=insufficient_quality_candidates")
    for row in rejected:
        print(f"SMART_MONEY_WALLET_ROSTER_REJECTED wallet={row['wallet']} reason={row['reason']}")

    rejected_reason_summary: dict[str, int] = {}
    for row in rejected:
        reasons = list(dict.fromkeys(row.get("rejectionReasons") or [row.get("rejectionReason") or "low_actionable_score"]))
        for reason in reasons:
            rejected_reason_summary[reason] = rejected_reason_summary.get(reason, 0) + 1
    for reason, count in sorted(rejected_reason_summary.items(), key=lambda item: (-item[1], item[0])):
        print(f"SMART_MONEY_WALLET_ROSTER_REJECTION_SUMMARY reason={reason} count={count}")

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "benchmarkWallet": benchmark_wallet,
        "targetRosterSize": target_roster_size,
        "candidatesFound": len(candidates),
        "selectedCount": selected_count,
        "explorationCount": exploration_count,
        "walletsForCopyabilityCount": wallets_for_copyability_count,
        "discoveryV2Enabled": SIGNAL_WALLET_DISCOVERY_V2_ENABLED,
        "discoveryV2CandidateCount": len(candidate_pool_rows),
        "discoveryV2CandidatesUsed": len(discovery_v2_used_wallets),
        "discoveryV2StrongCandidates": sum(1 for row in candidate_pool_rows if str(row.get("candidateRecommendation") or "") == "STRONG_CANDIDATE"),
        "discoveryV2SourceStatus": candidate_pool_source_status,
        "diagnosticCandidatesAnalyzed": len(diagnostic_profiles),
        "diagnosticPreflightTopN": SIGNAL_WALLET_DIAGNOSTIC_PREFLIGHT_TOP_N,
        "needsMoreDiscovery": needs_more_discovery,
        "needsMoreDiscoveryReason": "insufficient quality candidates" if needs_more_discovery else None,
        "rejectedReasonSummary": rejected_reason_summary,
        "selectedWallets": [
            {
                "wallet": row["wallet"],
                "rank": row["rank"],
                "isBenchmark": bool(row.get("isBenchmark")),
                "probationaryCandidate": bool(row.get("probationaryCandidate")),
                "signalWalletRosterScore": row["signalWalletRosterScore"],
                "primaryCategory": row.get("primaryCategory") or "mixed",
                "recentActivityStatus": row.get("recentActivityStatus") or "unknown",
                "recentRawTrades": int(row.get("recentRawTrades") or 0),
                "recentNormalizedTrades": int(row.get("recentNormalizedTrades") or 0),
                "estimatedTradeCount": int(row.get("estimatedTradeCount") or 0),
                "uniqueMarketsCount": int(row.get("uniqueMarketsCount") or 0),
                "totalRecentUsdc": round(_safe_float(row.get("totalRecentUsdc")), 2),
                "clusterViabilityScore": round(_safe_float(row.get("clusterViabilityScore")), 2),
                "sportsOnlyPenalty": round(_safe_float(row.get("sportsOnlyPenalty")), 2),
                "microBetPenalty": round(_safe_float(row.get("microBetPenalty")), 2),
                "exactScorePropPenalty": round(_safe_float(row.get("exactScorePropPenalty")), 2),
                "robustSkillScore": round(_safe_float(row.get("robustSkillScore")), 2),
                "categorySkillScore": round(_safe_float(row.get("categorySkillScore")), 2),
                "recentActivityScore": round(_safe_float(row.get("recentActivityScore")), 2),
                "staleActivityPenalty": round(_safe_float(row.get("staleActivityPenalty")), 2),
                "insufficientSamplePenalty": round(_safe_float(row.get("insufficientSamplePenalty")), 2),
                "hedgePenalty": round(_safe_float(row.get("hedgePenalty")), 2),
                "concentrationPenalty": round(_safe_float(row.get("concentrationPenalty")), 2),
                "previousActionableSignalScore": _safe_float(row.get("previousActionableSignalScore"), default=0.0) if row.get("previousActionableSignalScore") is not None else None,
                "previousQualityRecommendation": row.get("previousQualityRecommendation"),
                "previousRoutineClusterRate": _safe_float(row.get("previousRoutineClusterRate"), default=0.0) if row.get("previousRoutineClusterRate") is not None else None,
                "previousMicroMarketClusterRate": _safe_float(row.get("previousMicroMarketClusterRate"), default=0.0) if row.get("previousMicroMarketClusterRate") is not None else None,
                "qualityPenaltyApplied": round(_safe_float(row.get("qualityPenaltyApplied")), 2),
                "discoveryV2CandidateRecommendation": row.get("discoveryV2CandidateRecommendation"),
                "discoveryV2CandidateQualityScore": _safe_float(row.get("discoveryV2CandidateQualityScore"), default=0.0) if row.get("discoveryV2CandidateQualityScore") is not None else None,
                "discoveryV2DiscoverySources": row.get("discoveryV2DiscoverySources") or [],
                "selectionReason": row.get("selectionReason") or row["reason"],
                "reason": row["reason"],
                "scoreBreakdown": row.get("scoreBreakdown") or {},
            }
            for row in selected_wallet_rows
        ],
        "explorationWallets": [
            {
                "wallet": row["wallet"],
                "rank": index,
                "explorationReason": row.get("selectionReason") or row.get("reason") or "exploration",
                "previousQualityRecommendation": row.get("previousQualityRecommendation"),
                "previousActionableSignalScore": _safe_float(row.get("previousActionableSignalScore"), default=0.0) if row.get("previousActionableSignalScore") is not None else None,
                "previousRoutineClusterRate": _safe_float(row.get("previousRoutineClusterRate"), default=0.0) if row.get("previousRoutineClusterRate") is not None else None,
                "previousMicroMarketClusterRate": _safe_float(row.get("previousMicroMarketClusterRate"), default=0.0) if row.get("previousMicroMarketClusterRate") is not None else None,
                "qualityPenaltyApplied": round(_safe_float(row.get("qualityPenaltyApplied")), 2),
                "probationaryCandidate": bool(row.get("probationaryCandidate")),
                "discoveryV2CandidateRecommendation": row.get("discoveryV2CandidateRecommendation"),
                "discoveryV2CandidateQualityScore": _safe_float(row.get("discoveryV2CandidateQualityScore"), default=0.0) if row.get("discoveryV2CandidateQualityScore") is not None else None,
                "discoveryV2DiscoverySources": row.get("discoveryV2DiscoverySources") or [],
            }
            for index, row in enumerate(exploration_wallet_rows, start=1)
        ],
        "walletsForCopyability": [
            {
                "wallet": row["wallet"],
                "rank": row["rank"],
                "isBenchmark": bool(row.get("isBenchmark")),
                "probationaryCandidate": bool(row.get("probationaryCandidate")),
                "signalWalletRosterScore": row["signalWalletRosterScore"],
                "primaryCategory": row.get("primaryCategory") or "mixed",
                "recentActivityStatus": row.get("recentActivityStatus") or "unknown",
                "selectionReason": row.get("selectionReason") or row["reason"],
                "reason": row["reason"],
                "scoreBreakdown": row.get("scoreBreakdown") or {},
            }
            for row in wallets_for_copyability
        ],
        "rejectedWallets": rejected,
    }
    return payload


def build_adaptive_signal_wallet_roster(
    *,
    benchmark_wallet: str,
    target_roster_size: int = 6,
    priority_wallets: str | list[str] | None = None,
    wallet_scores: list[dict[str, Any]] | None = None,
    shadow_rows: list[dict[str, Any]] | None = None,
    copyability_seed_trades: list[dict[str, Any]] | None = None,
    output_dir: str | os.PathLike[str] | None = None,
) -> dict[str, Any]:
    return asyncio.run(
        _build_adaptive_signal_wallet_roster_async(
            benchmark_wallet=benchmark_wallet,
            target_roster_size=target_roster_size,
            priority_wallets=priority_wallets,
            wallet_scores=wallet_scores,
            shadow_rows=shadow_rows,
            copyability_seed_trades=copyability_seed_trades,
            output_dir=output_dir,
        )
    )


def write_adaptive_signal_wallet_roster(payload: dict[str, Any]) -> Path:
    ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE.with_suffix(ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_payload(payload), handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE)
    print(f"SMART_MONEY_WALLET_ROSTER_WRITTEN path={ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE}")
    return ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE
