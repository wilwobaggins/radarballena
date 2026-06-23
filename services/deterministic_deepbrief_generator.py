from __future__ import annotations

from typing import Any

from services.deepbrief_schema import DeepBriefSchema
from services.logger_service import get_logger
from services.scoring_service import days_to_close, safe_float


logger = get_logger("deterministic_deepbrief_generator")


def _text_or(value: Any, fallback: str) -> str:
    text = str(value).strip() if value not in (None, "") else ""
    return text or fallback


def _number_text(value: Any, *, decimals: int = 1) -> str:
    if value in (None, ""):
        return "dato no disponible"

    number = safe_float(value, default=float("nan"))
    if number != number:
        return "dato no disponible"

    if decimals == 0:
        return str(int(round(number)))

    return f"{number:.{decimals}f}".rstrip("0").rstrip(".")


def _percentage_points_text(value: Any, *, decimals: int = 1) -> str:
    if value in (None, ""):
        return "dato no disponible"

    number = safe_float(value, default=float("nan"))
    if number != number:
        return "dato no disponible"

    return f"{number * 100:.{decimals}f}"


def _closing_date_text(market: dict[str, Any]) -> str:
    closing_date = market.get("close_date") or market.get("closingTime") or market.get("closeDate")
    if closing_date:
        return _text_or(closing_date, "fecha de cierre no disponible")
    return "fecha de cierre no disponible"


def _build_signal_label(score: float) -> str:
    if score < 30:
        return "Ignore"
    if score < 50:
        return "Watchlist"
    if score < 70:
        return "Strong Watch"
    return "High Conviction"


def _normalize_breakdown(score_breakdown: dict[str, Any]) -> dict[str, int]:
    keys = (
        "movimiento_probabilidad",
        "volumen",
        "liquidez",
        "cercania_cierre",
        "claridad_resolucion",
        "fuerza_narrativa",
        "asimetria_detectada",
        "riesgo_ruido",
    )

    normalized: dict[str, int] = {}
    for key in keys:
        normalized[key] = int(round(safe_float(score_breakdown.get(key), default=0.0)))
    return normalized


def _build_environment_section(market: dict[str, Any]) -> dict[str, str]:
    volume = market.get("volume")
    liquidity = market.get("liquidity")
    movement = market.get("probability_change_24h")
    close_days = days_to_close(market)

    volume_band = "alta" if safe_float(volume) >= 250000 else "moderada" if safe_float(volume) >= 50000 else "baja" if safe_float(volume) > 0 else "sin"

    return {
        "steep_social": "No evaluado sin IA.",
        "steep_tecnologico": "No evaluado sin IA.",
        "steep_economico": (
            f"Resumen cuantitativo basado en volumen {_number_text(volume, decimals=0)}, "
            f"liquidez {_number_text(liquidity, decimals=0)} y cambio de probabilidad {_percentage_points_text(movement, decimals=1)} puntos porcentuales."
        ),
        "steep_ecologico": "No evaluado sin IA.",
        "steep_politico_regulatorio": "No evaluado sin IA.",
        "sintesis": (
            f"Mercado con actividad {volume_band}, liquidez {_number_text(liquidity, decimals=0)} y {_closing_date_text(market)}."
        ),
    }


def _build_noise_filter(market: dict[str, Any]) -> dict[str, str]:
    volume = safe_float(market.get("volume"), default=0.0)
    liquidity = safe_float(market.get("liquidity"), default=0.0)
    movement = safe_float(market.get("probability_change_24h"), default=0.0)
    close_days = days_to_close(market)

    return {
        "red_team": "No se infieren noticias, ballenas ni narrativas externas en modo determinístico.",
        "sesgos_detectados": "Riesgo de sobreleer el movimiento reciente sin confirmación externa.",
        "riesgo_liquidez": "Baja liquidez" if liquidity and liquidity < 10000 else "Liquidez suficiente o dato no disponible",
        "riesgo_resolucion": (
            "Resolución ambigua o dato no disponible"
            if not market.get("description") or not market.get("outcomes")
            else "Resolución relativamente clara por los datos disponibles"
        ),
        "informacion_ya_descontada": (
            f"Movimiento de probabilidad de {_percentage_points_text(movement, decimals=1)} puntos porcentuales, "
            f"volumen {_number_text(volume, decimals=0)}, liquidez {_number_text(liquidity, decimals=0)} y cierre cercano: {'sí' if close_days <= 1 else 'no'}."
        ),
    }


