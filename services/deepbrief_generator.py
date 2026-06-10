import json
import os
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

from services.deepbrief_schema import DeepBriefSchema
from services.logger_service import get_logger
from services.prompt_service import load_prompt, render_prompt
from services.scoring_service import days_to_close


load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT_DIR / "prompts"
GENAI_SDK_AVAILABLE = genai is not None and genai_types is not None

logger = get_logger("deepbrief_generator")

SYSTEM_INSTRUCTION = (
    "Eres DeepSignal Engine, un analista de mercados predictivos. "
    "Tu trabajo es generar DeepBriefs estructurados, prudentes y utiles. "
    "No inventes datos externos no incluidos en el input. "
    "Cuando uses contexto externo, menciona su relevancia, fecha o URL si aplica. "
    "Distingue informacion nueva, informacion ya descontada y ruido."
)

SUPPORTED_PROVIDERS = {"openai", "gemini"}

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


class ProviderGenerationError(RuntimeError):
    def __init__(
        self,
        provider: str,
        model: str,
        message: str,
        attempts: list[dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.attempts = attempts or []
        self.message = message


def parse_env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_provider_name(value: str | None, default: str) -> str:
    normalized = str(value or default).strip().lower()
    return normalized if normalized in SUPPORTED_PROVIDERS else default


def redact_secret_values(message: str) -> str:
    sanitized = str(message)

    for env_name in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        secret = os.getenv(env_name)

        if secret and len(secret) >= 6:
            sanitized = sanitized.replace(secret, "[REDACTED]")

    return sanitized


def summarize_exception(error: Exception) -> str:
    return redact_secret_values(str(error)).strip() or error.__class__.__name__


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


def validate_deepbrief_payload(payload: Any) -> dict[str, Any]:
    validated = DeepBriefSchema.model_validate(payload)
    return validated.model_dump()


def build_success_raw_output(
    *,
    provider: str,
    model: str,
    fallback_used: bool,
    primary_provider: str,
    attempts: list[dict[str, Any]],
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None,
    prompt_source: str,
    prompt: str,
    parsed_output: dict[str, Any],
    response_id: str | None = None,
) -> dict[str, Any]:
    return {
        "status": "ok",
        "provider": provider,
        "model": model,
        "fallback_used": fallback_used,
        "primary_provider": primary_provider,
        "attempts": attempts,
        "market_input": market,
        "context_sources": context_sources or [],
        "prompt_source": prompt_source,
        "prompt": prompt,
        "parsed_output": parsed_output,
        "response_id": response_id,
    }


def get_provider_sequence() -> tuple[str, list[str]]:
    primary = normalize_provider_name(
        os.getenv("LLM_PRIMARY_PROVIDER"),
        "openai",
    )
    fallback = normalize_provider_name(
        os.getenv("LLM_FALLBACK_PROVIDER"),
        "gemini",
    )
    fallback_enabled = parse_env_bool("LLM_ENABLE_FALLBACK", True)

    providers = [primary]

    if fallback_enabled and fallback != primary:
        providers.append(fallback)

    return primary, providers


def get_provider_model(provider: str) -> str:
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

    return os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def is_provider_configured(provider: str) -> tuple[bool, str | None]:
    if provider == "openai":
        if not os.getenv("OPENAI_API_KEY"):
            return False, "OPENAI_API_KEY no configurada"
        return True, None

    if provider == "gemini":
        if not GENAI_SDK_AVAILABLE:
            return False, "SDK google-genai no instalado"
        if not os.getenv("GEMINI_API_KEY"):
            return False, "GEMINI_API_KEY no configurada"
        return True, None

    return False, f"Proveedor no soportado: {provider}"


def generate_with_openai(
    *,
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None,
    max_retries: int,
    primary_provider: str,
    fallback_used: bool,
    prior_attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = get_provider_model("openai")
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    attempts = list(prior_attempts or [])
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
                        "content": SYSTEM_INSTRUCTION,
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

            deepbrief = validate_deepbrief_payload(parsed.model_dump())

            attempts.append(
                {
                    "provider": "openai",
                    "attempt": attempt,
                    "status": "ok",
                    "model": model,
                }
            )

            raw_output = build_success_raw_output(
                provider="openai",
                model=model,
                fallback_used=fallback_used,
                primary_provider=primary_provider,
                attempts=attempts,
                market=market,
                context_sources=context_sources,
                prompt_source=prompt_source,
                prompt=prompt,
                parsed_output=deepbrief,
                response_id=getattr(response, "id", None),
            )

            return deepbrief, raw_output

        except Exception as error:
            last_error = summarize_exception(error)
            attempts.append(
                {
                    "provider": "openai",
                    "attempt": attempt,
                    "status": "failed",
                    "model": model,
                    "error": last_error,
                }
            )

            if attempt >= max_retries + 1:
                raise ProviderGenerationError(
                    provider="openai",
                    model=model,
                    message=f"OpenAI fallo despues de retries: {last_error}",
                    attempts=attempts,
                ) from error

    raise ProviderGenerationError(
        provider="openai",
        model=model,
        message="OpenAI fallo de forma inesperada",
        attempts=attempts,
    )


def generate_with_gemini(
    *,
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None,
    max_retries: int,
    primary_provider: str,
    fallback_used: bool,
    prior_attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = get_provider_model("gemini")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    attempts = list(prior_attempts or [])
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
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=DeepBriefSchema,
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

            deepbrief = validate_deepbrief_payload(payload)

            attempts.append(
                {
                    "provider": "gemini",
                    "attempt": attempt,
                    "status": "ok",
                    "model": model,
                }
            )

            raw_output = build_success_raw_output(
                provider="gemini",
                model=model,
                fallback_used=fallback_used,
                primary_provider=primary_provider,
                attempts=attempts,
                market=market,
                context_sources=context_sources,
                prompt_source=prompt_source,
                prompt=prompt,
                parsed_output=deepbrief,
                response_id=getattr(response, "response_id", None),
            )

            return deepbrief, raw_output

        except Exception as error:
            last_error = summarize_exception(error)
            attempts.append(
                {
                    "provider": "gemini",
                    "attempt": attempt,
                    "status": "failed",
                    "model": model,
                    "error": last_error,
                }
            )

            if attempt >= max_retries + 1:
                raise ProviderGenerationError(
                    provider="gemini",
                    model=model,
                    message=f"Gemini fallo despues de retries: {last_error}",
                    attempts=attempts,
                ) from error

    raise ProviderGenerationError(
        provider="gemini",
        model=model,
        message="Gemini fallo de forma inesperada",
        attempts=attempts,
    )


def generate_deepbrief_for_market(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None = None,
    max_retries: int | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    max_retries = max_retries or int(os.getenv("DEEPBRIEF_MAX_RETRIES", "2"))
    primary_provider, provider_sequence = get_provider_sequence()
    attempts: list[dict[str, Any]] = []
    provider_errors: list[str] = []

    for index, provider in enumerate(provider_sequence):
        configured, reason = is_provider_configured(provider)
        is_fallback = index > 0
        provider_model = get_provider_model(provider)

        if not configured:
            if provider == "gemini":
                logger.warning(
                    "Proveedor gemini omitido: %s",
                    reason,
                )
            else:
                logger.warning(
                    "Proveedor %s omitido: %s",
                    provider,
                    reason,
                )
            provider_errors.append(f"{provider}: {reason}")
            continue

        if is_fallback:
            logger.info(
                "LLM_FALLBACK_ATTEMPT | provider=%s | model=%s",
                provider,
                provider_model,
            )
        else:
            logger.info(
                "LLM_PRIMARY_ATTEMPT | provider=%s | model=%s",
                provider,
                provider_model,
            )

        try:
            if provider == "gemini":
                deepbrief, raw_output = generate_with_gemini(
                    market=market,
                    context_sources=context_sources,
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    prior_attempts=attempts,
                )
            else:
                deepbrief, raw_output = generate_with_openai(
                    market=market,
                    context_sources=context_sources,
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    prior_attempts=attempts,
                )

            if is_fallback:
                logger.info(
                    "LLM_FALLBACK_SUCCESS | provider=%s | model=%s",
                    provider,
                    provider_model,
                )

            return deepbrief, raw_output

        except ProviderGenerationError as error:
            attempts = list(error.attempts)
            provider_errors.append(f"{provider}: {error.message}")

            if is_fallback:
                logger.error(
                    "LLM_ALL_PROVIDERS_FAILED | provider=%s | model=%s | error=%s",
                    provider,
                    provider_model,
                    error.message,
                )
            else:
                logger.warning(
                    "LLM_PRIMARY_FAILED | provider=%s | model=%s | error=%s",
                    provider,
                    provider_model,
                    error.message,
                )

    combined_error = " | ".join(provider_errors) or "No hay proveedores LLM configurados"
    logger.error("LLM_ALL_PROVIDERS_FAILED | errors=%s", combined_error)
    raise RuntimeError(f"Todos los proveedores LLM fallaron: {combined_error}")
