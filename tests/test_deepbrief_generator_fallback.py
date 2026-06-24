import pytest

import services.deepbrief_generator as deepbrief_generator


def fake_result(provider: str, fallback_used: bool, attempts=None):
    deepbrief = {
        "lectura_clave": "Lectura",
        "radar_score": 71,
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
        "signal_label": "Strong Watch",
        "estela_de_capital": "Capital estable",
        "entorno_de_senal": {
            "steep_social": "social",
            "steep_tecnologico": "tech",
            "steep_economico": "econ",
            "steep_ecologico": "eco",
            "steep_politico_regulatorio": "reg",
            "sintesis": "Sintesis",
        },
        "corriente_narrativa": "Narrativa",
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
            {
                "escenario": "Base",
                "probabilidad_interna": "50%",
                "descripcion": "desc",
                "impacto_en_mercado": "impacto",
            }
        ],
        "actualizacion_bayesiana": {
            "probabilidad_actual_del_mercado": "55%",
            "lectura_deepsignal": "lectura",
            "direccion_sugerida_del_update": "subir",
            "razon": "razon",
        },
        "deepsignal_verdict": "verdict",
        "confidence_level": "Medium",
        "watch_triggers": ["trigger"],
    }

    raw_output = {
        "status": "ok",
        "provider": provider,
        "model": f"{provider}-model",
        "fallback_used": fallback_used,
        "primary_provider": "openai",
        "attempts": attempts or [],
        "market_input": {"title": "test"},
        "context_sources": [],
        "prompt": "prompt",
        "parsed_output": deepbrief,
    }

    return deepbrief, raw_output


