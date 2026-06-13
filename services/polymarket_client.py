import json
from datetime import datetime, timezone
from typing import Any

import requests

from services.logger_service import get_logger


GAMMA_BASE_URL = "https://gamma-api.polymarket.com"
logger = get_logger("polymarket_client")


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first_float(*values: Any) -> float | None:
    for value in values:
        parsed = safe_float(value)
        if parsed is not None:
            return parsed
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
    outcomes = parse_json_array(market.get("outcomes"))
    prices = parse_json_array(market.get("outcomePrices"))

    if not outcomes or not prices:
        return first_float(
            market.get("lastTradePrice"),
            market.get("bestAsk"),
            market.get("bestBid"),
        )

    for index, outcome in enumerate(outcomes):
        if str(outcome).lower() in {"yes", "sí", "si"} and index < len(prices):
            return safe_float(prices[index])

    return safe_float(prices[0]) if prices else None


def get_probability_change_24h(raw_market: dict[str, Any]) -> float | None:
    return first_float(
        raw_market.get("oneDayPriceChange"),
        raw_market.get("priceChange24h"),
        raw_market.get("oneDayChange"),
        raw_market.get("change24h"),
    )


def derive_previous_probability_24h(
    current_probability: float | None,
    probability_change_24h: float | None,
) -> float | None:
    if current_probability is None or probability_change_24h is None:
        return None

    previous = current_probability - probability_change_24h

    if previous < 0 or previous > 1:
        return None

    return previous


def get_market_dedupe_key(raw_market: dict[str, Any]) -> str | None:
    for key in ("id", "conditionId", "questionID"):
        value = raw_market.get(key)
        if value not in (None, ""):
            return str(value)

    return None


def fetch_active_markets(limit: int = 20) -> list[dict[str, Any]]:
    requested_limit = max(limit, 0)
    page_size = min(100, requested_limit or 100)
    offset = 0
    raw_markets: list[dict[str, Any]] = []

    while len(raw_markets) < requested_limit or (requested_limit == 0 and offset == 0):
        response = requests.get(
            f"{GAMMA_BASE_URL}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": page_size,
                "offset": offset,
            },
            timeout=20,
        )
        response.raise_for_status()
        data = response.json()

        if not isinstance(data, list):
            raise RuntimeError("Respuesta inesperada de Polymarket")

        logger.info(
            "POLYMARKET_FETCH_PAGE | offset=%s | requested=%s | returned=%s",
            offset,
            page_size,
            len(data),
        )

        raw_markets.extend(data)

        if len(data) < page_size or requested_limit == 0:
            break

        offset += page_size

    unique_markets: list[dict[str, Any]] = []
    seen_keys: set[str] = set()

    for raw_market in raw_markets:
        dedupe_key = get_market_dedupe_key(raw_market)

        if dedupe_key and dedupe_key in seen_keys:
            continue

        if dedupe_key:
            seen_keys.add(dedupe_key)

        unique_markets.append(raw_market)

        if requested_limit and len(unique_markets) >= requested_limit:
            break

    logger.info(
        "POLYMARKET_FETCH_TOTAL | requested=%s | raw=%s | unique=%s",
        requested_limit,
        len(raw_markets),
        len(unique_markets),
    )

    return unique_markets


def normalize_market(raw_market: dict[str, Any]) -> dict[str, Any]:
    current_probability = get_yes_probability(raw_market)
    probability_change_24h = get_probability_change_24h(raw_market)
    previous_probability_24h = derive_previous_probability_24h(
        current_probability=current_probability,
        probability_change_24h=probability_change_24h,
    )

    volume = (
        first_float(
            raw_market.get("volume24hr"),
            raw_market.get("volume"),
            raw_market.get("volumeNum"),
            raw_market.get("volume24hrClob"),
        )
        or 0
    )

    liquidity = (
        first_float(
            raw_market.get("liquidity"),
            raw_market.get("liquidityNum"),
            raw_market.get("liquidityClob"),
        )
        or 0
    )

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
        "previous_probability_24h": previous_probability_24h,
        "probability_change_24h": probability_change_24h,
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
