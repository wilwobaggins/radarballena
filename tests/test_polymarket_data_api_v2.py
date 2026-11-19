from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from workers.smart_money.smart_money_engine import polymarket_data_api as api
from workers.smart_money.smart_money_engine import main as smart_money
from workers.smart_money.smart_money_engine import trade_copyability


FIXTURE = Path(__file__).parent / "fixtures" / "polymarket_v2_trade_page.json"


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.request = httpx.Request("GET", "https://data-api.polymarket.com/v2/trades")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("request failed", request=self.request, response=self)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    async def get(self, url, params):
        self.calls.append((url, dict(params)))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _envelope(rows, cursor=None):
    return FakeResponse({"data": rows, "pagination": {"next_cursor": cursor}})


def test_cursor_pagination_uses_v2_envelope_and_bounded_rows(monkeypatch):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    client = FakeClient(
        [
            FakeResponse(fixture),
            _envelope([{"proxy_wallet": "0x" + "d" * 40}], "fixture-cursor-page-3"),
        ]
    )
    async def run():
        rows = []
        async for page in api.iter_pages(
            client, "trades", {"limit": 1, "taker_only": False}, max_items=2
        ):
            rows.extend(page)
        return rows

    rows = asyncio.run(run())
    assert len(rows) == 2
    assert client.calls[0][1] == {"limit": 1, "taker_only": False}
    assert client.calls[1][1]["cursor"] == "fixture-cursor-page-2"
    assert "offset" not in client.calls[1][1]


def test_empty_page_stops_without_following_cursor():
    client = FakeClient([_envelope([], "should-not-be-followed")])

    async def run():
        return [page async for page in api.iter_pages(client, "trades", {"limit": 10}, max_items=20)]

    assert asyncio.run(run()) == []
    assert len(client.calls) == 1


def test_http_410_is_not_retried():
    response = FakeResponse({"error": "retired"}, status_code=410)
    client = FakeClient([response])

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(api.get_page(client, "trades", {"limit": 1}))
    assert len(client.calls) == 1


def test_http_429_retries_once_only_when_retry_after_is_bounded(monkeypatch):
    delays = []
    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(api.asyncio, "sleep", fake_sleep)
    client = FakeClient(
        [FakeResponse({}, 429, {"Retry-After": "1"}), _envelope([], None)]
    )

    assert asyncio.run(api.get_page(client, "trades", {"limit": 1})) == ([], None)
    assert len(client.calls) == 2
    assert delays == [1.0]


def test_connection_error_retries_once(monkeypatch):
    delays = []
    async def fake_sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(api.asyncio, "sleep", fake_sleep)
    error = httpx.ConnectError("connection refused", request=httpx.Request("GET", "https://example.test"))
    client = FakeClient([error, _envelope([], None)])

    assert asyncio.run(api.get_page(client, "trades", {"limit": 1})) == ([], None)
    assert len(client.calls) == 2
    assert delays == [0.25]


def test_v2_trade_share_size_is_converted_to_usdc_without_changing_threshold():
    trade = json.loads(FIXTURE.read_text(encoding="utf-8"))["data"][0]
    normalized = smart_money.normalize_activity(trade)
    assert normalized["wallet"] == "0x" + "a" * 40
    assert normalized["market_id"] == trade["condition_id"]
    assert normalized["size_usd"] == 4.0
    assert normalized["timestamp"].timestamp() == trade["timestamp"]

    copyability = trade_copyability.normalize_copyability_trade(trade, trade["proxy_wallet"])
    assert copyability is not None
    assert copyability["shares"] == 10.0
    assert copyability["sizeUsd"] == 4.0
    assert copyability["timestamp"] == trade["timestamp"]
