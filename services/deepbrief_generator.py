import json
import copy
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

SUPPORTED_PROVIDERS = {"openai", "gemini", "groq"}

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
- Incluye un bloque prediction_audit interno y auditable.
- predicted_probability no es radar_score.
- Si no puedes tomar postura clara, usa predicted_outcome=no_call y predicted_probability=null.

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


class AllDeepBriefProvidersFailedError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        attempts: list[dict[str, Any]] | None = None,
        classification: str = "all_llm_providers_failed",
    ) -> None:
        super().__init__(message)
        self.attempts = attempts or []
        self.classification = classification
        self.message = message


def _sanitize_attempts(attempts: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for attempt in attempts or []:
        if not isinstance(attempt, dict):
            continue
        sanitized.append(
            {
                "provider": attempt.get("provider"),
                "model": attempt.get("model"),
                "status": attempt.get("status"),
                "attempt": attempt.get("attempt"),
                "error_type": attempt.get("error_type"),
                "fallback_used": attempt.get("fallback_used"),
                "message": attempt.get("message") or attempt.get("error"),
            }
        )
    return sanitized


def _classify_provider_attempts(attempts: list[dict[str, Any]] | None) -> str:
    normalized = [str(item.get("error", item.get("message", ""))).lower() for item in attempts or []]
    if not normalized:
        return "all_llm_providers_failed"

    if all("quota" in item or "insufficient_quota" in item or "rate limit" in item for item in normalized):
        return "all_llm_providers_quota_exhausted"
    if any("schema" in item or "additional_properties" in item or "invalid_argument" in item for item in normalized):
        return "provider_schema_error"
    if any("auth" in item or "unauthorized" in item or "api key" in item for item in normalized):
        return "provider_auth_error"
    if any("timeout" in item or "network" in item or "connection" in item or "transient" in item for item in normalized):
        return "provider_transient_error"
    return "all_llm_providers_failed"


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

    for env_name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"):
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


def build_raw_market_input(market: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": market.get("title"),
        "description": market.get("description"),
        "category": market.get("category"),
        "deepengine_category": market.get("deepengine_category"),
        "url": market.get("url"),
        "close_date": market.get("close_date"),
        "current_probability": market.get("current_probability"),
        "previous_probability_24h": market.get("previous_probability_24h"),
        "probability_change_24h": market.get("probability_change_24h"),
        "volume": market.get("volume"),
        "liquidity": market.get("liquidity"),
        "outcomes": market.get("outcomes"),
        "preliminary_radar_score": market.get("preliminary_radar_score"),
        "score_breakdown": market.get("score_breakdown"),
        "relevance_reasons": market.get("relevance_reasons"),
        "novelty_market": market.get("novelty_market"),
        "relevance_exclusion_reason": market.get("relevance_exclusion_reason"),
    }


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


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            lines = lines[1:-1]
        stripped = "\n".join(lines).strip()
    return stripped


def _sanitize_json_schema(node: Any) -> Any:
    if isinstance(node, dict):
        cleaned: dict[str, Any] = {}
        for key, value in node.items():
            if key in {"additionalProperties", "additional_properties", "title"}:
                continue
            cleaned[key] = _sanitize_json_schema(value)
        return cleaned
    if isinstance(node, list):
        return [_sanitize_json_schema(item) for item in node]
    return node


def build_gemini_response_schema(schema_model: type[Any]) -> dict[str, Any]:
    return _sanitize_json_schema(copy.deepcopy(schema_model.model_json_schema()))


def build_groq_response_schema(schema_model: type[Any]) -> dict[str, Any]:
    schema = copy.deepcopy(schema_model.model_json_schema())

    def _sanitize(node: Any) -> Any:
        if isinstance(node, dict):
            cleaned: dict[str, Any] = {}
            for key, value in node.items():
                if key in {
                    "type",
                    "properties",
                    "required",
                    "items",
                    "enum",
                    "description",
                    "$defs",
                    "$ref",
                    "anyOf",
                    "nullable",
                }:
                    cleaned[key] = _sanitize(value)
                elif key in {
                    "title",
                    "additionalProperties",
                    "additional_properties",
                    "default",
                    "examples",
                    "const",
                    "format",
                    "minimum",
                    "maximum",
                    "exclusiveMinimum",
                    "exclusiveMaximum",
                    "minLength",
                    "maxLength",
                    "pattern",
                    "minItems",
                    "maxItems",
                    "unevaluatedProperties",
                }:
                    continue
                else:
                    cleaned[key] = _sanitize(value)
            return cleaned
        if isinstance(node, list):
            return [_sanitize(item) for item in node]
        return node

    return _sanitize(schema)


def build_deepbrief_prompt(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None = None,
    repair_note: str | None = None,
    anti_anchor_note: str | None = None,
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

    if anti_anchor_note:
        rendered_prompt = (
            f"{rendered_prompt}\n\n"
            f"VALIDACION SEMANTICA ANTI-ANCLAJE:\n{anti_anchor_note}\n"
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
        "market_input": build_raw_market_input(market),
        "context_sources": context_sources or [],
        "prompt_source": prompt_source,
        "prompt": prompt,
        "parsed_output": parsed_output,
        "response_id": response_id,
    }


def _build_provider_attempt(
    *,
    provider: str,
    model: str,
    attempt: int,
    status: str,
    error_type: str | None = None,
    message: str | None = None,
    fallback_used: bool | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": provider,
        "model": model,
        "attempt": attempt,
        "status": status,
    }
    if error_type is not None:
        payload["error_type"] = error_type
    if message is not None:
        payload["message"] = message
    if fallback_used is not None:
        payload["fallback_used"] = fallback_used
    return payload


def _classify_groq_error(error: Exception) -> str:
    status = getattr(error, "status_code", None) or getattr(error, "status", None)
    message = redact_secret_values(str(error)).lower()

    if status in {401, 403}:
        return "provider_auth_error"
    if status == 429:
        if "quota" in message or "insufficient" in message:
            return "provider_quota_error"
        return "provider_rate_limit"
    if status in {400, 422}:
        if "response_format" in message or "json_schema" in message or "structured" in message:
            return "provider_schema_error"
        return "provider_invalid_response"
    if status in {500, 502, 503, 504}:
        return "provider_transient_error"
    if "timeout" in message:
        return "provider_timeout"
    if "invalid" in message and "json" in message:
        return "provider_invalid_response"
    return "provider_transient_error"


def _parse_response_text(response: Any) -> dict[str, Any]:
    response_text = getattr(response, "text", None)
    if not response_text:
        raise RuntimeError("El modelo no devolvio texto JSON")
    payload = json.loads(_strip_code_fences(response_text))
    return payload

def _parse_chat_completion_json(response: Any) -> dict[str, Any]:
    choices = getattr(response, "choices", None)

    if not choices:
        raise RuntimeError("Groq no devolvio choices")

    message = getattr(choices[0], "message", None)
    response_text = getattr(message, "content", None)

    if not response_text:
        raise RuntimeError("Groq no devolvio contenido JSON")

    return json.loads(_strip_code_fences(response_text))


def _is_schema_error(error: Exception) -> bool:
    message = summarize_exception(error).lower()
    return any(
        token in message
        for token in (
            "additional_properties",
            "additionalproperties",
            "response_schema",
            "json_schema",
            "schema",
            "unknown name",
        )
    )

def _groq_client() -> OpenAI:
    timeout_seconds = os.getenv("GROQ_TIMEOUT_SECONDS", "120")
    try:
        timeout_value: Any = float(timeout_seconds)
    except ValueError:
        timeout_value = 120
    return OpenAI(
        api_key=os.environ["GROQ_API_KEY"],
        base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        timeout=timeout_value,
    )


def _groq_generation_attempt(
    *,
    client: OpenAI,
    model: str,
    prompt: str,
    prompt_source: str,
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None,
    primary_provider: str,
    fallback_used: bool,
    attempts: list[dict[str, Any]],
    response_format: dict[str, Any] | None,
    attempt: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": SYSTEM_INSTRUCTION,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        response_format=response_format,
        extra_body={
            "reasoning_effort": "low",
            "include_reasoning": False,
        },
    )

    payload = _parse_chat_completion_json(response)
    deepbrief = validate_deepbrief_payload(payload)
    attempts.append(_build_provider_attempt(provider="groq", model=model, attempt=attempt, status="ok"))
    raw_output = build_success_raw_output(
        provider="groq",
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
    usage = getattr(response, "usage", None)
    raw_output["usage"] = {
        "input_tokens": (
            getattr(usage, "prompt_tokens", None)
            if usage
            else None
        ),
        "output_tokens": (
            getattr(usage, "completion_tokens", None)
            if usage
            else None
        ),
        "total_tokens": (
            getattr(usage, "total_tokens", None)
            if usage
            else None
        ),
    }
    return deepbrief, raw_output


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

    if parse_env_bool("GROQ_ENABLED", False) and "groq" not in providers:
        providers.append("groq")

    return primary, providers


def get_provider_model(provider: str) -> str:
    if provider == "gemini":
        return os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    if provider == "groq":
        return os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

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

    if provider == "groq":
        if not parse_env_bool("GROQ_ENABLED", False):
            return False, "groq_disabled"
        if not os.getenv("GROQ_API_KEY"):
            return False, "groq_not_configured"
        return True, None

    return False, f"Proveedor no soportado: {provider}"


def generate_with_openai(
    *,
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None,
    max_retries: int,
    primary_provider: str,
    fallback_used: bool,
    anti_anchor_note: str | None = None,
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
            anti_anchor_note=anti_anchor_note,
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
    anti_anchor_note: str | None = None,
    prior_attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = get_provider_model("gemini")
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    attempts = list(prior_attempts or [])
    last_error = None
    gemini_schema = build_gemini_response_schema(DeepBriefSchema)

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
            anti_anchor_note=anti_anchor_note,
        )

        try:
            response = client.models.generate_content(
                model=model,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION,
                    response_mime_type="application/json",
                    response_schema=gemini_schema,
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
            if _is_schema_error(error):
                logger.info(
                    "[DEEPBRIEF_PROVIDER] provider=gemini action=structured_schema_rejected retry=json_object",
                )
                try:
                    response = client.models.generate_content(
                        model=model,
                        contents=prompt,
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
                        payload = json.loads(_strip_code_fences(response_text))

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
                except Exception as retry_error:
                    last_error = summarize_exception(retry_error)
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
                        ) from retry_error
                    continue

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


def generate_with_groq(
    *,
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None,
    max_retries: int,
    primary_provider: str,
    fallback_used: bool,
    anti_anchor_note: str | None = None,
    prior_attempts: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    model = get_provider_model("groq")
    client = _groq_client()
    attempts = list(prior_attempts or [])
    last_error: str | None = None
    groq_schema = build_groq_response_schema(DeepBriefSchema)

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
            anti_anchor_note=anti_anchor_note,
        )

        try:
            logger.info(
                "[DEEPBRIEF_PROVIDER] provider=groq action=started model=%s",
                model,
            )
            try:
                return _groq_generation_attempt(
                    client=client,
                    model=model,
                    prompt=prompt,
                    prompt_source=prompt_source,
                    market=market,
                    context_sources=context_sources,
                    primary_provider=primary_provider,
                    fallback_used=fallback_used,
                    attempts=attempts,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": "deepbrief",
                            "strict": False,
                            "schema": groq_schema,
                        },
                    },
                    attempt=attempt,
                )
            except Exception as error:
                message = summarize_exception(error)
                if getattr(error, "status_code", None) in {400, 422} or "response_format" in message.lower() or "json_schema" in message.lower():
                    logger.info(
                        "[DEEPBRIEF_PROVIDER] provider=groq action=structured_schema_rejected retry=json_object",
                    )
                    last_error = message
                    response = client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": SYSTEM_INSTRUCTION,
                            },
                            {
                                "role": "user",
                                "content": prompt,
                            },
                        ],
                        response_format={"type": "json_object"},
                        extra_body={
                            "reasoning_effort": "low",
                            "include_reasoning": False,
                        },
                    )

                    payload = _parse_chat_completion_json(response)
                    deepbrief = validate_deepbrief_payload(payload)
                    attempts.append(_build_provider_attempt(provider="groq", model=model, attempt=attempt, status="ok"))
                    raw_output = build_success_raw_output(
                        provider="groq",
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
                    usage = getattr(response, "usage", None)

                    raw_output["usage"] = {
                        "input_tokens": (
                            getattr(usage, "prompt_tokens", None)
                            if usage
                            else None
                        ),
                        "output_tokens": (
                            getattr(usage, "completion_tokens", None)
                            if usage
                            else None
                        ),
                        "total_tokens": (
                            getattr(usage, "total_tokens", None)
                            if usage
                            else None
                        ),
                    }
                    logger.info(
                        "[DEEPBRIEF_PROVIDER] provider=groq action=succeeded",
                    )
                    return deepbrief, raw_output
                raise

        except Exception as error:
            last_error = summarize_exception(error)
            attempts.append(
                _build_provider_attempt(
                    provider="groq",
                    model=model,
                    attempt=attempt,
                    status="failed",
                    error_type=_classify_groq_error(error),
                    message=last_error,
                )
            )
            logger.warning(
                "[DEEPBRIEF_PROVIDER] provider=groq action=failed errorType=%s",
                _classify_groq_error(error),
            )
            if attempt >= max_retries + 1:
                raise ProviderGenerationError(
                    provider="groq",
                    model=model,
                    message=f"Groq fallo despues de retries: {last_error}",
                    attempts=attempts,
                ) from error

    raise ProviderGenerationError(
        provider="groq",
        model=model,
        message="Groq fallo de forma inesperada",
        attempts=attempts,
    )


def generate_deepbrief_for_market(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]] | None = None,
    max_retries: int | None = None,
    anti_anchor_note: str | None = None,
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
            if provider == "groq" and reason == "groq_not_configured":
                attempts.append(
                    _build_provider_attempt(
                        provider="groq",
                        model=provider_model,
                        attempt=1,
                        status="failed",
                        error_type="groq_not_configured",
                        message=reason,
                    )
                )
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
                    anti_anchor_note=anti_anchor_note,
                    prior_attempts=attempts,
                )
            elif provider == "groq":
                deepbrief, raw_output = generate_with_groq(
                    market=market,
                    context_sources=context_sources,
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    anti_anchor_note=anti_anchor_note,
                    prior_attempts=attempts,
                )
            else:
                deepbrief, raw_output = generate_with_openai(
                    market=market,
                    context_sources=context_sources,
                    max_retries=max_retries,
                    primary_provider=primary_provider,
                    fallback_used=is_fallback,
                    anti_anchor_note=anti_anchor_note,
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
    classification = _classify_provider_attempts(attempts)
    logger.error("LLM_ALL_PROVIDERS_FAILED | classification=%s | errors=%s", classification, combined_error)
    raise AllDeepBriefProvidersFailedError(
        f"Todos los proveedores LLM fallaron: {combined_error}",
        attempts=_sanitize_attempts(attempts),
        classification=classification,
    )
