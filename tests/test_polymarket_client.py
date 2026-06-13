import services.polymarket_client as polymarket_client


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_fetch_active_markets_paginates_until_requested_limit(monkeypatch):
    calls = []

    def fake_get(url, params, timeout):
        calls.append(params.copy())
        offset = params["offset"]

        if offset == 0:
            payload = [{"id": f"m{i}"} for i in range(100)]
        elif offset == 100:
            payload = [{"id": f"m{i}"} for i in range(100, 200)]
        else:
            payload = [{"id": f"m{i}"} for i in range(200, 250)]

        return FakeResponse(payload)

    monkeypatch.setattr(polymarket_client.requests, "get", fake_get)

    markets = polymarket_client.fetch_active_markets(limit=250)

    assert len(calls) == 3
    assert calls[0]["limit"] == 100
    assert calls[0]["offset"] == 0
    assert calls[1]["offset"] == 100
    assert calls[2]["offset"] == 200
    assert len(markets) == 250


def test_fetch_active_markets_deduplicates_by_id(monkeypatch):
    def fake_get(url, params, timeout):
        if params["offset"] == 0:
            payload = [{"id": f"m{i}"} for i in range(100)]
        else:
            payload = [
                {"id": "m99"},
                {"id": "m100"},
            ]

        return FakeResponse(payload)

    monkeypatch.setattr(polymarket_client.requests, "get", fake_get)

    markets = polymarket_client.fetch_active_markets(limit=101)

    dedupe_keys = [
        polymarket_client.get_market_dedupe_key(market) for market in markets
    ]

    assert len(markets) == 101
    assert dedupe_keys[99] == "m99"
    assert dedupe_keys[100] == "m100"


def test_fetch_active_markets_uses_condition_id_when_id_missing(monkeypatch):
    def fake_get(url, params, timeout):
        payload = [
            {"conditionId": "cond-1"},
            {"conditionId": "cond-1"},
            {"questionID": "q-2"},
        ]
        return FakeResponse(payload)

    monkeypatch.setattr(polymarket_client.requests, "get", fake_get)

    markets = polymarket_client.fetch_active_markets(limit=3)

    assert len(markets) == 2
    assert polymarket_client.get_market_dedupe_key(markets[0]) == "cond-1"
    assert polymarket_client.get_market_dedupe_key(markets[1]) == "q-2"
