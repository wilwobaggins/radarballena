import asyncio

from workers.smart_money.smart_money_engine import polymarket_profile_client as client


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"{self.status_code} error")

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
        offset = params["offset"]
        payload = self.pages.get(offset, [])
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)


def test_fetch_closed_positions_paginates_until_incomplete_page(monkeypatch):
    pages = {
        0: [{"avgPrice": 0.2, "totalBought": 10, "realizedPnl": 2}] * 50,
        50: [{"avgPrice": 0.3, "totalBought": 10, "realizedPnl": -1}] * 50,
        100: [{"avgPrice": 0.4, "totalBought": 5, "realizedPnl": 3}] * 30,
    }
    fake_client = FakeAsyncClient(pages)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    positions = asyncio.run(client.fetch_closed_positions("0x" + "a" * 40, max_positions=500))

    assert [call["offset"] for call in fake_client.calls] == [0, 50, 100]
    assert positions[0]["avgPrice"] == 0.2
    assert len(positions) == 130


def test_fetch_closed_positions_stops_on_incomplete_page(monkeypatch):
    pages = {
        0: [{"avgPrice": 0.2, "totalBought": 10, "realizedPnl": 2}] * 50,
        50: [{"avgPrice": 0.3, "totalBought": 10, "realizedPnl": -1}] * 12,
    }
    fake_client = FakeAsyncClient(pages)
    monkeypatch.setattr(client.httpx, "AsyncClient", lambda **kwargs: fake_client)

    positions = asyncio.run(client.fetch_closed_positions("0x" + "b" * 40, max_positions=500))

    assert [call["offset"] for call in fake_client.calls] == [0, 50]
    assert len(positions) == 62


def test_fetch_closed_positions_invalid_wallet_returns_empty():
    assert asyncio.run(client.fetch_closed_positions("not-a-wallet")) == []
