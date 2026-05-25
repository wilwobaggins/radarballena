from services.context_client import query_builder, search_context
from services.supabase_service import (
    get_markets_for_context,
    insert_market_context,
)


def main():
    markets = get_markets_for_context(limit=5)

    print("Mercados para contexto:", len(markets))

    if not markets:
        print("No hay mercados disponibles.")
        return

    total_sources = 0

    for market in markets:
        print("\nMercado:", market.get("title"))
        print("Query:", query_builder(market))

        sources = search_context(market, max_results=3)

        print("Fuentes encontradas:", len(sources))

        for source in sources:
            saved = insert_market_context(
                market_db_id=market["id"],
                source=source,
            )

            total_sources += 1

            print("Fuente OK:", saved["id"], "|", source.get("source_title"))

    print("\nContexto guardado OK.")
    print("Fuentes totales guardadas:", total_sources)


if __name__ == "__main__":
    main()