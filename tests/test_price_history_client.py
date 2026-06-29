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
            [
                {"timestamp": (base.timestamp()), "price": 0.2},
                {"timestamp": (base.replace(hour=1).timestamp()), "price": 0.3},
            ]
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
    assert isinstance(params["start_ts"], int)
    assert isinstance(params["end_ts"], int)
