from types import SimpleNamespace

from services import closing_recheck_candidates_client as client


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def test_fetch_closing_recheck_candidates_normalizes_backend_payload(monkeypatch):
    payload = {
        "ok": True,
        "candidates": [
            {
                "marketId": "market-1",
                "recheckPriority": "HIGH",
                "recheckScore": 91,
                "market": {
                    "id": "market-1",
                    "title": "Will X happen?",
                    "closingTime": "2026-06-30T00:00:00Z",
                    "current_probability": 0.61,
                    "previous_probability_24h": 0.54,
                    "probability_change_24h": 0.07,
                },
                "previousAnalysis": {
                    "id": "analysis-prev",
                    "thesis": "Previous thesis",
                    "signalLabel": "Watchlist",
                    "radarScore": 60,
                    "probability": 0.54,
                },
                "latestAnalysis": {
                    "id": "analysis-latest",
                    "thesis": "Latest thesis",
                    "signalLabel": "Directional Edge",
                    "radarScore": 68,
                    "probability": 0.61,
                },
            }
        ],
    }

    monkeypatch.setattr(
        client.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(payload),
    )
    monkeypatch.setenv("BACKEND_URL", "https://backend.example")

    candidates = client.fetch_closing_recheck_candidates(days=3, limit=2, max_per_category=1)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["marketId"] == "market-1"
    assert candidate["market"]["title"] == "Will X happen?"
    assert candidate["previousAnalysis"]["analysisId"] == "analysis-prev"
    assert candidate["latestAnalysis"]["analysisId"] == "analysis-latest"
    assert candidate["recheckPriority"] == "HIGH"
    assert candidate["marketSnapshot"]["marketId"] == "market-1"


def test_fetch_closing_recheck_candidates_rejects_failed_payload(monkeypatch):
    payload = {"ok": False, "message": "boom"}

    monkeypatch.setattr(
        client.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    try:
        client.fetch_closing_recheck_candidates()
    except RuntimeError as error:
        assert "boom" in str(error)
    else:
        raise AssertionError("Expected RuntimeError")