def _build_premortem(market: dict[str, Any]) -> dict[str, Any]:
    close_days = days_to_close(market)
    return {
        "si_la_tesis_falla_probablemente_seria_por": "baja liquidez, falta de volumen, movimiento no confirmado, cierre próximo, resolución poco clara o datos desactualizados",
        "senales_tempranas_de_invalidacion": [
            "probabilidad cambia en contra de la lectura inicial",
            "volumen cae o no confirma el movimiento",
            "liquidez se deteriora",
            f"quedan {close_days} días o menos para el cierre" if close_days <= 1 else "se acerca el cierre sin confirmación adicional",
        ],
    }


def _build_breakout_map(market: dict[str, Any]) -> dict[str, str]:
    movement = abs(safe_float(market.get("probability_change_24h"), default=0.0))
    close_days = days_to_close(market)

    return {
        "confirmacion": f"Cambio de probabilidad superior a {max(3.0, round(movement or 3.0, 1))} puntos con volumen estable.",
        "ruptura_alcista": "Aumento de probabilidad, volumen creciente y liquidez no deteriorada.",
        "ruptura_bajista": "Caída de probabilidad, volumen decreciente o liquidez deteriorada.",
        "invalidacion": "Cambio contrario sostenido o falta de confirmación del movimiento inicial.",
        "evento_detonador": (
            "Últimas 24 horas antes del cierre si close_date está disponible"
            if close_days <= 1
            else f"Variación de volumen superior a 50% o cambio de probabilidad de {max(5.0, round(movement or 5.0, 1))} puntos porcentuales"
        ),
    }


def _build_scenarios(market: dict[str, Any]) -> list[dict[str, str]]:
    movement = abs(safe_float(market.get("probability_change_24h"), default=0.0))
    volume = safe_float(market.get("volume"), default=0.0)
    close_days = days_to_close(market)

    return [
        {
            "escenario": "Base",
            "probabilidad_interna": "50%",
            "descripcion": f"El mercado mantiene un comportamiento estable con movimiento limitado ({movement * 100:.1f} puntos porcentuales si aplica).",
            "impacto_en_mercado": "No hay ruptura cuantitativa clara.",
        },
        {
            "escenario": "Ruptura",
            "probabilidad_interna": "65%",
            "descripcion": f"Se activa si la probabilidad cambia más de {max(5.0, round((movement or 0) * 100, 1))} puntos porcentuales y el volumen supera {_number_text(volume * 1.5 if volume else 0, decimals=0)}.",
            "impacto_en_mercado": "La lectura cuantitativa se fortalece sin necesidad de narrativa externa.",
        },
        {
            "escenario": "Contrario",
            "probabilidad_interna": "35%",
            "descripcion": (
                "Se activa si la probabilidad revierte contra la tendencia, la liquidez cae o el mercado entra en las últimas 24 horas antes del cierre"
                if close_days <= 1
                else "Se activa si la probabilidad revierte contra la tendencia o la liquidez cae."
            ),
            "impacto_en_mercado": "La lectura preliminar pierde soporte cuantitativo.",
        },
    ]


def _build_bayesian_update(market: dict[str, Any]) -> dict[str, str]:
    movement = safe_float(market.get("probability_change_24h"), default=0.0)
    direction = "mantener"
    if movement >= 5:
        direction = "subir"
    elif movement <= -5:
        direction = "bajar"

    return {
        "probabilidad_actual_del_mercado": _number_text(market.get("current_probability"), decimals=1),
        "lectura_deepsignal": "No existe actualización interpretativa mediante IA.",
        "direccion_sugerida_del_update": direction,
        "razon": "No existe actualización interpretativa mediante IA. La sugerencia se deriva únicamente del cambio cuantitativo observado.",
    }


def _build_watch_triggers(market: dict[str, Any]) -> list[str]:
    triggers: list[str] = []
    movement = abs(safe_float(market.get("probability_change_24h"), default=0.0))
    volume = safe_float(market.get("volume"), default=0.0)
    liquidity = safe_float(market.get("liquidity"), default=0.0)
    close_days = days_to_close(market)

    if movement > 5:
        triggers.append("La probabilidad cambia más de 5 puntos.")
    if volume and volume > 0:
        triggers.append("El volumen aumenta más de 50% respecto a la base de referencia disponible.")
    if liquidity and liquidity < 10000:
        triggers.append("La liquidez cae por debajo de 10,000.")
    if close_days <= 1:
        triggers.append("Faltan menos de 24 horas para el cierre.")
    if not triggers:
        triggers.append("Monitorear variaciones adicionales de probabilidad, volumen y liquidez.")

    return triggers[:5]


