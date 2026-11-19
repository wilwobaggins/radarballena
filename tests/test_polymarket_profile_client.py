import asyncio

from workers.smart_money.smart_money_engine import polymarket_profile_client as client


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}
        self.request = __import__("httpx").Request("GET", "https://data-api.polymarket.com/v2/positions")

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("httpx").HTTPStatusError(
                f"{self.status_code} error", request=self.request, response=self
            )

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params):
        self.calls.append(params.copy())
        cursor = params.get("cursor")
        payload = self.pages.get(cursor, self.pages.get(None, {"data": [], "pagination": {"next_cursor": None}}))
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)


def test_fetch_closed_positions_paginates_until_incomplete_page(monkeypatch):
    pages = {
        None: {"data": [{"avg_price": 0.2, "total_size": 10, "realized_pnl": 2}] * 50,
               "pagination": {"next_cursor": "page-2"}},
        "page-2": {"data": [{"avg_price": 0.3, "total_size": 10, "realized_pnl": -1}] * 50,
                   "pagination": {"next_cursor": "page-3"}},
        "page-3": {"data": [{"avg_price": 0.4, "total_size": 5, "realized_pnl": 3}] * 30,
                   "pagination": {"next_cursor": None}},
    }
    fake_client = FakeAsyncClient(pages)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    positions = asyncio.run(client.fetch_closed_positions("0x" + "a" * 40, max_positions=500))

    assert [call.get("cursor") for call in fake_client.calls] == [None, "page-2", "page-3"]
    assert all(call["status"] == "CLOSED" and "offset" not in call for call in fake_client.calls)
    assert positions[0]["avgPrice"] == 0.2
    assert positions[0]["totalBought"] == 10
    assert len(positions) == 130


def test_fetch_closed_positions_stops_on_incomplete_page(monkeypatch):
    pages = {
        None: {"data": [{"avg_price": 0.2, "total_size": 10, "realized_pnl": 2}] * 50,
               "pagination": {"next_cursor": "page-2"}},
        "page-2": {"data": [{"avg_price": 0.3, "total_size": 10, "realized_pnl": -1}] * 12,
                   "pagination": {"next_cursor": None}},
    }
    fake_client = FakeAsyncClient(pages)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    positions = asyncio.run(client.fetch_closed_positions("0x" + "b" * 40, max_positions=500))

    assert [call.get("cursor") for call in fake_client.calls] == [None, "page-2"]
    assert len(positions) == 62


def test_fetch_closed_positions_invalid_wallet_returns_empty():
    assert asyncio.run(client.fetch_closed_positions("not-a-wallet")) == []
