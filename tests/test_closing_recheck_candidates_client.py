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
                "title": "Will X happen?",
                "category": "macro",
                "closingTime": "2026-06-30T00:00:00Z",
                "daysToClose": 8,
                "previousAnalysisId": "analysis-prev",
                "latestAnalysisId": "analysis-latest",
                "previousThesis": "Previous thesis",
                "thesis": "Latest thesis",
                "previousAnalysisRadarScore": 62,
                "latestRadarScore": 42,
                "previousAnalysisProbability": 9.8,
                "latestProbability": 3.6,
                "previousAnalysisGeneratedAt": "2026-06-20T10:00:00Z",
                "latestAnalysisGeneratedAt": "2026-06-21T10:00:00Z",
                "signalLabel": "Low Signal",
                "recheckPriority": "HIGH",
                "recheckStatus": "WEAKENED",
                "recheckScore": 32.4,
                "closingLabel": "8d",
                "probabilityChange24h": -6.2,
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
    assert candidate["previousAnalysis"]["thesis"] == "Previous thesis"
    assert candidate["latestAnalysis"]["thesis"] == "Latest thesis"
    assert candidate["previousAnalysis"]["radarScore"] == 62.0
    assert candidate["latestAnalysis"]["radarScore"] == 42.0
    assert candidate["previousAnalysis"]["probability"] == 9.8
    assert candidate["latestAnalysis"]["probability"] == 3.6
    assert candidate["deltas"]["probabilityChange24h"] == -6.2
    assert candidate["deltas"]["probabilityChangeSincePreviousAnalysis"] == -6.2
    assert candidate["deltas"]["radarScoreChangeSincePreviousAnalysis"] == -20.0


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


def test_fetch_closing_recheck_candidates_preserves_nested_payload(monkeypatch):
    payload = {
        "ok": True,
        "candidates": [
            {
                "marketId": "market-2",
                "market": {
                    "id": "market-2",
                    "title": "Nested market",
                    "closingTime": "2026-06-30T00:00:00Z",
                    "daysToClose": 5,
                },
                "previousAnalysis": {
                    "analysisId": "analysis-prev",
                    "thesis": "Previous thesis",
                },
                "latestAnalysis": {
                    "analysisId": "analysis-latest",
                    "thesis": "Latest thesis",
                },
                "recheckPriority": "CRITICAL",
            }
        ],
    }

    monkeypatch.setattr(
        client.requests,
        "get",
        lambda *args, **kwargs: FakeResponse(payload),
    )

    candidates = client.fetch_closing_recheck_candidates()

    assert candidates[0]["market"]["title"] == "Nested market"
    assert candidates[0]["previousAnalysis"]["analysisId"] == "analysis-prev"
    assert candidates[0]["latestAnalysis"]["analysisId"] == "analysis-latest"
    assert candidates[0]["recheckPriority"] == "CRITICAL"
