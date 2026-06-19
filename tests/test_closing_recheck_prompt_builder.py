from services.closing_recheck_prompt_builder import build_closing_recheck_prompt


def test_build_closing_recheck_prompt_renders_shared_criteria_and_inputs():
    prompt, prompt_source = build_closing_recheck_prompt(
        market={
            "marketId": "market-123",
            "title": "Will X happen before close?",
            "category": "politics",
            "closingTime": "2026-06-22T18:00:00Z",
            "daysToClose": 3,
        },
        previous_analysis={
            "analysisId": "analysis-prev",
            "thesis": "Previous thesis",
            "signalLabel": "Watchlist",
            "radarScore": 61,
            "probability": 0.54,
        },
        latest_analysis={
            "analysisId": "analysis-latest",
            "generatedAt": "2026-06-19T12:00:00Z",
            "thesis": "Latest thesis",
            "signalLabel": "Directional Edge",
            "radarScore": 68,
            "probability": 0.62,
        },
        deltas={
            "probabilityChangeSincePreviousAnalysis": 0.08,
            "radarScoreChangeSincePreviousAnalysis": 7,
            "probabilityChange24h": 0.03,
        },
        recheck_candidate={
            "recheckStatus": "STILL_VALID",
            "recheckPriority": "HIGH",
            "recheckReasons": ["Close is near", "Probability moved up"],
        },
        capital_trail={"status": "strong"},
        market_snapshot={"current_probability": 0.62},
    )

    assert prompt_source == "closing_recheck_comparative_prompt.txt"
    assert "closing_recheck" in prompt
    assert "Previous thesis" in prompt
    assert "Latest thesis" in prompt
    assert "Will X happen before close?" in prompt
    assert "shared_deepengine_criteria.txt" not in prompt
    assert "{{MERCADO}}" not in prompt
    assert "{{PREVIOUS_ANALYSIS}}" not in prompt
