from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from workers.smart_money.smart_money_engine.polymarket_price_history_client import (
    PRICE_HISTORY_CACHE,
    fetch_batch_price_history,
    fetch_price_history,
    find_nearest_price_point,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload
        self.status_code = 200
        self.headers = {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeClient:
    def __init__(self):
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        base = datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc)
        return FakeResponse(
            {
                "data": [
                    {"timestamp": int(base.timestamp()), "price": 0.2, "resolution_seconds": 300},
                    {"timestamp": int(base.replace(hour=1).timestamp()), "price": 0.3, "resolution_seconds": 300},
                ],
                "pagination": {"next_cursor": None},
            }
        )

    async def aclose(self):
        return None


def test_find_nearest_price_point():
    base = datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc)
    points = [
        {"timestamp": base, "price": 0.2},
        {"timestamp": base.replace(hour=1), "price": 0.3},
    ]
    target = base.replace(minute=7)
    nearest = find_nearest_price_point(points, target, tolerance_minutes=15)
    assert nearest["price"] == 0.2


def test_price_history_fetch_and_batch_cache(monkeypatch):
    PRICE_HISTORY_CACHE.clear()
    client = FakeClient()
    result = asyncio.run(fetch_price_history("token-1", client=client, cache_enabled=True))
    assert len(result) == 2
    assert client.calls
    assert client.calls[0][0].endswith("/v2/prices-history")
    assert client.calls[0][1]["interval"] == "1d"
    assert client.calls[0][1]["bucket_seconds"] == 300
    batch = asyncio.run(fetch_batch_price_history(["token-1", "token-1"], client=client, cache_enabled=True))
    assert batch["token-1"]
    assert len(client.calls) == 1
    assert PRICE_HISTORY_CACHE


def test_price_history_window_accepts_datetime_bounds(monkeypatch):
    PRICE_HISTORY_CACHE.clear()
    client = FakeClient()
    start = datetime(2026, 6, 28, 23, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 29, 6, 0, tzinfo=timezone.utc)

    result = asyncio.run(
        fetch_price_history(
            "token-2",
            start_timestamp=start,
            end_timestamp=end,
            client=client,
            cache_enabled=False,
        )
    )

    assert len(result) == 2
    assert client.calls
    _, params = client.calls[0]
    assert isinstance(params["start"], int)
    assert isinstance(params["end"], int)
    assert params["bucket_seconds"] == 300
    assert "start_ts" not in params and "end_ts" not in params and "fidelity" not in params


def test_price_history_normalizes_live_clob_p_t_shape_for_legacy_cached_data():
    from workers.smart_money.smart_money_engine.polymarket_price_history_client import _normalize_point

    point = _normalize_point({"t": 1782752879, "p": "0.42"})

    assert point is not None
    assert point["price"] == 0.42


def test_price_history_rejects_windows_over_api_limit_without_request():
    client = FakeClient()
    end = datetime(2026, 6, 29, tzinfo=timezone.utc)
    start = end.replace(day=1)

    result = asyncio.run(
        fetch_price_history(
            "token-too-wide",
            start_timestamp=start,
            end_timestamp=end,
            client=client,
            cache_enabled=False,
        )
    )

    assert result == []
    assert client.calls == []
