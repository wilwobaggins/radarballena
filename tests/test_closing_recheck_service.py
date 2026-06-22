from services import closing_recheck_service as service


def build_candidate() -> dict:
    return {
        "marketId": "market-1",
        "recheckPriority": "HIGH",
        "recheckScore": 91,
        "market": {
            "marketId": "market-1",
            "title": "Will X happen?",
            "category": "politics",
            "closingTime": "2026-06-30T00:00:00Z",
            "daysToClose": 3,
            "current_probability": 0.61,
            "previous_probability_24h": 0.54,
            "probability_change_24h": 0.07,
        },
        "previousAnalysisId": "analysis-prev",
        "latestAnalysisId": "analysis-latest",
        "previousAnalysis": {
            "analysisId": "analysis-prev",
            "thesis": "Previous thesis",
            "signalLabel": "Watchlist",
            "radarScore": 60,
            "probability": 0.54,
        },
        "latestAnalysis": {
            "analysisId": "analysis-latest",
            "thesis": "Latest thesis",
            "signalLabel": "Directional Edge",
            "radarScore": 68,
            "probability": 0.61,
        },
        "deltas": {
            "probabilityChangeSincePreviousAnalysis": 0.07,
            "radarScoreChangeSincePreviousAnalysis": 8,
        },
        "recheckCandidate": {
            "recheckStatus": "STILL_VALID",
            "recheckPriority": "HIGH",
            "recheckScore": 91,
        },
        "capitalTrail": {"status": "strong"},
        "marketSnapshot": {
            "marketId": "market-1",
            "title": "Will X happen?",
            "current_probability": 0.61,
        },
    }


def test_run_closing_recheck_for_candidate_skips_existing_latest_analysis(monkeypatch):
    candidate = build_candidate()

    monkeypatch.setattr(
        service,
        "get_closing_recheck_by_market_and_latest_analysis",
        lambda **kwargs: {"id": "existing"},
    )
    monkeypatch.setattr(service, "get_recent_closing_recheck_for_market", lambda **kwargs: None)
    monkeypatch.setattr(service, "get_closing_recheck_by_prompt_hash_for_market", lambda **kwargs: None)
    monkeypatch.setattr(
        service,
        "call_closing_recheck_model_with_provider_sequence",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("model should not be called")),
    )

    result = service.run_closing_recheck_for_candidate(candidate)

    assert result["status"] == "skipped"
    assert result["reason"] == "already_processed_latest_analysis"


def test_run_closing_recheck_for_candidate_persists_after_validation(monkeypatch):
    candidate = build_candidate()
    saved = {}

    monkeypatch.setattr(
        service,
        "get_closing_recheck_by_market_and_latest_analysis",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(service, "get_recent_closing_recheck_for_market", lambda **kwargs: None)
    monkeypatch.setattr(service, "get_closing_recheck_by_prompt_hash_for_market", lambda **kwargs: None)
    monkeypatch.setattr(
        service,
        "call_closing_recheck_model_with_provider_sequence",
        lambda **kwargs: (
            {
                "analysisMode": "closing_recheck",
                "marketId": "market-1",
                "previousAnalysisId": "analysis-prev",
                "latestAnalysisId": "analysis-latest",
                "closingContext": {
                    "daysToClose": 3,
                    "closingTime": "2026-06-30T00:00:00Z",
                },
                "reevaluation": {
                    "previousRadarScore": 60,
                    "newRadarScore": 68,
                    "radarScoreDelta": 8,
                    "previousSignalLabel": "Watchlist",
                    "newSignalLabel": "Directional Edge",
                    "scoreDirection": "UP",
                    "scoreChangeMagnitude": "HIGH",
                    "scoreChangeReasons": ["Improved thesis"],
                },
                "metricBreakdown": {
                    "signalStrength": {"score": 68, "reason": "Stable."},
                    "informationQuality": {"score": 60, "reason": "Good."},
                    "marketConsistency": {"score": 65, "reason": "Good."},
                    "timingAndClosureRisk": {"score": 55, "reason": "Near close."},
                    "noiseRisk": {"score": 40, "reason": "Okay."},
                    "capitalTrailImpact": {"score": 45, "reason": "Supportive."},
                },
                "comparison": {
                    "previousThesis": "Previous thesis",
                    "latestThesis": "Latest thesis",
                    "newThesis": "Updated thesis",
                    "whatChanged": ["Probability improved"],
                    "whatStayedTheSame": ["Core narrative remains"],
                    "contradictionDetected": False,
                    "contradictionExplanation": None,
                    "probabilityChangeSincePreviousAnalysis": 0.07,
                    "radarScoreChangeSincePreviousAnalysis": 8,
                },
                "recheckStatus": "STILL_VALID",
                "importance": "HIGH",
                "recommendation": "Monitor.",
                "thesis": "Updated thesis",
                "confidence": 75,
                "riskFlags": [],
            },
            {
                "status": "ok",
                "provider": "openai",
                "model": "gpt-4o-mini",
                "fallback_used": False,
                "primary_provider": "openai",
                "response_id": "response-1",
            },
            "openai",
            "gpt-4o-mini",
        ),
    )

    def fake_save(result, provider=None, model=None, fallback_used=False, prompt_hash=None, source="manual_debug"):
        saved["result"] = result
        saved["provider"] = provider
        saved["model"] = model
        saved["fallback_used"] = fallback_used
        saved["prompt_hash"] = prompt_hash
        saved["source"] = source
        return {"id": "row-1"}

    monkeypatch.setattr(service, "save_closing_recheck_result", fake_save)

    result = service.run_closing_recheck_for_candidate(candidate)

    assert result["status"] == "saved"
    assert result["saved_row"]["id"] == "row-1"
    assert saved["provider"] == "openai"
    assert saved["model"] == "gpt-4o-mini"
    assert saved["source"] == "automatic_worker"
    assert len(saved["prompt_hash"]) == 64

