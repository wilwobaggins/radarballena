from services.supabase_service import (
    get_supabase_client,
    insert_deepbrief,
    get_market_context,
    insert_market_context,
)
from services.deepbrief_generator import generate_deepbrief_for_market
from services.market_filter import select_top_markets
from services.context_client import search_context
from services.scoring_service import calculate_hybrid_radar_score

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


def main():
    markets = get_top_markets(limit=5)

    print("Markets encontrados:", len(markets))

    if len(markets) < 5:
        print("Aviso: hay menos de 5 mercados reales disponibles.")

    for market in markets:
        print("Generando DeepBrief para:", market.get("title"))

        context_sources = ensure_market_context(market, min_sources=3)

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

        print("DeepBrief guardado:", saved["id"])

    print("Generación de DeepBriefs terminada.")


if __name__ == "__main__":
    main()
