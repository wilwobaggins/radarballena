from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from workers.smart_money.smart_money_engine import copyability_storage
from workers.smart_money.smart_money_engine import trade_copyability


def _trade(wallet: str, *, minutes: int, asset: str, condition: str, side: str = "BUY", outcome: str = "Yes", price: float = 0.2, size: float = 100, shares: float = 10):
    ts = datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc) + timedelta(minutes=minutes)
    return {
        "wallet": wallet,
        "timestamp": int(ts.timestamp()),
        "timestampIso": ts.isoformat(),
        "conditionId": condition,
        "asset": asset,
        "marketTitle": f"{condition} market",
        "eventSlug": condition,
        "outcome": outcome,
        "side": side,
        "price": price,
        "shares": shares,
        "sizeUsd": size,
        "category": "politics",
        "tradeId": f"{wallet[-4:]}-{minutes}",
        "dedupeKey": f"{wallet}-{minutes}",
        "rawSource": "activity",
    }


async def _fake_batch_price_history(token_ids, **_kwargs):
    return {token_id: [] for token_id in token_ids}


def _assert_no_nan_or_infinity(value):
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_nan_or_infinity(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_nan_or_infinity(item)
    elif isinstance(value, float):
        assert value == value
        assert value not in {float("inf"), float("-inf")}


def test_copyability_phase_writes_five_outputs_and_logs(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_copyability_integration_tmp" / "outputs"
    shutil.rmtree(base.parent, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(copyability_storage, "OUTPUT_DIR", base)
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_SHADOW_FILE", base / "trade_copyability_shadow.json")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_HISTORY_FILE", base / "trade_copyability_history.jsonl")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_STATE_FILE", base / "trade_copyability_state.json")
    monkeypatch.setattr(copyability_storage, "WALLET_COPYABILITY_SUMMARY_FILE", base / "wallet_copyability_summary.json")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_BACKTEST_FILE", base / "trade_copyability_backtest.json")

    monkeypatch.setattr(trade_copyability, "write_trade_copyability_shadow", copyability_storage.write_trade_copyability_shadow)
    monkeypatch.setattr(trade_copyability, "append_trade_copyability_history", copyability_storage.append_trade_copyability_history)
    monkeypatch.setattr(trade_copyability, "read_trade_copyability_state", copyability_storage.read_trade_copyability_state)
    monkeypatch.setattr(trade_copyability, "write_trade_copyability_state", copyability_storage.write_trade_copyability_state)
    monkeypatch.setattr(trade_copyability, "write_wallet_copyability_summary", copyability_storage.write_wallet_copyability_summary)
    monkeypatch.setattr(trade_copyability, "write_trade_copyability_backtest", copyability_storage.write_trade_copyability_backtest)

    wallets = [
        "0x" + "1" * 40,
        "0x" + "2" * 40,
        "0x" + "3" * 40,
    ]
    deduped_trades = []
    for index, wallet in enumerate(wallets):
        deduped_trades.extend(
            [
                _trade(wallet, minutes=index * 10, asset=f"asset-{index}", condition=f"cond-{index}", price=0.2 + index * 0.05, size=100 + index * 10, shares=10 + index),
                _trade(wallet, minutes=index * 10 + 5, asset=f"asset-{index}", condition=f"cond-{index}", price=0.25 + index * 0.05, size=150 + index * 10, shares=15 + index),
                _trade(wallet, minutes=index * 10 + 10, asset=f"asset-{index}", condition=f"cond-{index}", price=0.3 + index * 0.05, size=200 + index * 10, shares=20 + index),
            ]
        )

    price_histories = {
        f"asset-{index}": [
            {"timestamp": datetime(2026, 6, 28, 23, 0, tzinfo=timezone.utc), "price": 0.15 + index * 0.01},
            {"timestamp": datetime(2026, 6, 29, 1, 0, tzinfo=timezone.utc), "price": 0.35 + index * 0.01},
            {"timestamp": datetime(2026, 6, 29, 6, 0, tzinfo=timezone.utc), "price": 0.45 + index * 0.01},
            {"timestamp": datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc), "price": 0.55 + index * 0.01},
        ]
        for index in range(3)
    }

    async def fake_batch_price_history(token_ids, **_kwargs):
        return {token_id: price_histories.get(token_id, []) for token_id in token_ids}

    monkeypatch.setattr(trade_copyability, "fetch_batch_price_history", fake_batch_price_history)

    shadow_phase = {
        "cohort": [
            {"wallet": wallets[0], "displayName": "Wallet 1", "roles": ["active"], "profiles": ["politics"], "sources": ["shadow"], "classification": "SIGNAL_WALLET", "shadowSkill": {"categorySkillScores": {"politics": {"closedPositionsCount": 10, "skillStatus": "sufficient", "skillScore": 80}}}, "shadowRobustEvaluation": {"robustSkillScore": 70}},
            {"wallet": wallets[1], "displayName": "Wallet 2", "roles": ["candidate"], "profiles": ["politics"], "sources": ["shadow"], "classification": "SIGNAL_WALLET", "shadowSkill": {"categorySkillScores": {"politics": {"closedPositionsCount": 10, "skillStatus": "sufficient", "skillScore": 78}}}, "shadowRobustEvaluation": {"robustSkillScore": 68}},
            {"wallet": wallets[2], "displayName": "Wallet 3", "roles": ["candidate"], "profiles": ["politics"], "sources": ["shadow"], "classification": "SIGNAL_WALLET", "shadowSkill": {"categorySkillScores": {"politics": {"closedPositionsCount": 10, "skillStatus": "sufficient", "skillScore": 76}}}, "shadowRobustEvaluation": {"robustSkillScore": 66}},
        ]
    }

    result = trade_copyability.run_trade_copyability_shadow
    import asyncio

    output = asyncio.run(
        result(
            run_id="run-copyability",
            wallet_scores=[
                {"wallet": wallets[0], "walletQualityScore": 72, "classification": "SIGNAL_WALLET"},
                {"wallet": wallets[1], "walletQualityScore": 71, "classification": "SIGNAL_WALLET"},
                {"wallet": wallets[2], "walletQualityScore": 70, "classification": "SIGNAL_WALLET"},
            ],
            shadow_phase=shadow_phase,
            deduped_trades=deduped_trades,
        )
    )

    captured = capsys.readouterr().out
    assert "SMART_MONEY_COPYABILITY_STARTED" in captured
    assert "SMART_MONEY_COPYABILITY_PRICE_HISTORY_BATCH" in captured
    assert "SMART_MONEY_COPYABILITY_WRITTEN" in captured
    assert "SMART_MONEY_COPYABILITY_COMPLETED" in captured

    assert (base / "trade_copyability_shadow.json").exists()
    assert (base / "trade_copyability_history.jsonl").exists()
    assert (base / "trade_copyability_state.json").exists()
    assert (base / "wallet_copyability_summary.json").exists()
    assert (base / "trade_copyability_backtest.json").exists()

    shadow = json.loads((base / "trade_copyability_shadow.json").read_text(encoding="utf-8"))
    summary = json.loads((base / "wallet_copyability_summary.json").read_text(encoding="utf-8"))
    backtest = json.loads((base / "trade_copyability_backtest.json").read_text(encoding="utf-8"))
    assert shadow["phase"] == "2_full_shadow"
    assert len(shadow["clusters"]) >= 3
    assert len(shadow["walletResults"]) == 3
    assert all(result["status"] == "completed" for result in shadow["walletResults"])
    _assert_no_nan_or_infinity(shadow)
    assert len(summary) == 3
    assert "groups" in backtest
    assert output["clusters"]
    shutil.rmtree(base.parent, ignore_errors=True)


def test_copyability_phase_reports_wallet_reasons_when_no_clusters(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_copyability_integration_tmp_reasons" / "outputs"
    shutil.rmtree(base.parent, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(copyability_storage, "OUTPUT_DIR", base)
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_SHADOW_FILE", base / "trade_copyability_shadow.json")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_HISTORY_FILE", base / "trade_copyability_history.jsonl")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_STATE_FILE", base / "trade_copyability_state.json")
    monkeypatch.setattr(copyability_storage, "WALLET_COPYABILITY_SUMMARY_FILE", base / "wallet_copyability_summary.json")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_BACKTEST_FILE", base / "trade_copyability_backtest.json")

    monkeypatch.setattr(trade_copyability, "write_trade_copyability_shadow", copyability_storage.write_trade_copyability_shadow)
    monkeypatch.setattr(trade_copyability, "append_trade_copyability_history", copyability_storage.append_trade_copyability_history)
    monkeypatch.setattr(trade_copyability, "read_trade_copyability_state", copyability_storage.read_trade_copyability_state)
    monkeypatch.setattr(trade_copyability, "write_trade_copyability_state", copyability_storage.write_trade_copyability_state)
    monkeypatch.setattr(trade_copyability, "write_wallet_copyability_summary", copyability_storage.write_wallet_copyability_summary)
    monkeypatch.setattr(trade_copyability, "write_trade_copyability_backtest", copyability_storage.write_trade_copyability_backtest)

    wallets = [
        "0x" + "4" * 40,
        "0x" + "5" * 40,
        "0x" + "6" * 40,
    ]

    async def fake_fetch(wallet, *_args, **_kwargs):
        if wallet == wallets[0]:
            return {
                "wallet": wallet,
                "status": "completed",
                "reason": "no_valid_trades",
                "rawTrades": 5,
                "normalizedTrades": 0,
                "trades": [],
                "error": None,
            }
        if wallet == wallets[1]:
            return {
                "wallet": wallet,
                "status": "completed",
                "reason": "no_valid_trades",
                "rawTrades": 4,
                "normalizedTrades": 0,
                "trades": [],
                "error": None,
            }
        return {
            "wallet": wallet,
            "status": "completed",
            "reason": "cache_hit",
            "rawTrades": 3,
            "normalizedTrades": 3,
            "trades": [
                _trade(wallet, minutes=0, asset="asset-6", condition="cond-6"),
                _trade(wallet, minutes=5, asset="asset-6", condition="cond-6"),
                _trade(wallet, minutes=10, asset="asset-6", condition="cond-6"),
            ],
            "error": None,
        }

    original_build_trade_clusters = trade_copyability.build_trade_clusters

    def fake_build_trade_clusters(trades):
        if trades and all(str(trade.get("wallet")) == wallets[2] for trade in trades):
            return []
        return original_build_trade_clusters(trades)

    monkeypatch.setattr(trade_copyability, "fetch_copyability_trades_for_wallet", fake_fetch)
    monkeypatch.setattr(trade_copyability, "build_trade_clusters", fake_build_trade_clusters)
    monkeypatch.setattr(trade_copyability, "fetch_batch_price_history", _fake_batch_price_history)

    shadow_phase = {
        "cohort": [
            {"wallet": wallets[0], "displayName": "Wallet 4", "roles": ["candidate"], "profiles": ["politics"], "sources": ["shadow"], "classification": "SIGNAL_WALLET", "shadowSkill": {"categorySkillScores": {"politics": {"closedPositionsCount": 10, "skillStatus": "sufficient", "skillScore": 80}}}, "shadowRobustEvaluation": {"robustSkillScore": 70}},
            {"wallet": wallets[1], "displayName": "Wallet 5", "roles": ["candidate"], "profiles": ["politics"], "sources": ["shadow"], "classification": "SIGNAL_WALLET", "shadowSkill": {"categorySkillScores": {"politics": {"closedPositionsCount": 10, "skillStatus": "sufficient", "skillScore": 78}}}, "shadowRobustEvaluation": {"robustSkillScore": 68}},
            {"wallet": wallets[2], "displayName": "Wallet 6", "roles": ["candidate"], "profiles": ["politics"], "sources": ["shadow"], "classification": "SIGNAL_WALLET", "shadowSkill": {"categorySkillScores": {"politics": {"closedPositionsCount": 10, "skillStatus": "sufficient", "skillScore": 76}}}, "shadowRobustEvaluation": {"robustSkillScore": 66}},
        ]
    }

    output = asyncio.run(
        trade_copyability.run_trade_copyability_shadow(
            run_id="run-copyability-reasons",
            wallet_scores=[{"wallet": wallet, "walletQualityScore": 70, "classification": "SIGNAL_WALLET"} for wallet in wallets],
            shadow_phase=shadow_phase,
            deduped_trades=[],
        )
    )

    captured = capsys.readouterr().out
    assert "SMART_MONEY_COPYABILITY_WALLET_FETCHED" in captured
    assert "SMART_MONEY_COPYABILITY_WALLET_FAILED" not in captured
    assert "SMART_MONEY_COPYABILITY_WALLET_SKIPPED" not in captured

    shadow = json.loads((base / "trade_copyability_shadow.json").read_text(encoding="utf-8"))
    assert shadow["walletsRequested"] == 3
    assert shadow["walletsCompleted"] == 0
    assert shadow["walletsFailed"] == 0
    assert len(shadow["walletResults"]) == 3
    reasons = {item["wallet"]: item["reason"] for item in shadow["walletResults"]}
    assert reasons[wallets[0]] == "no_valid_trades"
    assert reasons[wallets[1]] == "no_valid_trades"
    assert reasons[wallets[2]] == "no_clusters_after_filters"
    assert all(item["status"] == "completed" for item in shadow["walletResults"])
    assert shadow["clusters"] == []
    shutil.rmtree(base.parent, ignore_errors=True)


def test_copyability_phase_marks_network_failure_explicitly(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_copyability_integration_tmp_failure" / "outputs"
    shutil.rmtree(base.parent, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(copyability_storage, "OUTPUT_DIR", base)
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_SHADOW_FILE", base / "trade_copyability_shadow.json")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_HISTORY_FILE", base / "trade_copyability_history.jsonl")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_STATE_FILE", base / "trade_copyability_state.json")
    monkeypatch.setattr(copyability_storage, "WALLET_COPYABILITY_SUMMARY_FILE", base / "wallet_copyability_summary.json")
    monkeypatch.setattr(copyability_storage, "TRADE_COPYABILITY_BACKTEST_FILE", base / "trade_copyability_backtest.json")

    monkeypatch.setattr(trade_copyability, "write_trade_copyability_shadow", copyability_storage.write_trade_copyability_shadow)
    monkeypatch.setattr(trade_copyability, "append_trade_copyability_history", copyability_storage.append_trade_copyability_history)
    monkeypatch.setattr(trade_copyability, "read_trade_copyability_state", copyability_storage.read_trade_copyability_state)
    monkeypatch.setattr(trade_copyability, "write_trade_copyability_state", copyability_storage.write_trade_copyability_state)
    monkeypatch.setattr(trade_copyability, "write_wallet_copyability_summary", copyability_storage.write_wallet_copyability_summary)
    monkeypatch.setattr(trade_copyability, "write_trade_copyability_backtest", copyability_storage.write_trade_copyability_backtest)

    wallets = [
        "0x" + "7" * 40,
        "0x" + "8" * 40,
        "0x" + "9" * 40,
    ]

    async def fake_fetch(wallet, *_args, **_kwargs):
        if wallet == wallets[0]:
            raise httpx.ConnectError("network down", request=httpx.Request("GET", "https://data-api.polymarket.com/trades"))
        if wallet == wallets[1]:
            return {
                "wallet": wallet,
                "status": "completed",
                "reason": "no_valid_trades",
                "rawTrades": 2,
                "normalizedTrades": 0,
                "trades": [],
                "error": None,
            }
        return {
            "wallet": wallet,
            "status": "completed",
            "reason": "cache_hit",
            "rawTrades": 3,
            "normalizedTrades": 3,
            "trades": [
                _trade(wallet, minutes=0, asset="asset-9", condition="cond-9"),
                _trade(wallet, minutes=5, asset="asset-9", condition="cond-9"),
                _trade(wallet, minutes=10, asset="asset-9", condition="cond-9"),
            ],
            "error": None,
        }

    monkeypatch.setattr(trade_copyability, "fetch_copyability_trades_for_wallet", fake_fetch)
    monkeypatch.setattr(trade_copyability, "build_trade_clusters", lambda trades: [])
    monkeypatch.setattr(trade_copyability, "fetch_batch_price_history", _fake_batch_price_history)

    shadow_phase = {
        "cohort": [
            {"wallet": wallet, "displayName": f"Wallet {index + 7}", "roles": ["candidate"], "profiles": ["politics"], "sources": ["shadow"], "classification": "SIGNAL_WALLET", "shadowSkill": {"categorySkillScores": {"politics": {"closedPositionsCount": 10, "skillStatus": "sufficient", "skillScore": 80}}}, "shadowRobustEvaluation": {"robustSkillScore": 70}}
            for index, wallet in enumerate(wallets)
        ]
    }

    asyncio.run(
        trade_copyability.run_trade_copyability_shadow(
            run_id="run-copyability-failure",
            wallet_scores=[{"wallet": wallet, "walletQualityScore": 70, "classification": "SIGNAL_WALLET"} for wallet in wallets],
            shadow_phase=shadow_phase,
            deduped_trades=[],
        )
    )

    captured = capsys.readouterr().out
    assert "SMART_MONEY_COPYABILITY_WALLET_FAILED" in captured
    assert "reason=network_failure" in captured

    shadow = json.loads((base / "trade_copyability_shadow.json").read_text(encoding="utf-8"))
    reasons = {item["wallet"]: item["reason"] for item in shadow["walletResults"]}
    assert reasons[wallets[0]] == "network_failure"
    assert reasons[wallets[1]] == "no_valid_trades"
    assert reasons[wallets[2]] == "no_clusters_after_filters"
    assert shadow["walletsFailed"] == 1
    shutil.rmtree(base.parent, ignore_errors=True)
