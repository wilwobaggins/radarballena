from workers.smart_money.smart_money_engine.wallet_skill_score import (
    compute_shadow_meta_evaluation,
    compute_shadow_robust_evaluation,
    compute_wallet_skill,
)
from workers.smart_money.smart_money_engine.category_utils import (
    guess_skill_category_from_title,
)


def build_position(
    *,
    title: str = "politics market",
    avg_price: float = 1.0,
    total_bought: float = 100.0,
    realized_pnl: float = 25.0,
    outcome: str = "Yes",
):
    return {
        "title": title,
        "avgPrice": avg_price,
        "totalBought": total_bought,
        "realizedPnl": realized_pnl,
        "timestamp": "2026-06-24T00:00:00Z",
        "outcome": outcome,
        "conditionId": "condition-1",
        "endDate": "2026-06-25T00:00:00Z",
    }


def test_wallet_skill_score_profitable_wallet():
    positions = [
        build_position(realized_pnl=40.0, title="election market 1"),
        build_position(realized_pnl=10.0, title="election market 2"),
        build_position(realized_pnl=5.0, title="macro market 3"),
        build_position(realized_pnl=-3.0, title="macro market 4"),
        build_position(realized_pnl=8.0, title="crypto market 5"),
    ] + [
        build_position(realized_pnl=6.0, title=f"election market {index}")
        for index in range(6, 21)
    ]

    skill = compute_wallet_skill("0x" + "a" * 40, positions)

    assert skill["skillStatus"] == "sufficient"
    assert skill["roi"] > 0
    assert skill["profitFactor"] > 1
    assert skill["skillScore"] > 50
    assert skill["dominantCategory"] in {"politics", "macro", "crypto", "unknown"}


def test_wallet_skill_score_losing_wallet():
    positions = [
        build_position(realized_pnl=-10.0, title="sports market 1"),
        build_position(realized_pnl=-5.0, title="sports market 2"),
        build_position(realized_pnl=0.0, title="sports market 3"),
        build_position(realized_pnl=-4.0, title="sports market 4"),
        build_position(realized_pnl=-6.0, title="sports market 5"),
    ]

    skill = compute_wallet_skill("0x" + "b" * 40, positions)

    assert skill["roi"] < 0
    assert skill["profitFactor"] == 0
    assert skill["skillScore"] < 60


def test_wallet_skill_score_no_losses_is_bounded():
    positions = [
        build_position(realized_pnl=12.0),
        build_position(realized_pnl=8.0),
        build_position(realized_pnl=4.0),
        build_position(realized_pnl=6.0),
        build_position(realized_pnl=3.0),
    ]

    skill = compute_wallet_skill("0x" + "c" * 40, positions)

    assert skill["noLossesObserved"] is True
    assert skill["profitFactor"] == 5.0


def test_wallet_skill_score_no_gains_is_zero_profit_factor():
    positions = [
        build_position(realized_pnl=-2.0),
        build_position(realized_pnl=-1.0),
        build_position(realized_pnl=0.0),
        build_position(realized_pnl=-4.0),
        build_position(realized_pnl=-3.0),
    ]

    skill = compute_wallet_skill("0x" + "d" * 40, positions)

    assert skill["grossProfit"] == 0
    assert skill["profitFactor"] == 0


def test_skill_category_classification_cases():
    cases = {
        "Counter-Strike: FURIA vs Team Falcons (BO3)": "esports",
        "Knicks vs. Celtics": "sports",
        "Will Trump win the presidential election?": "politics",
        "US military strike on Iran before July?": "geopolitics",
        "Will the Fed cut interest rates in July?": "macro",
        "Will Bitcoin reach $100,000?": "crypto",
        "Will Oppenheimer win Best Picture at the Oscars?": "culture_awards",
        "Will OpenAI release a new AI model?": "technology",
        "Will the highest temperature exceed 33°C?": "unknown",
    }

    for title, expected in cases.items():
        assert guess_skill_category_from_title(title) == expected

    assert guess_skill_category_from_title("open") == "unknown"
    assert guess_skill_category_from_title("open championship") == "unknown"
    assert guess_skill_category_from_title("match") == "unknown"
    assert guess_skill_category_from_title("CS2 map 1 winner") == "esports"
    assert guess_skill_category_from_title("Ukraine war ceasefire") == "geopolitics"


def test_wallet_skill_score_insufficient_positions():
    skill = compute_wallet_skill("0x" + "e" * 40, [build_position()] * 4)
    meta = compute_shadow_meta_evaluation(40, skill)

    assert skill["skillStatus"] == "insufficient"
    assert meta["shadowMetaScore"] == 40
    assert meta["usedSkillScore"] is False


def test_category_coverage_metrics_handle_unknown_only():
    positions = [
        build_position(title="Random market 1"),
        build_position(title="Random market 2"),
        build_position(title="Random market 3"),
        build_position(title="Random market 4"),
        build_position(title="Random market 5"),
    ]
    skill = compute_wallet_skill("0x" + "f" * 40, positions)

    assert skill["knownCategoryCoverage"] == 0
    assert skill["dominantKnownCategory"] == "unknown"
    assert skill["knownCategoryConsistency"] == 0
    assert skill["categoryConsistencyScore"] == 0


