from enum import StrEnum
from typing import Any


class PipelineErrorType(StrEnum):
    OPENAI_JSON_ERROR = "OPENAI_JSON_ERROR"
    OPENAI_TIMEOUT = "OPENAI_TIMEOUT"
    CONTEXT_EMPTY = "CONTEXT_EMPTY"
    MARKET_DATA_INCOMPLETE = "MARKET_DATA_INCOMPLETE"
    SUPABASE_WRITE_ERROR = "SUPABASE_WRITE_ERROR"
    LOW_CONFIDENCE_OUTPUT = "LOW_CONFIDENCE_OUTPUT"
    POLYMARKET_FETCH_ERROR = "POLYMARKET_FETCH_ERROR"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


def classify_error(error: Exception | str) -> PipelineErrorType:
    text = str(error).lower()

    if "json" in text or "pydantic" in text or "validation" in text:
        return PipelineErrorType.OPENAI_JSON_ERROR

    if "timeout" in text or "timed out" in text:
        return PipelineErrorType.OPENAI_TIMEOUT

    if "context" in text and ("empty" in text or "insuficiente" in text):
        return PipelineErrorType.CONTEXT_EMPTY

    if "market sin id" in text or "missing" in text or "none" in text:
        return PipelineErrorType.MARKET_DATA_INCOMPLETE

    if "supabase" in text or "postgrest" in text or "schema cache" in text or "column" in text:
        return PipelineErrorType.SUPABASE_WRITE_ERROR

    if "confidence" in text or "low confidence" in text:
        return PipelineErrorType.LOW_CONFIDENCE_OUTPUT

    if "polymarket" in text or "gamma-api" in text or "requests" in text:
        return PipelineErrorType.POLYMARKET_FETCH_ERROR

    return PipelineErrorType.UNKNOWN_ERROR


def build_error_record(
    error: Exception | str,
    market: dict[str, Any] | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    error_type = classify_error(error)

    return {
        "error_type": error_type.value,
        "stage": stage or "unknown",
        "message": str(error),
        "market_id": market.get("id") if market else None,
        "external_market_id": market.get("external_market_id") if market else None,
        "market_title": market.get("title") if market else None,
    }