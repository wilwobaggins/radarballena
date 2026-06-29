from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any


def _resolve_output_dir() -> Path:
    configured = os.getenv("SMART_MONEY_ENGINE_OUTPUT_DIR")
    if not configured:
        output_dir = Path(__file__).resolve().parents[3] / "outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir
    output_dir = Path(configured)
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


OUTPUT_DIR = _resolve_output_dir()

TRADE_COPYABILITY_SHADOW_FILE = OUTPUT_DIR / "trade_copyability_shadow.json"
TRADE_COPYABILITY_HISTORY_FILE = OUTPUT_DIR / "trade_copyability_history.jsonl"
TRADE_COPYABILITY_STATE_FILE = OUTPUT_DIR / "trade_copyability_state.json"
WALLET_COPYABILITY_SUMMARY_FILE = OUTPUT_DIR / "wallet_copyability_summary.json"
TRADE_COPYABILITY_BACKTEST_FILE = OUTPUT_DIR / "trade_copyability_backtest.json"


def _sanitize_number(value: Any) -> Any:
    try:
        number = float(value)
    except Exception:
        return value
    if math.isnan(number) or math.isinf(number):
        return None
    if number.is_integer():
        return int(number)
    return number


def sanitize_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: sanitize_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_payload(item) for item in value]
    if isinstance(value, float):
        return _sanitize_number(value)
    return value


def _atomic_write_json(path: Path, payload: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(sanitize_payload(payload), handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, path)
    return path


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def read_trade_copyability_state() -> dict[str, Any]:
    state = _read_json(TRADE_COPYABILITY_STATE_FILE, {})
    return state if isinstance(state, dict) else {}


def write_trade_copyability_shadow(payload: dict[str, Any]) -> Path:
    return _atomic_write_json(TRADE_COPYABILITY_SHADOW_FILE, payload)


def write_trade_copyability_state(payload: dict[str, Any]) -> Path:
    return _atomic_write_json(TRADE_COPYABILITY_STATE_FILE, payload)


def write_wallet_copyability_summary(payload: dict[str, Any]) -> Path:
    return _atomic_write_json(WALLET_COPYABILITY_SUMMARY_FILE, payload)


def write_trade_copyability_backtest(payload: dict[str, Any]) -> Path:
    return _atomic_write_json(TRADE_COPYABILITY_BACKTEST_FILE, payload)


def append_trade_copyability_history(records: list[dict[str, Any]]) -> Path:
    existing: list[dict[str, Any]] = []
    if TRADE_COPYABILITY_HISTORY_FILE.exists():
        for line in TRADE_COPYABILITY_HISTORY_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if isinstance(payload, dict):
                existing.append(payload)

    seen = {
        (
            str(item.get("runId")),
            str(item.get("clusterId")),
            str(item.get("validationStatus")),
        )
        for item in existing
        if item.get("runId") is not None and item.get("clusterId") is not None and item.get("validationStatus") is not None
    }

    merged = list(existing)
    for record in records:
        key = (
            str(record.get("runId")),
            str(record.get("clusterId")),
            str(record.get("validationStatus")),
        )
        if key in seen:
            continue
        seen.add(key)
        merged.append(sanitize_payload(record))

    TRADE_COPYABILITY_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = TRADE_COPYABILITY_HISTORY_FILE.with_suffix(TRADE_COPYABILITY_HISTORY_FILE.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for record in merged:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp_path, TRADE_COPYABILITY_HISTORY_FILE)
    return TRADE_COPYABILITY_HISTORY_FILE
