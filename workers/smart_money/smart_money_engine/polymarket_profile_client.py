from __future__ import annotations

import math
import os
import re
from typing import Any

import httpx

try:
    from .polymarket_data_api import get_page
except ImportError:  # pragma: no cover - script-style container entrypoint
    from polymarket_data_api import get_page


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
    aliases = {
        "avg_price": "avgPrice",
        "total_size": "totalBought",
        "realized_pnl": "realizedPnl",
    }
    for key, value in position.items():
        normalized_key = aliases.get(key, key)
        if normalized_key in {"avgPrice", "totalBought", "realizedPnl"}:
            sanitized[normalized_key] = _normalize_number(value)
        else:
            sanitized[normalized_key] = value
    return sanitized


async def _fetch_page(
    client: httpx.AsyncClient,
    wallet: str,
    *,
    cursor: str | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    params: dict[str, Any] = {
        "user": wallet,
        "status": "CLOSED",
        "limit": min(1000, limit),
        "sort_by": "TIMESTAMP",
        "sort_direction": "DESC",
    }
    if cursor:
        params["cursor"] = cursor
    items, next_cursor = await get_page(client, "positions", params)
    return [_sanitize_position(item) for item in items], next_cursor


async def fetch_closed_positions(wallet: str, max_positions: int = 500) -> list[dict[str, Any]]:
    normalized_wallet = str(wallet or "").strip()
    if not WALLET_RE.match(normalized_wallet):
        return []

    timeout_seconds = float(os.getenv("SKILL_HTTP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    limit = 50
    collected: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        cursor: str | None = None
        seen_cursors: set[str] = set()
        max_pages = (max_positions + limit - 1) // limit
        for _ in range(max_pages):
            page, next_cursor = await _fetch_page(
                client, normalized_wallet, cursor=cursor, limit=limit
            )
            if not page:
                break
            if next_cursor is not None and next_cursor in seen_cursors:
                break

            collected.extend(page[: max_positions - len(collected)])
            if len(collected) >= max_positions or next_cursor is None or next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    return collected[:max_positions]

