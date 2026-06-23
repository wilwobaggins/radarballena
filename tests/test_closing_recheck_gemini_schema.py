from types import SimpleNamespace

from schemas.closing_recheck_schema import ClosingRecheckModelOutput
from services import closing_recheck_service as service


def test_build_gemini_response_schema_strips_incompatible_keys():
    original = ClosingRecheckModelOutput.model_json_schema(mode="validation")
    schema = service.build_gemini_response_schema(ClosingRecheckModelOutput)

    assert original != schema
    assert "additionalProperties" in original
    assert "additionalProperties" not in schema
    assert "additional_properties" not in schema
    assert "additional_properties" not in str(schema)


def test_gemini_schema_error_retries_without_response_schema(monkeypatch):
    candidate = {
        "marketId": "market-1",
        "marketCurrent": {
            "marketId": "market-1",
            "title": "Will X happen?",
            "category": "politics",
            "closingTime": "2026-06-30T00:00:00Z",
            "daysToClose": 3,
            "probabilityScale": "percent_0_100",
            "current_probability": 0.61,
            "previous_probability_24h": 0.54,
            "probability_change_24h": 0.07,
            "volume": 1200000,
            "liquidity": 400000,
            "outcomes": ["Yes", "No"],
        },
        "marketSnapshot": {
            "marketId": "market-1",
            "current_probability": 0.61,
            "probabilityScale": "percent_0_100",
        },
        "previousAnalysisId": "analysis-prev",
        "latestAnalysisId": "analysis-latest",
        "previousAnalysis": {
            "analysisId": "analysis-prev",
            "thesis": "Previous thesis",
            "radarScore": 60,
            "probability": 0.54,
        },
        "latestAnalysis": {
            "analysisId": "analysis-latest",
            "thesis": "Latest thesis",
            "radarScore": 68,
            "probability": 0.61,
        },
        "recheckPriority": "HIGH",
        "recheckStatus": "STILL_VALID",
        "recheckCandidate": {
            "recheckPriority": "HIGH",
            "recheckStatus": "STILL_VALID",
        },
    }

    monkeypatch.setattr(service, "_build_model_prompt", lambda *args, **kwargs: ("prompt", "prompt_source"))

    seen_configs = []

    class FakeResponse:
        def __init__(self, *, parsed=None, text=None):
            self.parsed = parsed
            self.text = text
            self.response_id = "resp-1"

    class FakeModels:
        def __init__(self):
            self.calls = 0

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            seen_configs.append(config)
            if self.calls == 1:
                raise RuntimeError("400 INVALID_ARGUMENT Unknown name \"additional_properties\"")
            payload = {
                "newAiInterpretiveScore": 52,
                "comparison": {
                    "previousThesis": "Previous thesis",
                    "latestThesis": "Latest thesis",
                    "newThesis": "Updated thesis",
                    "whatChanged": ["Aumento la probabilidad"],
                    "whatStayedTheSame": ["La resolucion sigue clara"],
                    "contradictionDetected": False,
                    "contradictionExplanation": None,
                    "probabilityChangeSincePreviousAnalysis": 0.07,
                    "radarScoreChangeSincePreviousAnalysis": 8,
                },
                    "updatedThesis": "Tesis actualizada",
                    "recommendation": "Mantener seguimiento",
                    "recheckStatus": "STILL_VALID",
                    "confidence": 60,
                "riskFlags": [],
                "whatChanged": ["Aumento la probabilidad"],
                "whatStayedTheSame": ["La resolucion sigue clara"],
            }
            return FakeResponse(parsed=SimpleNamespace(model_dump=lambda: payload))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.models = FakeModels()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(service, "genai", SimpleNamespace(Client=FakeClient))
    monkeypatch.setattr(service, "genai_types", SimpleNamespace(GenerateContentConfig=FakeConfig))

    result, raw_output = service._call_gemini_model(
        candidate=candidate,
        new_preliminary={
            "preliminary_radar_score": 55,
            "score_breakdown": {
                "volume_score": 10,
                "liquidity_score": 9,
                "time_to_close_score": 8,
                "probability_movement_score": 7,
                "resolution_score": 6,
                "narrative_score": 5,
            },
        },
        score_parity=None,
        context_source="fresh_context",
        max_retries=1,
        primary_provider="openai",
        fallback_used=True,
    )

    assert result["newAiInterpretiveScore"] == 52
    assert raw_output["provider"] == "gemini"
    assert len(seen_configs) == 2
    assert "response_schema" in seen_configs[0].__dict__
    assert "response_schema" not in seen_configs[1].__dict__
    assert seen_configs[0].response_mime_type == "application/json"
    assert seen_configs[1].response_mime_type == "application/json"
