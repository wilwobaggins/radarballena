import argparse
import json
import os
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from scripts.run_daily_pipeline import (
    fetch_markets,
    save_snapshots,
    filter_markets,
    score_market_batch,
    select_top_markets,
    fetch_context,
    build_selection_reason,
)
from services.deepbrief_generator import generate_deepbrief_for_market
from services.scoring_service import calculate_hybrid_radar_score


load_dotenv()

OUTPUT_DIR = Path("model_comparisons")
OUTPUT_DIR.mkdir(exist_ok=True)

MODEL_A = os.getenv("OPENAI_MODEL_A", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
MODEL_B = os.getenv("OPENAI_MODEL_B", "gpt-5.4")
JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL", MODEL_B)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def find_market(markets: list[dict[str, Any]], query: str | None) -> dict[str, Any]:
    if not markets:
        raise RuntimeError("No hay mercados candidatos después de filtros.")

    if not query:
        return markets[0]

    q = query.lower().strip()

    for market in markets:
        possible_values = [
            market.get("id"),
            market.get("marketId"),
            market.get("market_id"),
            market.get("externalMarketId"),
            market.get("external_market_id"),
            market.get("conditionId"),
            market.get("condition_id"),
            market.get("title"),
        ]

        raw_payload = market.get("raw_payload") or {}
        if isinstance(raw_payload, dict):
            possible_values.extend(
                [
                    raw_payload.get("id"),
                    raw_payload.get("marketId"),
                    raw_payload.get("conditionId"),
                    raw_payload.get("question"),
                    raw_payload.get("title"),
                ]
            )

        for value in possible_values:
            if value is not None and q in str(value).lower():
                return market

    raise RuntimeError(f"No encontré mercado que coincida con: {query}")


def generate_with_model(
    model: str,
    market: dict[str, Any],
    context_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    previous_model = os.getenv("OPENAI_MODEL")

    os.environ["OPENAI_MODEL"] = model

    try:
        deepbrief, raw_output = generate_deepbrief_for_market(
            market=deepcopy(market),
            context_sources=deepcopy(context_sources),
        )

        hybrid_score = calculate_hybrid_radar_score(
            preliminary_radar_score=market.get("preliminary_radar_score"),
            ai_interpretive_score=deepbrief.get("radar_score"),
        )

        return {
            "model": model,
            "deepbrief": deepbrief,
            "raw_output": raw_output,
            "hybrid_score": hybrid_score,
        }

    finally:
        if previous_model is None:
            os.environ.pop("OPENAI_MODEL", None)
        else:
            os.environ["OPENAI_MODEL"] = previous_model


def compare_outputs(
    market: dict[str, Any],
    result_a: dict[str, Any],
    result_b: dict[str, Any],
) -> str:
    prompt = f"""
Compara estos dos DeepBriefs generados para el mismo mercado usando el mismo flujo, mismas métricas y mismo contexto.

No evalúes cuál suena más bonito. Evalúa cuál es más útil, más fiel al contexto y más accionable para RadarBallena.

Criterios:
1. Apego al contexto disponible.
2. Profundidad estratégica.
3. Detección de señal vs ruido.
4. Claridad de lectura clave.
5. Prudencia y manejo de incertidumbre.
6. Calidad de escenarios.
7. Calidad de watch triggers.
8. Consistencia entre radarScore, signalLabel y verdict.
9. Riesgo de alucinación.
10. Utilidad para dashboard.

Devuelve texto plano con:
- Ganador general.
- Scores 1-10 por criterio para cada modelo.
- Fortalezas del modelo A.
- Fortalezas del modelo B.
- Debilidades del modelo A.
- Debilidades del modelo B.
- Qué modelo usarías en producción y por qué.

Mercado:
{safe_json({
    "id": market.get("id"),
    "title": market.get("title"),
    "category": market.get("category"),
    "current_probability": market.get("current_probability"),
    "probability_change_24h": market.get("probability_change_24h"),
    "volume": market.get("volume"),
    "liquidity": market.get("liquidity"),
    "preliminary_radar_score": market.get("preliminary_radar_score"),
    "score_breakdown": market.get("score_breakdown"),
})}

Modelo A:
{result_a["model"]}

DeepBrief A:
{safe_json(result_a["deepbrief"])}

Hybrid Score A:
{safe_json(result_a["hybrid_score"])}

Modelo B:
{result_b["model"]}

DeepBrief B:
{safe_json(result_b["deepbrief"])}

Hybrid Score B:
{safe_json(result_b["hybrid_score"])}
"""

    response = client.responses.create(
        model=JUDGE_MODEL,
        input=prompt,
    )

    return response.output_text.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--market",
        help="Opcional: texto, id o parte del título del mercado a probar.",
        default=None,
    )
    parser.add_argument(
        "--rank",
        type=int,
        default=0,
        help="Índice del candidato filtrado/ordenado si no pasas --market. Default 0.",
    )

    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("Falta OPENAI_API_KEY en .env")

    print("Obteniendo mercados con el mismo flujo del pipeline...")
    raw_markets = fetch_markets()

    print("Guardando/upserteando markets y snapshots igual que main...")
    saved_markets = save_snapshots(raw_markets)

    print("Filtrando mercados relevantes...")
    filtered_markets, filter_stats = filter_markets(saved_markets)

    print("Calculando preliminary_radar_score...")
    scored_markets = score_market_batch(filtered_markets)

    print("Seleccionando candidatos top...")
    selected_markets = select_top_markets(scored_markets)

    if not selected_markets:
        raise RuntimeError("No hubo mercados seleccionados para DeepEngine.")

    if args.market:
        market = find_market(selected_markets, args.market)
    else:
        if args.rank < 0 or args.rank >= len(selected_markets):
            raise RuntimeError(
                f"--rank inválido. Hay {len(selected_markets)} candidatos."
            )
        market = selected_markets[args.rank]

    print("\nMercado seleccionado:")
    print(market.get("title"))
    print(build_selection_reason(market))

    print("\nBuscando contexto igual que main...")
    context_sources = fetch_context(market, min_sources=3)

    if len(context_sources) < 3:
        raise RuntimeError(
            f"Contexto insuficiente para test: {len(context_sources)} fuentes."
        )

    print(f"\nGenerando con Modelo A: {MODEL_A}")
    result_a = generate_with_model(MODEL_A, market, context_sources)

    print(f"Generando con Modelo B: {MODEL_B}")
    result_b = generate_with_model(MODEL_B, market, context_sources)

    print(f"Comparando outputs con juez: {JUDGE_MODEL}")
    comparison = compare_outputs(market, result_a, result_b)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_title = "".join(
        c if c.isalnum() else "_"
        for c in str(market.get("title") or "market")[:60]
    )
    output_file = OUTPUT_DIR / f"compare_{timestamp}_{safe_title}.txt"

    report = f"""
COMPARACIÓN DE MODELOS — RADARBALLENA DEEPENGINE
Fecha: {datetime.now().isoformat()}

Modelo A: {MODEL_A}
Modelo B: {MODEL_B}
Modelo juez: {JUDGE_MODEL}

============================================================
MERCADO SELECCIONADO
============================================================

{safe_json(market)}

============================================================
FILTER STATS
============================================================

{safe_json(filter_stats)}

============================================================
SELECTION REASON
============================================================

{build_selection_reason(market)}

============================================================
CONTEXTO USADO
============================================================

{safe_json(context_sources)}

============================================================
OUTPUT MODELO A — {MODEL_A}
============================================================

DeepBrief:
{safe_json(result_a["deepbrief"])}

Hybrid Score:
{safe_json(result_a["hybrid_score"])}

Prompt usado:
{result_a["raw_output"].get("prompt")}

============================================================
OUTPUT MODELO B — {MODEL_B}
============================================================

DeepBrief:
{safe_json(result_b["deepbrief"])}

Hybrid Score:
{safe_json(result_b["hybrid_score"])}

Prompt usado:
{result_b["raw_output"].get("prompt")}

============================================================
COMPARACIÓN
============================================================

{comparison}
"""

    output_file.write_text(report, encoding="utf-8")

    print(f"\nListo. Archivo generado:")
    print(output_file)


if __name__ == "__main__":
    main()