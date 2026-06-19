import json
from pathlib import Path

from schemas.closing_recheck_schema import ClosingRecheckResult
from scripts import debug_run_closing_recheck_model as script


VALID_RESULT = {
    "analysisMode": "closing_recheck",
    "marketId": "market-1",
    "previousAnalysisId": "analysis-prev",
    "latestAnalysisId": "analysis-latest",
    "closingContext": {
        "daysToClose": 2,
        "closingTime": "2026-06-21T14:00:00.000Z",
    },
    "reevaluation": {
        "previousRadarScore": 68,
        "newRadarScore": 68,
        "radarScoreDelta": 0,
        "previousSignalLabel": "Strong Watch",
        "newSignalLabel": "Strong Watch",
        "scoreDirection": "UNCHANGED",
        "scoreChangeMagnitude": "LOW",
        "scoreChangeReasons": ["No material change"],
    },
    "metricBreakdown": {
        "signalStrength": {"score": 68, "reason": "Stable signal."},
        "informationQuality": {"score": 60, "reason": "Limited but consistent."},
        "marketConsistency": {"score": 65, "reason": "Context still aligns."},
        "timingAndClosureRisk": {"score": 55, "reason": "Close is near."},
        "noiseRisk": {"score": 40, "reason": "Noise remains manageable."},
        "capitalTrailImpact": {"score": 45, "reason": "Supportive but not decisive."},
    },
    "comparison": {
        "previousThesis": "Previous thesis",
        "latestThesis": "Latest thesis",
        "newThesis": "Updated thesis",
        "whatChanged": ["Probability stayed flat"],
        "whatStayedTheSame": ["Core narrative remains"],
        "contradictionDetected": False,
        "contradictionExplanation": None,
        "probabilityChangeSincePreviousAnalysis": -2,
        "radarScoreChangeSincePreviousAnalysis": 0,
    },
    "recheckStatus": "WEAKENED",
    "importance": "HIGH",
    "recommendation": "Monitor the close carefully.",
    "thesis": "The thesis is still alive but weaker.",
    "confidence": 74,
    "riskFlags": ["MARGINAL_PROBABILITY_DROP"],
}


def test_persist_result_from_file_reads_validates_and_saves(monkeypatch):
    input_path = Path("output") / "test_debug_closing_recheck_result.json"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    input_path.write_text(json.dumps(VALID_RESULT), encoding="utf-8")

    captured = {}

    def fake_save(result, provider=None, model=None, fallback_used=False, prompt_hash=None, source="manual_debug"):
        captured["result"] = result
        captured["provider"] = provider
        captured["model"] = model
        captured["fallback_used"] = fallback_used
        captured["prompt_hash"] = prompt_hash
        captured["source"] = source
        return {"id": "closing-recheck-row-1"}

    monkeypatch.setattr(script, "save_closing_recheck_result", fake_save)

    saved_row = script.persist_result_from_file(input_path)

    assert saved_row["id"] == "closing-recheck-row-1"
    assert isinstance(captured["result"], ClosingRecheckResult)
    assert captured["provider"] is None
    assert captured["model"] is None
    assert captured["fallback_used"] is False
    assert captured["source"] == "manual_debug"
    assert len(captured["prompt_hash"]) == 64
