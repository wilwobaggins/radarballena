from __future__ import annotations

import os
from pathlib import Path


def _candidate_paths() -> list[Path]:
    here = Path(__file__).resolve()
    repo_outputs = next((parent / "outputs" for index, parent in enumerate(here.parents) if index == 3), None)
    candidates = [
        repo_outputs,
        here.parent / "outputs",
        Path.cwd() / "outputs",
    ]
    seen: set[str] = set()
    unique: list[Path] = []
    for candidate in candidates:
        if candidate is None:
            continue
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def resolve_output_dir() -> Path:
    configured = (
        os.getenv("COPYABILITY_OUTPUTS_DIR")
        or os.getenv("SMART_MONEY_ENGINE_OUTPUT_DIR")
        or ""
    ).strip()
    if configured:
        output_dir = Path(configured)
        if not output_dir.is_absolute():
            output_dir = Path.cwd() / output_dir
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    for candidate in _candidate_paths():
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            return candidate
        except Exception:
            continue

    fallback = Path.cwd() / "outputs"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def resolve_copyability_output_dir() -> Path:
    return resolve_output_dir()
