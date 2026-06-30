import json
import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workers.smart_money.smart_money_engine import main as smart_money_main
from workers.smart_money.smart_money_engine import supabase_writer
from workers.smart_money.smart_money_engine.market_trail import build_market_capital_trails
from workers.smart_money.smart_money_engine.related_markets import build_related_market_inferences
from workers.smart_money.smart_money_engine.wallet_classifier import (
    INSUFFICIENT_HISTORY,
    SIGNAL_WALLET,
    SPECIALIST_WALLET,
    WHALE_BUT_NOISY,
)
from workers.smart_money.smart_money_engine.wallet_metrics import compute_wallet_scores


def build_trade(
    wallet: str,
    market_id: str,
    *,
    price: float,
    size_usd: float,
    side: str = "BUY",
    outcome: str = "Yes",
    category_guess: str = "macro",
):
    return {
        "wallet": wallet,
        "market_id": market_id,
        "side": side,
        "outcome": outcome,
        "title": f"{category_guess} market {market_id}",
        "category_guess": category_guess,
        "size_usd": size_usd,
        "price": price,
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=1),
        "raw": {},
    }


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


def _assert_utc_timestamp(value: str):
    parsed = datetime.fromisoformat(value)
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == timedelta(0)


def test_compute_wallet_scores_generates_expected_shape():
    trades = [
        build_trade("0xsignal", "m1", price=0.22, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal", "m2", price=0.28, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal", "m3", price=0.35, size_usd=1800, category_guess="macro"),
        build_trade("0xsignal", "m4", price=0.4, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal", "m5", price=0.18, size_usd=1700, category_guess="macro"),
        build_trade("0xsignal", "m6", price=0.3, size_usd=2300, category_guess="politics"),
        build_trade("0xthin", "m7", price=0.91, size_usd=300, category_guess="crypto"),
        build_trade("0xthin", "m8", price=0.97, size_usd=200, category_guess="crypto"),
    ]

    scores = compute_wallet_scores(trades)

    assert len(scores) == 2
    assert 0 <= scores[0]["walletQualityScore"] <= 100
    assert "classification" in scores[0]
    assert scores[0]["classification"] in {SIGNAL_WALLET, SPECIALIST_WALLET}
    assert scores[0]["metrics"]["tradeCount"] == 6
    assert scores[0]["metrics"]["uniqueMarkets"] == 6
    assert "noiseScore" in scores[0]
    assert "noiseLevel" in scores[0]
    assert isinstance(scores[0]["riskFlags"], list)
    assert scores[1]["classification"] == INSUFFICIENT_HISTORY


def test_main_run_writes_wallet_scores_json(monkeypatch):
    trades = [
        build_trade("0xabc", "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade("0xabc", "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade("0xabc", "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade("0xabc", "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade("0xabc", "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade("0xabc", "m6", price=0.5, size_usd=1300, category_guess="macro"),
    ]
    output_wallet_file = Path("workers/smart_money/smart_money_engine/outputs/test_wallet_scores.json")
    output_noise_file = Path("workers/smart_money/smart_money_engine/outputs/test_noise_scores.json")
    output_trails_file = Path("workers/smart_money/smart_money_engine/outputs/test_market_capital_trails.json")
    output_estela_file = Path("workers/smart_money/smart_money_engine/outputs/test_estela_capital_by_market.json")

    async def fake_fetch_recent_activity():
        return trades

    def fake_save_json(filename: str, data):
        if filename == "wallet_scores.json":
            target = output_wallet_file
        elif filename == "noise_scores.json":
            target = output_noise_file
        elif filename == "estela_capital_by_market.json":
            target = output_estela_file
        else:
            target = output_trails_file
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    monkeypatch.setattr(smart_money_main, "save_json", fake_save_json)

    wallet_scores = smart_money_main.asyncio.run(smart_money_main.run())

    assert len(wallet_scores) == 1
    payload = json.loads(output_wallet_file.read_text(encoding="utf-8"))
    assert payload[0]["wallet"] == "0xabc"
    assert 0 <= payload[0]["walletQualityScore"] <= 100
    assert "subScores" in payload[0]
    assert "noiseScore" in payload[0]
    assert "noiseLevel" in payload[0]
    trail_payload = json.loads(output_trails_file.read_text(encoding="utf-8"))
    assert len(trail_payload) == 6
    assert all("status" in item for item in trail_payload)
    noise_payload = json.loads(output_noise_file.read_text(encoding="utf-8"))
    assert len(noise_payload) == 1
    assert noise_payload[0]["wallet"] == "0xabc"
    assert "noiseScore" in noise_payload[0]
    estela_payload = json.loads(output_estela_file.read_text(encoding="utf-8"))
    assert len(estela_payload) == 6
    assert all(item["status"] == "DIRECT_WEAK" for item in estela_payload)


def test_main_shadow_disabled_preserves_productive_output(monkeypatch):
    trades = [
        build_trade("0xabc", "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade("0xabc", "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade("0xabc", "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade("0xabc", "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade("0xabc", "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade("0xabc", "m6", price=0.5, size_usd=1300, category_guess="macro"),
    ]

    async def fake_fetch_recent_activity():
        return trades

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    monkeypatch.setattr(smart_money_main, "SKILL_SHADOW_ENABLED", False)
    monkeypatch.setattr(
        smart_money_main,
        "_fetch_shadow_positions",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("shadow should be disabled")),
    )
    written = {}

    def fake_save_json(filename: str, data):
        written[filename] = data
        return Path(filename)

    monkeypatch.setattr(smart_money_main, "save_json", fake_save_json)

    result = asyncio.run(smart_money_main.execute_engine())

    assert "wallet_skill_shadow.json" not in written
    assert "shadow_rows" in result
    assert result["wallet_scores"][0]["walletQualityScore"] == written["wallet_scores.json"][0]["walletQualityScore"]


def test_copyability_shadow_disabled_skips_phase(monkeypatch):
    async def fake_execute_engine():
        return {
            "trades": [],
            "deduped_trades": [],
            "wallet_scores": [],
            "market_trails": [],
            "estela_capital": [],
            "shadow_rows": [],
        }

    called = {"copyability": False}

    async def fake_run_trade_copyability_shadow(*_args, **_kwargs):
        called["copyability"] = True
        raise AssertionError("copyability shadow should be disabled")

    monkeypatch.setattr(smart_money_main, "execute_engine", fake_execute_engine)
    monkeypatch.setattr(smart_money_main, "run_trade_copyability_shadow", fake_run_trade_copyability_shadow)
    monkeypatch.setattr(smart_money_main, "COPYABILITY_SHADOW_ENABLED", False)
    monkeypatch.setattr(smart_money_main, "upsert_wallet_scores", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "upsert_capital_trails", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "finish_engine_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "log_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "log_market_trail_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "start_engine_run", lambda: "run-copyability-disabled")

    asyncio.run(smart_money_main.main())

    assert called["copyability"] is False


def test_main_uses_adaptive_roster_for_copyability_when_enabled(monkeypatch, capsys):
    called = {}
    quality_called = {}

    async def fake_execute_engine():
        return {
            "trades": [],
            "deduped_trades": [],
            "wallet_scores": [{"wallet": "0x" + "1" * 40, "walletQualityScore": 81, "classification": SIGNAL_WALLET}],
            "market_trails": [],
            "estela_capital": [],
            "shadow_rows": [{"wallet": "0x" + "1" * 40}],
        }

    async def fake_run_trade_copyability_shadow(*_args, **kwargs):
        called["wallet_roster"] = kwargs.get("wallet_roster")
        print(f"SMART_MONEY_COPYABILITY_STARTED wallets={len((kwargs.get('wallet_roster') or {}).get('selectedWallets') or [])}")
        return {"clusters": [], "walletResults": []}

    def fake_build_adaptive_signal_wallet_quality(*_args, **kwargs):
        quality_called["copyability_phase"] = kwargs.get("copyability_phase")
        quality_called["wallet_roster"] = kwargs.get("wallet_roster")
        return {
            "runId": "run-adaptive-roster",
            "generatedAt": "2026-06-29T00:00:00+00:00",
            "benchmarkWallet": "0x" + "9" * 40,
            "walletCount": 3,
            "walletQualityRows": [
                {"wallet": "0x" + "9" * 40, "displayName": "Ken", "keepInRosterRecommendation": "KEEP_BENCHMARK"},
                {"wallet": "0x" + "1" * 40, "displayName": "Wallet 1", "keepInRosterRecommendation": "WATCHLIST"},
                {"wallet": "0x" + "2" * 40, "displayName": "Wallet 2", "keepInRosterRecommendation": "REPLACE_CANDIDATE"},
            ],
            "walletResults": [],
        }

    def fake_build_adaptive_signal_wallet_roster(*_args, **_kwargs):
        return {
            "generatedAt": "2026-06-29T00:00:00+00:00",
            "benchmarkWallet": "0x" + "9" * 40,
            "targetRosterSize": 6,
            "candidatesFound": 3,
            "selectedWallets": [
                {"wallet": "0x" + "9" * 40, "rank": 1, "isBenchmark": True, "signalWalletRosterScore": 100, "primaryCategory": "mixed", "reason": "benchmark wallet"},
                {"wallet": "0x" + "1" * 40, "rank": 2, "isBenchmark": False, "signalWalletRosterScore": 82, "primaryCategory": "macro", "reason": "strong robust skill score"},
                {"wallet": "0x" + "2" * 40, "rank": 3, "isBenchmark": False, "signalWalletRosterScore": 79, "primaryCategory": "politics", "reason": "recent activity"},
            ],
            "rejectedWallets": [],
        }

    written = {}
    quality_written = {}

    def fake_write_adaptive_signal_wallet_roster(payload):
        written["payload"] = payload
        return Path("outputs/adaptive_signal_wallet_roster.json")

    def fake_write_adaptive_signal_wallet_quality(payload):
        quality_written["payload"] = payload
        return Path("outputs/adaptive_signal_wallet_quality.json")

    monkeypatch.setattr(smart_money_main, "execute_engine", fake_execute_engine)
    monkeypatch.setattr(
        smart_money_main,
        "_run_shadow_cohort_phase",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={"cohort": [], "shadow_rows": []}),
    )
    monkeypatch.setattr(smart_money_main, "run_trade_copyability_shadow", fake_run_trade_copyability_shadow)
    monkeypatch.setattr(smart_money_main, "build_adaptive_signal_wallet_quality", fake_build_adaptive_signal_wallet_quality)
    monkeypatch.setattr(smart_money_main, "build_adaptive_signal_wallet_roster", fake_build_adaptive_signal_wallet_roster)
    monkeypatch.setattr(smart_money_main, "write_adaptive_signal_wallet_roster", fake_write_adaptive_signal_wallet_roster)
    monkeypatch.setattr(smart_money_main, "write_adaptive_signal_wallet_quality", fake_write_adaptive_signal_wallet_quality)
    monkeypatch.setattr(smart_money_main, "start_engine_run", lambda: "run-adaptive-roster")
    monkeypatch.setattr(smart_money_main, "COPYABILITY_SHADOW_ENABLED", True)
    monkeypatch.setattr(smart_money_main, "SIGNAL_WALLET_ROSTER_ENABLED", True)
    monkeypatch.setattr(smart_money_main, "COPYABILITY_MAX_WALLETS_PER_RUN", 6)
    monkeypatch.setattr(smart_money_main, "SIGNAL_WALLET_ROSTER_SIZE", 6)
    monkeypatch.setattr(smart_money_main, "upsert_wallet_scores", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "upsert_capital_trails", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "finish_engine_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "log_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "log_market_trail_summary", lambda *_args, **_kwargs: None)

    asyncio.run(smart_money_main.main())

    output = capsys.readouterr().out
    assert "SMART_MONEY_COPYABILITY_STARTED wallets=3" in output
    assert written["payload"]["selectedWallets"][0]["wallet"] == "0x" + "9" * 40
    assert quality_written["payload"]["benchmarkWallet"] == "0x" + "9" * 40
    assert quality_called["copyability_phase"]["clusters"] == []
    assert len(called["wallet_roster"]["selectedWallets"]) == 3


def test_main_copyability_failure_writes_diagnostic_shadow(monkeypatch, capsys):
    written = {}

    async def fake_execute_engine():
        return {
            "trades": [],
            "deduped_trades": [],
            "wallet_scores": [{"wallet": "0x" + "1" * 40, "classification": SIGNAL_WALLET}],
            "market_trails": [],
            "estela_capital": [],
            "shadow_rows": [{"wallet": "0x" + "1" * 40}],
        }

    async def fake_run_trade_copyability_shadow(*_args, **_kwargs):
        raise ValueError("boom")

    def fake_write_trade_copyability_shadow(payload):
        written["payload"] = payload
        return Path("outputs/trade_copyability_shadow.json")

    monkeypatch.setattr(smart_money_main, "execute_engine", fake_execute_engine)
    monkeypatch.setattr(
        smart_money_main,
        "_run_shadow_cohort_phase",
        lambda *_args, **_kwargs: asyncio.sleep(0, result={"cohort": [], "shadow_rows": []}),
    )
    monkeypatch.setattr(smart_money_main, "run_trade_copyability_shadow", fake_run_trade_copyability_shadow)
    monkeypatch.setattr(smart_money_main, "write_trade_copyability_shadow", fake_write_trade_copyability_shadow)
    monkeypatch.setattr(smart_money_main, "start_engine_run", lambda: "run-copyability-failed")
    monkeypatch.setattr(smart_money_main, "COPYABILITY_SHADOW_ENABLED", True)
    monkeypatch.setattr(smart_money_main, "upsert_wallet_scores", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "upsert_capital_trails", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "finish_engine_run", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "log_summary", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(smart_money_main, "log_market_trail_summary", lambda *_args, **_kwargs: None)

    asyncio.run(smart_money_main.main())

    output = capsys.readouterr().out
    assert "SMART_MONEY_COPYABILITY_FAILED" in output
    assert "run_id=run-copyability-failed" in output
    assert written["payload"]["runId"] == "run-copyability-failed"
    assert written["payload"]["status"] == "failed"
    assert written["payload"]["walletsRequested"] == 1
    assert written["payload"]["walletResults"] == []
    assert written["payload"]["clusters"] == []


def test_shadow_fetch_failure_does_not_cancel_other_wallets(monkeypatch):
    async def fake_fetch(wallet, max_positions=500):
        if wallet.endswith("1"):
            raise RuntimeError("boom")
        return [{"avgPrice": 0.2, "totalBought": 10, "realizedPnl": 2}]

    monkeypatch.setattr(smart_money_main, "fetch_closed_positions", fake_fetch)

    selected = [
        {"wallet": "0x" + "1" * 40, "walletQualityScore": 90, "metrics": {"totalVolume": 1000}},
        {"wallet": "0x" + "2" * 40, "walletQualityScore": 80, "metrics": {"totalVolume": 900}},
    ]

    shadow_positions = asyncio.run(smart_money_main._fetch_shadow_positions(selected))

    assert shadow_positions["0x" + "1" * 40]["error"]
    assert shadow_positions["0x" + "2" * 40]["closed_positions"]


def test_priority_wallet_present_reuses_global_behavior(monkeypatch):
    trades = [
        build_trade("0x" + "a" * 40, "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade("0x" + "a" * 40, "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade("0x" + "a" * 40, "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade("0x" + "a" * 40, "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade("0x" + "a" * 40, "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade("0x" + "a" * 40, "m6", price=0.5, size_usd=1300, category_guess="macro"),
        build_trade("0x" + "b" * 40, "m7", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade("0x" + "b" * 40, "m8", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade("0x" + "b" * 40, "m9", price=0.3, size_usd=900, category_guess="macro"),
        build_trade("0x" + "b" * 40, "m10", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade("0x" + "b" * 40, "m11", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade("0x" + "b" * 40, "m12", price=0.5, size_usd=1300, category_guess="macro"),
    ]

    async def fake_fetch_recent_activity():
        return trades

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    monkeypatch.setattr(smart_money_main, "SKILL_PRIORITY_WALLETS", "0x" + "a" * 40)
    monkeypatch.setattr(smart_money_main, "SKILL_MAX_WALLETS_PER_RUN", 1)

    selected = smart_money_main.build_shadow_wallet_targets(compute_wallet_scores(trades))
    assert len(selected) == 1
    assert selected[0]["wallet"] == "0x" + "a" * 40
    assert selected[0]["source"] == "global_wallet_scores"


def test_priority_wallet_missing_uses_targeted_activity_and_shadow_only(monkeypatch):
    global_wallet = "0x" + "b" * 40
    priority_wallet = "0x" + "c" * 40
    trades = [
        build_trade(global_wallet, "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade(global_wallet, "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade(global_wallet, "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade(global_wallet, "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade(global_wallet, "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade(global_wallet, "m6", price=0.5, size_usd=1300, category_guess="macro"),
    ]

    async def fake_fetch_recent_activity():
        return trades

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    async def fake_targeted_activity(wallet):
        assert wallet == priority_wallet
        return (
            [{"id": "evt-1"}],
            [
                {
                    "wallet": wallet,
                    "market_id": "m1",
                    "side": "BUY",
                    "outcome": "Yes",
                    "title": "election result",
                    "category_guess": "politics",
                    "size_usd": 1000,
                    "price": 0.2,
                    "timestamp": datetime.now(timezone.utc),
                    "raw": {},
                }
            ],
        )

    async def fake_closed_positions(wallet, max_positions=500):
        assert wallet == priority_wallet
        return [{"avgPrice": 0.2, "totalBought": 10, "realizedPnl": 2, "title": "election result"}]

    monkeypatch.setattr(smart_money_main, "_fetch_targeted_activity_for_wallet", fake_targeted_activity)
    monkeypatch.setattr(smart_money_main, "fetch_closed_positions", fake_closed_positions)
    monkeypatch.setattr(smart_money_main, "SKILL_PRIORITY_WALLETS", priority_wallet)
    monkeypatch.setattr(smart_money_main, "SKILL_MAX_WALLETS_PER_RUN", 1)

    selected = smart_money_main.build_shadow_wallet_targets(compute_wallet_scores(trades))
    assert selected[0]["wallet"] == priority_wallet
    assert selected[0]["source"] == "targeted_wallet_activity"

    targeted_behaviors = asyncio.run(smart_money_main._fetch_targeted_wallet_behaviors([selected[0]]))
    assert targeted_behaviors[priority_wallet]["walletScore"] is not None
    assert targeted_behaviors[priority_wallet]["behaviorStatus"] == "sufficient"


def test_priority_wallet_missing_without_activity_keeps_shadow_only(monkeypatch):
    global_wallet = "0x" + "b" * 40
    priority_wallet = "0x" + "d" * 40
    trades = [
        build_trade(global_wallet, "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade(global_wallet, "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade(global_wallet, "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade(global_wallet, "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade(global_wallet, "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade(global_wallet, "m6", price=0.5, size_usd=1300, category_guess="macro"),
    ]

    async def fake_fetch_recent_activity():
        return trades

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    async def fake_targeted_activity(wallet):
        assert wallet == priority_wallet
        return [], []

    async def fake_closed_positions(wallet, max_positions=500):
        assert wallet == priority_wallet
        return []

    monkeypatch.setattr(smart_money_main, "_fetch_targeted_activity_for_wallet", fake_targeted_activity)
    monkeypatch.setattr(smart_money_main, "fetch_closed_positions", fake_closed_positions)
    monkeypatch.setattr(smart_money_main, "SKILL_PRIORITY_WALLETS", priority_wallet)
    monkeypatch.setattr(smart_money_main, "SKILL_MAX_WALLETS_PER_RUN", 1)

    selected = smart_money_main.build_shadow_wallet_targets(compute_wallet_scores(trades))
    assert selected[0]["wallet"] == priority_wallet
    assert selected[0]["source"] == "targeted_wallet_activity"

    targeted_behaviors = asyncio.run(smart_money_main._fetch_targeted_wallet_behaviors([selected[0]]))
    assert targeted_behaviors[priority_wallet]["behaviorStatus"] == "insufficient_recent_activity"
    assert targeted_behaviors[priority_wallet]["walletScore"] is None


def test_priority_wallet_missing_does_not_enter_productive_wallet_scores(monkeypatch):
    priority_wallet = "0x" + "e" * 40
    global_wallet = "0x" + "f" * 40
    trades = [
        build_trade(global_wallet, "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade(global_wallet, "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade(global_wallet, "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade(global_wallet, "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade(global_wallet, "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade(global_wallet, "m6", price=0.5, size_usd=1300, category_guess="macro"),
    ]

    async def fake_fetch_recent_activity():
        return trades

    written = {}

    def fake_save_json(filename: str, data):
        written[filename] = data
        return Path(filename)

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    async def fake_targeted_activity(wallet):
        return [], []

    async def fake_closed_positions(wallet, max_positions=500):
        return []

    monkeypatch.setattr(smart_money_main, "_fetch_targeted_activity_for_wallet", fake_targeted_activity)
    monkeypatch.setattr(smart_money_main, "fetch_closed_positions", fake_closed_positions)
    monkeypatch.setattr(smart_money_main, "SKILL_PRIORITY_WALLETS", priority_wallet)
    monkeypatch.setattr(smart_money_main, "SKILL_MAX_WALLETS_PER_RUN", 1)
    monkeypatch.setattr(smart_money_main, "SKILL_SHADOW_ENABLED", True)
    monkeypatch.setattr(smart_money_main, "save_json", fake_save_json)
    monkeypatch.setattr(smart_money_main, "build_market_capital_trails", lambda trades, wallet_scores: [])
    monkeypatch.setattr(smart_money_main, "build_estela_capital_by_market", lambda trades, market_trails, wallet_scores: [])

    result = asyncio.run(smart_money_main.execute_engine())

    assert all(entry["wallet"] != priority_wallet for entry in written["wallet_scores.json"])
    assert any(entry["wallet"] == priority_wallet for entry in written["wallet_skill_shadow.json"])
    assert result["wallet_scores"] == written["wallet_scores.json"]


def test_shadow_logs_include_scored_before_robust(monkeypatch, capsys):
    wallet = "0x" + "a" * 40
    trades = [
        build_trade(wallet, "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade(wallet, "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade(wallet, "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade(wallet, "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade(wallet, "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade(wallet, "m6", price=0.5, size_usd=1300, category_guess="macro"),
    ]

    async def fake_fetch_recent_activity():
        return trades

    async def fake_closed_positions(_wallet, max_positions=500):
        return [{"avgPrice": 0.2, "totalBought": 10, "realizedPnl": 2, "title": "Will Trump win election?"}]

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    async def fake_targeted_activity(_wallet):
        return [], []

    monkeypatch.setattr(smart_money_main, "_fetch_targeted_activity_for_wallet", fake_targeted_activity)
    monkeypatch.setattr(smart_money_main, "fetch_closed_positions", fake_closed_positions)
    monkeypatch.setattr(smart_money_main, "SKILL_PRIORITY_WALLETS", wallet)
    monkeypatch.setattr(smart_money_main, "SKILL_MAX_WALLETS_PER_RUN", 1)

    selected = smart_money_main.build_shadow_wallet_targets(compute_wallet_scores(trades))
    targeted_behaviors = asyncio.run(smart_money_main._fetch_targeted_wallet_behaviors([selected[0]]))
    selected[0]["behaviorStatus"] = targeted_behaviors[wallet]["behaviorStatus"]
    selected[0]["walletScore"] = targeted_behaviors[wallet]["walletScore"]

    shadow_positions = asyncio.run(smart_money_main._fetch_shadow_positions(selected))
    smart_money_main._attach_shadow_outputs(compute_wallet_scores(trades), selected, shadow_positions)

    output = capsys.readouterr().out.splitlines()
    scored_index = next(i for i, line in enumerate(output) if "SMART_MONEY_SKILL_SCORED" in line)
    robust_index = next(i for i, line in enumerate(output) if "SMART_MONEY_SKILL_ROBUST_SCORED" in line)

    assert scored_index < robust_index


def test_shadow_cohort_phase_writes_valid_utc_artifacts_without_nameerror(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_shadow_phase_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    active_wallet = "0x" + "1" * 40
    candidate_wallet = "0x" + "2" * 40
    third_wallet = "0x" + "3" * 40
    wallet_scores = [
        {
            "wallet": active_wallet,
            "walletQualityScore": 72,
            "classification": SIGNAL_WALLET,
            "generatedAt": "2026-06-29T00:00:00+00:00",
        }
    ]
    cohort = [
        {
            "wallet": active_wallet,
            "displayName": "Active Wallet",
            "roles": ["active"],
            "profiles": ["sports"],
            "sources": ["active_wallet_config"],
            "aliases": [],
            "classification": SIGNAL_WALLET,
            "behaviorQualityScore": 72,
            "candidateScore": None,
            "candidateStatus": None,
            "replacementFor": None,
        },
        {
            "wallet": candidate_wallet,
            "displayName": "Candidate Wallet",
            "roles": ["candidate"],
            "profiles": ["sports"],
            "sources": ["whale_finder"],
            "aliases": [],
            "classification": SIGNAL_WALLET,
            "behaviorQualityScore": 63,
            "candidateScore": 91,
            "candidateStatus": "candidate",
            "replacementFor": None,
        },
        {
            "wallet": third_wallet,
            "displayName": "Third Wallet",
            "roles": ["candidate"],
            "profiles": ["sports"],
            "sources": ["whale_finder"],
            "aliases": [],
            "classification": SIGNAL_WALLET,
            "behaviorQualityScore": 61,
            "candidateScore": 88,
            "candidateStatus": "candidate",
            "replacementFor": None,
        },
    ]

    async def fake_targeted_behaviors(_wallets):
        return {}

    async def fake_shadow_positions(selected_wallets):
        return {
            active_wallet: {
                "wallet": active_wallet,
                "closed_positions": [{"avgPrice": 0.2, "totalBought": 10, "realizedPnl": 2}],
            },
            candidate_wallet: {
                "wallet": candidate_wallet,
                "closed_positions": [{"avgPrice": 0.25, "totalBought": 8, "realizedPnl": 1.5}],
            },
            third_wallet: {
                "wallet": third_wallet,
                "closed_positions": [{"avgPrice": 0.3, "totalBought": 6, "realizedPnl": 1.0}],
            },
        }

    def fake_shadow_skill(wallet, closed_positions):
        return {
            "wallet": wallet,
            "skillStatus": "sufficient",
            "skillScore": 79.5,
            "sampleConfidence": 84,
            "knownCategoryCoverageScore": 61,
            "dominantKnownCategory": "sports",
            "closedPositionsCount": len(closed_positions),
            "categorySkillScores": {
                "sports": {
                    "closedPositionsCount": len(closed_positions),
                    "skillScore": 78.5,
                    "skillStatus": "sufficient",
                }
            },
        }

    def fake_shadow_meta(behavior_score, shadow_skill):
        return {"shadowMetaScore": behavior_score + 1}

    def fake_shadow_robust(behavior_score, shadow_skill):
        return {
            "shadowRobustMetaScore": behavior_score + 2,
            "robustSkillScore": behavior_score + 3,
            "pnlConcentrationLevel": "moderate",
        }

    def fake_load_whale_finder_outputs():
        return {}

    def fake_build_cohort(*_args, **_kwargs):
        return [row.copy() for row in cohort]

    def fake_resolve_history_paths():
        history_file = base / "wallet_shadow_history.jsonl"
        runs_dir = base / "runs"
        output_dir = base / "outputs"
        return {
            "history_file": history_file,
            "runs_dir": runs_dir,
            "output_dir": output_dir,
        }

    def fake_save_json(filename, data):
        target = base / "outputs" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    monkeypatch.setattr(smart_money_main, "load_whale_finder_outputs", fake_load_whale_finder_outputs)
    monkeypatch.setattr(smart_money_main, "build_shadow_wallet_cohort", fake_build_cohort)
    monkeypatch.setattr(smart_money_main, "_fetch_targeted_wallet_behaviors", fake_targeted_behaviors)
    monkeypatch.setattr(smart_money_main, "_fetch_shadow_positions", fake_shadow_positions)
    monkeypatch.setattr(smart_money_main, "compute_wallet_skill", fake_shadow_skill)
    monkeypatch.setattr(smart_money_main, "compute_shadow_meta_evaluation", fake_shadow_meta)
    monkeypatch.setattr(smart_money_main, "compute_shadow_robust_evaluation", fake_shadow_robust)
    monkeypatch.setattr(smart_money_main, "resolve_history_paths", fake_resolve_history_paths)
    monkeypatch.setattr(smart_money_main, "save_json", fake_save_json)

    result = asyncio.run(
        smart_money_main._run_shadow_cohort_phase(
            run_id="run-1",
            wallet_scores=wallet_scores,
            phase_one_shadow_rows=[],
        )
    )

    output = capsys.readouterr().out
    assert "SMART_MONEY_SHADOW_COHORT_FAILED" not in output
    assert "SMART_MONEY_SHADOW_HISTORY_WRITTEN" in output
    assert "SMART_MONEY_SHADOW_RANKINGS_WRITTEN" in output
    assert "SMART_MONEY_SHADOW_COMPARISONS_WRITTEN" in output

    try:
        snapshot = json.loads((base / "runs" / "run-1.json").read_text(encoding="utf-8"))
        assert snapshot["generatedAt"].endswith("+00:00")
        _assert_utc_timestamp(snapshot["generatedAt"])
        _assert_no_nan_or_infinity(snapshot)

        history_lines = (base / "wallet_shadow_history.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(history_lines) == 3
        history = [json.loads(line) for line in history_lines]
        assert len({(row["runId"], row["wallet"]) for row in history}) == 3
        for row in history:
            assert row["generatedAt"].endswith("+00:00")
            _assert_utc_timestamp(row["generatedAt"])

        rankings = json.loads((base / "outputs" / "wallet_shadow_rankings.json").read_text(encoding="utf-8"))
        comparisons = json.loads((base / "outputs" / "wallet_comparison_summary.json").read_text(encoding="utf-8"))
        _assert_no_nan_or_infinity(rankings)
        _assert_no_nan_or_infinity(comparisons)

        assert result["shadow_rows"]
        assert len(result["shadow_rows"]) == 3
        assert all(row["generatedAt"].endswith("+00:00") for row in result["shadow_rows"])
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_high_noise_high_volume_wallet_is_demoted_to_whale_but_noisy():
    trades = [
        build_trade("0xnoisy", "m1", price=0.96, size_usd=4000, category_guess="crypto"),
        build_trade("0xnoisy", "m2", price=0.94, size_usd=3800, category_guess="crypto"),
        build_trade("0xnoisy", "m3", price=0.92, size_usd=4200, category_guess="crypto"),
        build_trade("0xnoisy", "m4", price=0.89, size_usd=4100, category_guess="crypto"),
        build_trade("0xnoisy", "m1", price=0.97, size_usd=3600, category_guess="politics"),
        build_trade("0xnoisy", "m2", price=0.95, size_usd=3900, category_guess="macro"),
        build_trade("0xnoisy", "m3", price=0.99, size_usd=4050, category_guess="politics"),
        build_trade("0xnoisy", "m4", price=0.93, size_usd=3950, category_guess="macro"),
        build_trade("0xnoisy", "m1", price=0.98, size_usd=4150, category_guess="crypto"),
        build_trade("0xnoisy", "m2", price=0.91, size_usd=3850, category_guess="politics"),
        build_trade("0xnoisy", "m3", price=0.96, size_usd=3750, category_guess="macro"),
        build_trade("0xnoisy", "m4", price=0.94, size_usd=4300, category_guess="crypto"),
        build_trade("0xsignal", "m10", price=0.24, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal", "m11", price=0.26, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal", "m12", price=0.28, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal", "m13", price=0.31, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal", "m14", price=0.22, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal", "m15", price=0.27, size_usd=2300, category_guess="macro"),
    ]

    scores = compute_wallet_scores(trades)
    by_wallet = {item["wallet"]: item for item in scores}

    assert by_wallet["0xnoisy"]["noiseLevel"] == "HIGH_NOISE"
    assert by_wallet["0xnoisy"]["noiseScore"] >= 70
    assert by_wallet["0xnoisy"]["classification"] == WHALE_BUT_NOISY
    assert by_wallet["0xsignal"]["classification"] in {SIGNAL_WALLET, SPECIALIST_WALLET}


def test_related_market_inference_fills_no_reliable_trail():
    trades = [
        build_trade("0xsignal1", "m1", price=0.22, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal1", "m2", price=0.24, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal1", "m3", price=0.27, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal1", "m4", price=0.29, size_usd=2300, category_guess="macro"),
        build_trade("0xsignal1", "m5", price=0.25, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal1", "m6", price=0.23, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal2", "m1", price=0.31, size_usd=2800, category_guess="macro"),
        build_trade("0xsignal2", "m2", price=0.28, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal2", "m3", price=0.33, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal2", "m4", price=0.30, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal2", "m5", price=0.26, size_usd=2000, category_guess="macro"),
        build_trade("0xsignal2", "m6", price=0.32, size_usd=2300, category_guess="macro"),
        build_trade("0xnoise", "m11", price=0.97, size_usd=350, category_guess="macro"),
    ]

    wallet_scores = compute_wallet_scores(trades)
    market_trails = build_market_capital_trails(trades, wallet_scores)
    estela = build_related_market_inferences(trades, market_trails)
    by_market = {item["marketId"]: item for item in estela}

    assert by_market["m1"]["status"] == "DIRECT_STRONG"
    assert by_market["m6"]["status"] in {"DIRECT_WEAK", "DIRECT_STRONG"}
    assert by_market["m11"]["status"] == "INFERRED_RELATED"
    assert by_market["m11"]["confidence"] <= 60
    assert by_market["m11"]["relatedMarketsUsed"] >= 2
    assert "relatedMarkets" in by_market["m11"]
    assert all(isinstance(item["confidence"], int) for item in estela)
    assert all(0 <= item["confidence"] <= 100 for item in estela)
    assert all("headline" in item for item in estela)
    assert all("interpretation" in item for item in estela)
    assert all(isinstance(item["riskFlags"], list) for item in estela)
    assert all(isinstance(item["events"], list) for item in estela)


def test_estela_no_reliable_trail_uses_fallback_shape():
    trades = [
        build_trade("0xsignal", "sports-1", price=0.24, size_usd=2800, category_guess="sports"),
        build_trade("0xsignal", "sports-2", price=0.29, size_usd=2600, category_guess="sports"),
        build_trade("0xsignal", "sports-3", price=0.27, size_usd=2400, category_guess="sports"),
        build_trade("0xsignal", "sports-1", price=0.26, size_usd=2200, category_guess="sports"),
        build_trade("0xsignal", "sports-2", price=0.31, size_usd=2100, category_guess="sports"),
        build_trade("0xsignal", "sports-3", price=0.28, size_usd=2300, category_guess="sports"),
        build_trade("0xnoise", "finance-1", price=0.96, size_usd=300, category_guess="macro"),
    ]

    wallet_scores = compute_wallet_scores(trades)
    market_trails = build_market_capital_trails(trades, wallet_scores)
    estela = build_related_market_inferences(trades, market_trails, wallet_scores)
    by_market = {item["marketId"]: item for item in estela}

    assert by_market["sports-1"]["status"] in {"DIRECT_STRONG", "DIRECT_WEAK"}
    assert by_market["finance-1"]["status"] == "NO_RELIABLE_TRAIL"
    assert by_market["finance-1"]["headline"] == "No hay trail confiable de Smart Money"
    assert by_market["finance-1"]["interpretation"] == (
        "No existe suficiente capital calificado o la señal actual es demasiado débil para una lectura confiable."
    )
    assert by_market["finance-1"]["confidence"] >= 20
    assert by_market["finance-1"]["confidence"] <= 35
    assert by_market["finance-1"]["events"] == []
    assert isinstance(by_market["finance-1"]["riskFlags"], list)
    assert "low_wallet_count" in by_market["finance-1"]["riskFlags"]


def test_build_market_capital_trails_generates_strong_and_no_reliable_statuses():
    trades = [
        build_trade("0xsignal1", "m1", price=0.22, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal1", "m1", price=0.28, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal1", "m2", price=0.26, size_usd=1800, category_guess="macro"),
        build_trade("0xsignal1", "m3", price=0.31, size_usd=1700, category_guess="macro"),
        build_trade("0xsignal1", "m4", price=0.24, size_usd=2000, category_guess="macro"),
        build_trade("0xsignal1", "m5", price=0.21, size_usd=1900, category_guess="macro"),
        build_trade("0xsignal2", "m1", price=0.33, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal2", "m1", price=0.3, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal2", "m6", price=0.34, size_usd=2300, category_guess="macro"),
        build_trade("0xsignal2", "m7", price=0.29, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal2", "m8", price=0.27, size_usd=1800, category_guess="macro"),
        build_trade("0xsignal2", "m9", price=0.25, size_usd=2000, category_guess="macro"),
        build_trade("0xnoise", "m10", price=0.97, size_usd=500, category_guess="crypto"),
        build_trade("0xnoise", "m10", price=0.96, size_usd=400, category_guess="crypto"),
    ]

    wallet_scores = compute_wallet_scores(trades)
    trails = build_market_capital_trails(trades, wallet_scores)
    by_market = {item["marketId"]: item for item in trails}

    assert by_market["m1"]["qualifiedWalletCount"] >= 2
    assert by_market["m1"]["smartMoneyVolume"] > 0
    assert by_market["m1"]["smartBias"] > 0.35
    assert by_market["m1"]["status"] == "DIRECT_STRONG"
    assert by_market["m10"]["qualifiedWalletCount"] == 0
    assert by_market["m10"]["status"] == "NO_RELIABLE_TRAIL"


def test_upsert_capital_trails_preserves_existing_mapping_and_resolves_market_matches(monkeypatch):
    class FakeResult:
        def __init__(self, data):
            self.data = data

    class FakeQuery:
        def __init__(self, client, table_name):
            self.client = client
            self.table_name = table_name
            self.operation = "select"
            self.filters = {}
            self.payload = None

        def select(self, *_args, **_kwargs):
            self.operation = "select"
            return self

        def eq(self, field, value):
            self.filters[field] = value
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def upsert(self, payload, **_kwargs):
            self.operation = "upsert"
            self.payload = payload
            self.client.last_upsert_payload = payload
            return self

        def execute(self):
            if self.table_name == "markets":
                return FakeResult(self.client.markets_rows)

            if self.table_name == "smart_money_capital_trails" and self.operation == "select":
                source_market_id = self.filters.get("sourceMarketId")
                rows = [
                    row
                    for row in self.client.existing_trails
                    if row.get("sourceMarketId") == source_market_id
                ]
                return FakeResult(rows[:1])

            return FakeResult([])

    class FakeClient:
        def __init__(self):
            self.markets_rows = [
                {
                    "id": "market-1",
                    "title": "Crypto Market 1",
                    "external_market_id": "source-1",
                },
                {
                    "id": "market-2",
                    "title": "Title Match Market",
                    "externalMarketId": "source-2",
                },
            ]
            self.existing_trails = [
                {
                    "sourceMarketId": "source-3",
                    "marketId": "market-existing",
                    "externalMarketId": "source-3-existing",
                },
                {
                    "sourceMarketId": "source-4",
                    "marketId": None,
                    "externalMarketId": "source-4-old",
                },
            ]
            self.last_upsert_payload = None

        def table(self, table_name):
            return FakeQuery(self, table_name)

    fake_client = FakeClient()

    monkeypatch.setattr(supabase_writer, "_get_client", lambda: fake_client)
    supabase_writer._MARKETS_CACHE = None
    supabase_writer._CAPITAL_TRAIL_CACHE.clear()
    supabase_writer._MARKET_RESOLUTION_CACHE.clear()

    trails = [
        {
            "marketId": "source-1",
            "title": "Some unrelated title",
            "status": "DIRECT_WEAK",
            "headline": "Matched by id",
            "interpretation": "id",
            "confidence": 10,
            "smartBias": 0.1,
            "qualifiedWalletCount": 1,
            "smartMoneyVolume": 100,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
        {
            "marketId": "source-2",
            "title": "title match market",
            "status": "DIRECT_WEAK",
            "headline": "Matched by title",
            "interpretation": "title",
            "confidence": 20,
            "smartBias": 0.2,
            "qualifiedWalletCount": 2,
            "smartMoneyVolume": 200,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
        {
            "marketId": "source-3",
            "title": "No match but preserve",
            "status": "DIRECT_WEAK",
            "headline": "Preserve",
            "interpretation": "preserve",
            "confidence": 30,
            "smartBias": 0.3,
            "qualifiedWalletCount": 3,
            "smartMoneyVolume": 300,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
        {
            "marketId": "source-4",
            "title": "Still unmapped",
            "status": "DIRECT_WEAK",
            "headline": "Unmapped",
            "interpretation": "unmapped",
            "confidence": 40,
            "smartBias": 0.4,
            "qualifiedWalletCount": 4,
            "smartMoneyVolume": 400,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
    ]

    supabase_writer.upsert_capital_trails("run-1", trails)

    payload = fake_client.last_upsert_payload
    by_source = {row["sourceMarketId"]: row for row in payload}

    assert by_source["source-1"]["marketId"] == "market-1"
    assert by_source["source-1"]["externalMarketId"] == "source-1"
    assert by_source["source-2"]["marketId"] == "market-2"
    assert by_source["source-2"]["externalMarketId"] == "source-2"
    assert by_source["source-3"]["marketId"] == "market-existing"
    assert by_source["source-3"]["externalMarketId"] == "source-3-existing"
    assert by_source["source-4"]["marketId"] is None
    assert by_source["source-4"]["externalMarketId"] == "source-4"
