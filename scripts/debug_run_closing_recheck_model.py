import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

try:
    from google import genai
    from google.genai import types as genai_types
except ImportError:
    genai = None
    genai_types = None


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from schemas.closing_recheck_schema import ClosingRecheckModelOutput, ClosingRecheckResult
from services.closing_recheck_repository import (
    compute_prompt_hash,
    save_closing_recheck_result,
)
from services.closing_recheck_scoring import (
    build_current_market_for_scoring,
    calculate_current_hybrid_score,
    calculate_current_preliminary_score,
)
from services.closing_recheck_prompt_builder import build_closing_recheck_prompt
from services.closing_recheck_service import (
    call_closing_recheck_model_with_provider_sequence,
)
from services.scoring_service import get_signal_label_for_final_score
from services.deepbrief_generator import (
    SYSTEM_INSTRUCTION,
    get_provider_model,
    get_provider_sequence,
    is_provider_configured,
    load_json_repair_prompt,
    summarize_exception,
)


load_dotenv()

DEFAULT_MARKET_ID = "e4fdcd9b-12e8-457f-9617-6f9b062c305b"
DEFAULT_OUTPUT_PATH = Path("output") / "debug_closing_recheck_result.json"
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"
CURRENT_MARKET_ID = DEFAULT_MARKET_ID


def build_debug_input(market_id: str) -> dict[str, Any]:
    market = {
            "marketId": market_id,
            "title": "Will Abelardo de la Espriella win the 2026 Colombian presidential election?",
            "category": "politica",
            "closingTime": "2026-06-21T14:00:00.000Z",
            "closingLabel": "2d",
            "daysToClose": 2,
        }

    market_current = {
        **market,
        "probabilityScale": "percent_0_100",
        "current_probability": 87.5,
        "previous_probability_24h": 89.5,
        "probability_change_24h": -2,
        "volume": 1845000,
        "liquidity": 412300,
        "outcomes": ["Yes", "No"],
    }

    return {
        "market": market,
        "market_current": market_current,
        "previousAnalysis": {
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
        },
        "latestAnalysis": {
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
        },
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
            **market_current,
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
        "La señal favorece a Abelardo de la Espriella con ventaja de mercado alta",
        "La señal favorece a Abelardo de la Espriella con ventaja alta en el mercado",
        "87.5",
        "89.5",
        "-2",
        "2d",
        "STILL_VALID",
        "Metodologias internas obligatorias",
        "Las probabilidades del input vienen expresadas en puntos porcentuales de 0 a 100.",
        "newAiInterpretiveScore",
        "new preliminary radar score",
        "score breakdown actual",
        "scoreChangeReasons",
    ]

    missing = [phrase for phrase in required_phrases if phrase not in prompt]

    if prompt.count("Metodologias internas obligatorias") != 1:
        raise RuntimeError("Los criterios DeepEngine aparecen duplicados o ausentes.")

    if "finalRadarScore" in prompt or "calcular el score final" in prompt.lower():
        raise RuntimeError("El prompt no debe pedir al modelo calcular el score final.")

    if missing:
        raise RuntimeError(
            "El prompt renderizado no contiene estas piezas esperadas: "
            + ", ".join(missing)
        )


def call_openai_model(
    *,
    prompt: str,
    model: str,
    max_retries: int,
) -> tuple[dict[str, Any], str]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    last_error = None

    for attempt in range(1, max_retries + 2):
        repair_note = None

        if attempt > 1:
            repair_note = load_json_repair_prompt()
            if last_error:
                repair_note += f"\n\nError anterior:\n{last_error}"

        final_prompt = prompt
        if repair_note:
            final_prompt = f"{prompt}\n\nMODO REPARACION:\n{repair_note}\n"

        try:
            response = client.responses.parse(
                model=model,
                input=[
                    {"role": "system", "content": SYSTEM_INSTRUCTION},
                    {"role": "user", "content": final_prompt},
                ],
                text_format=ClosingRecheckResult,
            )

            parsed = response.output_parsed
            if parsed is None:
                raise RuntimeError("El modelo no devolvio un ClosingRecheckResult valido")

            payload = parsed.model_dump()
            return payload, getattr(response, "id", "")
        except Exception as error:
            last_error = summarize_exception(error)

            if attempt >= max_retries + 1:
                raise RuntimeError(
                    f"OpenAI fallo despues de retries: {last_error}"
                ) from error

    raise RuntimeError("OpenAI fallo de forma inesperada")


