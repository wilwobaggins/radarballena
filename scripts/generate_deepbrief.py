from services.supabase_service import get_supabase_client, insert_deepbrief
from services.deepbrief_generator import generate_deepbrief_for_market
from services.market_filter import select_top_markets


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


def main():
    markets = get_top_markets(limit=5)

    print("Markets encontrados:", len(markets))

    if len(markets) < 5:
        print("Aviso: hay menos de 5 mercados reales disponibles.")

    for market in markets:
        print("Generando DeepBrief para:", market.get("title"))

        deepbrief, raw_output = generate_deepbrief_for_market(market)

        saved = insert_deepbrief(
            market_db_id=market["id"],
            deepbrief=deepbrief,
            raw_output=raw_output,
        )

        print("DeepBrief guardado:", saved["id"])

    print("Generación de DeepBriefs terminada.")


if __name__ == "__main__":
    main()
