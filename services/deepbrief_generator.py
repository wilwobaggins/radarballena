from services.deepbrief_schema import DeepBriefSchema


def generate_deepbrief_for_market(market: dict) -> dict:
    deepbrief = {
        "lectura_clave": f"Análisis preliminar del mercado: {market.get('title')}",
        "radar_score": 60,
        "radar_score_breakdown": {
            "movimiento_probabilidad": 5,
            "volumen": 10,
            "liquidez": 10,
            "cercania_cierre": 10,
            "claridad_resolucion": 10,
            "fuerza_narrativa": 10,
            "asimetria_detectada": 5,
            "riesgo_ruido": 0,
        },
        "signal_label": "Watchlist",
        "estela_de_capital": "Movimiento preliminar basado en volumen y liquidez.",
        "entorno_de_senal": {
            "sintesis": "Entorno preliminar sin análisis externo profundo."
        },
        "corriente_narrativa": "Narrativa inicial pendiente de validación.",
        "filtro_de_ruido": {
            "riesgo_liquidez": "Pendiente de evaluación."
        },
        "premortem": {
            "si_la_tesis_falla_probablemente_seria_por": "Falta de información o baja liquidez.",
            "senales_tempranas_de_invalidacion": []
        },
        "mapa_de_ruptura": {
            "confirmacion": "Pendiente.",
            "ruptura_alcista": "Pendiente.",
            "ruptura_bajista": "Pendiente.",
            "invalidacion": "Pendiente.",
            "evento_detonador": "Pendiente."
        },
        "mapa_de_escenarios": [],
        "actualizacion_bayesiana": {
            "probabilidad_actual_del_mercado": market.get("current_probability"),
            "direccion_sugerida_del_update": "mantener",
            "razon": "Análisis preliminar."
        },
        "deepsignal_verdict": "DeepBrief preliminar generado correctamente.",
        "confidence_level": "Low",
        "watch_triggers": []
    }

    validated = DeepBriefSchema(**deepbrief)
    return validated.model_dump()