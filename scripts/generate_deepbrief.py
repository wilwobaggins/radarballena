from services.supabase_service import get_supabase_client, insert_deepbrief
from services.deepbrief_generator import generate_deepbrief_for_market


def get_top_markets(limit: int = 5):
    supabase = get_supabase_client()

    response = (
        supabase
        .table("markets")
        .select("*")
        .eq("platform", "polymarket")
        .neq("external_market_id", "test_market_001")
        .order("volume", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


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