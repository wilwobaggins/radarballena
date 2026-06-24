from __future__ import annotations

import asyncio
import math
import os
import re
from typing import Any

import httpx


WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
DEFAULT_TIMEOUT_SECONDS = float(os.getenv("SKILL_HTTP_TIMEOUT_SECONDS", "25"))


def _normalize_number(value: Any) -> float | None:
    try:
        number = float(value)
    except Exception:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _sanitize_position(position: dict[str, Any]) -> dict[str, Any]:
    sanitized: dict[str, Any] = {}
    for key, value in position.items():
        if key in {"avgPrice", "totalBought", "realizedPnl"}:
            sanitized[key] = _normalize_number(value)
        else:
            sanitized[key] = value
    return sanitized


def _is_transient_error(error: Exception) -> bool:
    if isinstance(error, (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError, httpx.ConnectTimeout, httpx.ReadError)):
        return True

    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    if status_code in {429, 500, 502, 503, 504}:
        return True

    status_code = getattr(error, "status_code", None)
    return status_code in {429, 500, 502, 503, 504}


async def _fetch_page(
    client: httpx.AsyncClient,
    wallet: str,
    *,
    offset: int,
    limit: int,
) -> list[dict[str, Any]]:
    response = await client.get(
        "https://data-api.polymarket.com/closed-positions",
        params={
            "user": wallet,
            "limit": limit,
            "offset": offset,
            "sortBy": "TIMESTAMP",
            "sortDirection": "DESC",
        },
    )
    response.raise_for_status()
    data = response.json()
    if isinstance(data, dict):
        items = data.get("data") or data.get("items") or data.get("positions") or []
    else:
        items = data
    if not isinstance(items, list):
        return []
    return [_sanitize_position(item) for item in items if isinstance(item, dict)]


async def fetch_closed_positions(wallet: str, max_positions: int = 500) -> list[dict[str, Any]]:
    normalized_wallet = str(wallet or "").strip()
    if not WALLET_RE.match(normalized_wallet):
        return []

    timeout_seconds = float(os.getenv("SKILL_HTTP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    retries = 3
    limit = 50
    collected: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        offset = 0
        while offset < max_positions:
            last_error: Exception | None = None
            page: list[dict[str, Any]] = []
            for attempt in range(retries):
                try:
                    page = await _fetch_page(client, normalized_wallet, offset=offset, limit=limit)
                    last_error = None
                    break
                except Exception as error:
                    last_error = error
                    if not _is_transient_error(error) or attempt >= retries - 1:
                        raise
                    await asyncio.sleep(0.5 * (2**attempt))

            if last_error is not None:
                raise last_error

            if not page:
                break

            collected.extend(page[: max_positions - len(collected)])
            if len(page) < limit or len(collected) >= max_positions:
                break
            offset += limit

    return collected[:max_positions]

