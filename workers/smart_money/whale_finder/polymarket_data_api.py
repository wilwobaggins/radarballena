from __future__ import annotations

import asyncio
from typing import Any

import httpx


BASE_URL = "https://data-api.polymarket.com/v2"
MAX_PAGE_SIZE = 1000
MAX_RETRY_AFTER_SECONDS = 5.0


def parse_page(payload: Any) -> tuple[list[dict[str, Any]], str | None]:
    if not isinstance(payload, dict):
        raise ValueError("Polymarket v2 response must be an object envelope")
    rows = payload.get("data")
    pagination = payload.get("pagination")
    if not isinstance(rows, list) or not isinstance(pagination, dict):
        raise ValueError("Polymarket v2 response is missing data/pagination")
    items = [row for row in rows if isinstance(row, dict)]
    cursor = pagination.get("next_cursor")
    return items, cursor if isinstance(cursor, str) and cursor else None


async def get_page(client: httpx.AsyncClient, params: dict[str, Any]) -> tuple[list[dict[str, Any]], str | None]:
    for attempt in range(2):
        try:
            response = await client.get(f"{BASE_URL}/trades", params=params)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout):
            if attempt:
                raise
            await asyncio.sleep(0.25)
            continue

        if response.status_code in {429, 503} and attempt == 0:
            try:
                delay = float(response.headers.get("Retry-After", ""))
            except ValueError:
                delay = None
            if delay is not None and 0 <= delay <= MAX_RETRY_AFTER_SECONDS:
                await asyncio.sleep(delay)
                continue
        response.raise_for_status()
        return parse_page(response.json())
    raise RuntimeError("Polymarket request exhausted its retry budget")


async def iter_pages(client: httpx.AsyncClient, params: dict[str, Any], *, max_items: int):
    budget = max(0, int(max_items))
    if budget == 0:
        return
    page_size = min(MAX_PAGE_SIZE, max(1, int(params.get("limit", 100))))
    query = {**params, "limit": page_size}
    cursor: str | None = None
    seen_cursors: set[str] = set()
    collected = 0
    max_pages = (budget + page_size - 1) // page_size
    for _ in range(max_pages):
        request_params = dict(query)
        if cursor:
            request_params["cursor"] = cursor
        rows, next_cursor = await get_page(client, request_params)
        if not rows:
            break
        if next_cursor is not None and next_cursor in seen_cursors:
            break
        page = rows[: budget - collected]
        yield page
        collected += len(page)
        if collected >= budget or next_cursor is None or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor
