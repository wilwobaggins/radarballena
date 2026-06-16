import json
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def save_json(filename: str, data: Any) -> Path:
    path = OUTPUT_DIR / filename

    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)

    return path


def load_json(filename: str) -> Any:
    path = OUTPUT_DIR / filename

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
