from types import SimpleNamespace

from schemas.closing_recheck_schema import ClosingRecheckResult
from services import closing_recheck_repository as repo


class FakeTable:
    def __init__(self):
        self.payload = None

    def insert(self, payload):
        self.payload = payload
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "closing-recheck-row-1", **self.payload}])


class FakeSupabase:
    def __init__(self):
        self.table_name = None
        self.table_ref = FakeTable()

    def table(self, name):
        self.table_name = name
        return self.table_ref


def test_save_closing_recheck_result_builds_expected_payload(monkeypatch):
    fake_supabase = FakeSupabase()
    monkeypatch.setattr(repo, "get_supabase_client", lambda: fake_supabase)

    result = ClosingRecheckResult.model_validate(
        {
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
    )

    saved = repo.save_closing_recheck_result(
        result,
        provider="openai",
        model="gpt-5.4-mini",
        fallback_used=False,
        prompt_hash="abc123",
        source="manual_debug",
    )

    assert saved["id"] == "closing-recheck-row-1"
    assert fake_supabase.table_name == "closing_recheck_results"
    assert fake_supabase.table_ref.payload["market_id"] == "market-1"
    assert fake_supabase.table_ref.payload["previous_analysis_id"] == "analysis-prev"
    assert fake_supabase.table_ref.payload["latest_analysis_id"] == "analysis-latest"
    assert fake_supabase.table_ref.payload["recheck_status"] == "WEAKENED"
    assert fake_supabase.table_ref.payload["new_radar_score"] == 68
    assert fake_supabase.table_ref.payload["score_direction"] == "UNCHANGED"
    assert fake_supabase.table_ref.payload["provider"] == "openai"
    assert fake_supabase.table_ref.payload["model"] == "gpt-5.4-mini"
    assert fake_supabase.table_ref.payload["prompt_hash"] == "abc123"
    assert fake_supabase.table_ref.payload["result"]["analysisMode"] == "closing_recheck"