def call_gemini_model(
    *,
    prompt: str,
    model: str,
    max_retries: int,
) -> tuple[dict[str, Any], str]:
    if genai is None or genai_types is None:
        raise RuntimeError("SDK google-genai no instalado")

    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    last_error = None

    for attempt in range(1, max_retries + 2):
        repair_note = None

        if attempt > 1:
            repair_note = load_json_repair_prompt()
            if last_error:
                repair_note += f"\n\nError anterior:\n{last_error}"

        final_prompt = prompt
        if repair_note:
            final_prompt = f"{prompt}\n\nMODO REPARACION:\n{repair_note}\n"

        try:
            response = client.models.generate_content(
                model=model,
                contents=final_prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                ),
            )

            parsed_candidate = getattr(response, "parsed", None)
            if parsed_candidate is not None:
                if hasattr(parsed_candidate, "model_dump"):
                    payload = parsed_candidate.model_dump()
                else:
                    payload = parsed_candidate
            else:
                response_text = getattr(response, "text", None)
                if not response_text:
                    raise RuntimeError("Gemini no devolvio texto JSON")
                payload = json.loads(response_text)

            validated = ClosingRecheckResult.model_validate(payload)
            return validated.model_dump(), getattr(response, "response_id", "")
        except Exception as error:
            last_error = summarize_exception(error)

            if attempt >= max_retries + 1:
                raise RuntimeError(
                    f"Gemini fallo despues de retries: {last_error}"
                ) from error

    raise RuntimeError("Gemini fallo de forma inesperada")


def normalize_debug_model_name(provider: str, model: str) -> str:
    if provider == "gemini" and model.strip() == "gemini-2.5":
        return DEFAULT_GEMINI_MODEL

    return model


