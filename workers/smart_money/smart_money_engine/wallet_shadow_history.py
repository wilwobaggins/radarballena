from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median, pstdev
from typing import Any


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[3] / "outputs"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    if math.isnan(value) or math.isinf(value):
        return lower
    return max(lower, min(upper, value))


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def _resolve_path(value: str | os.PathLike[str] | None, default: Path) -> Path:
    path = Path(value) if value else default
    if not path.is_absolute():
        path = Path.cwd() / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_history_paths() -> dict[str, Path]:
    output_dir = _resolve_path(os.getenv("SMART_MONEY_ENGINE_OUTPUT_DIR"), DEFAULT_OUTPUT_DIR)
    runs_dir = _resolve_path(os.getenv("SHADOW_RUNS_DIR"), output_dir / "wallet_shadow_runs")
    history_file = Path(os.getenv("SHADOW_HISTORY_FILE") or (output_dir / "wallet_shadow_history.jsonl"))
    if not history_file.is_absolute():
        history_file = Path.cwd() / history_file
    history_file.parent.mkdir(parents=True, exist_ok=True)
    return {
        "output_dir": output_dir,
        "runs_dir": runs_dir,
        "history_file": history_file,
    }


def _dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
    os.replace(tmp_path, path)


def load_history_file(history_file: Path) -> list[dict[str, Any]]:
    if not history_file.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in history_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def write_shadow_run_snapshot(runs_dir: Path, run_id: str, payload: dict[str, Any]) -> Path:
    path = runs_dir / f"{run_id}.json"
    _dump_json(path, payload)
    return path


def append_shadow_history(history_file: Path, records: list[dict[str, Any]]) -> None:
    existing = load_history_file(history_file)
    seen = {
        (str(item.get("runId")), str(item.get("wallet")))
        for item in existing
        if item.get("runId") is not None and item.get("wallet") is not None
    }

    merged = list(existing)
    for record in records:
        key = (str(record.get("runId")), str(record.get("wallet")))
        if key in seen:
            continue
        seen.add(key)
        merged.append(record)

    tmp_path = history_file.with_suffix(history_file.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        for record in merged:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    os.replace(tmp_path, history_file)


def build_shadow_history_record(
    *,
    run_id: str,
    wallet_row: dict[str, Any],
    generated_at: str | None = None,
) -> dict[str, Any]:
    shadow_skill = wallet_row.get("shadowSkill") or {}
    shadow_meta = wallet_row.get("shadowMetaEvaluation") or {}
    shadow_robust = wallet_row.get("shadowRobustEvaluation") or {}
    generated_at = generated_at or wallet_row.get("generatedAt") or iso_now()
    return {
        "runId": run_id,
        "wallet": wallet_row.get("wallet"),
        "displayName": wallet_row.get("displayName"),
        "roles": wallet_row.get("roles") or [],
        "profiles": wallet_row.get("profiles") or [],
        "sources": wallet_row.get("sources") or [],
        "classification": wallet_row.get("classification"),
        "behaviorQualityScore": wallet_row.get("behaviorQualityScore"),
        "skillScore": shadow_skill.get("skillScore"),
        "robustSkillScore": shadow_robust.get("robustSkillScore"),
        "shadowMetaScore": shadow_meta.get("shadowMetaScore"),
        "shadowRobustMetaScore": shadow_robust.get("shadowRobustMetaScore"),
        "generatedAt": generated_at,
    }


def _trend(latest_value: float, first_value: float) -> str:
    delta = latest_value - first_value
    if delta >= 5:
        return "rising"
    if delta <= -5:
        return "falling"
    return "stable"


def compute_longitudinal_metrics(history_records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_wallet: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in history_records:
        wallet = str(record.get("wallet") or "").strip().lower()
        if not wallet:
            continue
        by_wallet[wallet].append(record)

    result: dict[str, dict[str, Any]] = {}
    for wallet, records in by_wallet.items():
        ordered = sorted(records, key=lambda item: str(item.get("generatedAt") or ""))
        robust_meta_scores = [
            _safe_float(item.get("shadowRobustMetaScore") or item.get("shadowRobustEvaluation", {}).get("shadowRobustMetaScore"))
            for item in ordered
        ]
        robust_skill_scores = [
            _safe_float(item.get("robustSkillScore") or item.get("shadowRobustEvaluation", {}).get("robustSkillScore"))
            for item in ordered
        ]
        valid_scores = [score for score in robust_meta_scores if not math.isnan(score)]
        valid_skill_scores = [score for score in robust_skill_scores if not math.isnan(score)]
        successful = [item for item in ordered if item.get("shadowRobustMetaScore") is not None]

        if not valid_scores:
            continue

        latest_meta = valid_scores[-1]
        latest_skill = valid_skill_scores[-1] if valid_skill_scores else latest_meta
        first_meta = valid_scores[0]

        if len(valid_scores) >= 3:
            stability = _clamp(100.0 - (pstdev(valid_scores) * 4.0))
            comparison_score = _clamp(
                0.70 * latest_meta + 0.20 * median(valid_scores) + 0.10 * stability
            )
            score_trend = _trend(latest_meta, first_meta)
            comparison_confidence = "sufficient"
        else:
            stability = None
            comparison_score = _clamp(latest_meta)
            score_trend = None
            comparison_confidence = "limited"

        result[wallet] = {
            "wallet": wallet,
            "runCount": len(ordered),
            "successfulRunCount": len(successful),
            "firstSeenAt": ordered[0].get("generatedAt"),
            "lastSeenAt": ordered[-1].get("generatedAt"),
            "latestRobustMetaScore": round(latest_meta, 2),
            "averageRobustMetaScore": round(mean(valid_scores), 2),
            "medianRobustMetaScore": round(median(valid_scores), 2),
            "minRobustMetaScore": round(min(valid_scores), 2),
            "maxRobustMetaScore": round(max(valid_scores), 2),
            "robustMetaStdDev": round(pstdev(valid_scores), 4) if len(valid_scores) > 1 else 0.0,
            "latestRobustSkillScore": round(latest_skill, 2),
            "averageRobustSkillScore": round(mean(valid_skill_scores), 2) if valid_skill_scores else round(latest_skill, 2),
            "scoreTrend": score_trend,
            "stabilityScore": round(stability, 2) if stability is not None else None,
            "longitudinalStatus": "sufficient_history" if len(valid_scores) >= 3 else "insufficient_history",
            "longitudinalComparisonScore": round(comparison_score, 2),
            "comparisonConfidence": comparison_confidence,
        }

    return result
