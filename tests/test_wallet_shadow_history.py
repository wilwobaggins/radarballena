
import shutil
from datetime import datetime
from pathlib import Path

from workers.smart_money.smart_money_engine.wallet_shadow_history import (
    append_shadow_history,
    build_shadow_history_record,
    compute_longitudinal_metrics,
    iso_now,
    load_history_file,
    resolve_history_paths,
    write_shadow_run_snapshot,
)


def test_shadow_history_dedupes_run_wallet():
    base = Path.cwd() / "tests" / "_shadow_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    try:
        history_file = base / "wallet_shadow_history.jsonl"
        run_dir = base / "runs"
        record = {
            "runId": "run-1",
            "wallet": "0x" + "a" * 40,
            "shadowRobustMetaScore": 60,
            "robustSkillScore": 55,
            "generatedAt": "2026-06-24T00:00:00+00:00",
        }

        append_shadow_history(history_file, [record])
        append_shadow_history(history_file, [record])
        loaded = load_history_file(history_file)

        assert len(loaded) == 1
        snapshot = write_shadow_run_snapshot(run_dir, "run-1", {"wallets": [record]})
        assert snapshot.exists()
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_longitudinal_metrics_compute_stability_and_trend():
    records = [
        {
            "runId": "run-1",
            "wallet": "0x" + "a" * 40,
            "shadowRobustMetaScore": 60,
            "robustSkillScore": 50,
            "generatedAt": "2026-06-22T00:00:00+00:00",
        },
        {
            "runId": "run-2",
            "wallet": "0x" + "a" * 40,
            "shadowRobustMetaScore": 66,
            "robustSkillScore": 54,
            "generatedAt": "2026-06-23T00:00:00+00:00",
        },
        {
            "runId": "run-3",
            "wallet": "0x" + "a" * 40,
            "shadowRobustMetaScore": 72,
            "robustSkillScore": 58,
            "generatedAt": "2026-06-24T00:00:00+00:00",
        },
        {
            "runId": "run-1",
            "wallet": "0x" + "b" * 40,
            "shadowRobustMetaScore": 44,
            "robustSkillScore": 40,
            "generatedAt": "2026-06-24T00:00:00+00:00",
        },
        {
            "runId": "run-2",
            "wallet": "0x" + "b" * 40,
            "shadowRobustMetaScore": 46,
            "robustSkillScore": 41,
            "generatedAt": "2026-06-25T00:00:00+00:00",
        },
    ]

    metrics = compute_longitudinal_metrics(records)
    alpha = metrics["0x" + "a" * 40]
    beta = metrics["0x" + "b" * 40]

    assert alpha["longitudinalStatus"] == "sufficient_history"
    assert alpha["stabilityScore"] is not None
    assert alpha["scoreTrend"] == "rising"
    assert alpha["comparisonConfidence"] == "sufficient"
    assert beta["longitudinalStatus"] == "insufficient_history"
    assert beta["stabilityScore"] is None
    assert beta["scoreTrend"] is None


def test_shadow_history_record_shape():
    row = {
        "wallet": "0x" + "c" * 40,
        "displayName": "Wallet C",
        "roles": ["active"],
        "profiles": ["sports"],
        "sources": ["active_wallet_config"],
        "classification": "SCALPER",
        "behaviorQualityScore": 66,
        "shadowSkill": {"skillScore": 80},
        "shadowMetaEvaluation": {"shadowMetaScore": 70},
        "shadowRobustEvaluation": {"shadowRobustMetaScore": 68, "robustSkillScore": 65},
        "generatedAt": "2026-06-24T00:00:00+00:00",
    }
    record = build_shadow_history_record(run_id="run-9", wallet_row=row)

    assert record["runId"] == "run-9"
    assert record["wallet"] == row["wallet"]
    assert record["shadowRobustMetaScore"] == 68
    assert record["skillScore"] == 80


def test_iso_now_returns_utc_timestamp():
    timestamp = iso_now()

    assert timestamp.endswith("+00:00")
    assert datetime.fromisoformat(timestamp).tzinfo is not None


def test_resolve_history_paths_defaults_to_repo_outputs(monkeypatch):
    monkeypatch.delenv("SMART_MONEY_ENGINE_OUTPUT_DIR", raising=False)
    monkeypatch.delenv("SHADOW_RUNS_DIR", raising=False)
    monkeypatch.delenv("SHADOW_HISTORY_FILE", raising=False)

    paths = resolve_history_paths()

    assert paths["output_dir"].name == "outputs"
    assert paths["history_file"].name == "wallet_shadow_history.jsonl"
    assert paths["history_file"].parent.name == "outputs"


def test_shadow_history_record_generates_timestamp_when_missing():
    row = {
        "wallet": "0x" + "d" * 40,
        "displayName": "Wallet D",
        "roles": ["active"],
        "profiles": ["macro"],
        "sources": ["global_wallet_scores"],
        "classification": "SIGNAL_WALLET",
        "behaviorQualityScore": 74,
        "shadowSkill": {"skillScore": 81},
        "shadowMetaEvaluation": {"shadowMetaScore": 79},
        "shadowRobustEvaluation": {"shadowRobustMetaScore": 77, "robustSkillScore": 76},
    }

    record = build_shadow_history_record(run_id="run-missing", wallet_row=row)

    assert record["generatedAt"].endswith("+00:00")
    assert datetime.fromisoformat(record["generatedAt"]).tzinfo is not None
