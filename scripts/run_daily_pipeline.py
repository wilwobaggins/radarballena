import os
import time
from typing import Any

from services import supabase_service as db
from services.context_client import search_context
from services.deepbrief_generator import generate_deepbrief_for_market
from services.error_types import build_error_record
from services.logger_service import get_logger
from services.market_filter import filter_relevant_markets
from services.polymarket_client import get_normalized_active_markets
from services.scoring_service import (
    calculate_hybrid_radar_score,
    score_markets,
    sort_markets_by_score,
    days_to_close,
    safe_float,
)


logger = get_logger("run_daily_pipeline")


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def register_pipeline_error(
    error: Exception,
    market: dict[str, Any] | None = None,
    stage: str = "unknown",
) -> None:
    error_record = build_error_record(
        error=error,
        market=market,
        stage=stage,
    )

    logger.error(
        "Pipeline error | type=%s | stage=%s | market=%s | message=%s",
        error_record["error_type"],
        error_record["stage"],
        error_record.get("market_title"),
        error_record["message"],
    )

    if hasattr(db, "insert_pipeline_error"):
        try:
            db.insert_pipeline_error(error_record)
        except Exception as save_error:
            logger.error("No se pudo guardar pipeline_error: %s", save_error)


def start_pipeline_run() -> dict[str, Any]:
    logger.info("Iniciando pipeline run")
    return db.start_pipeline_run()


def fetch_markets() -> list[dict[str, Any]]:
    limit = env_int("POLYMARKET_LIMIT", 100)

    logger.info("Obteniendo mercados Polymarket | limit=%s", limit)

    markets = get_normalized_active_markets(limit=limit)

    logger.info("Mercados obtenidos: %s", len(markets))

    return markets


