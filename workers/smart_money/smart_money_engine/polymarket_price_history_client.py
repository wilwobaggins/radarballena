from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

try:  # pragma: no cover - support package and script-style imports
    from .time_utils import to_unix_seconds, to_utc_datetime
except ImportError:  # pragma: no cover
    from time_utils import to_unix_seconds, to_utc_datetime


DEFAULT_BASE_URL = os.getenv("COPYABILITY_PRICE_HISTORY_BASE_URL", "https://clob.polymarket.com")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("COPYABILITY_PRICE_HISTORY_TIMEOUT_SECONDS", "25"))
DEFAULT_FIDELITY = os.getenv("COPYABILITY_PRICE_FIDELITY_DEFAULT", "5")
PRICE_HISTORY_CACHE_ENABLED = os.getenv("COPYABILITY_PRICE_CACHE_ENABLED", "true").lower() == "true"

PRICE_HISTORY_CACHE: dict[str, list[dict[str, Any]]] = {}


def _normalize_token_id(token_id: Any) -> str:
    return str(token_id or "").strip()


def _normalize_point(point: dict[str, Any]) -> dict[str, Any] | None:
    try:
        timestamp_value = point.get("timestamp") or point.get("time") or point.get("t")
        if timestamp_value is None:
            return None
        timestamp = to_utc_datetime(timestamp_value)
        if timestamp is None:
            return None
        price_value = point.get("price") or point.get("value") or point.get("midpoint")
        price = float(price_value)
        if price != price or price in {float("inf"), float("-inf")}:
            return None
        return {
            "timestamp": timestamp,
            "timestampIso": timestamp.isoformat(),
            "price": price,
        }
    except Exception:
        return None


def _cache_key(token_id: str, start_timestamp: datetime | None, end_timestamp: datetime | None, fidelity: str) -> str:
    start = to_utc_datetime(start_timestamp).isoformat() if start_timestamp else ""
    end = to_utc_datetime(end_timestamp).isoformat() if end_timestamp else ""
    return f"{token_id}|{start}|{end}|{fidelity}"


def find_nearest_price_point(
    price_points: list[dict[str, Any]],
    target_timestamp: datetime,
    *,
    tolerance_minutes: int = 15,
) -> dict[str, Any] | None:
    if not price_points:
        return None
    if target_timestamp.tzinfo is None:
        target_timestamp = target_timestamp.replace(tzinfo=timezone.utc)
    tolerance = timedelta(minutes=tolerance_minutes)
    nearest: dict[str, Any] | None = None
    nearest_distance: timedelta | None = None
    for point in price_points:
        timestamp = point.get("timestamp")
        if not isinstance(timestamp, datetime):
            continue
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        distance = abs(timestamp.astimezone(timezone.utc) - target_timestamp.astimezone(timezone.utc))
        if distance > tolerance:
            continue
        if nearest_distance is None or distance < nearest_distance:
            nearest_distance = distance
            nearest = point
    return nearest


async def _fetch_history(
    client: httpx.AsyncClient,
    token_id: str,
    *,
    start_timestamp: datetime | None,
    end_timestamp: datetime | None,
    fidelity: str,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"token_id": token_id, "fidelity": fidelity}
    if start_timestamp is not None:
        start_dt = to_utc_datetime(start_timestamp)
        if start_dt is not None:
            params["start_ts"] = to_unix_seconds(start_dt)
    if end_timestamp is not None:
        end_dt = to_utc_datetime(end_timestamp)
        if end_dt is not None:
            params["end_ts"] = to_unix_seconds(end_dt)

    for path in ("prices-history", "price-history", "history"):
        try:
            response = await client.get(f"{DEFAULT_BASE_URL}/{path}", params=params)
            response.raise_for_status()
        except Exception:
            continue
        data = response.json()
        if isinstance(data, dict):
            items = data.get("data") or data.get("history") or data.get("prices") or data.get("items") or []
        else:
            items = data
        if not isinstance(items, list):
            return []
        points = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_point(item)
            if normalized is not None:
                points.append(normalized)
        points.sort(key=lambda item: item["timestamp"])
        return points
    return []


async def fetch_price_history(
    token_id: str,
    *,
    start_timestamp: datetime | None = None,
    end_timestamp: datetime | None = None,
    fidelity: str | None = None,
    client: httpx.AsyncClient | None = None,
    semaphore: asyncio.Semaphore | None = None,
    cache_enabled: bool | None = None,
) -> list[dict[str, Any]]:
    token_id = _normalize_token_id(token_id)
    if not token_id:
        return []

    fidelity = str(fidelity or DEFAULT_FIDELITY)
    cache_enabled = PRICE_HISTORY_CACHE_ENABLED if cache_enabled is None else cache_enabled
    key = _cache_key(token_id, start_timestamp, end_timestamp, fidelity)
    if cache_enabled and key in PRICE_HISTORY_CACHE:
        return list(PRICE_HISTORY_CACHE[key])

    close_client = False
    if client is None:
        client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT_SECONDS)
        close_client = True

    try:
        if semaphore is not None:
            async with semaphore:
                points = await _fetch_history(client, token_id, start_timestamp=start_timestamp, end_timestamp=end_timestamp, fidelity=fidelity)
        else:
            points = await _fetch_history(client, token_id, start_timestamp=start_timestamp, end_timestamp=end_timestamp, fidelity=fidelity)
    except Exception:
        points = []
    finally:
        if close_client:
            await client.aclose()

    if cache_enabled:
        PRICE_HISTORY_CACHE[key] = list(points)
    return points


async def fetch_batch_price_history(
    token_ids: list[str],
    *,
    start_timestamp: datetime | None = None,
    end_timestamp: datetime | None = None,
    fidelity: str | None = None,
    client: httpx.AsyncClient | None = None,
    semaphore: asyncio.Semaphore | None = None,
    cache_enabled: bool | None = None,
) -> dict[str, list[dict[str, Any]]]:
    unique_tokens: list[str] = []
    seen: set[str] = set()
    for token_id in token_ids:
        token = _normalize_token_id(token_id)
        if token and token not in seen:
            seen.add(token)
            unique_tokens.append(token)

    results: dict[str, list[dict[str, Any]]] = {}
    tasks = [
        asyncio.create_task(
            fetch_price_history(
                token_id,
                start_timestamp=start_timestamp,
                end_timestamp=end_timestamp,
                fidelity=fidelity,
                client=client,
                semaphore=semaphore,
                cache_enabled=cache_enabled,
            )
        )
        for token_id in unique_tokens
    ]
    for token_id, task in zip(unique_tokens, tasks):
        results[token_id] = await task
    return results
