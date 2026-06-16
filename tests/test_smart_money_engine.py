import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workers.smart_money.smart_money_engine import main as smart_money_main
from workers.smart_money.smart_money_engine.market_trail import build_market_capital_trails
from workers.smart_money.smart_money_engine.wallet_classifier import (
    INSUFFICIENT_HISTORY,
    SIGNAL_WALLET,
    SPECIALIST_WALLET,
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
    output_trails_file = Path("workers/smart_money/smart_money_engine/outputs/test_market_capital_trails.json")

    async def fake_fetch_recent_activity():
        return trades

    def fake_save_json(filename: str, data):
        target = output_wallet_file if filename == "wallet_scores.json" else output_trails_file
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
    trail_payload = json.loads(output_trails_file.read_text(encoding="utf-8"))
    assert len(trail_payload) == 6
    assert all("status" in item for item in trail_payload)


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