def save_snapshots(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saved_markets = []

    logger.info("Guardando markets y snapshots")

    for market in markets:
        try:
            saved_market = db.upsert_market(market)
            db.save_market_snapshot(saved_market["id"], market)

            merged_market = {
                **market,
                **saved_market,
            }

            saved_markets.append(merged_market)

        except Exception as error:
            register_pipeline_error(
                error=error,
                market=market,
                stage="save_snapshots",
            )
            continue

    logger.info("Markets guardados/actualizados: %s", len(saved_markets))

    return saved_markets


def filter_markets(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger.info("Filtrando mercados relevantes para DeepEngine MVP")

    try:
        filtered = filter_relevant_markets(markets)

        logger.info("Mercados filtrados: %s", len(filtered))

        return filtered

    except Exception as error:
        register_pipeline_error(
            error=error,
            market=None,
            stage="filter_markets",
        )

        logger.error("Falló el filtro general de mercados")
        return []


def score_market_batch(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger.info("Calculando preliminary_radar_score")

    scored = score_markets(markets)

    logger.info("Mercados con score: %s", len(scored))

    return scored

def build_selection_reason(market: dict[str, Any]) -> str:
    breakdown = market.get("score_breakdown") or {}

    parts = [
        f"category={market.get('category') or market.get('deepengine_category')}",
        f"score={market.get('preliminary_radar_score')}",
        f"volume={safe_float(market.get('volume')):.0f}",
        f"liquidity={safe_float(market.get('liquidity')):.0f}",
        f"prob_move_24h={safe_float(market.get('probability_change_24h')):.4f}",
        f"days_to_close={days_to_close(market)}",
    ]

    if breakdown:
        parts.append(f"breakdown={breakdown}")

    return " | ".join(parts)

def select_top_markets(
    markets: list[dict[str, Any]],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    top_n = limit or env_int("DAILY_PIPELINE_TOP_N", 10)
    candidate_pool_size = env_int("DAILY_PIPELINE_CANDIDATE_POOL", top_n * 3)

    sorted_markets = sort_markets_by_score(markets)
    selected = sorted_markets[:candidate_pool_size]

    logger.info(
        "Pool de candidatos seleccionado: %s | objetivo_deepbriefs=%s",
        len(selected),
        top_n,
    )

    for market in selected:
        logger.info(
            "Candidate | title=%s | reason=%s",
            market.get("title"),
            build_selection_reason(market),
        )

    return selected


def fetch_context(
    market: dict[str, Any],
    min_sources: int | None = None,
) -> list[dict[str, Any]]:
    min_sources = min_sources or env_int("CONTEXT_MIN_SOURCES", 3)

    existing_context = db.get_market_context(
        market_db_id=market["id"],
        limit=min_sources,
    )

    if len(existing_context) >= min_sources:
        logger.info(
            "Contexto existente suficiente | market=%s | sources=%s",
            market.get("title"),
            len(existing_context),
        )
        return existing_context

    logger.info(
        "Contexto insuficiente | market=%s | existing=%s | buscando nuevas fuentes",
        market.get("title"),
        len(existing_context),
    )

    try:
        new_sources = search_context(
            market=market,
            max_results=min_sources,
        )

        for source in new_sources:
            try:
                db.insert_market_context(
                    market_db_id=market["id"],
                    source=source,
                )
            except Exception as error:
                register_pipeline_error(
                    error=error,
                    market=market,
                    stage="insert_market_context",
                )

        refreshed_context = db.get_market_context(
            market_db_id=market["id"],
            limit=min_sources,
        )

        logger.info(
            "Contexto final | market=%s | sources=%s",
            market.get("title"),
            len(refreshed_context),
        )

        return refreshed_context

    except Exception as error:
        register_pipeline_error(
            error=error,
            market=market,
            stage="fetch_context",
        )

        return existing_context


def generate_deepbrief(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    logger.info("Generando DeepBrief | market=%s", market.get("title"))

    deepbrief, raw_output = generate_deepbrief_for_market(
        market=market,
        context_sources=context_sources,
    )

    validate_output(
        deepbrief=deepbrief,
        raw_output=raw_output,
    )

    preliminary_radar_score = market.get("preliminary_radar_score")
    ai_interpretive_score = deepbrief.get("radar_score")

    hybrid_score = calculate_hybrid_radar_score(
        preliminary_radar_score=preliminary_radar_score,
        ai_interpretive_score=ai_interpretive_score,
    )

    raw_output["hybrid_score"] = hybrid_score

    saved = save_results(
        market=market,
        deepbrief=deepbrief,
        raw_output=raw_output,
        hybrid_score=hybrid_score,
    )

    alerts = create_alerts(
        market=market,
        deepbrief=deepbrief,
        hybrid_score=hybrid_score,
    )

    raw_output["alerts"] = alerts

    logger.info(
        "DeepBrief guardado | id=%s | preliminary=%s | ai=%s | final=%s | alerts=%s",
        saved["id"],
        hybrid_score["preliminary_radar_score"],
        hybrid_score["ai_interpretive_score"],
        hybrid_score["final_radar_score"],
        len(alerts),
    )

    return saved

def validate_output(
    deepbrief: dict[str, Any],
    raw_output: dict[str, Any],
) -> bool:
    """
    Validación mínima post-generación.

    La validación fuerte ya ocurre en generate_deepbrief_for_market()
    usando Structured Outputs + Pydantic.
    """
    required_fields = [
        "lectura_clave",
        "radar_score",
        "signal_label",
        "deepsignal_verdict",
        "confidence_level",
    ]

    for field in required_fields:
        if field not in deepbrief:
            raise ValueError(f"DeepBrief inválido: falta {field}")

    radar_score = deepbrief.get("radar_score")

    if not isinstance(radar_score, int | float):
        raise ValueError("DeepBrief inválido: radar_score no es numérico")

    if radar_score < 0 or radar_score > 100:
        raise ValueError("DeepBrief inválido: radar_score fuera de 0-100")

    if not raw_output:
        raise ValueError("DeepBrief inválido: raw_output vacío")

    return True


def save_results(
    market: dict[str, Any],
    deepbrief: dict[str, Any],
    raw_output: dict[str, Any],
    hybrid_score: dict[str, Any],
) -> dict[str, Any]:
    """
    Guarda resultado final en Supabase.
    """
    saved = db.insert_deepbrief(
        market_db_id=market["id"],
        deepbrief=deepbrief,
        raw_output=raw_output,
        hybrid_score=hybrid_score,
    )

    logger.info("Resultado guardado | deepbrief_id=%s", saved["id"])

    return saved


def create_alerts(
    market: dict[str, Any],
    deepbrief: dict[str, Any],
    hybrid_score: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    MVP: todavía no envía alertas.
    Solo construye alerta candidata si el score final es alto.

    Después esto puede guardar en tabla alerts o mandar Telegram/email.
    """
    final_score = hybrid_score.get("final_radar_score", 0)

    if final_score < 70:
        return []

    alert = {
        "market_id": market.get("id"),
        "title": market.get("title"),
        "final_radar_score": final_score,
        "signal_label": deepbrief.get("signal_label"),
        "message": (
            f"RadarBallena detectó mercado relevante: "
            f"{market.get('title')} | score={final_score}"
        ),
    }

    logger.info("Alerta candidata creada | market=%s | score=%s", market.get("title"), final_score)

    return [alert]


def main():
    started_at = time.time()
    pipeline_run = start_pipeline_run()
    pipeline_run_id = pipeline_run["id"]

    markets_fetched = 0
    markets_filtered = 0
    markets_analyzed = 0
    deepbriefs_generated = 0
    errors_count = 0

    try:
        raw_markets = fetch_markets()
        markets_fetched = len(raw_markets)

        saved_markets = save_snapshots(raw_markets)

        filtered_markets = filter_markets(saved_markets)
        markets_filtered = len(filtered_markets)

        scored_markets = score_market_batch(filtered_markets)

        selected_markets = select_top_markets(scored_markets)
        target_deepbriefs = env_int("DAILY_PIPELINE_TOP_N", 10)

        for market in selected_markets:
            if deepbriefs_generated >= target_deepbriefs:
                break

            try:
                logger.info("Evaluando candidato: %s", market.get("title"))
                logger.info(
                    "Selection reason | market=%s | %s",
                    market.get("title"),
                    build_selection_reason(market),
                )

                context_sources = fetch_context(market, min_sources=3)

                if len(context_sources) < 3:
                    logger.info(
                        "Mercado excluido por contexto insuficiente | market=%s | sources=%s",
                        market.get("title"),
                        len(context_sources),
                    )
                    continue

                logger.info(
                    "Fuentes usadas | market=%s | sources=%s",
                    market.get("title"),
                    len(context_sources),
                )

                generate_deepbrief(
                    market=market,
                    context_sources=context_sources,
                )

                deepbriefs_generated += 1
                markets_analyzed += 1

            except Exception as error:
                errors_count += 1

                register_pipeline_error(
                    error=error,
                    market=market,
                    stage="generate_deepbrief",
                )

                logger.error(
                    "El pipeline continúa con el siguiente mercado | failed_market=%s",
                    market.get("title"),
                )

                continue

        duration_seconds = round(time.time() - started_at, 2)
        status = "completed" if errors_count == 0 else "completed_with_errors"

        db.finish_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            status=status,
            markets_fetched=markets_fetched,
            markets_filtered=markets_filtered,
            markets_analyzed=markets_analyzed,
            deepbriefs_generated=deepbriefs_generated,
            errors_count=errors_count,
            duration_seconds=duration_seconds,
            error_message=None if errors_count == 0 else f"{errors_count} errores",
        )

        logger.info("Pipeline terminado")
        logger.info("Markets fetched: %s", markets_fetched)
        logger.info("Markets filtered: %s", markets_filtered)
        logger.info("Markets analyzed: %s", markets_analyzed)
        logger.info("DeepBriefs generated: %s", deepbriefs_generated)
        logger.info("Errors: %s", errors_count)
        logger.info("Duration seconds: %s", duration_seconds)

        print("\nPipeline maestro terminado.")
        print("Markets fetched:", markets_fetched)
        print("Markets filtered:", markets_filtered)
        print("Markets analyzed:", markets_analyzed)
        print("DeepBriefs generated:", deepbriefs_generated)
        print("Errors:", errors_count)
        print("Duration:", duration_seconds, "seconds")

    except Exception as fatal_error:
        duration_seconds = round(time.time() - started_at, 2)
        errors_count += 1

        register_pipeline_error(
            error=fatal_error,
            market=None,
            stage="run_daily_pipeline",
        )

        db.finish_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            status="failed",
            markets_fetched=markets_fetched,
            markets_filtered=markets_filtered,
            markets_analyzed=markets_analyzed,
            deepbriefs_generated=deepbriefs_generated,
            errors_count=errors_count,
            duration_seconds=duration_seconds,
            error_message=str(fatal_error),
        )

        logger.exception("Pipeline maestro falló completamente: %s", fatal_error)

        raise


if __name__ == "__main__":
    main()