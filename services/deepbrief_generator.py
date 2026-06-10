import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI

from services.deepbrief_schema import DeepBriefSchema
from services.logger_service import get_logger
from services.prompt_service import load_prompt, render_prompt
from services.scoring_service import days_to_close


load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT_DIR / "prompts"

logger = get_logger("deepbrief_generator")

FALLBACK_MASTER_PROMPT = """
Eres DeepSignal Engine, un sistema de inteligencia estrategica para mercados de prediccion.

Tu objetivo es analizar un mercado usando metodologias internas formales, pero entregar el resultado con nombres visibles de RadarBallena.

Metodologias internas obligatorias:
- STEEP Analysis
- Premortem Analysis
- Red Team Analysis
- Scenario Planning
- Weak Signals Analysis
- Narrative Intelligence
- Capital Flow / Market Movement Analysis
- Resolution Risk Analysis
- Bayesian Update
- Catalyst / Trigger Analysis

Reglas estrictas:
- Escribe en espanol.
- No des asesoria financiera.
- No prometas ganancias.
- No uses lenguaje de certeza absoluta.
- No uses lenguaje directo de compra, venta, apuesta o inversion.
- Usa solamente el contexto proporcionado.
- Si no hay fuentes externas verificadas, dilo claramente.
- Devuelve exclusivamente JSON valido.
- No agregues markdown.
- No agregues texto fuera del JSON.

MERCADO:
{{MERCADO}}

CONTEXTO:
{{CONTEXTO}}

METRICAS CALCULADAS:
{{METRICAS}}
""".strip()


def load_json_repair_prompt() -> str:
    prompt_path = PROMPTS_DIR / "json_repair_prompt.txt"

    if not prompt_path.exists():
        return (
            "Corrige la salida anterior. Devuelve una respuesta valida, "
            "compatible con el schema solicitado, sin markdown ni texto extra."
        )

    return prompt_path.read_text(encoding="utf-8")


def load_master_prompt() -> tuple[str, str]:
    prompt_name = "deepbrief_master_prompt.txt"

    try:
        prompt = load_prompt(prompt_name)
        logger.info("Prompt maestro cargado desde archivo: %s", prompt_name)
        return prompt, prompt_name
    except FileNotFoundError:
        logger.warning(
            "No se encontro %s. Usando fallback seguro de prompt maestro.",
            prompt_name,
        )
        return FALLBACK_MASTER_PROMPT, "fallback"


def format_context_sources(
    context_sources: list[dict[str, Any]] | None,
) -> str:
    if not context_sources:
        return (
            "No hay fuentes externas verificadas para este mercado. "
            "El analisis debe tratar esto como una limitacion explicita."
        )

    blocks = []

    for index, source in enumerate(context_sources, start=1):
        blocks.append(
            "\n".join(
                [
                    f"Fuente {index}:",
                    f"- Titulo: {source.get('sourceTitle') or source.get('source_title')}",
                    f"- URL: {source.get('sourceUrl') or source.get('source_url')}",
                    f"- Fecha: {source.get('publishedDate') or source.get('published_date')}",
                    f"- Resumen: {source.get('summary')}",
                    f"- Relevancia: {source.get('relevanceScore') or source.get('relevance_score')}",
                ]
            )
        )

    return "\n\n".join(blocks)


def build_market_section(market: dict[str, Any]) -> str:
    market_payload = {
        "title": market.get("title"),
        "description": market.get("description"),
        "category": market.get("category"),
        "url": market.get("url"),
        "close_date": market.get("close_date"),
        "current_probability": market.get("current_probability"),
        "previous_probability_24h": market.get("previous_probability_24h"),
        "probability_change_24h": market.get("probability_change_24h"),
        "volume": market.get("volume"),
        "liquidity": market.get("liquidity"),
        "outcomes": market.get("outcomes"),
    }
    return json.dumps(market_payload, ensure_ascii=False, indent=2)


def build_metrics_section(market: dict[str, Any]) -> str:
    metrics_payload = {
        "preliminary_radar_score": market.get("preliminary_radar_score"),
        "score_breakdown": market.get("score_breakdown"),
        "days_to_close": days_to_close(market),
        "volume": market.get("volume"),
        "liquidity": market.get("liquidity"),
        "probability_change_24h": market.get("probability_change_24h"),
    }
    return json.dumps(metrics_payload, ensure_ascii=False, indent=2)


def build_deepbrief_prompt(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None = None,
    repair_note: str | None = None,
) -> tuple[str, str]:
    prompt_template, prompt_source = load_master_prompt()
    formatted_context = format_context_sources(context_sources)
    rendered_prompt = render_prompt(
        prompt_template=prompt_template,
        mercado=build_market_section(market),
        contexto=formatted_context,
        metricas=build_metrics_section(market),
    )

    if repair_note:
        rendered_prompt = (
            f"{rendered_prompt}\n\n"
            f"MODO REPARACION:\n{repair_note}\n"
        )

    return rendered_prompt, prompt_source


def generate_deepbrief_for_market(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None = None,
    max_retries: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    max_retries = max_retries or int(os.getenv("DEEPBRIEF_MAX_RETRIES", "2"))

    attempts = []
    last_error = None

    for attempt in range(1, max_retries + 2):
        repair_note = None

        if attempt > 1:
            repair_note = load_json_repair_prompt()

            if last_error:
                repair_note += f"\n\nError anterior:\n{last_error}"

        prompt, prompt_source = build_deepbrief_prompt(
            market=market,
            context_sources=context_sources,
            repair_note=repair_note,
        )

        try:
            response = client.responses.parse(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": (
                            "Eres DeepSignal Engine, un analista de mercados predictivos. "
                            "Tu trabajo es generar DeepBriefs estructurados, prudentes y utiles. "
                            "No inventes datos externos no incluidos en el input. "
                            "Cuando uses contexto externo, menciona su relevancia, fecha o URL si aplica. "
                            "Distingue informacion nueva, informacion ya descontada y ruido."
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
                raise RuntimeError("El modelo no regreso un DeepBrief valido")

            deepbrief = parsed.model_dump()

            raw_output = {
                "status": "ok",
                "model": model,
                "attempts": attempts,
                "attempt_count": attempt,
                "market_input": market,
                "context_sources": context_sources or [],
                "prompt_source": prompt_source,
                "prompt": prompt,
                "parsed_output": deepbrief,
                "response_id": getattr(response, "id", None),
            }

            return deepbrief, raw_output

        except Exception as error:
            last_error = str(error)

            attempts.append(
                {
                    "attempt": attempt,
                    "status": "failed",
                    "error": last_error,
                }
            )

            if attempt >= max_retries + 1:
                raw_output = {
                    "status": "failed",
                    "model": model,
                    "attempts": attempts,
                    "attempt_count": attempt,
                    "market_input": market,
                    "context_sources": context_sources or [],
                    "prompt_source": prompt_source,
                    "last_error": last_error,
                }

                raise RuntimeError(
                    f"DeepBrief fallo despues de retries: {last_error}"
                ) from error

    raise RuntimeError("DeepBrief fallo de forma inesperada")
