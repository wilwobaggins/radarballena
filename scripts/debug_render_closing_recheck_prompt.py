import argparse
import sys
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.closing_recheck_prompt_builder import build_closing_recheck_prompt


DEFAULT_MARKET_ID = "e4fdcd9b-12e8-457f-9617-6f9b062c305b"
DEFAULT_OUTPUT_PATH = Path("output") / "debug_closing_recheck_prompt.txt"


def build_debug_input(market_id: str) -> dict[str, Any]:
    """
    Local debug fixture that mirrors the structure expected from
    /api/deepsignal/closing-recheck-candidates.
    """
    title = "Will the Fed cut rates before the September close?"

    market = {
        "marketId": market_id,
        "title": title,
        "category": "macro",
        "closingTime": "2026-06-22T18:00:00Z",
        "daysToClose": 3,
    }

    previous_analysis = {
        "analysisId": "deepbrief-prev-20260617",
        "generatedAt": "2026-06-17T14:20:00Z",
        "thesis": (
            "The market was still noisy, but the odds of a near-term policy move "
            "were beginning to matter more than background macro chatter."
        ),
        "signalLabel": "Watchlist",
        "radarScore": 61,
        "probability": 0.54,
        "modules": {
            "lectura_clave": "Weak but improving setup near the close.",
            "deepsignal_verdict": "Monitor rather than act aggressively.",
        },
        "radarBreakdown": {
            "movimiento_probabilidad": 7,
            "volumen": 8,
            "liquidez": 10,
            "cercania_cierre": 7,
            "claridad_resolucion": 8,
            "fuerza_narrativa": 9,
            "asimetria_detectada": 8,
            "riesgo_ruido": 4,
        },
        "hybridScoreBreakdown": {
            "preliminary_radar_score": 58,
            "ai_interpretive_score": 61,
            "final_radar_score": 60,
        },
    }

    latest_analysis = {
        "analysisId": "deepbrief-latest-20260619",
        "generatedAt": "2026-06-19T11:05:00Z",
        "thesis": (
            "The latest snapshot suggests the market has become cleaner: the near-term "
            "close matters more, and probability movement is now directionally consistent."
        ),
        "signalLabel": "Directional Edge",
        "radarScore": 69,
        "probability": 0.63,
        "modules": {
            "lectura_clave": "Better defined setup with less noise than the prior pass.",
            "deepsignal_verdict": "The thesis is still alive and modestly stronger.",
        },
        "radarBreakdown": {
            "movimiento_probabilidad": 10,
            "volumen": 8,
            "liquidez": 10,
            "cercania_cierre": 8,
            "claridad_resolucion": 9,
            "fuerza_narrativa": 10,
            "asimetria_detectada": 9,
            "riesgo_ruido": 5,
        },
        "hybridScoreBreakdown": {
            "preliminary_radar_score": 62,
            "ai_interpretive_score": 69,
            "final_radar_score": 66,
        },
    }

    return {
        "market": market,
        "previousAnalysis": previous_analysis,
        "latestAnalysis": latest_analysis,
        "deltas": {
            "probabilityChangeSincePreviousAnalysis": 0.09,
            "radarScoreChangeSincePreviousAnalysis": 8,
            "probabilityChange24h": 0.04,
        },
        "recheckCandidate": {
            "recheckStatus": "STILL_VALID",
            "recheckPriority": "HIGH",
            "recheckReasons": [
                "The market is inside the closing window.",
                "The latest analysis shows cleaner signal quality.",
                "Probability moved in the same direction as the thesis.",
            ],
        },
        "capitalTrail": {
            "status": "strong",
            "summary": "Capital trail remains present and supportive, but not decisive.",
            "lastObservedAt": "2026-06-19T10:50:00Z",
        },
        "marketSnapshot": {
            "marketId": market_id,
            "title": title,
            "current_probability": 0.63,
            "previous_probability_24h": 0.59,
            "probability_change_24h": 0.04,
            "volume": 1845000,
            "liquidity": 412300,
            "outcomes": ["Yes", "No"],
            "score_breakdown": {
                "volume_score": 8,
                "liquidity_score": 10,
                "time_to_close_score": 8,
                "probability_movement_score": 9,
                "resolution_score": 9,
                "narrative_score": 10,
            },
        },
    }


def validate_rendered_prompt(prompt: str) -> None:
    required_phrases = [
        "Will the Fed cut rates before the September close?",
        "The market was still noisy",
        "The latest snapshot suggests the market has become cleaner",
        "61",
        "69",
        "Metodologias internas obligatorias",
        "probabilityChangeSincePreviousAnalysis",
        "radarScoreChangeSincePreviousAnalysis",
        "daysToClose",
        "recheckStatus",
        "recheckPriority",
        "recheckReasons",
        "newRadarScore",
        "scoreChangeReasons",
    ]

    missing = [phrase for phrase in required_phrases if phrase not in prompt]

    if missing:
        raise RuntimeError(
            "El prompt renderizado no contiene estas piezas esperadas: "
            + ", ".join(missing)
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render local debug prompt for closing recheck comparative mode."
    )
    parser.add_argument(
        "--market-id",
        default=DEFAULT_MARKET_ID,
        help="Market ID candidato a usar en el fixture de debug.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Ruta donde guardar el prompt renderizado. Si falla, se imprime en consola.",
    )

    args = parser.parse_args()

    input_data = build_debug_input(args.market_id)
    prompt, prompt_source = build_closing_recheck_prompt(
        market=input_data["market"],
        previous_analysis=input_data["previousAnalysis"],
        latest_analysis=input_data["latestAnalysis"],
        deltas=input_data["deltas"],
        recheck_candidate=input_data["recheckCandidate"],
        capital_trail=input_data["capitalTrail"],
        market_snapshot=input_data["marketSnapshot"],
    )

    validate_rendered_prompt(prompt)

    output_path = Path(args.output)
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(prompt, encoding="utf-8")
        print(f"Prompt renderizado guardado en: {output_path}")
    except Exception as error:
        print(f"No se pudo guardar el archivo de salida ({error}).")
        print("Imprimiendo prompt en consola.")
        print(prompt)

    print(f"Prompt source: {prompt_source}")
    print(f"Market ID: {args.market_id}")
    print("Validacion de contenido: OK")


if __name__ == "__main__":
    main()
