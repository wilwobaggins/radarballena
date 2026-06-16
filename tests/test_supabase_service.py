from types import SimpleNamespace

from services import supabase_service


class FakeTable:
    def __init__(self):
        self.payload = None
        self.on_conflict = None

    def upsert(self, payload, on_conflict=None):
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "prediction-row-1", **self.payload}])


class FakeSupabase:
    def __init__(self):
        self.table_name = None
        self.table_ref = FakeTable()

    def table(self, name):
        self.table_name = name
        return self.table_ref


def test_insert_deepsignal_prediction_builds_expected_payload(monkeypatch):
    fake_supabase = FakeSupabase()
    monkeypatch.setattr(supabase_service, "get_supabase_client", lambda: fake_supabase)

    saved = supabase_service.insert_deepsignal_prediction(
        deepbrief_id="deepbrief-1",
        market_id="market-1",
        deepbrief_output={
            "signal_label": "Watchlist",
            "finalRadarScore": 67,
            "prediction_audit": {
                "predicted_outcome": "yes",
                "predicted_probability": 0.72,
                "expected_direction": "yes_up",
                "prediction_confidence": "high",
                "prediction_reasoning_summary": "Catalizador fuerte y contexto alineado.",
            },
            "rawOutput": {
                "provider": "openai",
                "model": "gpt-4o-mini",
                "pipeline_run_id": "pipeline-1",
            },
        },
        market_input={
            "current_probability": 0.58,
        },
    )

    assert saved["id"] == "prediction-row-1"
    assert fake_supabase.table_name == "deepsignal_predictions"
    assert fake_supabase.table_ref.on_conflict == "deepbriefId"
    assert fake_supabase.table_ref.payload["deepbriefId"] == "deepbrief-1"
    assert fake_supabase.table_ref.payload["marketId"] == "market-1"
    assert fake_supabase.table_ref.payload["predictedOutcome"] == "yes"
    assert fake_supabase.table_ref.payload["predictedProbability"] == 0.72
    assert fake_supabase.table_ref.payload["marketProbabilityAtGeneration"] == 0.58
    assert fake_supabase.table_ref.payload["radarScoreAtGeneration"] == 67
    assert (
        fake_supabase.table_ref.payload["rawPrediction"]["raw_output_metadata"]["provider"]
        == "openai"
    )
