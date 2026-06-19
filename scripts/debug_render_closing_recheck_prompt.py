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
    title = "Will Abelardo de la Espriella win the 2026 Colombian presidential election?"

    market = {
        "marketId": market_id,
        "title": title,
        "category": "politica",
        "closingTime": "2026-06-21T14:00:00.000Z",
        "closingLabel": "2d",
        "daysToClose": 2,
    }

    previous_analysis = {
        "analysisId": "fdf72f74-d135-43ce-821f-87951d167fec",
        "generatedAt": "2026-06-14T18:04:33.61033+00:00",
        "thesis": (
            "La señal favorece a Abelardo de la Espriella con ventaja alta en el mercado y "
            "una suba reciente de probabilidad, pero la evidencia externa incluida sigue siendo "
            "limitada y no totalmente verificable. La lectura es de continuidad alcista moderada, "
            "con riesgo de que parte del movimiento ya esté descontado."
        ),
        "signalLabel": "Strong Watch",
        "radarScore": 68,
        "probability": 89.5,
        "modules": {
            "lectura_clave": "La ventaja seguia alta, pero sin confirmacion fuerte de cierre.",
            "deepsignal_verdict": "Continuidad alcista moderada con riesgo de descuento parcial.",
        },
        "radarBreakdown": {
            "movimiento_probabilidad": 8,
            "volumen": 8,
            "liquidez": 9,
            "cercania_cierre": 8,
            "claridad_resolucion": 8,
            "fuerza_narrativa": 9,
            "asimetria_detectada": 9,
            "riesgo_ruido": 4,
        },
        "hybridScoreBreakdown": {
            "preliminary_radar_score": 67,
            "ai_interpretive_score": 68,
            "final_radar_score": 68,
        },
    }

    latest_analysis = {
        "analysisId": "4819fa5f-ab9c-4840-b21d-15a78ce1eccc",
        "generatedAt": "2026-06-15T08:00:05.458637+00:00",
        "thesis": (
            "La señal favorece a Abelardo de la Espriella con ventaja de mercado alta, pero con "
            "ruido no trivial: la probabilidad cayó levemente en 24h y la evidencia externa incluida "
            "es limitada y parcialmente indirecta. El mercado ya parece haber incorporado una narrativa "
            "favorable de derecha/populismo, pero aún no hay confirmación suficiente para tratarlo como "
            "cierre de tesis."
        ),
        "signalLabel": "Strong Watch",
        "radarScore": 68,
        "probability": 87.5,
        "modules": {
            "lectura_clave": "La ventaja seguia alta, pero la lectura ya mostraba ruido de cierre.",
            "deepsignal_verdict": "La tesis sigue viva, aunque no cierra con confirmacion plena.",
        },
        "radarBreakdown": {
            "movimiento_probabilidad": 8,
            "volumen": 8,
            "liquidez": 9,
            "cercania_cierre": 8,
            "claridad_resolucion": 8,
            "fuerza_narrativa": 9,
            "asimetria_detectada": 9,
            "riesgo_ruido": 4,
        },
        "hybridScoreBreakdown": {
            "preliminary_radar_score": 67,
            "ai_interpretive_score": 68,
            "final_radar_score": 68,
        },
    }

    return {
        "market": market,
        "previousAnalysis": previous_analysis,
        "latestAnalysis": latest_analysis,
        "deltas": {
            "probabilityChangeSincePreviousAnalysis": -2,
            "radarScoreChangeSincePreviousAnalysis": 0,
            "probabilityChange24h": -2,
        },
        "recheckCandidate": {
            "recheckStatus": "STILL_VALID",
            "recheckPriority": "MEDIUM",
            "recheckReasons": [
                "closes_in_2d",
                "probability_delta_-2.0pts",
                "radar_delta_0.0pts",
                "high_radar_score",
                "thesis_still_valid",
            ],
        },
        "capitalTrail": {
            "status": "strong",
            "summary": "Capital trail remains supportive but not decisive.",
            "lastObservedAt": "2026-06-15T07:45:00+00:00",
        },
        "marketSnapshot": {
            "marketId": market_id,
            "title": title,
            "current_probability": 87.5,
            "previous_probability_24h": 89.5,
            "probability_change_24h": -2,
            "volume": 1845000,
            "liquidity": 412300,
            "outcomes": ["Yes", "No"],
            "score_breakdown": {
                "volume_score": 8,
                "liquidity_score": 10,
                "time_to_close_score": 8,
                "probability_movement_score": 8,
                "resolution_score": 8,
                "narrative_score": 9,
            },
        },
    }


def validate_rendered_prompt(prompt: str) -> None:
    required_phrases = [
        "Will Abelardo de la Espriella win the 2026 Colombian presidential election?",
        "La señal favorece a Abelardo de la Espriella con ventaja alta en el mercado",
        "La señal favorece a Abelardo de la Espriella con ventaja de mercado alta",
        "68",
        "87.5",
        "89.5",
        "-2",
        "2d",
        "STILL_VALID",
        "MEDIUM",
        "Metodologias internas obligatorias",
        "Las probabilidades del input vienen expresadas en puntos porcentuales de 0 a 100.",
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

    if prompt.count("Metodologias internas obligatorias") != 1:
        raise RuntimeError("Los criterios DeepEngine aparecen duplicados o ausentes.")

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
