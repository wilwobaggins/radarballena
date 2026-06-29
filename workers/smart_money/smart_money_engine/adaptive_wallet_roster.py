from __future__ import annotations

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
    from .time_utils import to_utc_datetime
    from .wallet_shadow_cohort import parse_wallet_specifiers
except ImportError:  # pragma: no cover
    from copyability_storage import sanitize_payload
    from path_utils import resolve_output_dir
    from time_utils import to_utc_datetime
    from wallet_shadow_cohort import parse_wallet_specifiers


OUTPUT_DIR = resolve_output_dir()
ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE = OUTPUT_DIR / "adaptive_signal_wallet_roster.json"


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


def load_adaptive_signal_roster_sources(output_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    base = Path(output_dir) if output_dir else OUTPUT_DIR
    return {
        "wallet_shadow_rankings": _load_json(base / "wallet_shadow_rankings.json", []),
        "wallet_category_rankings": _load_json(base / "wallet_category_rankings.json", {}),
        "wallet_comparison_summary": _load_json(base / "wallet_comparison_summary.json", {}),
        "wallet_shadow_history": _load_jsonl(base / "wallet_shadow_history.jsonl"),
        "trade_copyability_shadow": _load_json(base / "trade_copyability_shadow.json", {}),
        "wallet_copyability_summary": _load_json(base / "wallet_copyability_summary.json", {}),
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


def _age_score_and_penalty(latest_generated_at: Any) -> tuple[float, float]:
    latest = to_utc_datetime(latest_generated_at)
    if latest is None:
        return 0.0, 18.0
    now = datetime.now(timezone.utc)
    age_days = max(0.0, (now - latest).total_seconds() / 86400.0)
    if age_days <= 7:
        return 100.0, 0.0
    if age_days <= 30:
        return 82.0, 5.0
    if age_days <= 90:
        return 60.0, 12.0
    return 35.0, 22.0


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

    if hedge_rate >= 0.5 or not_copyable >= 5:
        return "high hedge rate"
    if stale_penalty >= 15:
        return "stale activity"
    if insufficient_penalty >= 10:
        return "insufficient sample"
    if concentration_penalty >= 18:
        return "high concentration penalty"
    if _safe_float(candidate.get("copyabilityScore")) < 40:
        return "low copyability"
    return "lower signal score than selected roster"


def _score_candidate(candidate: dict[str, Any]) -> None:
    robust = _clamp(_safe_float(candidate.get("robustSkillScore"), default=_safe_float(candidate.get("walletQualityScore"))))
    category = _clamp(_safe_float(candidate.get("categorySkillScore"), default=0.0))
    recent, stale_penalty = _age_score_and_penalty(candidate.get("latestGeneratedAt"))
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
        insufficient_sample_penalty = 18.0
    elif sample_size < 5:
        insufficient_sample_penalty = 16.0
    elif sample_size < 10:
        insufficient_sample_penalty = 8.0

    category_concentration_penalty = 0.0
    if category_count <= 1 and len(candidate.get("profiles") or []) <= 1 and not candidate.get("benchmark"):
        category_concentration_penalty = 8.0
    coverage = _safe_float(candidate.get("knownCategoryCoverageScore"))
    if coverage and coverage < 45:
        category_concentration_penalty += 6.0

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
    weighted_score -= concentration_penalty + insufficient_sample_penalty + category_concentration_penalty + stale_penalty

    candidate["robustSkillScore"] = round(robust, 2)
    candidate["categorySkillScore"] = round(category, 2)
    candidate["recentActivityScore"] = round(recent, 2)
    candidate["marketDiversityScore"] = round(market_diversity, 2)
    candidate["usefulAccumulationScore"] = round(useful_accumulation, 2)
    candidate["reductionSignalQualityScore"] = round(reduction_quality, 2)
    candidate["copyabilityScore"] = round(copyability_score, 2)
    candidate["lowHedgeScore"] = round(low_hedge, 2)
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
        "recentActivityScore": candidate["recentActivityScore"],
        "marketDiversityScore": candidate["marketDiversityScore"],
        "usefulAccumulationScore": candidate["usefulAccumulationScore"],
        "reductionSignalQualityScore": candidate["reductionSignalQualityScore"],
        "copyabilityScore": candidate["copyabilityScore"],
        "lowHedgeScore": candidate["lowHedgeScore"],
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

    trade_copyability_shadow = sources["trade_copyability_shadow"] or {}
    if isinstance(trade_copyability_shadow, dict):
        for wallet in list({*_merge_copyability_summary_map.keys(), *[row.get("wallet") for row in trade_copyability_shadow.get("walletResults") or []]}):
            if not wallet:
                continue
            candidate = include(wallet)
            if candidate is None:
                continue
            _merge_copyability_shadow(candidate, trade_copyability_shadow)

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
            benchmark_candidate["scoreBreakdown"] = {
                "robustSkillScore": _safe_float(benchmark_candidate.get("robustSkillScore")),
                "categorySkillScore": _safe_float(benchmark_candidate.get("categorySkillScore")),
                "recentActivityScore": _safe_float(benchmark_candidate.get("recentActivityScore")),
                "marketDiversityScore": _safe_float(benchmark_candidate.get("marketDiversityScore")),
                "usefulAccumulationScore": _safe_float(benchmark_candidate.get("usefulAccumulationScore")),
                "reductionSignalQualityScore": _safe_float(benchmark_candidate.get("reductionSignalQualityScore")),
                "copyabilityScore": _safe_float(benchmark_candidate.get("copyabilityScore")),
                "lowHedgeScore": _safe_float(benchmark_candidate.get("lowHedgeScore")),
                "concentrationPenalty": _safe_float(benchmark_candidate.get("concentrationPenalty")),
                "staleActivityPenalty": _safe_float(benchmark_candidate.get("staleActivityPenalty")),
                "insufficientSamplePenalty": _safe_float(benchmark_candidate.get("insufficientSamplePenalty")),
                "categoryConcentrationPenalty": _safe_float(benchmark_candidate.get("categoryConcentrationPenalty")),
            }

    for candidate in candidates.values():
        if candidate.get("benchmark"):
            continue
        _score_candidate(candidate)

    print(f"SMART_MONEY_WALLET_ROSTER_DISCOVERY_STARTED benchmark={benchmark_wallet}")
    print(f"SMART_MONEY_WALLET_ROSTER_CANDIDATES_FOUND count={len(candidates)}")

    return {
        "benchmarkWallet": benchmark_wallet,
        "targetRosterSize": target_roster_size,
        "candidates": candidates,
    }


def build_adaptive_signal_wallet_roster(
    *,
    benchmark_wallet: str,
    target_roster_size: int = 6,
    priority_wallets: str | list[str] | None = None,
    wallet_scores: list[dict[str, Any]] | None = None,
    shadow_rows: list[dict[str, Any]] | None = None,
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
    selected.append(benchmark_candidate)
    selected_categories = {str(benchmark_candidate.get("primaryCategory") or "mixed")}

    remaining_candidates = [
        candidate
        for wallet, candidate in candidates.items()
        if wallet != benchmark_wallet
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
    qualifying_candidates = [candidate for candidate in remaining_candidates if _safe_float(candidate.get("signalWalletRosterScore")) >= min_qualifying_score]

    pool = qualifying_candidates
    while pool and len(selected) < target_roster_size:
        best_index = 0
        best_effective = -10_000.0
        for index, candidate in enumerate(pool):
            category = str(candidate.get("primaryCategory") or "mixed")
            novelty_bonus = 8.0 if category not in selected_categories else 0.0
            priority_bonus = 6.0 if candidate.get("priority") else 0.0
            effective_score = _safe_float(candidate.get("signalWalletRosterScore")) + novelty_bonus + priority_bonus
            if effective_score > best_effective:
                best_effective = effective_score
                best_index = index
        chosen = pool.pop(best_index)
        chosen["rank"] = len(selected) + 1
        chosen["isBenchmark"] = False
        selected.append(chosen)
        selected_categories.add(str(chosen.get("primaryCategory") or "mixed"))

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
        print(
            "SMART_MONEY_WALLET_ROSTER_SELECTED_WALLET "
            f"wallet={wallet_row['wallet']} "
            f"rank={index} "
            f"score={wallet_row['signalWalletRosterScore']} "
            f"reason={wallet_row['reason']}"
        )

    selected_wallet_set = {row["wallet"] for row in selected}
    for candidate in candidates.values():
        if candidate["wallet"] in selected_wallet_set:
            continue
        rejected.append(
            {
                "wallet": candidate["wallet"],
                "primaryCategory": candidate.get("primaryCategory") or "mixed",
                "signalWalletRosterScore": round(_safe_float(candidate.get("signalWalletRosterScore")), 2),
                "reason": _build_rejection_reason(candidate),
            }
        )

    print(f"SMART_MONEY_WALLET_ROSTER_SELECTED count={len(selected)}")
    for row in rejected:
        print(f"SMART_MONEY_WALLET_ROSTER_REJECTED wallet={row['wallet']} reason={row['reason']}")

    payload = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "benchmarkWallet": benchmark_wallet,
        "targetRosterSize": target_roster_size,
        "candidatesFound": len(candidates),
        "selectedWallets": [
            {
                "wallet": row["wallet"],
                "rank": row["rank"],
                "isBenchmark": bool(row.get("isBenchmark")),
                "signalWalletRosterScore": row["signalWalletRosterScore"],
                "primaryCategory": row.get("primaryCategory") or "mixed",
                "reason": row["reason"],
                "scoreBreakdown": row.get("scoreBreakdown") or {},
            }
            for row in selected
        ],
        "rejectedWallets": rejected,
    }
    return payload


def write_adaptive_signal_wallet_roster(payload: dict[str, Any]) -> Path:
    ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE.with_suffix(ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_payload(payload), handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE)
    print(f"SMART_MONEY_WALLET_ROSTER_WRITTEN path={ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE}")
    return ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE
