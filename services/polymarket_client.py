import json
from datetime import datetime, timezone
from typing import Any

import requests


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_json_array(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []

    return []


def get_yes_probability(market: dict[str, Any]) -> float | None:
    """
    En Polymarket, outcomes y outcomePrices van relacionados por índice.
    Normalmente índice 0 = Yes, índice 1 = No.
    """
    outcomes = parse_json_array(market.get("outcomes"))
    prices = parse_json_array(market.get("outcomePrices"))

    if not outcomes or not prices:
        return safe_float(market.get("lastTradePrice"))

    for index, outcome in enumerate(outcomes):
        if str(outcome).lower() == "yes" and index < len(prices):
            return safe_float(prices[index])

    return safe_float(prices[0]) if prices else None


def fetch_active_markets(limit: int = 20) -> list[dict[str, Any]]:
    response = requests.get(
        f"{GAMMA_BASE_URL}/markets",
        params={
            "active": "true",
            "closed": "false",
            "limit": limit,
        },
        timeout=20,
    )

    response.raise_for_status()
    data = response.json()

    if not isinstance(data, list):
        raise RuntimeError("Respuesta inesperada de Polymarket")

    return data


def normalize_market(raw_market: dict[str, Any]) -> dict[str, Any]:
    current_probability = get_yes_probability(raw_market)

    volume = (
        safe_float(raw_market.get("volume24hr"))
        or safe_float(raw_market.get("volume"))
        or 0
    )

    liquidity = safe_float(raw_market.get("liquidity")) or 0

    external_market_id = str(
        raw_market.get("id")
        or raw_market.get("conditionId")
        or raw_market.get("questionID")
        or ""
    )

    if not external_market_id:
        raise ValueError("Market sin id válido")

    slug = raw_market.get("slug")
    url = f"https://polymarket.com/event/{slug}" if slug else None

    return {
        "external_market_id": external_market_id,
        "platform": "polymarket",
        "title": raw_market.get("question") or raw_market.get("title"),
        "description": raw_market.get("description"),
        "category": raw_market.get("category"),
        "url": url,
        "close_date": raw_market.get("endDate") or raw_market.get("endDateIso"),
        "current_probability": current_probability,
        "previous_probability_24h": None,
        "probability_change_24h": None,
        "volume": volume,
        "liquidity": liquidity,
        "outcomes": parse_json_array(raw_market.get("outcomes")),
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "raw_payload": raw_market,
    }


def get_normalized_active_markets(limit: int = 20) -> list[dict[str, Any]]:
    raw_markets = fetch_active_markets(limit=limit)

    normalized = []

    for raw_market in raw_markets:
        try:
            normalized.append(normalize_market(raw_market))
        except Exception as error:
            print("Market omitido:", error)

    return normalized