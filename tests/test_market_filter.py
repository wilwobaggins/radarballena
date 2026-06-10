from datetime import datetime, timedelta, timezone

from services.market_filter import (
    filter_relevant_markets_with_stats,
    is_market_open,
)


def iso_date(days: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def build_market(**overrides):
    market = {
        "title": "Will BTC finish the week above 100k?",
        "description": "Binary market with clear resolution.",
        "category": "crypto",
        "close_date": iso_date(10),
        "probability_change_24h": 0.02,
        "volume": 150_000,
        "liquidity": 25_000,
        "outcomes": ["Yes", "No"],
        "deepengine_eligible": True,
        "raw_payload": {},
    }
    market.update(overrides)
    return market


def test_market_with_past_close_date_is_not_open():
    market = build_market(close_date=iso_date(-1))

    assert is_market_open(market) is False


def test_market_with_closed_flag_is_not_open():
    market = build_market(raw_payload={"closed": True})

    assert is_market_open(market) is False


def test_market_with_active_false_is_not_open():
    market = build_market(raw_payload={"active": False})

    assert is_market_open(market) is False


def test_market_with_future_close_date_is_open():
    market = build_market(close_date=iso_date(2))

    assert is_market_open(market) is True


def test_filter_relevant_markets_reports_closed_and_inactive_exclusions():
    markets = [
        build_market(title="future-open", close_date=iso_date(5)),
        build_market(title="past-date", close_date=iso_date(-2)),
        build_market(title="closed-flag", raw_payload={"closed": True}),
        build_market(title="inactive-flag", raw_payload={"active": False}),
    ]

    filtered, stats = filter_relevant_markets_with_stats(markets)

    assert [market["title"] for market in filtered] == ["future-open"]
    assert stats["closed_market_excluded"] == 3
    assert stats["closed_by_date"] == 1
    assert stats["closed_by_flag"] == 1
    assert stats["inactive_market_excluded"] == 1
    assert stats["eligible_after_filters"] == 1
