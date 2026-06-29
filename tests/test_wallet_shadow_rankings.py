
from workers.smart_money.smart_money_engine.wallet_shadow_rankings import (
    build_wallet_category_rankings,
    build_wallet_comparison_summary,
    build_wallet_general_rankings,
)


def _row(wallet: str, score: int, robust: int, profiles=None, roles=None, category_score=70):
    return {
        "wallet": wallet,
        "displayName": wallet[-4:],
        "roles": roles or [],
        "profiles": profiles or [],
        "classification": "SCALPER",
        "behaviorQualityScore": 66,
        "shadowSkill": {
            "skillScore": score,
            "sampleConfidence": 80,
            "knownCategoryCoverageScore": 63,
            "dominantKnownCategory": "geopolitics",
            "categorySkillScores": {
                "politics": {
                    "closedPositionsCount": 6,
                    "totalRealizedPnl": 12,
                    "roi": 0.12,
                    "winRate": 0.8,
                    "profitFactor": 1.4,
                    "payoffRatio": 1.1,
                    "skillScore": category_score,
                    "skillStatus": "sufficient",
                }
            },
        },
        "shadowMetaEvaluation": {"shadowMetaScore": score - 5},
        "shadowRobustEvaluation": {
            "shadowRobustMetaScore": robust,
            "robustSkillScore": robust,
            "skillScoreWithoutTopWinner": score - 10,
            "pnlConcentrationLevel": "moderate",
        },
        "generatedAt": "2026-06-24T00:00:00+00:00",
        "candidateScore": None,
        "candidateStatus": None,
    }


def test_general_rankings_sort_and_tie_breakers():
    cohort = [
        _row("0x" + "1" * 40, 80, 78, profiles=["sports"], roles=["active"]),
        _row("0x" + "2" * 40, 75, 80, profiles=["sports"], roles=["candidate"]),
    ]
    longitudinal = {
        "0x" + "1" * 40: {"longitudinalComparisonScore": 82, "comparisonConfidence": "sufficient", "runCount": 3, "stabilityScore": 90, "scoreTrend": "rising"},
        "0x" + "2" * 40: {"longitudinalComparisonScore": 82, "comparisonConfidence": "sufficient", "runCount": 3, "stabilityScore": 85, "scoreTrend": "stable"},
    }
    rankings = build_wallet_general_rankings(cohort, longitudinal)

    assert rankings[0]["wallet"] == "0x" + "2" * 40
    assert rankings[0]["rank"] == 1
    assert rankings[1]["rank"] == 2


def test_category_rankings_exclude_unknown_and_rank_low_samples():
    cohort = [
        _row("0x" + "3" * 40, 74, 70, profiles=["sports"], roles=["candidate"], category_score=72),
    ]
    rankings = build_wallet_category_rankings(cohort)

    assert "unknown" not in rankings
    assert rankings["politics"][0]["categoryRankingScore"] >= 0
    assert rankings["politics"][0]["categorySkillStatus"] == "sufficient"


def test_category_rankings_separate_unranked_from_competitive_rows():
    cohort = [
        _row("0x" + "6" * 40, 74, 70, profiles=["sports"], roles=["candidate"], category_score=72),
        _row("0x" + "7" * 40, 71, 69, profiles=["sports"], roles=["candidate"], category_score=68),
    ]
    cohort[0]["shadowSkill"]["categorySkillScores"]["politics"]["closedPositionsCount"] = 6
    cohort[0]["shadowSkill"]["categorySkillScores"]["politics"]["skillStatus"] = "sufficient"
    cohort[1]["shadowSkill"]["categorySkillScores"]["politics"]["closedPositionsCount"] = 4
    cohort[1]["shadowSkill"]["categorySkillScores"]["politics"]["skillStatus"] = "unranked"

    rankings = build_wallet_category_rankings(cohort)
    politics = rankings["politics"]

    eligible = next(row for row in politics if row["wallet"] == "0x" + "6" * 40)
    ineligible = next(row for row in politics if row["wallet"] == "0x" + "7" * 40)

    assert eligible["rankingEligible"] is True
    assert eligible["rank"] == 1
    assert ineligible["rankingEligible"] is False
    assert ineligible["rank"] is None


def test_comparison_summary_requires_profile_overlap_or_replacement_link():
    active = _row("0x" + "4" * 40, 78, 76, profiles=["sports"], roles=["active"])
    candidate = _row("0x" + "5" * 40, 84, 82, profiles=["sports"], roles=["candidate"])
    longitudinal = {
        active["wallet"]: {"longitudinalComparisonScore": 72, "runCount": 3, "comparisonConfidence": "sufficient"},
        candidate["wallet"]: {"longitudinalComparisonScore": 81, "runCount": 3, "comparisonConfidence": "sufficient"},
    }
    summary = build_wallet_comparison_summary([active, candidate], longitudinal)

    assert summary["comparisons"]
    comparison = summary["comparisons"][0]
    assert comparison["comparisonStatus"] in {"candidate_leads", "close_comparison", "active_leads"}
    assert comparison["shadowRecommendation"] in {
        "continue_observation",
        "candidate_outperforming_shadow",
        "active_remains_stronger",
        "too_close_to_call",
    }