def call_model_with_provider_sequence(
    *,
    prompt: str,
    max_retries: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate = build_debug_input(CURRENT_MARKET_ID)
    market_current = candidate["market_current"]
    new_preliminary = calculate_current_preliminary_score(candidate)
    prompt_inputs = {
        "market_current": market_current,
        "new_preliminary": new_preliminary,
    }

    payload, raw_output, provider, model = call_closing_recheck_model_with_provider_sequence(
        candidate=candidate,
        new_preliminary=new_preliminary,
        score_parity=None,
        context_source="fresh_context",
        max_retries=max_retries,
    )

    print(
        f"[CLOSING_RECHECK_DEBUG] model_called provider={provider} "
        f"model={model} fallback_used={bool(raw_output.get('fallback_used', False))}"
    )

    return payload, {
        "provider": provider,
        "model": model,
        "response_id": raw_output.get("response_id", ""),
        "fallback_used": bool(raw_output.get("fallback_used", False)),
        "primary_provider": raw_output.get("primary_provider"),
        "market_current": prompt_inputs["market_current"],
        "new_preliminary": prompt_inputs["new_preliminary"],
    }


def persist_result_from_file(input_path: Path) -> dict[str, Any]:
    print(f"[CLOSING_RECHECK_PERSIST_ONLY] reading path={input_path}")

    if not input_path.exists():
        raise SystemExit(f"No existe el archivo indicado en --from-file: {input_path}")

    raw_text = input_path.read_text(encoding="utf-8")

    try:
        loaded_payload = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise SystemExit(f"El JSON de --from-file no es valido: {error}") from error

    validated = ClosingRecheckResult.model_validate(loaded_payload)
    result = validated.model_dump()

    print(
        "[CLOSING_RECHECK_PERSIST_ONLY] schema_validated "
        f"status={result['recheckStatus']} "
        f"newRadarScore={result['reevaluation']['newRadarScore']}"
    )

    prompt_hash = compute_prompt_hash(raw_text)

    print(
        f"[CLOSING_RECHECK_PERSIST] saving marketId={result['marketId']} "
        f"source=manual_debug"
    )

    saved_row = save_closing_recheck_result(
        validated,
        provider=None,
        model=None,
        fallback_used=False,
        prompt_hash=prompt_hash,
        source="manual_debug",
    )
    print(f"[CLOSING_RECHECK_PERSIST] saved id={saved_row.get('id')}")
    return saved_row


def main() -> None:
    global CURRENT_MARKET_ID
    parser = argparse.ArgumentParser(
        description="Run a manual closing recheck model call without persistence."
    )
    parser.add_argument(
        "--market-id",
        default=DEFAULT_MARKET_ID,
        help="Market ID candidato a usar en el fixture de debug.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT_PATH),
        help="Ruta donde guardar el JSON validado.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=1,
        help="Numero de reintentos de reparacion JSON por proveedor.",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Si se incluye, tambien persiste el resultado en Supabase.",
    )
    parser.add_argument(
        "--persist-only",
        action="store_true",
        help="Si se incluye, no llama al modelo y solo persiste un resultado desde archivo.",
    )
    parser.add_argument(
        "--from-file",
        dest="from_file",
        default=None,
        help="Ruta al JSON ya validado que se usara con --persist-only.",
    )

    args = parser.parse_args()
    CURRENT_MARKET_ID = args.market_id

    if args.persist_only and not args.from_file:
        raise SystemExit("--persist-only requiere --from-file <ruta>")

    if args.persist_only:
        try:
            persist_result_from_file(Path(args.from_file))
        except Exception as error:
            print(f"[CLOSING_RECHECK_PERSIST] error={error}")
            raise SystemExit(1) from error

        return

    input_data = build_debug_input(args.market_id)
    current_market = build_current_market_for_scoring(input_data)
    new_preliminary = calculate_current_preliminary_score(input_data)
    score_parity_preview = {
        "formula": "final_radar_score = 0.40 preliminary_radar_score + 0.60 ai_interpretive_score",
        "baselineAnalysisId": input_data["latestAnalysis"]["analysisId"],
        "previousPreliminaryRadarScore": input_data["latestAnalysis"].get("preliminaryRadarScore"),
        "newPreliminaryRadarScore": new_preliminary["preliminary_radar_score"],
        "previousAiInterpretiveScore": input_data["latestAnalysis"].get("aiInterpretiveScore"),
        "newAiInterpretiveScore": None,
        "previousFinalRadarScore": input_data["latestAnalysis"].get("finalRadarScore"),
        "newFinalRadarScore": None,
        "previousScoreBreakdown": input_data["latestAnalysis"].get("score_breakdown"),
        "newScoreBreakdown": new_preliminary["score_breakdown"],
        "hybridScoreBreakdown": None,
    }
    prompt, prompt_source = build_closing_recheck_prompt(
        market_current=current_market,
        new_preliminary_radar_score=new_preliminary["preliminary_radar_score"],
        new_preliminary_score_breakdown=new_preliminary["score_breakdown"],
        previous_analysis=input_data["previousAnalysis"],
        latest_analysis=input_data["latestAnalysis"],
        deltas=input_data["deltas"],
        recheck_candidate=input_data["recheckCandidate"],
        capital_trail=input_data["capitalTrail"],
        market_snapshot=input_data["marketSnapshot"],
        score_parity=score_parity_preview,
        context_source="fresh_context",
    )

    validate_rendered_prompt(prompt)
    print(f"[CLOSING_RECHECK_DEBUG] prompt_built marketId={args.market_id}")

    raw_payload, raw_meta = call_model_with_provider_sequence(
        prompt=prompt,
        max_retries=args.max_retries,
    )
    model_output = ClosingRecheckModelOutput.model_validate(raw_payload)
    new_hybrid = calculate_current_hybrid_score(
        preliminary_radar_score=new_preliminary["preliminary_radar_score"],
        ai_interpretive_score=model_output.newAiInterpretiveScore,
    )
    score_parity = {
        **score_parity_preview,
        "newAiInterpretiveScore": model_output.newAiInterpretiveScore,
        "newFinalRadarScore": new_hybrid["final_radar_score"],
        "aiInterpretiveScoreDelta": None
        if score_parity_preview["previousAiInterpretiveScore"] is None
        else model_output.newAiInterpretiveScore - score_parity_preview["previousAiInterpretiveScore"],
        "finalRadarScoreDelta": None
        if score_parity_preview["previousFinalRadarScore"] is None
        else new_hybrid["final_radar_score"] - score_parity_preview["previousFinalRadarScore"],
        "hybridScoreBreakdown": new_hybrid["score_breakdown"],
    }

    result = {
        "analysisMode": "closing_recheck",
        "marketId": input_data["market"]["marketId"],
        "previousAnalysisId": input_data["previousAnalysis"]["analysisId"],
        "latestAnalysisId": input_data["latestAnalysis"]["analysisId"],
        "closingContext": {
            "daysToClose": current_market.get("daysToClose"),
            "closingTime": current_market.get("close_date") or current_market.get("closingTime"),
        },
        "reevaluation": {
            "previousRadarScore": input_data["latestAnalysis"].get("finalRadarScore"),
            "newRadarScore": new_hybrid["final_radar_score"],
            "radarScoreDelta": None
            if input_data["latestAnalysis"].get("finalRadarScore") is None
            else new_hybrid["final_radar_score"] - input_data["latestAnalysis"].get("finalRadarScore"),
            "previousSignalLabel": input_data["latestAnalysis"].get("signalLabel"),
            "newSignalLabel": get_signal_label_for_final_score(new_hybrid["final_radar_score"]),
            "scoreDirection": "UNCHANGED"
            if input_data["latestAnalysis"].get("finalRadarScore") == new_hybrid["final_radar_score"]
            else ("UP" if new_hybrid["final_radar_score"] > input_data["latestAnalysis"].get("finalRadarScore", 0) else "DOWN"),
            "scoreChangeMagnitude": "LOW",
            "scoreChangeReasons": model_output.whatChanged or [model_output.recommendation],
        },
        "metricBreakdown": {
            "signalStrength": {
                "score": new_hybrid["ai_interpretive_score"],
                "reason": "Derived from the model AI interpretive score.",
            },
            "informationQuality": {
                "score": new_preliminary["score_breakdown"]["resolution_score"],
                "reason": "Derived from code using resolution score.",
            },
            "marketConsistency": {
                "score": new_preliminary["score_breakdown"]["narrative_score"],
                "reason": "Derived from code using narrative score.",
            },
            "timingAndClosureRisk": {
                "score": new_preliminary["score_breakdown"]["time_to_close_score"],
                "reason": "Derived from code using time-to-close score.",
            },
            "noiseRisk": {
                "score": new_preliminary["score_breakdown"]["liquidity_score"],
                "reason": "Derived from code using liquidity score as a noise proxy.",
            },
            "capitalTrailImpact": {
                "score": None,
                "reason": "No capital trail score computed.",
            },
        },
        "comparison": model_output.comparison.model_dump(),
        "recheckStatus": model_output.recheckStatus,
        "importance": input_data["recheckCandidate"]["recheckPriority"],
        "recommendation": model_output.recommendation,
        "thesis": model_output.updatedThesis,
        "confidence": model_output.confidence,
        "riskFlags": model_output.riskFlags,
        "scoreParity": score_parity,
    }

    validated = ClosingRecheckResult.model_validate(result)
    result = validated.model_dump()

    print(
        "[CLOSING_RECHECK_DEBUG] schema_validated "
        f"status={result['recheckStatus']} "
        f"newRadarScore={result['reevaluation']['newRadarScore']} "
        f"newAiInterpretiveScore={model_output.newAiInterpretiveScore}"
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    print(f"[CLOSING_RECHECK_DEBUG] result_written path={output_path}")

    if args.persist:
        prompt_hash = compute_prompt_hash(prompt)
        print(
            f"[CLOSING_RECHECK_PERSIST] saving marketId={result['marketId']} "
            f"source=manual_debug"
        )

        try:
            saved_row = save_closing_recheck_result(
                validated,
                provider=raw_meta.get("provider"),
                model=raw_meta.get("model"),
                fallback_used=bool(raw_meta.get("fallback_used", False)),
                prompt_hash=prompt_hash,
                source="manual_debug",
            )
            print(f"[CLOSING_RECHECK_PERSIST] saved id={saved_row.get('id')}")
        except Exception as error:
            print(f"[CLOSING_RECHECK_PERSIST] error={error}")
            raise SystemExit(1) from error


if __name__ == "__main__":
    main()
