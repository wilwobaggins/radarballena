import pytest

from services.deterministic_deepbrief_generator import (
    build_deterministic_raw_output,
    generate_deterministic_deepbrief,
)


def base_market(**overrides):
    market = {
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
    market.update(overrides)
    return market


def test_generates_valid_deterministic_deepbrief_with_full_data():
    market = base_market()
    score_breakdown = {
        "movimiento_probabilidad": 2,
        "volumen": 15,
        "liquidez": 18,
        "cercania_cierre": 10,
        "claridad_resolucion": 9,
        "fuerza_narrativa": 4,
        "asimetria_detectada": 5,
        "riesgo_ruido": 3,
    }

    deepbrief = generate_deterministic_deepbrief(
        market=market,
        preliminary_score=58,
        score_breakdown=score_breakdown,
        selection_reason=market["selection_reason"],
    )

    assert deepbrief.radar_score == 58
    assert deepbrief.prediction_audit.predicted_outcome == "no_call"
    assert deepbrief.prediction_audit.predicted_probability is None
    assert deepbrief.confidence_level == "Low"
    assert len(deepbrief.mapa_de_escenarios) == 3
    assert [item.escenario for item in deepbrief.mapa_de_escenarios] == [
        "Base",
        "Ruptura",
        "Contrario",
    ]
    assert 1 <= len(deepbrief.watch_triggers) <= 5


def test_high_liquidity_and_volume_still_valid():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(volume=900000, liquidity=250000),
        preliminary_score=82,
        score_breakdown={"volumen": 20, "liquidez": 20},
    )

    assert deepbrief.radar_score == 82
    assert deepbrief.signal_label == "High Conviction"


def test_low_liquidity_generates_quantitative_risks():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(liquidity=5000),
        preliminary_score=41,
        score_breakdown={"liquidez": 2},
    )

    assert "baja liquidez" in deepbrief.filtro_de_ruido.riesgo_liquidez.lower()


def test_strong_probability_change_activates_bayesian_direction():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(probability_change_24h=8),
        preliminary_score=67,
        score_breakdown={"movimiento_probabilidad": 18},
    )

    assert deepbrief.actualizacion_bayesiana.direccion_sugerida_del_update == "subir"


def test_no_probability_change_keeps_update_on_hold():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(probability_change_24h=0),
        preliminary_score=49,
        score_breakdown={"movimiento_probabilidad": 0},
    )

    assert deepbrief.actualizacion_bayesiana.direccion_sugerida_del_update == "mantener"


def test_close_to_closing_generates_trigger():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(close_date="2026-06-22T12:00:00+00:00"),
        preliminary_score=61,
        score_breakdown={"cercania_cierre": 15},
    )

    assert any("24 horas" in trigger for trigger in deepbrief.watch_triggers)


def test_handles_null_volume_and_liquidity():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(volume=None, liquidity=None),
        preliminary_score=36,
        score_breakdown={},
    )

    assert "dato no disponible" in deepbrief.lectura_clave.lower()
    assert deepbrief.radar_score == 36


def test_handles_missing_description():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(description=None),
        preliminary_score=44,
        score_breakdown={},
    )

    assert deepbrief.deepsignal_verdict.startswith("Análisis básico automático")
    assert deepbrief.filtro_de_ruido.riesgo_resolucion


def test_handles_missing_close_date():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(close_date=None),
        preliminary_score=52,
        score_breakdown={},
    )

    assert deepbrief.mapa_de_ruptura.evento_detonador
    assert deepbrief.actualizacion_bayesiana.razon.startswith("No existe actualización")


def test_raw_output_metadata_shape():
    raw_output = build_deterministic_raw_output(
        market=base_market(),
        preliminary_score=58,
        score_breakdown={"volumen": 10},
        fallback_reason="all_llm_providers_unavailable",
    )

    assert raw_output["provider"] == "deterministic"
    assert raw_output["model"] == "none"
    assert raw_output["generation_mode"] == "deterministic_fallback"
    assert raw_output["needs_ai_refresh"] is True
    assert raw_output["fallback_used"] is True


def test_module_does_not_require_openai_or_gemini_clients():
    deepbrief = generate_deterministic_deepbrief(
        market=base_market(),
        preliminary_score=58,
        score_breakdown={},
    )

    assert deepbrief.radar_score == 58


def test_no_http_requests_are_made(monkeypatch):
    import requests

    called = {"count": 0}

    def fail_request(*args, **kwargs):
        called["count"] += 1
        raise AssertionError("HTTP request no deberia ocurrir")

    monkeypatch.setattr(requests.sessions.Session, "request", fail_request)

    generate_deterministic_deepbrief(
        market=base_market(),
        preliminary_score=58,
        score_breakdown={},
    )

    assert called["count"] == 0
