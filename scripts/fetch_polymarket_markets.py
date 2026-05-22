from services.polymarket_client import get_normalized_active_markets
from services.supabase_service import insert_market, insert_snapshot


def main():
    markets = get_normalized_active_markets(limit=100)

    print("Markets obtenidos:", len(markets))

    for market in markets:
        print("Guardando:", market.get("title"))

        # No mandes raw_payload todavía si tu tabla markets no tiene esa columna
        market_payload = dict(market)

        saved_market = insert_market(market_payload)
        print("Market OK:", saved_market["id"])

        snapshot = insert_snapshot(saved_market["id"], market_payload)
        print("Snapshot OK:", snapshot["id"])

    print("Carga de mercados Polymarket OK.")


if __name__ == "__main__":
    main()