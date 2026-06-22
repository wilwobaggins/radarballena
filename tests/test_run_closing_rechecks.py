from services.closing_recheck_candidates_client import normalize_closing_recheck_candidates
from services.closing_recheck_service import ClosingRecheckQuotaExceeded
from scripts import run_closing_rechecks as runner


def build_flat_candidate(
    market_id: str,
    priority: str,
    score: float,
    days_to_close: int = 2,
    *,
    previous_thesis: str = "Previous thesis",
    latest_thesis: str = "Latest thesis",
    same_ids: bool = False,
):
    latest_analysis_id = f"{market_id}-latest"
    previous_analysis_id = latest_analysis_id if same_ids else f"{market_id}-prev"

    return {
        "marketId": market_id,
        "title": f"Market {market_id}",
        "category": "macro",
        "closingTime": "2026-06-30T00:00:00Z",
        "daysToClose": days_to_close,
        "previousAnalysisId": previous_analysis_id,
        "latestAnalysisId": latest_analysis_id,
        "previousThesis": previous_thesis,
        "thesis": latest_thesis,
        "previousAnalysisRadarScore": 62,
        "latestRadarScore": 42,
        "previousAnalysisProbability": 9.8,
        "latestProbability": 3.6,
        "previousAnalysisGeneratedAt": "2026-06-20T10:00:00Z",
        "latestAnalysisGeneratedAt": "2026-06-21T10:00:00Z",
        "signalLabel": "Low Signal",
        "recheckPriority": priority,
        "recheckStatus": "WEAKENED",
        "recheckScore": score,
        "closingLabel": f"{days_to_close}d",
        "probabilityChange24h": -6.2,
        "probabilityChangeSincePreviousAnalysis": -6.2,
        "radarScoreChangeSincePreviousAnalysis": -20.0,
    }


def test_select_candidates_filters_and_orders(monkeypatch):
    candidates = normalize_closing_recheck_candidates(
        {
            "ok": True,
            "candidates": [
                build_flat_candidate("low", "LOW", 100),
                build_flat_candidate("critical-1", "CRITICAL", 70, days_to_close=2),
                build_flat_candidate("high-2", "HIGH", 80, days_to_close=1),
                build_flat_candidate("high-1", "HIGH", 90, days_to_close=1),
            ],
        }
    )
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

    assert runner.has_comparable_analyses(candidates[1]) is True

    selected_from_dry_run = runner.select_candidates(
        candidates,
        min_priority="HIGH",
        max_days_to_close=3,
        max_per_run=1,
    )
    assert len(selected_from_dry_run) == 1
    assert selected_from_dry_run[0]["marketId"] == "critical-1"


def test_run_cycle_dry_run_does_not_call_model(monkeypatch):
    monkeypatch.setenv("CLOSING_RECHECK_ENABLED", "false")
    monkeypatch.setattr(
        runner,
        "fetch_closing_recheck_candidates",
        lambda **kwargs: normalize_closing_recheck_candidates(
            {"ok": True, "candidates": [build_flat_candidate("m1", "HIGH", 90)]}
        ),
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
        lambda **kwargs: normalize_closing_recheck_candidates(
            {
                "ok": True,
                "candidates": [
                    build_flat_candidate("m1", "HIGH", 90),
                    build_flat_candidate("m2", "HIGH", 80),
                ],
            }
        ),
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
        lambda **kwargs: normalize_closing_recheck_candidates(
            {
                "ok": True,
                "candidates": [
                    build_flat_candidate("m1", "HIGH", 90),
                    build_flat_candidate("m2", "HIGH", 80),
                ],
            }
        ),
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


def test_payload_with_missing_previous_thesis_is_rejected():
    candidates = normalize_closing_recheck_candidates(
        {
            "ok": True,
            "candidates": [
                build_flat_candidate("m1", "HIGH", 90, previous_thesis=""),
            ],
        }
    )

    assert runner.has_comparable_analyses(candidates[0]) is False


def test_same_analysis_ids_are_rejected_after_normalization():
    candidates = normalize_closing_recheck_candidates(
        {
            "ok": True,
            "candidates": [
                build_flat_candidate("m1", "HIGH", 90, same_ids=True),
            ],
        }
    )

    assert runner.has_comparable_analyses(candidates[0]) is False
