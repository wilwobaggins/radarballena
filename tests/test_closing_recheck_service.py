from types import SimpleNamespace

from services import closing_recheck_service as service
from schemas.closing_recheck_schema import ClosingRecheckModelOutput


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


def build_flat_candidate() -> dict:
    return {
        "marketId": "market-1",
        "title": "Will X happen?",
        "category": "politics",
        "closingTime": "2026-06-30T00:00:00Z",
        "daysToClose": 3,
        "previousAnalysisId": "analysis-prev",
        "latestAnalysisId": "analysis-latest",
        "previousThesis": "Previous thesis",
        "thesis": "Latest thesis",
        "previousAnalysisRadarScore": 60,
        "latestRadarScore": 68,
        "previousAnalysisProbability": 0.54,
        "latestProbability": 0.61,
        "previousAnalysisGeneratedAt": "2026-06-20T10:00:00Z",
        "latestAnalysisGeneratedAt": "2026-06-21T10:00:00Z",
        "signalLabel": "Directional Edge",
        "recheckPriority": "HIGH",
        "recheckScore": 91,
        "recheckStatus": "STILL_VALID",
        "probabilityChange24h": 0.07,
        "probabilityChangeSincePreviousAnalysis": 0.07,
        "radarScoreChangeSincePreviousAnalysis": 8,
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
                    "newAiInterpretiveScore": 70,
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
                    "recommendation": "Monitor.",
                    "confidence": 75,
                    "riskFlags": [],
                    "updatedThesis": "Updated thesis",
                    "whatChanged": ["Probability improved"],
                    "whatStayedTheSame": ["Core narrative remains"],
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


def test_run_closing_recheck_for_candidate_accepts_flat_payload(monkeypatch):
    candidate = build_flat_candidate()
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
                    "newAiInterpretiveScore": 70,
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
                    "recommendation": "Monitor.",
                    "confidence": 75,
                    "riskFlags": [],
                    "updatedThesis": "Updated thesis",
                    "whatChanged": ["Probability improved"],
                    "whatStayedTheSame": ["Core narrative remains"],
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
    assert saved["provider"] == "openai"
    assert saved["source"] == "automatic_worker"


def test_call_groq_model_retries_json_schema_then_json_object(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

    candidate = build_candidate()
    seen = []

    class FakeUsage:
        prompt_tokens = 11
        completion_tokens = 7
        total_tokens = 18

    class FakeResponse:
        def __init__(self, payload):
            self.choices = [SimpleNamespace(message=SimpleNamespace(content=payload))]
            self.response_id = "resp-1"
            self.id = "resp-1"
            self.usage = FakeUsage()

    class FakeCompletions:
        def __init__(self):
            self.calls = 0

        def create(self, **kwargs):
            self.calls += 1
            seen.append(kwargs)
            assert "response_mime_type" not in kwargs
            assert "response_schema" not in kwargs
            assert "messages" in kwargs
            assert "model" in kwargs
            assert "response_format" in kwargs
            if self.calls == 1:
                raise RuntimeError('400 INVALID_ARGUMENT Unknown name "additional_properties"')

            payload = ClosingRecheckModelOutput.model_validate(
                {
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
                    "recheckStatus": "STILL_VALID",
                    "recommendation": "Mantener seguimiento",
                    "confidence": 60,
                    "riskFlags": [],
                    "updatedThesis": "Tesis actualizada",
                    "whatChanged": ["Aumento la probabilidad"],
                    "whatStayedTheSame": ["La resolucion sigue clara"],
                }
            ).model_dump()
            return FakeResponse("```json\n{}\n```".format(__import__("json").dumps(payload)))

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(service, "OpenAI", FakeClient)

    result, raw_output = service._call_groq_model(
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
    assert raw_output["provider"] == "groq"
    assert raw_output["model"] == "openai/gpt-oss-120b"
    assert raw_output["fallback_used"] is True
    assert raw_output["usage"] == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }
    assert len(seen) == 2
    assert seen[0]["response_format"]["type"] == "json_schema"
    assert seen[1]["response_format"]["type"] == "json_object"
    assert "response_mime_type" not in seen[0]
    assert "response_schema" not in seen[0]
    assert "response_mime_type" not in seen[1]
    assert "response_schema" not in seen[1]


def test_provider_sequence_routes_groq_to_groq_model(monkeypatch):
    candidate = build_candidate()
    new_preliminary = {
        "preliminary_radar_score": 55,
        "score_breakdown": {
            "volume_score": 10,
            "liquidity_score": 9,
            "time_to_close_score": 8,
            "probability_movement_score": 7,
            "resolution_score": 6,
            "narrative_score": 5,
        },
    }

    monkeypatch.setattr(service, "get_provider_sequence", lambda: ("openai", ["groq"]))
    monkeypatch.setattr(service, "is_provider_configured", lambda provider: (True, None))
    monkeypatch.setattr(service, "get_provider_model", lambda provider: "openai/gpt-oss-120b" if provider == "groq" else "gpt-test")
    monkeypatch.setattr(
        service,
        "_call_openai_model",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("openai no debe ejecutarse para provider=groq")),
    )
    monkeypatch.setattr(
        service,
        "_call_gemini_model",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("gemini no debe ejecutarse para provider=groq")),
    )
    groq_called = {"count": 0}

    def fake_groq(**kwargs):
        groq_called["count"] += 1
        return (
            ClosingRecheckModelOutput.model_validate(
                {
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
                    "recheckStatus": "STILL_VALID",
                    "recommendation": "Mantener seguimiento",
                    "confidence": 60,
                    "riskFlags": [],
                    "updatedThesis": "Tesis actualizada",
                    "whatChanged": ["Aumento la probabilidad"],
                    "whatStayedTheSame": ["La resolucion sigue clara"],
                }
            ).model_dump(),
            {
                "status": "ok",
                "provider": "groq",
                "model": "openai/gpt-oss-120b",
                "fallback_used": True,
                "primary_provider": "openai",
                "attempts": [],
                "prompt_source": "prompt_source",
                "prompt": "prompt",
                "parsed_output": {},
                "response_id": "resp-1",
            },
        )

    monkeypatch.setattr(service, "_call_groq_model", fake_groq)

    result_payload, raw_output, provider, model = service.call_closing_recheck_model_with_provider_sequence(
        candidate=candidate,
        new_preliminary=new_preliminary,
        score_parity=None,
        context_source="fresh_context",
        max_retries=0,
    )

    assert groq_called["count"] == 1
    assert provider == "groq"
    assert model == "openai/gpt-oss-120b"
    assert raw_output["provider"] == "groq"
    assert result_payload["newAiInterpretiveScore"] == 52
