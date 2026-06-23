import copy

import pytest

import services.deepbrief_generator as deepbrief_generator
from services.deepbrief_schema import DeepBriefSchema


def _valid_deepbrief():
    return {
        "lectura_clave": "Lectura suficientemente larga",
        "radar_score": 61,
        "radar_score_breakdown": {
            "movimiento_probabilidad": 8,
            "volumen": 8,
            "liquidez": 8,
            "cercania_cierre": 8,
            "claridad_resolucion": 8,
            "fuerza_narrativa": 8,
            "asimetria_detectada": 8,
            "riesgo_ruido": 3,
        },
        "signal_label": "Watchlist",
        "estela_de_capital": "Capital suficiente para la lectura",
        "entorno_de_senal": {
            "steep_social": "social",
            "steep_tecnologico": "tech",
            "steep_economico": "econ",
            "steep_ecologico": "eco",
            "steep_politico_regulatorio": "reg",
            "sintesis": "Sintesis",
        },
        "corriente_narrativa": "Narrativa suficientemente descriptiva",
        "filtro_de_ruido": {
            "red_team": "red",
            "sesgos_detectados": "sesgos",
            "riesgo_liquidez": "medio",
            "riesgo_resolucion": "bajo",
            "informacion_ya_descontada": "parcial",
        },
        "premortem": {
            "si_la_tesis_falla_probablemente_seria_por": "motivo",
            "senales_tempranas_de_invalidacion": ["senal"],
        },
        "mapa_de_ruptura": {
            "confirmacion": "conf",
            "ruptura_alcista": "up",
            "ruptura_bajista": "down",
            "invalidacion": "invalid",
            "evento_detonador": "evento",
        },
        "mapa_de_escenarios": [
            {"escenario": "Base", "probabilidad_interna": "50%", "descripcion": "desc", "impacto_en_mercado": "impacto"},
            {"escenario": "Ruptura", "probabilidad_interna": "65%", "descripcion": "desc", "impacto_en_mercado": "impacto"},
            {"escenario": "Contrario", "probabilidad_interna": "35%", "descripcion": "desc", "impacto_en_mercado": "impacto"},
        ],
        "actualizacion_bayesiana": {
            "probabilidad_actual_del_mercado": "55%",
            "lectura_deepsignal": "lectura",
            "direccion_sugerida_del_update": "subir",
            "razon": "razon",
        },
        "deepsignal_verdict": "verdict suficientemente largo",
        "confidence_level": "Medium",
        "watch_triggers": ["trigger"],
        "prediction_audit": {
            "predicted_outcome": "no_call",
            "predicted_probability": None,
            "expected_direction": None,
            "prediction_confidence": None,
            "prediction_reasoning_summary": "suficientemente largo",
        },
    }


