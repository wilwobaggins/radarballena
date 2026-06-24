from workers.smart_money.smart_money_engine.wallet_skill_score import (
    compute_shadow_meta_evaluation,
    compute_wallet_skill,
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


def test_wallet_skill_score_insufficient_positions():
    skill = compute_wallet_skill("0x" + "e" * 40, [build_position()] * 4)
    meta = compute_shadow_meta_evaluation(40, skill)

    assert skill["skillStatus"] == "insufficient"
    assert meta["shadowMetaScore"] == 40
    assert meta["usedSkillScore"] is False


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
