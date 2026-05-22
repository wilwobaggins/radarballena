from services.supabase_service import get_supabase_client, insert_deepbrief
from services.deepbrief_generator import generate_deepbrief_for_market


def get_top_markets(limit: int = 5):
    supabase = get_supabase_client()

    response = (
        supabase
        .table("markets")
        .select("*")
        .order("volume", desc=True)
        .limit(limit)
        .execute()
    )

    return response.data or []


def main():
    markets = get_top_markets(limit=5)

    for market in markets:
        print("Generando DeepBrief para:", market.get("title"))

        deepbrief = generate_deepbrief_for_market(market)

        saved = insert_deepbrief(
            market_db_id=market["id"],
            deepbrief=deepbrief,
            raw_output=deepbrief,
        )

        print("DeepBrief guardado:", saved["id"])


if __name__ == "__main__":
    main()