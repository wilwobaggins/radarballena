from schemas.closing_recheck_schema import ClosingRecheckSchema


VALID_CLOSING_RECHECK = {
    "analysisMode": "closing_recheck",
    "marketId": "market-123",
    "previousAnalysisId": "analysis-prev",
    "latestAnalysisId": "analysis-latest",
    "closingContext": {
        "daysToClose": 3,
        "closingTime": "2026-06-22T18:00:00Z",
    },
    "reevaluation": {
        "previousRadarScore": 61,
        "newRadarScore": 68,
        "radarScoreDelta": 7,
        "previousSignalLabel": "Watchlist",
        "newSignalLabel": "Directional Edge",
        "scoreDirection": "UP",
        "scoreChangeMagnitude": "MEDIUM",
        "scoreChangeReasons": ["More relevant context", "Probability improved"],
    },
    "metricBreakdown": {
        "signalStrength": {"score": 72, "reason": "The thesis gained clarity."},
        "informationQuality": {"score": 70, "reason": "Latest snapshot is richer."},
        "marketConsistency": {"score": 66, "reason": "Price and narrative now align better."},
        "timingAndClosureRisk": {"score": 58, "reason": "Close is near, so resolution matters more."},
        "noiseRisk": {"score": 42, "reason": "Some noise remains but is contained."},
        "capitalTrailImpact": {"score": 63, "reason": "Capital trail reinforces the thesis."},
    },
    "comparison": {
        "previousThesis": "The market was viable but noisy.",
        "latestThesis": "The market now has cleaner directional support.",
        "newThesis": "The market remains viable with stronger closing conviction.",
        "whatChanged": ["Probability improved", "Context became cleaner"],
        "whatStayedTheSame": ["Core market theme remains"],
        "contradictionDetected": False,
        "contradictionExplanation": None,
        "probabilityChangeSincePreviousAnalysis": 0.08,
        "radarScoreChangeSincePreviousAnalysis": 7,
    },
    "recheckStatus": "STILL_VALID",
    "importance": "HIGH",
    "recommendation": "Maintain focus and monitor the final confirmation signals.",
    "thesis": "The thesis remains valid and is now better supported into the close.",
    "confidence": 78,
    "riskFlags": ["PROBABILITY_SWING"],
}


def test_valid_closing_recheck_schema():
    schema = ClosingRecheckSchema.model_validate(VALID_CLOSING_RECHECK)

    assert schema.analysisMode == "closing_recheck"
    assert schema.reevaluation.newRadarScore == 68
    assert schema.recheckStatus == "STILL_VALID"
    assert schema.metricBreakdown.capitalTrailImpact.score == 63
