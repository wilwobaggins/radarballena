from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _coerce_numeric_timestamp(value: Any) -> float | None:
    try:
        if isinstance(value, bool):
            return None
        number = float(value)
    except Exception:
        return None
    if number != number:
        return None
    if abs(number) >= 10_000_000_000:
        number /= 1000.0
    return number


def to_utc_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    numeric_value = _coerce_numeric_timestamp(value)
    if numeric_value is not None:
        try:
            return datetime.fromtimestamp(numeric_value, tz=timezone.utc)
        except Exception:
            return None

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def to_unix_seconds(value: Any) -> int | None:
    utc_value = to_utc_datetime(value)
    if utc_value is None:
        return None
    return int(utc_value.timestamp())


def to_utc_iso(value: Any) -> str | None:
    utc_value = to_utc_datetime(value)
    if utc_value is None:
        return None
    return utc_value.isoformat()
