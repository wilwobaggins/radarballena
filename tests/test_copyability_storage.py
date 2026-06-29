from __future__ import annotations

import json
import shutil
from pathlib import Path

from workers.smart_money.smart_money_engine import copyability_storage as storage


def test_copyability_storage_write_append_and_state():
    base = Path.cwd() / "tests" / "_copyability_storage_tmp" / "outputs"
    shutil.rmtree(base.parent, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    monkey_paths = {
        "OUTPUT_DIR": base,
        "TRADE_COPYABILITY_SHADOW_FILE": base / "trade_copyability_shadow.json",
        "TRADE_COPYABILITY_HISTORY_FILE": base / "trade_copyability_history.jsonl",
        "TRADE_COPYABILITY_STATE_FILE": base / "trade_copyability_state.json",
        "WALLET_COPYABILITY_SUMMARY_FILE": base / "wallet_copyability_summary.json",
        "TRADE_COPYABILITY_BACKTEST_FILE": base / "trade_copyability_backtest.json",
    }
    old_values = {name: getattr(storage, name) for name in monkey_paths}
    try:
        for name, value in monkey_paths.items():
            setattr(storage, name, value)

        storage.write_trade_copyability_shadow({"runId": "run-1", "generatedAt": "2026-06-29T00:00:00+00:00", "clusters": []})
        storage.write_trade_copyability_state({"cluster-1": {"validationStatus": "complete"}})
        storage.write_wallet_copyability_summary({"0x1": {"wallet": "0x1"}})
        storage.write_trade_copyability_backtest({"groups": []})
        storage.append_trade_copyability_history(
            [
                {"runId": "run-1", "clusterId": "cluster-1", "validationStatus": "complete", "generatedAt": "2026-06-29T00:00:00+00:00"},
                {"runId": "run-1", "clusterId": "cluster-1", "validationStatus": "complete", "generatedAt": "2026-06-29T00:00:00+00:00"},
            ]
        )

        history = (base / "trade_copyability_history.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(history) == 1
        payload = json.loads(history[0])
        assert payload["clusterId"] == "cluster-1"
        assert (base / "trade_copyability_shadow.json").exists()
        assert (base / "trade_copyability_state.json").exists()
        assert (base / "wallet_copyability_summary.json").exists()
        assert (base / "trade_copyability_backtest.json").exists()
    finally:
        for name, value in old_values.items():
            setattr(storage, name, value)
        shutil.rmtree(base.parent, ignore_errors=True)