def test_groq_disabled_does_not_call_groq(monkeypatch):
    monkeypatch.delenv("GROQ_ENABLED", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")

    called = {"groq": False}

    def fake_openai(**kwargs):
        return _valid_deepbrief(), {"provider": "openai", "fallback_used": False, "parsed_output": _valid_deepbrief()}

    def fake_groq(**kwargs):
        called["groq"] = True
        raise AssertionError("groq no deberia ejecutarse")

    monkeypatch.setattr(deepbrief_generator, "generate_with_openai", fake_openai)
    monkeypatch.setattr(deepbrief_generator, "generate_with_groq", fake_groq)

    deepbrief, raw_output = deepbrief_generator.generate_deepbrief_for_market(market={"title": "m"}, context_sources=[])
    assert deepbrief["radar_score"] == 61
    assert raw_output["provider"] == "openai"
    assert called["groq"] is False


def test_groq_enabled_without_key_registers_not_configured(monkeypatch):
    monkeypatch.setenv("GROQ_ENABLED", "true")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(deepbrief_generator, "GENAI_SDK_AVAILABLE", True)

    def fail_openai(**kwargs):
        raise deepbrief_generator.ProviderGenerationError("openai", "m", "openai down", attempts=[])

    def fail_gemini(**kwargs):
        raise deepbrief_generator.ProviderGenerationError("gemini", "m", "gemini down", attempts=kwargs["prior_attempts"])

    monkeypatch.setattr(deepbrief_generator, "generate_with_openai", fail_openai)
    monkeypatch.setattr(deepbrief_generator, "generate_with_gemini", fail_gemini)

    with pytest.raises(deepbrief_generator.AllDeepBriefProvidersFailedError) as exc_info:
        deepbrief_generator.generate_deepbrief_for_market(market={"title": "m"}, context_sources=[])

    assert any(item.get("error_type") == "groq_not_configured" for item in exc_info.value.attempts)


def test_groq_success_after_openai_and_gemini_failures(monkeypatch):
    monkeypatch.setenv("GROQ_ENABLED", "true")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setattr(deepbrief_generator, "GENAI_SDK_AVAILABLE", True)

    def fail_openai(**kwargs):
        raise deepbrief_generator.ProviderGenerationError("openai", "m", "openai down", attempts=[])

    def fail_gemini(**kwargs):
        raise deepbrief_generator.ProviderGenerationError("gemini", "m", "gemini down", attempts=kwargs["prior_attempts"])

    def fake_groq(**kwargs):
        deepbrief = _valid_deepbrief()
        raw_output = {
            "status": "ok",
            "provider": "groq",
            "model": "openai/gpt-oss-120b",
            "fallback_used": True,
            "primary_provider": "openai",
            "attempts": kwargs["prior_attempts"] + [{"provider": "groq", "attempt": 1, "status": "ok", "model": "openai/gpt-oss-120b"}],
            "market_input": {"title": "m"},
            "context_sources": [],
            "prompt_source": "deepbrief_master_prompt.txt",
            "prompt": "prompt",
            "parsed_output": copy.deepcopy(deepbrief),
            "usage": {"input_tokens": 1, "output_tokens": 2, "total_tokens": 3},
        }
        return deepbrief, raw_output

    monkeypatch.setattr(deepbrief_generator, "generate_with_openai", fail_openai)
    monkeypatch.setattr(deepbrief_generator, "generate_with_gemini", fail_gemini)
    monkeypatch.setattr(deepbrief_generator, "generate_with_groq", fake_groq)

    deepbrief, raw_output = deepbrief_generator.generate_deepbrief_for_market(market={"title": "m"}, context_sources=[])

    assert raw_output["provider"] == "groq"
    assert raw_output["model"] == "openai/gpt-oss-120b"
    assert raw_output["fallback_used"] is True
    assert deepbrief["radar_score"] == 61


def test_build_groq_response_schema_does_not_mutate_original_schema():
    before = DeepBriefSchema.model_json_schema()
    copy_before = copy.deepcopy(before)

    groq_schema = deepbrief_generator.build_groq_response_schema(DeepBriefSchema)

    assert before == copy_before
    assert groq_schema != {}
    assert "properties" in groq_schema


def test_groq_schema_rejection_retries_with_json_object(monkeypatch):
    monkeypatch.setenv("GROQ_ENABLED", "true")
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")

    class FakeUsage:
        input_tokens = 11
        output_tokens = 7
        total_tokens = 18

    class FakeResponse:
        def __init__(self, text, response_id="resp-1"):
            self.text = text
            self.id = response_id
            self.usage = FakeUsage()

    class FakeResponses:
        def __init__(self):
            self.calls = []

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if kwargs.get("response_format", {}).get("type") == "json_schema":
                raise RuntimeError("400 invalid_request_error response_format json_schema")
            return FakeResponse("```json\n" + __import__("json").dumps(_valid_deepbrief()) + "\n```")

    class FakeClient:
        def __init__(self):
            self.responses = FakeResponses()

    monkeypatch.setattr(deepbrief_generator, "_groq_client", lambda: FakeClient())

    deepbrief, raw_output = deepbrief_generator.generate_with_groq(
        market={"title": "m"},
        context_sources=[],
        max_retries=0,
        primary_provider="openai",
        fallback_used=True,
    )

    assert deepbrief["radar_score"] == 61
    assert raw_output["usage"] == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
