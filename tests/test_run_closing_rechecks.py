from services.closing_recheck_service import ClosingRecheckQuotaExceeded
from scripts import run_closing_rechecks as runner


def build_candidate(market_id: str, priority: str, score: int, days_to_close: int = 2):
    return {
        "marketId": market_id,
        "recheckPriority": priority,
        "recheckScore": score,
        "market": {
            "marketId": market_id,
            "title": f"Market {market_id}",
            "closingTime": "2026-06-30T00:00:00Z",
            "daysToClose": days_to_close,
            "current_probability": 0.61,
        },
        "previousAnalysisId": f"{market_id}-prev",
        "latestAnalysisId": f"{market_id}-latest",
        "previousAnalysis": {
            "analysisId": f"{market_id}-prev",
            "thesis": "Previous thesis",
        },
        "latestAnalysis": {
            "analysisId": f"{market_id}-latest",
            "thesis": "Latest thesis",
        },
        "recheckCandidate": {
            "recheckStatus": "STILL_VALID",
            "recheckPriority": priority,
            "recheckScore": score,
        },
        "marketSnapshot": {
            "marketId": market_id,
            "title": f"Market {market_id}",
            "daysToClose": days_to_close,
        },
    }


def test_select_candidates_filters_and_orders(monkeypatch):
    candidates = [
        build_candidate("low", "LOW", 100),
        build_candidate("critical-1", "CRITICAL", 70, days_to_close=2),
        build_candidate("high-2", "HIGH", 80, days_to_close=1),
        build_candidate("high-1", "HIGH", 90, days_to_close=1),
    ]
    candidates[2]["previousAnalysisId"] = candidates[2]["latestAnalysisId"]

    selected = runner.select_candidates(
        candidates,
        min_priority="HIGH",
        max_days_to_close=3,
        max_per_run=2,
    )

    assert [candidate["marketId"] for candidate in selected] == [
        "critical-1",
        "high-1",
    ]


def test_run_cycle_dry_run_does_not_call_model(monkeypatch):
    monkeypatch.setenv("CLOSING_RECHECK_ENABLED", "false")
    monkeypatch.setattr(
        runner,
        "fetch_closing_recheck_candidates",
        lambda **kwargs: [build_candidate("m1", "HIGH", 90)],
    )
    monkeypatch.setattr(
        runner,
        "run_closing_recheck_for_candidate",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("model should not be called")),
    )

    summary = runner.run_closing_rechecks_cycle(dry_run=True)

    assert summary["dry_run"] is True
    assert summary["selected"] == 1
    assert summary["saved"] == 0


def test_run_cycle_continues_after_single_candidate_failure(monkeypatch):
    monkeypatch.setenv("CLOSING_RECHECK_ENABLED", "true")
    monkeypatch.setenv("CLOSING_RECHECK_MAX_PER_RUN", "2")
    monkeypatch.setattr(
        runner,
        "fetch_closing_recheck_candidates",
        lambda **kwargs: [
            build_candidate("m1", "HIGH", 90),
            build_candidate("m2", "HIGH", 80),
        ],
    )

    calls = []

    def fake_run(candidate, **kwargs):
        calls.append(candidate["marketId"])
        if candidate["marketId"] == "m1":
            raise RuntimeError("boom")
        return {
            "status": "saved",
            "provider": "openai",
            "model": "gpt-4o-mini",
            "fallback_used": False,
            "saved_row": {"id": "row-1"},
        }

    monkeypatch.setattr(runner, "run_closing_recheck_for_candidate", fake_run)

    summary = runner.run_closing_rechecks_cycle(dry_run=False)

    assert calls == ["m1", "m2"]
    assert summary["saved"] == 1
    assert summary["errors"] == 1


def test_run_cycle_stops_after_quota_error(monkeypatch):
    monkeypatch.setenv("CLOSING_RECHECK_ENABLED", "true")
    monkeypatch.setenv("CLOSING_RECHECK_MAX_PER_RUN", "2")
    monkeypatch.setattr(
        runner,
        "fetch_closing_recheck_candidates",
        lambda **kwargs: [
            build_candidate("m1", "HIGH", 90),
            build_candidate("m2", "HIGH", 80),
        ],
    )

    calls = []

    def fake_run(candidate, **kwargs):
        calls.append(candidate["marketId"])
        raise ClosingRecheckQuotaExceeded("quota")

    monkeypatch.setattr(runner, "run_closing_recheck_for_candidate", fake_run)

    summary = runner.run_closing_rechecks_cycle(dry_run=False)

    assert calls == ["m1"]
    assert summary["saved"] == 0
    assert summary["errors"] == 1
