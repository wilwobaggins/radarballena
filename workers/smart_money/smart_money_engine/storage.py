import json
from pathlib import Path
from typing import Any

try:  # pragma: no cover - support package and script-style imports
    from .path_utils import resolve_output_dir
except ImportError:  # pragma: no cover
    from path_utils import resolve_output_dir

OUTPUT_DIR = resolve_output_dir()


def save_json(filename: str, data: Any) -> Path:
    path = OUTPUT_DIR / filename

    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=2, default=str)

    return path


def load_json(filename: str) -> Any:
    path = OUTPUT_DIR / filename

    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)
