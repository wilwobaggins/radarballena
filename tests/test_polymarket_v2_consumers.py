from __future__ import annotations

import json
from pathlib import Path

import pytest

from workers.smart_money.whale_worker import discover, whale_worker
from workers.smart_money.whale_finder import polymarket_data_api as whale_finder_api


FIXTURE = Path(__file__).parent / "fixtures" / "polymarket_v2_trade_page.json"


def _trade_payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_whale_worker_unwraps_v2_activity_and_keeps_trade_alert_fields(monkeypatch):
    calls = []
    payload = _trade_payload()
    activity = {
        **payload["data"][0],
        "type": "TRADE",
        "usdc_size": 4.0,
    }
    monkeypatch.setattr(
        whale_worker,
        "get_json",
        lambda url, params, timeout: calls.append((url, params, timeout))
        or {"data": [activity], "pagination": {"next_cursor": None}},
    )
    rows = whale_worker.fetch_activity("0x" + "a" * 40)
    monkeypatch.setattr(whale_worker, "resolve_market_id", lambda *_args: "gamma-market-id")

    alert = whale_worker.parse_alert(rows[0], "global_trader", "Test whale")

    assert len(rows) == 1
    assert calls[0][0].endswith("/v2/activity")
    assert calls[0][1]["type"] == "TRADE"
    assert calls[0][1]["limit"] == 50
    assert calls[0][2] == 10
    assert alert["size_usd"] == 4.0
    assert alert["shares"] == 10
    assert alert["event_slug"] == "fixture-event"
    assert alert["polymarket_url"].endswith("/fixture-event")


def test_discovery_uses_condition_and_cursor_with_a_fixed_trade_budget(monkeypatch):
    payload = _trade_payload()
    calls = []
    later = {"data": payload["data"], "pagination": {"next_cursor": None}}

    def fake_get_json(url, params):
        calls.append((url, dict(params)))
        if len(calls) == 1:
            return payload
        return later

    monkeypatch.setattr(discover, "get_json", fake_get_json)
    monkeypatch.setattr(discover, "TRADES_PER_MARKET", 2000)

    rows = discover.fetch_trades("0x" + "b" * 64)

    assert len(rows) == 2
    assert len(calls) == 2
    assert calls[0][0].endswith("/v2/trades")
    assert calls[0][1]["condition"] == "0x" + "b" * 64
    assert calls[0][1]["taker_only"] == "false"
    assert calls[1][1]["cursor"] == "fixture-cursor-page-2"
    assert all("market" not in params and "offset" not in params for _, params in calls)


def test_discovery_empty_v2_page_returns_empty_without_repeating(monkeypatch):
    calls = []
    monkeypatch.setattr(
        discover,
        "get_json",
        lambda url, params: calls.append(params) or {"data": [], "pagination": {"next_cursor": None}},
    )
    assert discover.fetch_trades("0x" + "b" * 64) == []
    assert len(calls) == 1


def test_whale_finder_normalizes_v2_wallet_and_usdc_trade_size():
    pytest.importorskip("pandas")
    from workers.smart_money.whale_finder import main as whale_finder

    trade = _trade_payload()["data"][0]
    normalized = whale_finder.normalize_activity(trade)

    assert normalized["wallet"] == "0x" + "a" * 40
    assert normalized["market_id"] == trade["condition_id"]
    assert normalized["size_usd"] == 4.0


def test_whale_finder_page_adapter_follows_v2_cursor(monkeypatch):
    payload = _trade_payload()
    calls = []

    class FakeResponse:
        status_code = 200
        headers = {}

        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return self.content

    class FakeClient:
        async def get(self, url, params):
            calls.append((url, dict(params)))
            return FakeResponse(payload if len(calls) == 1 else {"data": [], "pagination": {"next_cursor": None}})

    async def run():
        return [
            page
            async for page in whale_finder_api.iter_pages(
                FakeClient(), {"limit": 1}, max_items=2
            )
        ]

    pages = __import__("asyncio").run(run())
    assert len(pages) == 1
    assert calls[0][0].endswith("/v2/trades")
    assert calls[1][1]["cursor"] == "fixture-cursor-page-2"
    assert "offset" not in calls[1][1]
