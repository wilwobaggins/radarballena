from workers.smart_money.smart_money_engine.wallet_skill_score import compute_shadow_meta_evaluation


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
