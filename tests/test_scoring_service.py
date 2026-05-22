from datetime import datetime, timedelta, timezone

from services.scoring_service import (
    calculate_volume_score,
    calculate_liquidity_score,
    calculate_time_to_close_score,
    calculate_probability_movement_score,
    calculate_preliminary_radar_score,
    score_markets,
    sort_markets_by_score,
)


def future_date(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


MOCK_MARKET = {
    "title": "Will bitcoin hit $1m before GTA VI?",
    "description": "This market resolves based on BTCUSDT price and GTA VI release.",
    "category": "crypto",
    "close_date": future_date(20),
    "current_probability": 0.49,
    "previous_probability_24h": 0.46,
    "probability_change_24h": 0.03,
    "volume": 250_000,
    "liquidity": 50_000,
    "outcomes": ["Yes", "No"],
}


def test_calculate_volume_score():
    assert calculate_volume_score(MOCK_MARKET) == 20


def test_calculate_liquidity_score():
    assert calculate_liquidity_score(MOCK_MARKET) == 20


def test_calculate_time_to_close_score():
    assert calculate_time_to_close_score(MOCK_MARKET) == 15


def test_calculate_probability_movement_score():
    assert calculate_probability_movement_score(MOCK_MARKET) == 15


def test_calculate_preliminary_radar_score():
    result = calculate_preliminary_radar_score(MOCK_MARKET)

    assert 0 <= result["preliminary_radar_score"] <= 100
    assert "score_breakdown" in result
    assert result["score_breakdown"]["volume_score"] == 20
    assert result["score_breakdown"]["liquidity_score"] == 20


def test_score_markets_adds_score():
    scored = score_markets([MOCK_MARKET])

    assert len(scored) == 1
    assert "preliminary_radar_score" in scored[0]
    assert "score_breakdown" in scored[0]


def test_sort_markets_by_score():
    weak_market = {
        **MOCK_MARKET,
        "volume": 1_000,
        "liquidity": 500,
        "probability_change_24h": 0.0,
    }

    scored = score_markets([weak_market, MOCK_MARKET])
    sorted_markets = sort_markets_by_score(scored)

    assert sorted_markets[0]["preliminary_radar_score"] >= sorted_markets[1]["preliminary_radar_score"]