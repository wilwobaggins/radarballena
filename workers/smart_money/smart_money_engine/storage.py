import json
import os
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent


def _resolve_output_dir() -> Path:
    configured = os.getenv("SMART_MONEY_ENGINE_OUTPUT_DIR", "outputs")
    output_dir = Path(configured)
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


OUTPUT_DIR = _resolve_output_dir()


def save_json(filename: str, data: Any) -> Path:
    path = OUTPUT_DIR / filename

    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)

    return path


def load_json(filename: str) -> Any:
    path = OUTPUT_DIR / filename

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