def build_deterministic_raw_output(
    *,
    market: dict[str, Any],
    preliminary_score: float,
    score_breakdown: dict[str, Any],
    fallback_reason: str,
) -> dict[str, Any]:
    close_date = market.get("close_date") or market.get("closingTime") or market.get("closeDate")
    return {
        "provider": "deterministic",
        "model": "none",
        "fallback_used": True,
        "generation_mode": "deterministic_fallback",
        "needs_ai_refresh": True,
        "fallback_reason": fallback_reason,
        "deterministic_version": "v1",
        "market_input": {
            "title": market.get("title"),
            "description": market.get("description"),
            "category": market.get("category"),
            "current_probability": market.get("current_probability"),
            "previous_probability_24h": market.get("previous_probability_24h"),
            "probability_change_24h": market.get("probability_change_24h"),
            "volume": market.get("volume"),
            "liquidity": market.get("liquidity"),
            "close_date": close_date,
            "days_to_close": None if not close_date else days_to_close(market),
            "outcomes": market.get("outcomes"),
            "selection_reason": market.get("selection_reason"),
        },
        "score_breakdown": score_breakdown,
        "context_sources": [],
        "prompt": None,
        "response_id": None,
        "preliminary_score": preliminary_score,
    }


def generate_deterministic_deepbrief(
    *,
    market: dict[str, Any],
    preliminary_score: float,
    score_breakdown: dict[str, Any],
    selection_reason: str | None = None,
    fallback_reason: str = "all_llm_providers_unavailable",
) -> dict[str, Any]:
    score = int(round(safe_float(preliminary_score, default=0.0)))
    score = max(0, min(score, 100))
    normalized_breakdown = _normalize_breakdown(score_breakdown or {})
    volume_text = _number_text(market.get("volume"), decimals=0)
    liquidity_text = _number_text(market.get("liquidity"), decimals=0)
    movement_text = _percentage_points_text(market.get("probability_change_24h"), decimals=1)
    selection_text = selection_reason or market.get("selection_reason") or "Sin razón de selección específica."

    deepbrief_payload = {
        "lectura_clave": (
            f"El mercado presenta un Radar Score preliminar de {score}, volumen {volume_text}, liquidez {liquidity_text} y cambio de probabilidad de {movement_text} puntos porcentuales en 24 horas. "
            "Este resultado no incluye interpretación mediante IA."
        ),
        "radar_score": score,
        "radar_score_breakdown": normalized_breakdown,
        "signal_label": _build_signal_label(score),
        "estela_de_capital": (
            "No evaluada sin IA ni datos específicos de Smart Money. "
            f"La lectura disponible se limita a volumen {volume_text} y liquidez {liquidity_text}."
        ),
        "entorno_de_senal": _build_environment_section(market),
        "corriente_narrativa": "No evaluada sin IA. No se infieren narrativas externas en el modo determinístico.",
        "filtro_de_ruido": _build_noise_filter(market),
        "premortem": _build_premortem(market),
        "mapa_de_ruptura": _build_breakout_map(market),
        "mapa_de_escenarios": _build_scenarios(market),
        "actualizacion_bayesiana": _build_bayesian_update(market),
        "deepsignal_verdict": "Análisis básico automático basado únicamente en métricas cuantitativas. Pendiente de enriquecimiento mediante IA.",
        "confidence_level": "Low",
        "watch_triggers": _build_watch_triggers(market),
        "prediction_audit": {
            "predicted_outcome": "no_call",
            "predicted_probability": None,
            "expected_direction": None,
            "prediction_confidence": None,
            "prediction_reasoning_summary": "No se emite predicción direccional en modo determinístico.",
        },
    }

    logger.info(
        "Deterministic deepbrief generated | title=%s | score=%s | triggers=%s",
        market.get("title"),
        score,
        len(deepbrief_payload["watch_triggers"]),
    )

    return DeepBriefSchema.model_validate(deepbrief_payload)
