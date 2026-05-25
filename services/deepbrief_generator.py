import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from services.deepbrief_schema import DeepBriefSchema


load_dotenv()


def format_context_sources(
    context_sources: list[dict[str, Any]] | None,
) -> str:
    if not context_sources:
        return (
            "No hay fuentes externas verificadas para este mercado. "
            "El análisis debe tratar esto como una limitación explícita."
        )

    blocks = []

    for index, source in enumerate(context_sources, start=1):
        blocks.append(
            f"""
Fuente {index}:
- Título: {source.get("sourceTitle") or source.get("source_title")}
- URL: {source.get("sourceUrl") or source.get("source_url")}
- Fecha: {source.get("publishedDate") or source.get("published_date")}
- Resumen: {source.get("summary")}
- Relevancia: {source.get("relevanceScore") or source.get("relevance_score")}
"""
        )

    return "\n".join(blocks)


def build_deepbrief_prompt(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None = None,
) -> str:
    formatted_context = format_context_sources(context_sources)

    return f"""
Genera un DeepBrief analítico para el siguiente mercado de predicción.

Usa SOLO la información disponible del mercado y las fuentes externas incluidas abajo.
No inventes datos externos específicos.
Si falta información, dilo como limitación dentro del análisis.

Mercado:
- Título: {market.get("title")}
- Descripción: {market.get("description")}
- Categoría: {market.get("category")}
- URL: {market.get("url")}
- Fecha de cierre: {market.get("close_date")}
- Probabilidad actual: {market.get("current_probability")}
- Probabilidad previa 24h: {market.get("previous_probability_24h")}
- Cambio 24h: {market.get("probability_change_24h")}
- Volumen: {market.get("volume")}
- Liquidez: {market.get("liquidity")}
- Outcomes: {market.get("outcomes")}

Contexto externo:
{formatted_context}

Instrucciones:
- Evalúa señal, ruido, liquidez, narrativa, escenarios y riesgos.
- Usa las fuentes externas solo si son relevantes para el mercado.
- Distingue entre información nueva, información posiblemente ya descontada y ruido.
- Incluye fechas y URLs cuando el contexto externo influya en la lectura.
- Si las fuentes externas son débiles o poco relacionadas, dilo claramente.
- No afirmes que algo es cierto si la fuente solo lo sugiere.
- El radar_score debe estar entre 0 y 100.
- signal_label debe ser uno de estos valores aproximados: Ignore, Watchlist, Strong Watch, High Conviction.
- confidence_level debe ser Low, Medium o High.
- Responde siguiendo exactamente el schema solicitado.
"""


def generate_deepbrief_for_market(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    prompt = build_deepbrief_prompt(
        market=market,
        context_sources=context_sources,
    )

    response = client.responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "Eres DeepSignal Engine, un analista de mercados predictivos. "
                    "Tu trabajo es generar DeepBriefs estructurados, prudentes y útiles. "
                    "No inventes datos externos no incluidos en el input. "
                    "Cuando uses contexto externo, menciona su relevancia, fecha o URL si aplica. "
                    "Distingue información nueva, información ya descontada y ruido."
                ),
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        text_format=DeepBriefSchema,
    )

    parsed = response.output_parsed

    if parsed is None:
        raise RuntimeError("El modelo no regresó un DeepBrief válido")

    deepbrief = parsed.model_dump()

    raw_output = {
        "model": model,
        "market_input": market,
        "context_sources": context_sources or [],
        "prompt": prompt,
        "parsed_output": deepbrief,
        "response_id": getattr(response, "id", None),
    }

    return deepbrief, raw_output