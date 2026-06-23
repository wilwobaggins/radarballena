from types import SimpleNamespace

from services import deterministic_deepbrief_persistence as persistence


def base_market():
    return {
        "title": "Will BTC close above 100k this month?",
        "description": "Binary crypto market.",
        "category": "crypto",
        "current_probability": 0.58,
        "previous_probability_24h": 0.62,
        "probability_change_24h": -0.04,
        "volume": 125000,
        "liquidity": 45000,
        "close_date": "2026-06-30T00:00:00+00:00",
        "outcomes": ["Yes", "No"],
        "selection_reason": "category=crypto | score=58",
    }


class FakeDb:
    def __init__(self):
        self.insert_calls = []
        self.recent_calls = []

    def insert_deepbrief(self, **kwargs):
        self.insert_calls.append(kwargs)
        return {"id": "deepbrief-123", **kwargs}

    def get_recent_deepbrief(self, market_db_id: str, hours: int):
        self.recent_calls.append((market_db_id, hours))
        return None


def test_persist_deterministic_deepbrief_builds_expected_payload():
    fake_db = FakeDb()

    saved = persistence.persist_deterministic_deepbrief(
        db=fake_db,
        market_db_id="market-1",
        market=base_market(),
        preliminary_score=58,
        score_breakdown={"movimiento_probabilidad": 2},
        selection_reason="category=crypto | score=58",
        pipeline_run_id="pipeline-1",
        provider_attempts=[
            {
                "provider": "openai",
                "status": "failed",
                "error_type": "quota",
                "secret": "should-not-pass",
            }
        ],
    )

    assert saved["id"] == "deepbrief-123"
    assert len(fake_db.insert_calls) == 1
    payload = fake_db.insert_calls[0]

    assert payload["deepbrief"]["aiInterpretiveScore"] is None
    assert payload["deepbrief"]["finalRadarScore"] == 58
    assert payload["deepbrief"]["radarScore"] == 58
    assert payload["hybrid_score"]["ai_interpretive_score"] is None
    assert payload["hybrid_score"]["final_radar_score"] == 58
    assert payload["raw_output"]["provider"] == "deterministic"
    assert payload["raw_output"]["model"] == "none"
    assert payload["raw_output"]["generation_mode"] == "deterministic_fallback"
    assert payload["raw_output"]["needs_ai_refresh"] is True
    assert payload["raw_output"]["fallback_used"] is True
    assert payload["raw_output"]["pipeline_run_id"] == "pipeline-1"
    assert payload["raw_output"]["provider_attempts"][0]["error_type"] == "quota"
    assert "secret" not in payload["raw_output"]["provider_attempts"][0]
    assert payload["raw_output"]["market_input"]["current_probability"] == 0.58
    assert payload["raw_output"]["market_input"]["volume"] == 125000
    assert payload["raw_output"]["market_input"]["liquidity"] == 45000
    assert payload["raw_output"]["market_input"]["close_date"] == "2026-06-30T00:00:00+00:00"
    assert payload["raw_output"]["preliminary_score"] == 58


def test_recent_deterministic_fallback_probe_uses_recent_deepbrief():
    fake_db = FakeDb()
    fake_db.get_recent_deepbrief = lambda market_db_id, hours: {
        "id": "deepbrief-1",
        "rawOutput": {
            "provider": "deterministic",
            "generation_mode": "deterministic_fallback",
        },
    }

    assert persistence.has_recent_deterministic_fallback(db=fake_db, market_db_id="market-1")
