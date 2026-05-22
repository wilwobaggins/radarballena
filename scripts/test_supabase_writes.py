from services.supabase_service import (
    insert_market,
    insert_snapshot,
    insert_deepbrief,
)


MOCK_MARKET = {
    "external_market_id": "test_market_001",
    "platform": "polymarket",
    "title": "Test market from Python",
    "description": "Mercado mock para validar escritura desde Python.",
    "category": "test",
    "url": "https://example.com/test-market",
    "close_date": "2026-12-31T23:59:59Z",
    "current_probability": 0.42,
    "previous_probability_24h": 0.40,
    "probability_change_24h": 0.02,
    "volume": 10000,
    "liquidity": 2500,
    "outcomes": ["Yes", "No"],
    "last_updated": "2026-01-01T00:00:00Z",
}


MOCK_DEEPBRIEF = {
    "lectura_clave": "Mercado mock usado para validar escritura en Supabase.",
    "radar_score": 66,
    "radar_score_breakdown": {
        "movimiento_probabilidad": 4,
        "volumen": 15,
        "liquidez": 10,
        "cercania_cierre": 12,
        "claridad_resolucion": 10,
        "fuerza_narrativa": 8,
        "asimetria_detectada": 7,
        "riesgo_ruido": 0,
    },
    "signal_label": "Watchlist",
    "estela_de_capital": "El mercado mock tiene volumen suficiente para prueba.",
    "entorno_de_senal": {
        "steep_social": "Mock social.",
        "steep_tecnologico": "Mock tecnológico.",
        "steep_economico": "Mock económico.",
        "steep_ecologico": "Mock ecológico.",
        "steep_politico_regulatorio": "Mock regulatorio.",
        "sintesis": "Mock de entorno.",
    },
    "corriente_narrativa": "Narrativa mock.",
    "filtro_de_ruido": {
        "red_team": "Mock red team.",
        "sesgos_detectados": "Mock sesgos.",
        "riesgo_liquidez": "Mock liquidez.",
        "riesgo_resolucion": "Mock resolución.",
        "informacion_ya_descontada": "Mock información descontada.",
    },
    "premortem": {
        "si_la_tesis_falla_probablemente_seria_por": "Mock premortem.",
        "senales_tempranas_de_invalidacion": ["Mock trigger 1", "Mock trigger 2"],
    },
    "mapa_de_ruptura": {
        "confirmacion": "Mock confirmación.",
        "ruptura_alcista": "Mock ruptura alcista.",
        "ruptura_bajista": "Mock ruptura bajista.",
        "invalidacion": "Mock invalidación.",
        "evento_detonador": "Mock detonador.",
    },
    "mapa_de_escenarios": [
        {
            "escenario": "Base",
            "probabilidad_interna": "50%",
            "descripcion": "Mock base.",
            "impacto_en_mercado": "Mock impacto base.",
        },
        {
            "escenario": "Ruptura",
            "probabilidad_interna": "30%",
            "descripcion": "Mock ruptura.",
            "impacto_en_mercado": "Mock impacto ruptura.",
        },
        {
            "escenario": "Contrario",
            "probabilidad_interna": "20%",
            "descripcion": "Mock contrario.",
            "impacto_en_mercado": "Mock impacto contrario.",
        },
    ],
    "actualizacion_bayesiana": {
        "probabilidad_actual_del_mercado": "42%",
        "lectura_deepsignal": "Mock bayesiano.",
        "direccion_sugerida_del_update": "mantener",
        "razon": "Mock razón.",
    },
    "deepsignal_verdict": "Mock verdict.",
    "confidence_level": "Medium",
    "watch_triggers": ["Mock watch trigger"],
}


def main():
    print("Insertando market...")
    market_record = insert_market(MOCK_MARKET)
    print("Market OK:", market_record["id"])

    print("Insertando snapshot...")
    snapshot_record = insert_snapshot(market_record["id"], MOCK_MARKET)
    print("Snapshot OK:", snapshot_record["id"])

    print("Insertando deepbrief...")
    deepbrief_record = insert_deepbrief(
        market_db_id=market_record["id"],
        deepbrief=MOCK_DEEPBRIEF,
        raw_output={"source": "test_supabase_writes.py"},
    )
    print("DeepBrief OK:", deepbrief_record["id"])

    print("Prueba de escritura completa OK.")


if __name__ == "__main__":
    main()