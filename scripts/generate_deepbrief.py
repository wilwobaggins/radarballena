import time

from services.logger_service import get_logger
from services.supabase_service import (
    get_supabase_client,
    insert_deepbrief,
    get_market_context,
    insert_market_context,
    start_pipeline_run, finish_pipeline_run,
    insert_pipeline_error
)
from services.deepbrief_generator import generate_deepbrief_for_market
from services.market_filter import select_top_markets
from services.context_client import search_context
from services.scoring_service import calculate_hybrid_radar_score
from services.error_types import build_error_record


def get_top_markets(limit: int = 5):
    supabase = get_supabase_client()

    response = (
        supabase
        .table("markets")
        .select("*")
        .eq("platform", "polymarket")
        .neq("external_market_id", "test_market_001")
        .order("volume", desc=True)
        .limit(50)
        .execute()
    )

    candidates = response.data or []
    selected = select_top_markets(candidates, limit=limit)

    print("Candidatos desde Supabase:", len(candidates))
    print("Mercados seleccionados por score:", len(selected))

    for market in selected:
        print(
            "Score:",
            market.get("preliminary_radar_score"),
            "|",
            market.get("title"),
        )

    return selected

def ensure_market_context(market: dict, min_sources: int = 3) -> list[dict]:
    """
    Garantiza que el mercado tenga contexto externo.
    Si ya existe en Supabase, lo usa.
    Si no existe o hay menos de min_sources, busca nuevas fuentes y las guarda.
    """
    existing_context = get_market_context(market["id"], limit=min_sources)

    if len(existing_context) >= min_sources:
        return existing_context

    print(
        "Contexto insuficiente:",
        len(existing_context),
        "| buscando fuentes externas...",
    )

    new_sources = search_context(market, max_results=min_sources)

    for source in new_sources:
        insert_market_context(
            market_db_id=market["id"],
            source=source,
        )

    refreshed_context = get_market_context(market["id"], limit=min_sources)

    return refreshed_context

logger = get_logger("generate_deepbrief")

def main():
    started_at = time.time()
    pipeline_run = start_pipeline_run()
    pipeline_run_id = pipeline_run["id"]

    success_count = 0
    error_count = 0
    markets_fetched = 0
    markets_filtered = 0

    logger.info("Pipeline iniciado: generate_deepbrief")
    logger.info("Pipeline run id: %s", pipeline_run_id)

    try:
        markets = get_top_markets(limit=5)

        markets_fetched = 50
        markets_filtered = len(markets)

        logger.info("Markets candidatos: %s", markets_fetched)
        logger.info("Markets seleccionados: %s", markets_filtered)

        print("Markets encontrados:", len(markets))

        if len(markets) < 5:
            logger.warning("Hay menos de 5 mercados reales disponibles.")
            print("Aviso: hay menos de 5 mercados reales disponibles.")

        for market in markets:
            logger.info("Generando DeepBrief para: %s", market.get("title"))
            print("\nGenerando DeepBrief para:", market.get("title"))

            try:
                context_sources = ensure_market_context(market, min_sources=3)

                logger.info(
                    "Fuentes de contexto usadas para %s: %s",
                    market.get("title"),
                    len(context_sources),
                )

                print("Fuentes de contexto usadas:", len(context_sources))

                deepbrief, raw_output = generate_deepbrief_for_market(
                    market=market,
                    context_sources=context_sources,
                )

                preliminary_radar_score = market.get("preliminary_radar_score")
                ai_interpretive_score = deepbrief.get("radar_score")

                hybrid_score = calculate_hybrid_radar_score(
                    preliminary_radar_score=preliminary_radar_score,
                    ai_interpretive_score=ai_interpretive_score,
                )

                logger.info(
                    "Scores para %s | preliminary=%s | ai=%s | final=%s",
                    market.get("title"),
                    hybrid_score["preliminary_radar_score"],
                    hybrid_score["ai_interpretive_score"],
                    hybrid_score["final_radar_score"],
                )

                print(
                    "Scores:",
                    "preliminary=", hybrid_score["preliminary_radar_score"],
                    "| ai=", hybrid_score["ai_interpretive_score"],
                    "| final=", hybrid_score["final_radar_score"],
                )

                raw_output["hybrid_score"] = hybrid_score

                saved = insert_deepbrief(
                    market_db_id=market["id"],
                    deepbrief=deepbrief,
                    raw_output=raw_output,
                    hybrid_score=hybrid_score,
                )

                success_count += 1

                logger.info("DeepBrief guardado: %s", saved["id"])
                print("DeepBrief guardado:", saved["id"])

            except Exception as error:
                error_count += 1

                logger.exception(
                    "Error generando DeepBrief para %s: %s",
                    market.get("title"),
                    error,
                )

                print("ERROR generando DeepBrief para:", market.get("title"))
                print("Error:", error)
                print("El pipeline continúa con el siguiente mercado.")

                continue

        duration_seconds = round(time.time() - started_at, 2)
        final_status = "completed" if error_count == 0 else "completed_with_errors"

        finish_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            status=final_status,
            markets_fetched=markets_fetched,
            markets_filtered=markets_filtered,
            markets_analyzed=len(markets),
            deepbriefs_generated=success_count,
            errors_count=error_count,
            duration_seconds=duration_seconds,
            error_message=None if error_count == 0 else f"{error_count} errores",
        )

        logger.info("Pipeline terminado.")
        logger.info("DeepBriefs exitosos: %s", success_count)
        logger.info("Errores: %s", error_count)
        logger.info("Duración: %s segundos", duration_seconds)

        print("\nGeneración de DeepBriefs terminada.")
        print("DeepBriefs exitosos:", success_count)
        print("Errores:", error_count)
        print("Duración:", duration_seconds, "segundos")

    except Exception as fatal_error:
        duration_seconds = round(time.time() - started_at, 2)

        logger.exception("Pipeline falló completamente: %s", fatal_error)

        finish_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            status="failed",
            markets_fetched=markets_fetched,
            markets_filtered=markets_filtered,
            markets_analyzed=0,
            deepbriefs_generated=success_count,
            errors_count=error_count + 1,
            duration_seconds=duration_seconds,
            error_message=str(fatal_error),
        )

        raise


if __name__ == "__main__":
    main()
