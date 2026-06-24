from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import Any

from dotenv import load_dotenv

load_dotenv(override=True)

from services import supabase_service as db
from services.deepbrief_generator import (
    AllDeepBriefProvidersFailedError,
    build_raw_market_input,
    generate_deepbrief_for_market,
)
from services.scoring_service import (
    calculate_hybrid_radar_score,
    get_signal_label_for_final_score,
    safe_float,
    score_markets,
)
from scripts.run_daily_pipeline import (
    ANTI_ANCHOR_NOTE,
    save_results,
    validate_output,
)


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _parse_json_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    stripped = value.strip()
    if not stripped:
        return value

    if not (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        return value

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _get_supabase_client() -> Any:
    existing_client = getattr(db, "supabase", None)
    if existing_client is not None:
        return existing_client

    try:
        from supabase import create_client
    except ImportError as error:
        raise RuntimeError(
            "No se encontro el cliente Supabase en services.supabase_service "
            "ni esta instalado el paquete supabase."
        ) from error

    url = os.getenv("SUPABASE_URL")
    key = (
        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
    )

    if not url or not key:
        raise RuntimeError(
            "Faltan SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY/SUPABASE_KEY."
        )

    return create_client(url, key)


def _load_market_row(market_id: str) -> dict[str, Any] | None:
    client = _get_supabase_client()
    response = (
        client.table("markets")
        .select("*")
        .eq("id", market_id)
        .limit(1)
        .execute()
    )
    rows = getattr(response, "data", None) or []
    return rows[0] if rows else None


def _normalize_market_row(row: dict[str, Any]) -> dict[str, Any]:
    raw_payload = _parse_json_value(
        _coalesce(row.get("raw_payload"), row.get("rawPayload"))
    )
    merged: dict[str, Any] = {}

    if isinstance(raw_payload, dict):
        merged.update(raw_payload)

    merged.update(row)

    outcomes = _parse_json_value(
        _coalesce(merged.get("outcomes"), row.get("outcomes"))
    )

    normalized = {
        **merged,
        "id": row.get("id"),
        "external_market_id": _coalesce(
            merged.get("external_market_id"),
            merged.get("externalMarketId"),
        ),
        "title": merged.get("title"),
        "description": merged.get("description"),
        "category": merged.get("category"),
        "deepengine_category": _coalesce(
            merged.get("deepengine_category"),
            merged.get("deepengineCategory"),
            merged.get("category"),
        ),
        "platform": merged.get("platform"),
        "url": merged.get("url"),
        "close_date": _coalesce(
            merged.get("close_date"),
            merged.get("closeDate"),
            merged.get("closing_date"),
            merged.get("closingDate"),
            merged.get("end_date"),
            merged.get("endDate"),
        ),
        "current_probability": _coalesce(
            merged.get("current_probability"),
            merged.get("currentProbability"),
            merged.get("probability"),
        ),
        "previous_probability_24h": _coalesce(
            merged.get("previous_probability_24h"),
            merged.get("previousProbability24h"),
        ),
        "probability_change_24h": _coalesce(
            merged.get("probability_change_24h"),
            merged.get("probabilityChange24h"),
        ),
        "volume": merged.get("volume"),
        "liquidity": merged.get("liquidity"),
        "outcomes": outcomes,
        "relevance_reasons": _coalesce(
            merged.get("relevance_reasons"),
            merged.get("relevanceReasons"),
            [],
        ),
        "novelty_market": bool(
            _coalesce(
                merged.get("novelty_market"),
                merged.get("noveltyMarket"),
                False,
            )
        ),
    }

    return normalized


def _load_existing_context(
    market_id: str,
    minimum_sources: int,
) -> list[dict[str, Any]]:
    sources = db.get_market_context(
        market_db_id=market_id,
        limit=minimum_sources,
    )

    if not isinstance(sources, list):
        return []

    return [source for source in sources if isinstance(source, dict)]


def _score_single_market(market: dict[str, Any]) -> dict[str, Any]:
    scored = score_markets([market])

    if not scored:
        raise RuntimeError("No se pudo calcular preliminary_radar_score.")

    scored_market = scored[0]

    if scored_market.get("preliminary_radar_score") is None:
        raise RuntimeError("El preliminary_radar_score quedo vacio.")

    return scored_market


def _apply_production_scoring(
    *,
    market: dict[str, Any],
    deepbrief: dict[str, Any],
    raw_output: dict[str, Any],
    context_sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    validate_output(deepbrief=deepbrief, raw_output=raw_output)

    preliminary_radar_score = market.get("preliminary_radar_score")
    ai_interpretive_score = deepbrief.get("radar_score")

    if ai_interpretive_score == preliminary_radar_score:
        deepbrief, raw_output = generate_deepbrief_for_market(
            market=market,
            context_sources=context_sources,
            anti_anchor_note=ANTI_ANCHOR_NOTE,
        )
        validate_output(deepbrief=deepbrief, raw_output=raw_output)
        ai_interpretive_score = deepbrief.get("radar_score")

    probability_move = abs(
        safe_float(market.get("probability_change_24h"))
    )
    relevance_reasons = market.get("relevance_reasons") or []
    has_strong_context = "strategic_context" in relevance_reasons
    has_real_movement_signal = "probability_move" in relevance_reasons

    ai_original = int(safe_float(ai_interpretive_score))
    ai_adjusted = ai_original
    score_adjustment = {
        "applied": False,
        "reason": None,
        "original_ai_score": ai_original,
        "adjusted_ai_score": ai_original,
    }

    if ai_original == int(safe_float(preliminary_radar_score)):
        if market.get("novelty_market") is True:
            ai_adjusted = min(ai_adjusted, 35)

        if probability_move == 0 and not has_strong_context:
            ai_adjusted = min(ai_adjusted, 44)

        if str(deepbrief.get("signal_label") or "").strip().lower() == "ignore":
            ai_adjusted = min(ai_adjusted, 30)

        if has_real_movement_signal or has_strong_context:
            ai_adjusted = ai_original

        if ai_adjusted != ai_original:
            score_adjustment = {
                "applied": True,
                "reason": "anti_anchor_postprocess",
                "original_ai_score": ai_original,
                "adjusted_ai_score": ai_adjusted,
            }

    hybrid_score = calculate_hybrid_radar_score(
        preliminary_radar_score=preliminary_radar_score,
        ai_interpretive_score=ai_adjusted,
    )

    original_signal_label = deepbrief.get("signal_label")
    normalized_signal_label = get_signal_label_for_final_score(
        hybrid_score["final_radar_score"]
    )
    deepbrief["signal_label"] = normalized_signal_label

    raw_output["market_input"] = build_raw_market_input(market)
    raw_output["pipeline_run_id"] = None
    raw_output["score_adjustment"] = score_adjustment
    raw_output["hybrid_score"] = hybrid_score
    raw_output["model_signal_label"] = original_signal_label
    raw_output["normalized_signal_label"] = normalized_signal_label
    raw_output.setdefault(
        "generation_mode",
        "llm_fallback"
        if raw_output.get("fallback_used")
        else "llm_primary",
    )
    raw_output.setdefault("needs_ai_refresh", False)

    parsed_output = raw_output.get("parsed_output")
    if isinstance(parsed_output, dict):
        parsed_output["model_signal_label"] = original_signal_label
        parsed_output["signal_label"] = normalized_signal_label

    return deepbrief, raw_output, hybrid_score


def _usage_value(raw_output: dict[str, Any], key: str) -> Any:
    usage = raw_output.get("usage")
    if not isinstance(usage, dict):
        return None
    return usage.get(key)


def _print_result(
    *,
    market: dict[str, Any],
    raw_output: dict[str, Any],
    hybrid_score: dict[str, Any],
    persisted: bool,
    saved_id: str | None,
    show_json: bool,
    deepbrief: dict[str, Any],
) -> None:
    print("SINGLE_DEEPBRIEF_RESULT")
    print(f"market_id={market.get('id')}")
    print(f"market_title={market.get('title')}")
    print(f"provider={raw_output.get('provider')}")
    print(f"model={raw_output.get('model')}")
    print(
        "preliminary_score="
        f"{hybrid_score.get('preliminary_radar_score')}"
    )
    print(
        "ai_interpretive_score="
        f"{hybrid_score.get('ai_interpretive_score')}"
    )
    print(
        f"final_radar_score={hybrid_score.get('final_radar_score')}"
    )
    print(
        "fallback_used="
        f"{str(bool(raw_output.get('fallback_used'))).lower()}"
    )
    print(
        "generation_mode="
        f"{raw_output.get('generation_mode')}"
    )
    print(f"persisted={str(persisted).lower()}")
    print(f"deepbrief_id={saved_id or 'null'}")
    print(
        "usage_input_tokens="
        f"{_usage_value(raw_output, 'input_tokens')}"
    )
    print(
        "usage_output_tokens="
        f"{_usage_value(raw_output, 'output_tokens')}"
    )
    print(
        "usage_total_tokens="
        f"{_usage_value(raw_output, 'total_tokens')}"
    )

    if show_json:
        safe_output = {
            "market": {
                "id": market.get("id"),
                "title": market.get("title"),
            },
            "deepbrief": deepbrief,
            "metadata": {
                "provider": raw_output.get("provider"),
                "model": raw_output.get("model"),
                "fallback_used": raw_output.get("fallback_used"),
                "generation_mode": raw_output.get("generation_mode"),
                "needs_ai_refresh": raw_output.get("needs_ai_refresh"),
                "usage": raw_output.get("usage"),
                "attempts": raw_output.get("attempts"),
                "hybrid_score": hybrid_score,
            },
        }
        print(
            json.dumps(
                safe_output,
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Genera un DeepBrief para exactamente un mercado existente. "
            "No persiste por defecto."
        )
    )
    parser.add_argument(
        "--market-id",
        required=True,
        help="UUID interno de markets.id",
    )
    parser.add_argument(
        "--persist",
        action="store_true",
        help="Persiste el DeepBrief y su prediccion.",
    )
    parser.add_argument(
        "--show-json",
        action="store_true",
        help="Muestra el DeepBrief validado y metadata sanitizada.",
    )
    parser.add_argument(
        "--min-context-sources",
        type=int,
        default=3,
        help="Fuentes existentes minimas requeridas. Default: 3.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=0,
        help=(
            "Retries adicionales por proveedor. Default: 0, "
            "es decir, un intento por proveedor."
        ),
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        market_uuid = str(uuid.UUID(args.market_id))
    except ValueError:
        print("ERROR: --market-id no es un UUID valido.", file=sys.stderr)
        return 2

    if args.min_context_sources <= 0:
        print(
            "ERROR: --min-context-sources debe ser mayor que cero.",
            file=sys.stderr,
        )
        return 2

    if args.max_retries < 0:
        print(
            "ERROR: --max-retries no puede ser negativo.",
            file=sys.stderr,
        )
        return 2

    # generate_deepbrief_for_market lee esta variable cuando max_retries
    # no se pasa explícitamente. Con 0 realiza un intento por proveedor.
    os.environ["DEEPBRIEF_MAX_RETRIES"] = str(args.max_retries)

    try:
        market_row = _load_market_row(market_uuid)
    except Exception as error:
        print(f"ERROR_DB: no se pudo leer markets: {error}", file=sys.stderr)
        return 1

    if market_row is None:
        print(
            f"ERROR: no existe markets.id={market_uuid}",
            file=sys.stderr,
        )
        return 2

    try:
        market = _score_single_market(
            _normalize_market_row(market_row)
        )
    except Exception as error:
        print(f"ERROR_SCORING: {error}", file=sys.stderr)
        return 1

    try:
        context_sources = _load_existing_context(
            market_uuid,
            args.min_context_sources,
        )
    except Exception as error:
        print(
            f"ERROR_DB: no se pudo leer market_context: {error}",
            file=sys.stderr,
        )
        return 1

    if len(context_sources) < args.min_context_sources:
        print(
            "ERROR_CONTEXT: "
            f"se requieren {args.min_context_sources} fuentes existentes "
            f"y solo hay {len(context_sources)}.",
            file=sys.stderr,
        )
        return 2

    try:
        deepbrief, raw_output = generate_deepbrief_for_market(
            market=market,
            context_sources=context_sources,
        )
    except AllDeepBriefProvidersFailedError as error:
        print(
            "ALL_LLM_PROVIDERS_FAILED",
            file=sys.stderr,
        )
        print(
            f"classification={error.classification}",
            file=sys.stderr,
        )
        print(
            json.dumps(
                error.attempts,
                ensure_ascii=False,
                indent=2,
                default=str,
            ),
            file=sys.stderr,
        )
        return 3
    except Exception as error:
        print(f"ERROR_GENERATION: {error}", file=sys.stderr)
        return 1

    try:
        deepbrief, raw_output, hybrid_score = _apply_production_scoring(
            market=market,
            deepbrief=deepbrief,
            raw_output=raw_output,
            context_sources=context_sources,
        )
    except AllDeepBriefProvidersFailedError as error:
        print(
            "ALL_LLM_PROVIDERS_FAILED_DURING_ANTI_ANCHOR",
            file=sys.stderr,
        )
        print(
            f"classification={error.classification}",
            file=sys.stderr,
        )
        return 3
    except Exception as error:
        print(f"ERROR_VALIDATION: {error}", file=sys.stderr)
        return 1

    saved_id: str | None = None

    if args.persist:
        try:
            saved = save_results(
                market=market,
                deepbrief=deepbrief,
                raw_output=raw_output,
                hybrid_score=hybrid_score,
                pipeline_run_id=None,  # type: ignore[arg-type]
            )
            saved_id = str(saved.get("id")) if saved.get("id") else None
        except Exception as error:
            print(f"ERROR_PERSISTENCE: {error}", file=sys.stderr)
            return 4

    _print_result(
        market=market,
        raw_output=raw_output,
        hybrid_score=hybrid_score,
        persisted=args.persist,
        saved_id=saved_id,
        show_json=args.show_json,
        deepbrief=deepbrief,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
