import os
from typing import Any

from dotenv import load_dotenv
from tavily import TavilyClient
from services.context_ranker import rank_context_sources


load_dotenv()


def required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Falta variable de entorno: {name}")

    return value


def query_builder(market: dict[str, Any]) -> str:
    """
    Construye una búsqueda corta.
    Tavily recomienda queries concisas; no mandes todo el prompt.
    """
    title = str(market.get("title") or "").strip()
    category = str(market.get("category") or "").strip()
    close_date = str(market.get("close_date") or "").strip()

    parts = [title]

    if category:
        parts.append(category)

    if close_date:
        parts.append(f"before {close_date[:10]}")

    parts.append("latest context prediction market")

    query = " ".join(parts)

    return query[:350]


def normalize_tavily_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_title": result.get("title"),
        "source_url": result.get("url"),
        "published_date": result.get("published_date"),
        "summary": result.get("content") or result.get("raw_content") or "",
        "relevance_score": result.get("score") or 0.7,
        "raw_payload": result,
    }


def search_context(
    market: dict[str, Any],
    max_results: int = 3,
) -> list[dict[str, Any]]:
    provider = os.getenv("CONTEXT_PROVIDER", "tavily").lower()

    if provider != "tavily":
        raise RuntimeError(f"Proveedor de contexto no soportado: {provider}")

    api_key = required_env("TAVILY_API_KEY")
    client = TavilyClient(api_key=api_key)

    query = query_builder(market)

    response = client.search(
        query=query,
        search_depth="basic",
        topic="general",
        max_results=max_results,
        include_answer=False,
        include_raw_content=False,
    )

    results = response.get("results") or []

    normalized = []

    for result in results[:max_results]:
        source = normalize_tavily_result(result)

        if source["source_title"] and source["source_url"]:
            normalized.append(source)

    return rank_context_sources(
    market=market,
    sources=normalized,
    limit=max_results,
)