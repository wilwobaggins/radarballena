from services.polymarket_client import get_normalized_active_markets
from services.supabase_service import upsert_market, save_market_snapshot


def main():
    markets = get_normalized_active_markets(limit=100)

    print("Markets obtenidos:", len(markets))

    saved_count = 0
    snapshot_count = 0

    for market in markets:
        print("Guardando:", market.get("title"))

        saved_market = upsert_market(market)
        saved_count += 1

        print("Market OK:", saved_market["id"])

        snapshot = save_market_snapshot(saved_market["id"], market)
        snapshot_count += 1

        print("Snapshot OK:", snapshot["id"])

    print("Carga de mercados y snapshots OK.")
    print("Markets guardados/actualizados:", saved_count)
    print("Snapshots creados:", snapshot_count)


if __name__ == "__main__":
    main()