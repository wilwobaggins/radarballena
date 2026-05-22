import os
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from services.deepbrief_schema import DeepBriefSchema


load_dotenv()


def build_deepbrief_prompt(market: dict[str, Any]) -> str:
    return f"""
Genera un DeepBrief analítico para el siguiente mercado de predicción.

Usa la información disponible del mercado. No inventes datos externos específicos.
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

Instrucciones:
- Evalúa señal, ruido, liquidez, narrativa, escenarios y riesgos.
- El radar_score debe estar entre 0 y 100.
- signal_label debe ser uno de estos valores aproximados: Ignore, Watchlist, Strong Watch, High Conviction.
- confidence_level debe ser Low, Medium o High.
- Responde siguiendo exactamente el schema solicitado.
"""


def generate_deepbrief_for_market(market: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt = build_deepbrief_prompt(market)

    response = client.responses.parse(
        model=model,
        input=[
            {
                "role": "system",
                "content": (
                    "Eres un analista de mercados predictivos. "
                    "Tu trabajo es generar DeepBriefs estructurados, prudentes y útiles. "
                    "No inventes datos externos no incluidos en el input."
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
        "parsed_output": deepbrief,
        "response_id": getattr(response, "id", None),
    }

    return deepbrief, raw_output