def test_generate_deepbrief_primary_openai_success(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_ENABLE_FALLBACK", "true")
    monkeypatch.setattr(deepbrief_generator, "GENAI_SDK_AVAILABLE", True)

    def fake_openai(**kwargs):
        return fake_result("openai", False)

    def fail_gemini(**kwargs):
        raise AssertionError("Gemini no deberia ejecutarse")

    monkeypatch.setattr(deepbrief_generator, "generate_with_openai", fake_openai)
    monkeypatch.setattr(deepbrief_generator, "generate_with_gemini", fail_gemini)

    _deepbrief, raw_output = deepbrief_generator.generate_deepbrief_for_market(
        market={"title": "market"},
        context_sources=[],
    )

    assert raw_output["provider"] == "openai"
    assert raw_output["fallback_used"] is False


def test_generate_deepbrief_uses_gemini_fallback_after_openai_failure(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_ENABLE_FALLBACK", "true")
    monkeypatch.setattr(deepbrief_generator, "GENAI_SDK_AVAILABLE", True)

    def fake_openai(**kwargs):
        raise deepbrief_generator.ProviderGenerationError(
            provider="openai",
            model="gpt-test",
            message="openai auth error",
            attempts=[
                {
                    "provider": "openai",
                    "attempt": 1,
                    "status": "failed",
                    "model": "gpt-test",
                    "error": "openai auth error",
                }
            ],
        )

    def fake_gemini(**kwargs):
        assert kwargs["fallback_used"] is True
        assert kwargs["prior_attempts"][0]["provider"] == "openai"
        attempts = kwargs["prior_attempts"] + [
            {
                "provider": "gemini",
                "attempt": 1,
                "status": "ok",
                "model": "gemini-test",
            }
        ]
        return fake_result("gemini", True, attempts=attempts)

    monkeypatch.setattr(deepbrief_generator, "generate_with_openai", fake_openai)
    monkeypatch.setattr(deepbrief_generator, "generate_with_gemini", fake_gemini)

    _deepbrief, raw_output = deepbrief_generator.generate_deepbrief_for_market(
        market={"title": "market"},
        context_sources=[],
    )

    assert raw_output["provider"] == "gemini"
    assert raw_output["fallback_used"] is True
    assert raw_output["attempts"][0]["provider"] == "openai"


def test_generate_deepbrief_uses_gemini_directly_when_openai_key_missing(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_ENABLE_FALLBACK", "true")
    monkeypatch.setattr(deepbrief_generator, "GENAI_SDK_AVAILABLE", True)

    def fail_openai(**kwargs):
        raise AssertionError("OpenAI no deberia ejecutarse sin key")

    def fake_gemini(**kwargs):
        return fake_result("gemini", True)

    monkeypatch.setattr(deepbrief_generator, "generate_with_openai", fail_openai)
    monkeypatch.setattr(deepbrief_generator, "generate_with_gemini", fake_gemini)

    _deepbrief, raw_output = deepbrief_generator.generate_deepbrief_for_market(
        market={"title": "market"},
        context_sources=[],
    )

    assert raw_output["provider"] == "gemini"
    assert raw_output["fallback_used"] is True


def test_generate_deepbrief_fails_clearly_when_all_providers_fail(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_ENABLE_FALLBACK", "true")
    monkeypatch.setattr(deepbrief_generator, "GENAI_SDK_AVAILABLE", True)

    def fake_openai(**kwargs):
        raise deepbrief_generator.ProviderGenerationError(
            provider="openai",
            model="gpt-test",
            message="openai timeout",
            attempts=[],
        )

    def fake_gemini(**kwargs):
        raise deepbrief_generator.ProviderGenerationError(
            provider="gemini",
            model="gemini-test",
            message="gemini unavailable",
            attempts=kwargs["prior_attempts"],
        )

    monkeypatch.setattr(deepbrief_generator, "generate_with_openai", fake_openai)
    monkeypatch.setattr(deepbrief_generator, "generate_with_gemini", fake_gemini)

    with pytest.raises(deepbrief_generator.AllDeepBriefProvidersFailedError) as exc_info:
        deepbrief_generator.generate_deepbrief_for_market(
            market={"title": "market"},
            context_sources=[],
        )

    assert "Todos los proveedores LLM fallaron" in str(exc_info.value)
    assert "openai" in str(exc_info.value)
    assert "gemini" in str(exc_info.value)
    assert exc_info.value.classification == "all_llm_providers_failed"


def test_gemini_schema_error_retries_without_response_schema(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("LLM_PRIMARY_PROVIDER", "openai")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_ENABLE_FALLBACK", "true")
    monkeypatch.setattr(deepbrief_generator, "GENAI_SDK_AVAILABLE", True)

    class FakeParsed:
        def model_dump(self):
            return {
                "lectura_clave": "Lectura suficientemente larga",
                "radar_score": 58,
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
                "estela_de_capital": "Capital estable",
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

    class FakeResponse:
        def __init__(self, *, text=None, parsed=None, response_id="resp-1"):
            self.text = text
            self.parsed = parsed
            self.response_id = response_id

    class FakeModels:
        def __init__(self):
            self.calls = 0
            self.configs = []

        def generate_content(self, *, model, contents, config):
            self.calls += 1
            self.configs.append(config)
            if self.calls == 1:
                raise RuntimeError('400 INVALID_ARGUMENT Unknown name "additional_properties"')
            return FakeResponse(parsed=FakeParsed())

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.models = FakeModels()

    class FakeConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    monkeypatch.setattr(deepbrief_generator, "genai", type("GenAI", (), {"Client": FakeClient}))
    monkeypatch.setattr(deepbrief_generator, "genai_types", type("GenAITypes", (), {"GenerateContentConfig": FakeConfig}))

    deepbrief, raw_output = deepbrief_generator.generate_with_gemini(
        market={"title": "market"},
        context_sources=[],
        max_retries=0,
        primary_provider="openai",
        fallback_used=True,
    )

    assert deepbrief["radar_score"] == 58
    assert raw_output["provider"] == "gemini"
    assert raw_output["fallback_used"] is True