def test_category_coverage_metrics_handle_known_and_unknown_mix():
    positions = [
        build_position(title="Will Trump win election?"),
    ] * 60 + [
        build_position(title="Random market"),
    ] * 40
    skill = compute_wallet_skill("0x" + "1" * 40, positions)

    assert round(skill["knownCategoryCoverage"], 2) == 0.60
    assert skill["dominantKnownCategory"] == "politics"
    assert round(skill["knownCategoryConsistency"], 2) == 1.00


def test_category_coverage_metrics_multiple_known_categories():
    positions = [
        build_position(title="Will Trump win election?"),
    ] * 30 + [
        build_position(title="Will the Fed cut interest rates?"),
    ] * 20 + [
        build_position(title="Random market"),
    ] * 50
    skill = compute_wallet_skill("0x" + "2" * 40, positions)

    assert round(skill["knownCategoryCoverage"], 2) == 0.50
    assert skill["dominantKnownCategory"] == "politics"
    assert round(skill["knownCategoryConsistency"], 2) == 0.60


def test_shadow_meta_evaluation_weights():
    sufficient = compute_shadow_meta_evaluation(
        40,
        {
            "skillStatus": "sufficient",
            "skillScore": 80,
            "sampleConfidence": 100,
            "categoryConsistencyScore": 58,
        },
    )
    limited = compute_shadow_meta_evaluation(
        40,
        {
            "skillStatus": "limited",
            "skillScore": 80,
            "sampleConfidence": 100,
            "categoryConsistencyScore": 58,
        },
    )

    assert sufficient["shadowMetaScore"] == 66
    assert sufficient["usedSkillScore"] is True
    assert sufficient["shadowRecommendation"] == "shadow_watch"
    assert limited["shadowMetaScore"] == 58
    assert limited["usedSkillScore"] is True


def test_concentration_and_robust_skill_metrics():
    distributed_positions = [
        build_position(realized_pnl=10.0, title="Will Trump win election?"),
        build_position(realized_pnl=10.0, title="Will the Fed cut interest rates?"),
        build_position(realized_pnl=10.0, title="Will Bitcoin reach $100k?"),
        build_position(realized_pnl=10.0, title="Will OpenAI release a new model?"),
        build_position(realized_pnl=10.0, title="Will Oppenheimer win Best Picture?"),
        build_position(realized_pnl=10.0, title="Knicks vs Celtics"),
        build_position(realized_pnl=10.0, title="Will the Supreme Court rule on tariffs?"),
        build_position(realized_pnl=10.0, title="Will the Fed hold rates steady?"),
        build_position(realized_pnl=10.0, title="Will Ethereum hit new highs?"),
        build_position(realized_pnl=10.0, title="Will a new AI model launch?"),
    ]
    concentrated_positions = [
        build_position(realized_pnl=80.0, title="Will Trump win election?"),
        build_position(realized_pnl=5.0, title="Will the Fed cut interest rates?"),
        build_position(realized_pnl=4.0, title="Will Bitcoin reach $100k?"),
        build_position(realized_pnl=3.0, title="Will OpenAI release a new model?"),
        build_position(realized_pnl=2.0, title="Will Oppenheimer win Best Picture?"),
        build_position(realized_pnl=-1.0, title="Knicks vs Celtics"),
    ]

    distributed = compute_wallet_skill("0x" + "3" * 40, distributed_positions)
    concentrated = compute_wallet_skill("0x" + "4" * 40, concentrated_positions)

    assert distributed["pnlConcentrationLevel"] in {"low", "moderate"}
    assert concentrated["pnlConcentrationLevel"] == "extreme"
    assert concentrated["skillScoreWithoutTopWinner"] <= concentrated["skillScore"]
    assert concentrated["robustSkillScore"] <= concentrated["skillScore"]
    assert distributed["robustSkillScore"] >= 0
    assert 0 <= concentrated["top1PositionPnlShare"] <= 1
    assert 0 <= concentrated["top5PositionsPnlShare"] <= 1


def test_pnl_concentration_level_thresholds():
    extreme_at_sixty = compute_wallet_skill("0x" + "6" * 40, [
        build_position(realized_pnl=60.0, title="Will Trump win election?"),
        build_position(realized_pnl=40.0, title="Will the Fed cut interest rates?"),
    ])
    extreme_above_sixty = compute_wallet_skill("0x" + "7" * 40, [
        build_position(realized_pnl=62.0402, title="Will Trump win election?"),
        build_position(realized_pnl=37.9598, title="Will the Fed cut interest rates?"),
    ])
    not_extreme = compute_wallet_skill("0x" + "8" * 40, [
        build_position(realized_pnl=59.0, title="Will Trump win election?"),
        build_position(realized_pnl=41.0, title="Will the Fed cut interest rates?"),
    ])

    assert round(extreme_at_sixty["top1PositionPnlShare"], 2) == 0.60
    assert extreme_at_sixty["pnlConcentrationLevel"] == "extreme"
    assert round(extreme_above_sixty["top1PositionPnlShare"], 6) == 0.620402
    assert extreme_above_sixty["pnlConcentrationLevel"] == "extreme"
    assert round(not_extreme["top1PositionPnlShare"], 2) == 0.59
    assert not_extreme["pnlConcentrationLevel"] != "extreme"


def test_single_position_skill_is_valid():
    skill = compute_wallet_skill("0x" + "5" * 40, [build_position(realized_pnl=12.0, title="Will Trump win election?")])

    assert skill["skillScoreWithoutTopWinner"] == skill["skillScore"]
    assert skill["skillStatus"] == "insufficient"
    assert skill["robustSkillScore"] == skill["skillScore"]
