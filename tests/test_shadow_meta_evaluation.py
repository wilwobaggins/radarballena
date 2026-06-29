from workers.smart_money.smart_money_engine.wallet_skill_score import (
    compute_shadow_meta_evaluation,
    compute_shadow_robust_evaluation,
)


def test_shadow_meta_insufficient_uses_behavior_only():
    meta = compute_shadow_meta_evaluation(
        44,
        {
            "skillStatus": "insufficient",
            "skillScore": 91,
            "sampleConfidence": 100,
            "categoryConsistencyScore": 88,
        },
    )

    assert meta["shadowMetaScore"] == 44
    assert meta["usedSkillScore"] is False
    assert meta["shadowRecommendation"] == "shadow_low"


def test_shadow_meta_limited_uses_conservative_weighting():
    meta = compute_shadow_meta_evaluation(
        40,
        {
            "skillStatus": "limited",
            "skillScore": 80,
            "sampleConfidence": 100,
            "categoryConsistencyScore": 58,
        },
    )

    assert meta["shadowMetaScore"] == 58
    assert meta["usedSkillScore"] is True
    assert meta["shadowRecommendation"] == "shadow_low"


def test_shadow_meta_sufficient_uses_full_weighting():
    meta = compute_shadow_meta_evaluation(
        40,
        {
            "skillStatus": "sufficient",
            "skillScore": 80,
            "sampleConfidence": 100,
            "categoryConsistencyScore": 58,
        },
    )

    assert meta["shadowMetaScore"] == 66
    assert meta["usedSkillScore"] is True
    assert meta["shadowRecommendation"] == "shadow_watch"


def test_shadow_robust_evaluation_weights_and_parallel_output():
    sufficient = compute_shadow_robust_evaluation(
        40,
        {
            "skillStatus": "sufficient",
            "skillScore": 80,
            "robustSkillScore": 80,
            "skillScoreWithoutTopWinner": 72,
            "sampleConfidence": 100,
            "knownCategoryCoverageScore": 31,
            "knownCategoryConsistencyScore": 63,
            "concentrationPenalty": 14,
            "pnlConcentrationLevel": "extreme",
        },
    )
    limited = compute_shadow_robust_evaluation(
        40,
        {
            "skillStatus": "limited",
            "skillScore": 80,
            "robustSkillScore": 80,
            "skillScoreWithoutTopWinner": 72,
            "sampleConfidence": 100,
            "knownCategoryCoverageScore": 31,
            "knownCategoryConsistencyScore": 63,
            "concentrationPenalty": 14,
            "pnlConcentrationLevel": "extreme",
        },
    )

    assert sufficient["shadowRobustMetaScore"] == 63
    assert sufficient["usedRobustSkillScore"] is True
    assert sufficient["shadowRobustRecommendation"] == "robust_shadow_watch"
    assert limited["shadowRobustMetaScore"] == 57
    assert limited["usedRobustSkillScore"] is True


def test_shadow_robust_insufficient_uses_behavior_only():
    meta = compute_shadow_robust_evaluation(
        44,
        {
            "skillStatus": "insufficient",
            "skillScore": 91,
            "robustSkillScore": 70,
            "sampleConfidence": 100,
            "knownCategoryCoverageScore": 88,
            "knownCategoryConsistencyScore": 88,
            "concentrationPenalty": 10,
            "pnlConcentrationLevel": "low",
        },
    )

    assert meta["shadowRobustMetaScore"] == 44
    assert meta["usedRobustSkillScore"] is False
