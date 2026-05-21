import pytest
from pydantic import ValidationError

from schemas.deepbrief_schema import DeepBrief


VALID_DEEPBRIEF_MOCK = {
    "lectura_clave": "El mercado muestra una señal cuantitativa moderada.",
    "radar_score": 66,
    "radar_score_breakdown": {
        "movimiento_probabilidad": 2,
        "volumen": 15,
        "liquidez": 15,
        "cercania_cierre": 15,
        "claridad_resolucion": 10,
        "fuerza_narrativa": 7,
        "asimetria_detectada": 7,
        "riesgo_ruido": -5,
    },
    "signal_label": "Watchlist",
    "estela_de_capital": "El volumen y la liquidez muestran actividad suficiente para seguimiento.",
    "entorno_de_senal": {
        "steep_social": "No hay fuente externa verificada para evaluar conversación social.",
        "steep_tecnologico": "No hay factor tecnológico confirmado en el contexto.",
        "steep_economico": "El análisis económico se basa en volumen, liquidez y probabilidad.",
        "steep_ecologico": "No hay factor ecológico relevante en el contexto disponible.",
        "steep_politico_regulatorio": "No hay cambio regulatorio confirmado en el contexto.",
        "sintesis": "La señal depende principalmente de datos de mercado.",
    },
    "corriente_narrativa": "La narrativa se limita a la dirección de probabilidad y actividad del mercado.",
    "filtro_de_ruido": {
        "red_team": "El riesgo principal es extrapolar sin fuentes externas.",
        "sesgos_detectados": "Puede existir sesgo por movimiento reciente de precio.",
        "riesgo_liquidez": "La liquidez debe compararse contra el tamaño del mercado.",
        "riesgo_resolucion": "La resolución depende de las reglas descritas por el mercado.",
        "informacion_ya_descontada": "No se puede confirmar información externa descontada.",
    },
    "premortem": {
        "si_la_tesis_falla_probablemente_seria_por": "La probabilidad cambia bruscamente contra la lectura inicial.",
        "senales_tempranas_de_invalidacion": [
            "Cambio fuerte de probabilidad",
            "Caída relevante de liquidez",
        ],
    },
    "mapa_de_ruptura": {
        "confirmacion": "Movimiento sostenido de probabilidad con volumen suficiente.",
        "ruptura_alcista": "Aumento relevante de probabilidad.",
        "ruptura_bajista": "Caída relevante de probabilidad.",
        "invalidacion": "Cambio contrario a la tesis inicial.",
        "evento_detonador": "Actualización directa en la fuente de resolución.",
    },
    "mapa_de_escenarios": [
        {
            "escenario": "Base",
            "probabilidad_interna": "50%",
            "descripcion": "El mercado se mantiene cerca del nivel actual.",
            "impacto_en_mercado": "La probabilidad permanece estable.",
        },
        {
            "escenario": "Ruptura",
            "probabilidad_interna": "65%",
            "descripcion": "El mercado rompe al alza con volumen suficiente.",
            "impacto_en_mercado": "La probabilidad aumenta de forma relevante.",
        },
        {
            "escenario": "Contrario",
            "probabilidad_interna": "35%",
            "descripcion": "El mercado revierte el movimiento reciente.",
            "impacto_en_mercado": "La probabilidad cae contra la lectura inicial.",
        },
    ],
    "actualizacion_bayesiana": {
        "probabilidad_actual_del_mercado": "42%",
        "lectura_deepsignal": "La lectura sugiere mantener vigilancia.",
        "direccion_sugerida_del_update": "mantener",
        "razon": "El movimiento reciente no justifica una lectura fuerte.",
    },
    "deepsignal_verdict": "Mercado en vigilancia con señal cuantitativa moderada.",
    "confidence_level": "Medium",
    "watch_triggers": [
        "Cambio de probabilidad mayor a 3 puntos",
        "Variación relevante en liquidez",
    ],
}


def test_valid_deepbrief_schema():
    deepbrief = DeepBrief.model_validate(VALID_DEEPBRIEF_MOCK)

    assert deepbrief.radar_score == 66
    assert deepbrief.signal_label == "Watchlist"
    assert len(deepbrief.mapa_de_escenarios) == 3


def test_rejects_invalid_radar_score():
    invalid = VALID_DEEPBRIEF_MOCK.copy()
    invalid["radar_score"] = 101

    with pytest.raises(ValidationError):
        DeepBrief.model_validate(invalid)


def test_rejects_missing_required_field():
    invalid = VALID_DEEPBRIEF_MOCK.copy()
    invalid.pop("lectura_clave")

    with pytest.raises(ValidationError):
        DeepBrief.model_validate(invalid)


def test_rejects_wrong_scenario_order():
    invalid = VALID_DEEPBRIEF_MOCK.copy()
    invalid["mapa_de_escenarios"] = [
        VALID_DEEPBRIEF_MOCK["mapa_de_escenarios"][1],
        VALID_DEEPBRIEF_MOCK["mapa_de_escenarios"][0],
        VALID_DEEPBRIEF_MOCK["mapa_de_escenarios"][2],
    ]

    with pytest.raises(ValidationError):
        DeepBrief.model_validate(invalid)