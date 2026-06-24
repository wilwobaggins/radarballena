import sys
import types
from types import SimpleNamespace

import pytest

fake_tavily = types.ModuleType("tavily")
fake_tavily.TavilyClient = object
sys.modules.setdefault("tavily", fake_tavily)

import scripts.run_single_deepbrief as runner


def _market():
    return {
        "id": "market-1",
        "title": "Will China blockade Taiwan by June 30?",
        "category": "geopolitics",
        "deepengine_category": "geopolitics",
        "preliminary_radar_score": 48,
        "score_breakdown": {"movimiento_probabilidad": 8},
        "selection_reason": "test",
        "probability_change_24h": 0.05,
        "volume": 200000,
        "liquidity": 80000,
        "current_probability": 0.52,
        "previous_probability_24h": 0.47,
        "outcomes": ["Yes", "No"],
    }


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
        "rawOutput": {
            "provider": "deterministic",
            "model": "none",
            "fallback_used": True,
            "generation_mode": "deterministic_fallback",
            "needs_ai_refresh": True,
        },
    }


def _patch_common_success(monkeypatch):
    monkeypatch.setattr(runner, "_load_market_row", lambda market_id: _market())
    monkeypatch.setattr(
        runner,
        "_normalize_market_row",
        lambda row: row,
    )
    monkeypatch.setattr(runner, "_score_single_market", lambda market: market)
    monkeypatch.setattr(runner, "_load_existing_context", lambda market_id, minimum_sources: [{"sourceTitle": "s1"}] * minimum_sources)


def test_allow_deterministic_flag_defaults_false():
    parser = runner.build_parser()
    args = parser.parse_args(["--market-id", "11111111-1111-1111-1111-111111111111"])
    assert args.allow_deterministic is False


def test_all_llm_fail_without_allow_deterministic_returns_3(monkeypatch, capsys):
    _patch_common_success(monkeypatch)

    def fail_generate(**kwargs):
        raise runner.AllDeepBriefProvidersFailedError(
            "failed",
            attempts=[{"provider": "openai"}],
            classification="all_llm_providers_failed",
        )

    monkeypatch.setattr(runner, "generate_deepbrief_for_market", fail_generate)
    monkeypatch.setattr(runner, "save_results", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no debe persistir")))

    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_single_deepbrief.py",
            "--market-id",
            "11111111-1111-1111-1111-111111111111",
        ],
    )

    code = runner.main()
    captured = capsys.readouterr()
    assert code == 3
    assert "ALL_LLM_PROVIDERS_FAILED" in captured.err
    assert "DETERMINISTIC_FALLBACK_TEST | allowed=false" in captured.out


def test_all_llm_fail_with_allow_deterministic_no_persist_generates_fallback(monkeypatch, capsys):
    _patch_common_success(monkeypatch)

    def fail_generate(**kwargs):
        raise runner.AllDeepBriefProvidersFailedError(
            "failed",
            attempts=[{"provider": "openai"}],
            classification="all_llm_providers_failed",
        )

    generated = {"called": False}
    monkeypatch.setattr(runner, "generate_deepbrief_for_market", fail_generate)
    monkeypatch.setattr(runner, "calculate_hybrid_radar_score", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no debe calcular 40/60")))
    monkeypatch.setattr(runner, "save_results", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no debe usar save_results")))

    def fake_generate_deterministic_deepbrief(**kwargs):
        generated["called"] = True
        return SimpleNamespace(
            model_dump=lambda: _valid_deepbrief(),
        )

    monkeypatch.setattr(runner, "generate_deterministic_deepbrief", fake_generate_deterministic_deepbrief)

    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_single_deepbrief.py",
            "--market-id",
            "11111111-1111-1111-1111-111111111111",
            "--allow-deterministic",
        ],
    )

    code = runner.main()
    captured = capsys.readouterr()
    assert code == 0
    assert generated["called"] is True
    assert "DETERMINISTIC_FALLBACK_TEST | allowed=true | persist=false" in captured.out
    assert "DETERMINISTIC_FALLBACK_TEST | action=generated" in captured.out
    assert "provider=deterministic" in captured.out
    assert "persisted=false" in captured.out
    assert "deepbrief_id=null" in captured.out


def test_all_llm_fail_with_allow_deterministic_and_persist(monkeypatch, capsys):
    _patch_common_success(monkeypatch)

    def fail_generate(**kwargs):
        raise runner.AllDeepBriefProvidersFailedError(
            "failed",
            attempts=[{"provider": "openai"}],
            classification="all_llm_providers_failed",
        )

    persisted = []
    monkeypatch.setattr(runner, "generate_deepbrief_for_market", fail_generate)
    monkeypatch.setattr(runner, "save_results", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no debe usar save_results")))

    def fake_generate_deterministic_deepbrief(**kwargs):
        return SimpleNamespace(model_dump=lambda: _valid_deepbrief())

    monkeypatch.setattr(runner, "generate_deterministic_deepbrief", fake_generate_deterministic_deepbrief)
    monkeypatch.setattr(
        runner,
        "persist_deterministic_deepbrief",
        lambda **kwargs: persisted.append(kwargs) or {"id": "deepbrief-123"},
    )

    monkeypatch.setattr(
        runner.sys,
        "argv",
        [
            "run_single_deepbrief.py",
            "--market-id",
            "11111111-1111-1111-1111-111111111111",
            "--allow-deterministic",
            "--persist",
        ],
    )

    code = runner.main()
    captured = capsys.readouterr()
    assert code == 0
    assert len(persisted) == 1
    assert persisted[0]["provider_attempts"] == [{"provider": "openai"}]
    assert persisted[0]["fallback_reason"] == "all_llm_providers_failed"
    assert "DETERMINISTIC_FALLBACK_TEST | action=persisted | deepbrief_id=deepbrief-123" in captured.out
