from __future__ import annotations

import math
from collections import defaultdict
from typing import Any


SKILL_CATEGORIES = (
    "sports",
    "esports",
    "politics",
    "geopolitics",
    "macro",
    "crypto",
    "culture_awards",
    "technology",
)


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    if math.isnan(value) or math.isinf(value):
        return lower
    return max(lower, min(upper, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def _recommendation_for_comparison_score(score: float) -> str:
    if score >= 80:
        return "shadow_leader"
    if score >= 70:
        return "shadow_strong"
    if score >= 60:
        return "shadow_watch"
    return "shadow_low"


def build_wallet_general_rankings(
    cohort_rows: list[dict[str, Any]],
    longitudinal_metrics: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    ranked_rows: list[dict[str, Any]] = []
    for row in cohort_rows:
        wallet = str(row.get("wallet") or "").strip().lower()
        if not wallet:
            continue
        metrics = longitudinal_metrics.get(wallet) or {}
        shadow_skill = row.get("shadowSkill") or {}
        shadow_meta = row.get("shadowMetaEvaluation") or {}
        shadow_robust = row.get("shadowRobustEvaluation") or {}
        score = _safe_float(metrics.get("longitudinalComparisonScore"), _safe_float(shadow_robust.get("shadowRobustMetaScore")))
        ranked_rows.append(
            {
                "wallet": wallet,
                "displayName": row.get("displayName") or wallet,
                "roles": row.get("roles") or [],
                "profiles": row.get("profiles") or [],
                "classification": row.get("classification"),
                "behaviorQualityScore": row.get("behaviorQualityScore"),
                "skillScore": shadow_skill.get("skillScore"),
                "robustSkillScore": shadow_robust.get("robustSkillScore"),
                "shadowMetaScore": shadow_meta.get("shadowMetaScore"),
                "shadowRobustMetaScore": shadow_robust.get("shadowRobustMetaScore"),
                "longitudinalComparisonScore": round(score, 2),
                "comparisonConfidence": metrics.get("comparisonConfidence") or "limited",
                "runCount": metrics.get("runCount", 0),
                "stabilityScore": metrics.get("stabilityScore"),
                "scoreTrend": metrics.get("scoreTrend"),
                "dominantKnownCategory": (shadow_skill or {}).get("dominantKnownCategory"),
                "knownCategoryCoverageScore": (shadow_skill or {}).get("knownCategoryCoverageScore"),
                "pnlConcentrationLevel": (shadow_robust or {}).get("pnlConcentrationLevel"),
                "recommendation": _recommendation_for_comparison_score(score),
                "_sort": (
                    round(score, 2),
                    _safe_float(shadow_robust.get("shadowRobustMetaScore")),
                    _safe_float(shadow_robust.get("robustSkillScore")),
                    _safe_float((shadow_skill or {}).get("sampleConfidence")),
                    _safe_float((shadow_skill or {}).get("knownCategoryCoverageScore")),
                    _safe_float((shadow_skill or {}).get("closedPositionsCount")),
                ),
            }
        )

    ranked_rows.sort(key=lambda item: item["_sort"], reverse=True)
    for index, row in enumerate(ranked_rows, start=1):
        row["rank"] = index
        row.pop("_sort", None)
    return ranked_rows


def build_wallet_category_rankings(cohort_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rankings: dict[str, list[dict[str, Any]]] = {category: [] for category in SKILL_CATEGORIES}

    for row in cohort_rows:
        wallet = str(row.get("wallet") or "").strip().lower()
        shadow_skill = row.get("shadowSkill") or {}
        category_scores = shadow_skill.get("categorySkillScores") or {}
        for category in SKILL_CATEGORIES:
            category_score = category_scores.get(category) or {}
            closed_count = int(category_score.get("closedPositionsCount") or 0)
            if closed_count <= 0:
                continue
            ranking_eligible = closed_count >= 5
            category_status = str(category_score.get("skillStatus") or "sufficient")
            if not ranking_eligible:
                category_status = "unranked"
            sample_confidence = min(100.0, (closed_count / 30.0) * 100.0)
            category_ranking_score = _clamp(
                _safe_float(category_score.get("skillScore"))
                * (0.70 + 0.30 * (sample_confidence / 100.0))
            )
            if category == "unknown":
                continue
            rankings[category].append(
                {
                    "wallet": wallet,
                    "displayName": row.get("displayName") or wallet,
                    "roles": row.get("roles") or [],
                    "profiles": row.get("profiles") or [],
                    "classification": row.get("classification"),
                    "closedPositionsCount": closed_count,
                    "totalRealizedPnl": category_score.get("totalRealizedPnl"),
                    "roi": category_score.get("roi"),
                    "winRate": category_score.get("winRate"),
                    "profitFactor": category_score.get("profitFactor"),
                    "payoffRatio": category_score.get("payoffRatio"),
                    "categorySkillScore": category_score.get("skillScore"),
                    "categorySkillStatus": category_status,
                    "rankingEligible": ranking_eligible,
                    "categorySampleConfidence": round(sample_confidence, 2),
                    "categoryRankingScore": round(category_ranking_score, 2),
                    "_sort": (
                        1 if ranking_eligible else 0,
                        round(category_ranking_score, 2),
                        closed_count,
                        _safe_float(category_score.get("roi")),
                    ),
                }
            )

    for category in list(rankings.keys()):
        rows = rankings[category]
        rows.sort(key=lambda item: item["_sort"], reverse=True)
        eligible_rows = [row for row in rows if row["rankingEligible"]]
        ineligible_rows = [row for row in rows if not row["rankingEligible"]]

        for index, row in enumerate(eligible_rows, start=1):
            row["rank"] = index
            row.pop("_sort", None)

        for row in ineligible_rows:
            row["rank"] = None
            row.pop("_sort", None)

        rows = eligible_rows + ineligible_rows
        rankings[category] = rows

    return rankings


def build_wallet_comparison_summary(
    cohort_rows: list[dict[str, Any]],
    longitudinal_metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    active_wallets = [row for row in cohort_rows if "active" in (row.get("roles") or [])]
    candidate_wallets = [
        row
        for row in cohort_rows
        if "candidate" in (row.get("roles") or []) or "replacement_candidate" in (row.get("roles") or [])
    ]

    comparisons: list[dict[str, Any]] = []

    for active in active_wallets:
        active_wallet = str(active.get("wallet") or "").strip().lower()
        active_metrics = longitudinal_metrics.get(active_wallet) or {}
        active_score = _safe_float(active_metrics.get("longitudinalComparisonScore"))
        active_runs = int(active_metrics.get("runCount") or 0)
        active_profiles = set(active.get("profiles") or [])

        for candidate in candidate_wallets:
            candidate_wallet = str(candidate.get("wallet") or "").strip().lower()
            if candidate_wallet == active_wallet:
                continue
            candidate_metrics = longitudinal_metrics.get(candidate_wallet) or {}
            candidate_score = _safe_float(candidate_metrics.get("longitudinalComparisonScore"))
            candidate_runs = int(candidate_metrics.get("runCount") or 0)
            candidate_profiles = set(candidate.get("profiles") or [])
            shared_profiles = sorted(active_profiles.intersection(candidate_profiles))
            if not shared_profiles and candidate.get("replacementFor") not in {None, active.get("wallet"), active.get("displayName")}:
                continue

            if active_runs < 3 or candidate_runs < 3:
                status = "insufficient_history"
                recommendation = "continue_observation"
            elif candidate_score - active_score >= 5 and candidate_score >= 70 and str((candidate.get("shadowSkill") or {}).get("skillStatus") or "") == "sufficient":
                status = "candidate_leads"
                recommendation = "candidate_outperforming_shadow"
            elif active_score - candidate_score >= 5:
                status = "active_leads"
                recommendation = "active_remains_stronger"
            else:
                status = "close_comparison"
                recommendation = "too_close_to_call"

            comparisons.append(
                {
                    "activeWallet": active_wallet,
                    "candidateWallet": candidate_wallet,
                    "profile": shared_profiles[0] if shared_profiles else (candidate.get("profiles") or [None])[0],
                    "activeScore": round(active_score, 2),
                    "candidateScore": round(candidate_score, 2),
                    "scoreGap": round(candidate_score - active_score, 2),
                    "activeRunCount": active_runs,
                    "candidateRunCount": candidate_runs,
                    "comparisonStatus": status,
                    "shadowRecommendation": recommendation,
                    "reasons": [
                        f"shared_profiles={','.join(shared_profiles)}" if shared_profiles else "no_shared_profile",
                    ],
                }
            )

    sufficient = sum(1 for comparison in comparisons if comparison["comparisonStatus"] != "insufficient_history")
    return {
        "comparisons": comparisons,
        "sufficient": sufficient,
    }
