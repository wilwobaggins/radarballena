from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workers.smart_money.smart_money_engine import adaptive_wallet_discovery_v2 as discovery


BENCHMARK = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"
WALLETS = {
    "strong": "0x" + "1" * 40,
    "replace": "0x" + "2" * 40,
    "crypto": "0x" + "3" * 40,
    "micro": "0x" + "4" * 40,
    "extra": "0x" + "5" * 40,
}


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n", encoding="utf-8")


def _trade(wallet: str, *, market: str, category: str, size_usd: float, index: int) -> dict[str, object]:
    ts = int((datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=index * 5)).timestamp())
    return {
        "tradeId": f"{wallet}-{market}-{index}",
        "wallet": wallet,
        "timestamp": ts,
        "conditionId": market,
        "asset": f"{market}-asset",
        "marketTitle": market,
        "eventSlug": market,
        "outcome": "yes",
        "side": "BUY",
        "price": 0.55,
        "shares": 1,
        "sizeUsd": size_usd,
        "category": category,
        "rawSource": "activity",
    }


def _seed_sources(base: Path) -> None:
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc).isoformat()
    _write_json(
        base / "wallet_shadow_rankings.json",
        [
            {
                "wallet": BENCHMARK,
                "displayName": "Ken",
                "robustSkillScore": 80,
                "categorySkillScore": 70,
                "dominantKnownCategory": "geopolitics",
                "recommendation": "shadow_watch",
                "rank": 1,
            },
            {
                "wallet": WALLETS["strong"],
                "displayName": "Strong",
                "robustSkillScore": 88,
                "categorySkillScore": 84,
                "dominantKnownCategory": "politics",
                "recommendation": "shadow_strong",
                "rank": 2,
            },
            {
                "wallet": WALLETS["replace"],
                "displayName": "Replace",
                "robustSkillScore": 72,
                "categorySkillScore": 64,
                "dominantKnownCategory": "macro",
                "recommendation": "shadow_watch",
                "rank": 3,
            },
            {
                "wallet": WALLETS["crypto"],
                "displayName": "Crypto",
                "robustSkillScore": 66,
                "categorySkillScore": 62,
                "dominantKnownCategory": "crypto",
                "recommendation": "shadow_watch",
                "rank": 4,
            },
            {
                "wallet": WALLETS["micro"],
                "displayName": "Micro",
                "robustSkillScore": 65,
                "categorySkillScore": 61,
                "dominantKnownCategory": "sports",
                "recommendation": "shadow_watch",
                "rank": 5,
            },
        ],
    )
    _write_json(
        base / "wallet_category_rankings.json",
        {
            "politics": [{"wallet": WALLETS["strong"], "categorySkillScore": 80, "categorySkillStatus": "sufficient"}],
            "macro": [{"wallet": WALLETS["replace"], "categorySkillScore": 63, "categorySkillStatus": "sufficient"}],
            "crypto": [{"wallet": WALLETS["crypto"], "categorySkillScore": 65, "categorySkillStatus": "sufficient"}],
            "sports": [{"wallet": WALLETS["micro"], "categorySkillScore": 58, "categorySkillStatus": "sufficient"}],
        },
    )
    _write_json(
        base / "wallet_copyability_summary.json",
        {
            WALLETS["strong"]: {"clustersCount": 8, "actionableClusterCount": 4, "hedgeRate": 0.1},
            WALLETS["replace"]: {"clustersCount": 8, "actionableClusterCount": 1, "hedgeRate": 0.6},
            WALLETS["crypto"]: {"clustersCount": 8, "actionableClusterCount": 3, "hedgeRate": 0.15},
            WALLETS["micro"]: {"clustersCount": 8, "actionableClusterCount": 1, "hedgeRate": 0.2},
        },
    )
    _write_json(
        base / "adaptive_signal_wallet_quality.json",
        {
            "runId": "quality",
            "generatedAt": now,
            "benchmarkWallet": BENCHMARK,
            "walletCount": 4,
            "wallets": [
                {"wallet": BENCHMARK, "keepInRosterRecommendation": "KEEP_BENCHMARK", "actionableSignalScore": 90},
                {"wallet": WALLETS["strong"], "keepInRosterRecommendation": "KEEP_CANDIDATE", "actionableSignalScore": 84},
                {"wallet": WALLETS["replace"], "keepInRosterRecommendation": "REPLACE_CANDIDATE", "actionableSignalScore": 18},
                {"wallet": WALLETS["crypto"], "keepInRosterRecommendation": "KEEP_CANDIDATE", "actionableSignalScore": 61},
            ],
        },
    )
    _write_json(base / "adaptive_signal_wallet_roster.json", {"selectedWallets": [{"wallet": BENCHMARK}], "explorationWallets": []})
    _write_json(
        base / "trade_copyability_shadow.json",
        {
            "clusters": [
                {"wallet": WALLETS["strong"], "marketTitle": "Politics election outcome", "category": "politics", "copyabilityStatus": "high_copyability", "copyabilityLabel": "ALTA_CONVICCION", "totalSizeUsd": 500, "hedge": {"hedgeProbability": 10}},
                {"wallet": WALLETS["replace"], "marketTitle": "Macro GDP print", "category": "macro", "copyabilityStatus": "watch_copyability", "copyabilityLabel": "ACUMULACION", "totalSizeUsd": 300, "hedge": {"hedgeProbability": 60}},
                {"wallet": WALLETS["crypto"], "marketTitle": "Crypto cycle trade", "category": "crypto", "copyabilityStatus": "watch_copyability", "copyabilityLabel": "ACUMULACION", "totalSizeUsd": 400, "hedge": {"hedgeProbability": 15}},
                {"wallet": WALLETS["micro"], "marketTitle": "Bitcoin Up or Down - June 29, 4:50PM-4:55PM ET", "category": "sports", "copyabilityStatus": "low_copyability", "copyabilityLabel": "ACTIVIDAD_RUTINARIA", "totalSizeUsd": 20, "hedge": {"hedgeProbability": 0}},
            ],
            "walletResults": [
                {"wallet": WALLETS["strong"], "clusters": 8, "highCopyabilityCount": 4, "watchCopyabilityCount": 2, "notCopyableCount": 0, "hedgeRate": 0.1},
                {"wallet": WALLETS["replace"], "clusters": 8, "highCopyabilityCount": 1, "watchCopyabilityCount": 1, "notCopyableCount": 3, "hedgeRate": 0.6},
                {"wallet": WALLETS["crypto"], "clusters": 8, "highCopyabilityCount": 2, "watchCopyabilityCount": 2, "notCopyableCount": 0, "hedgeRate": 0.15},
                {"wallet": WALLETS["micro"], "clusters": 8, "highCopyabilityCount": 0, "watchCopyabilityCount": 1, "notCopyableCount": 7, "hedgeRate": 0.2},
            ],
        },
    )
    _write_json(base / "wallet_shadow_history.jsonl", [])


def _fake_fetch_factory(trade_map: dict[str, list[dict[str, object]]]):
    async def _fake_fetch(wallet, limit, lookback_hours, *, return_details=False, **_kwargs):
        normalized = list(trade_map.get(str(wallet).lower(), []))[:limit]
        payload = {
            "wallet": str(wallet).lower(),
            "status": "completed",
            "reason": "clusters_generated" if normalized else "no_valid_trades",
            "rawTrades": len(normalized),
            "normalizedTrades": len(normalized),
            "trades": normalized,
            "error": None,
        }
        return payload if return_details else normalized

    return _fake_fetch


def test_candidate_pool_generates_json_and_scores_wallets(monkeypatch):
    base = Path.cwd() / "tests" / "_adaptive_discovery_v2_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _seed_sources(base)
    trade_map = {
        WALLETS["strong"]: [_trade(WALLETS["strong"], market=f"p{i}", category="politics", size_usd=200, index=i) for i in range(1, 16)],
        WALLETS["replace"]: [_trade(WALLETS["replace"], market=f"m{i}", category="macro", size_usd=120, index=i) for i in range(1, 8)],
        WALLETS["crypto"]: [_trade(WALLETS["crypto"], market=f"c{i}", category="crypto", size_usd=160, index=i) for i in range(1, 12)],
        WALLETS["micro"]: [_trade(WALLETS["micro"], market="Bitcoin Up or Down - June 29, 4:50PM-4:55PM ET", category="sports", size_usd=15, index=i) for i in range(1, 10)],
    }
    monkeypatch.setattr(discovery, "OUTPUT_DIR", base)
    monkeypatch.setattr(discovery, "ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE", base / "adaptive_signal_candidate_pool.json")
    monkeypatch.setattr(discovery, "fetch_copyability_trades_for_wallet", _fake_fetch_factory(trade_map))
    monkeypatch.setattr(discovery, "SIGNAL_WALLET_DISCOVERY_V2_PREFLIGHT_TOP_N", 2)
    monkeypatch.setattr(discovery, "SIGNAL_WALLET_DISCOVERY_V2_MAX_CANDIDATES", 3)

    payload = discovery.build_adaptive_signal_candidate_pool(
        wallet_scores=[{"wallet": BENCHMARK, "walletQualityScore": 90}],
        shadow_rows=[],
        copyability_seed_trades=trade_map[WALLETS["strong"]],
        output_dir=base,
    )
    path = discovery.write_adaptive_signal_candidate_pool(payload)

    assert path.exists()
    assert payload["candidateCount"] == 3
    assert payload["strongCandidateCount"] >= 1
    assert payload["watchlistCandidateCount"] >= 1
    assert payload["rejectedCandidateCount"] >= 0
    assert len(payload["candidates"]) == 3
    assert len({row["wallet"] for row in payload["candidates"]}) == len(payload["candidates"])
    assert all(0 <= row["candidateQualityScore"] <= 100 for row in payload["candidates"])
    crypto_row = next(row for row in payload["candidates"] if row["wallet"] == WALLETS["crypto"])
    replace_row = next(row for row in payload["candidates"] if row["wallet"] == WALLETS["replace"])
    micro_row = next(row for row in payload["rejectedCandidates"] if row["wallet"] == WALLETS["micro"])
    assert replace_row["candidateRecommendation"] in {"WEAK_CANDIDATE", "REJECT", "WATCHLIST_CANDIDATE", "CANDIDATE"}
    assert crypto_row["candidateRecommendation"] != "REJECT"
    assert micro_row["candidateRecommendation"] == "REJECT"


def test_candidate_pool_handles_missing_optional_outputs(monkeypatch):
    base = Path.cwd() / "tests" / "_adaptive_discovery_v2_tmp_missing"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(discovery, "OUTPUT_DIR", base)
    monkeypatch.setattr(discovery, "ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE", base / "adaptive_signal_candidate_pool.json")
    monkeypatch.setattr(discovery, "fetch_copyability_trades_for_wallet", _fake_fetch_factory({}))
    monkeypatch.setattr(discovery, "SIGNAL_WALLET_DISCOVERY_V2_PREFLIGHT_TOP_N", 0)
    monkeypatch.setattr(discovery, "SIGNAL_WALLET_DISCOVERY_V2_MAX_CANDIDATES", 5)

    payload = discovery.build_adaptive_signal_candidate_pool(output_dir=base)

    assert payload["sourceStatus"] == "empty"
    assert payload["candidateCount"] == 0
    assert payload["candidates"] == []


def test_candidate_pool_penalizes_replace_candidate_and_micro_markets(monkeypatch):
    base = Path.cwd() / "tests" / "_adaptive_discovery_v2_tmp_penalty"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _seed_sources(base)
    monkeypatch.setattr(discovery, "OUTPUT_DIR", base)
    monkeypatch.setattr(discovery, "ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE", base / "adaptive_signal_candidate_pool.json")
    monkeypatch.setattr(discovery, "fetch_copyability_trades_for_wallet", _fake_fetch_factory({}))
    monkeypatch.setattr(discovery, "SIGNAL_WALLET_DISCOVERY_V2_PREFLIGHT_TOP_N", 0)

    payload = discovery.build_adaptive_signal_candidate_pool(output_dir=base)
    replace_row = next(row for row in payload["candidates"] if row["wallet"] == WALLETS["replace"])
    crypto_row = next(row for row in payload["candidates"] if row["wallet"] == WALLETS["crypto"])
    micro_row = next(row for row in payload["candidates"] if row["wallet"] == WALLETS["micro"])

    assert "previous_replace_candidate" in replace_row["candidateRisks"]
    assert replace_row["candidateQualityScore"] < crypto_row["candidateQualityScore"]
    assert micro_row["candidateRecommendation"] == "REJECT"
    assert crypto_row["candidateRecommendation"] != "REJECT"


def test_candidate_pool_respects_top_n_and_dedupes_wallets(monkeypatch):
    base = Path.cwd() / "tests" / "_adaptive_discovery_v2_tmp_topn"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _seed_sources(base)
    calls: list[str] = []

    async def fake_fetch(wallet, limit, lookback_hours, *, return_details=False, **_kwargs):
        calls.append(str(wallet).lower())
        return {"wallet": wallet, "status": "completed", "reason": "no_valid_trades", "rawTrades": 0, "normalizedTrades": 0, "trades": [], "error": None}

    monkeypatch.setattr(discovery, "OUTPUT_DIR", base)
    monkeypatch.setattr(discovery, "ADAPTIVE_SIGNAL_CANDIDATE_POOL_FILE", base / "adaptive_signal_candidate_pool.json")
    monkeypatch.setattr(discovery, "fetch_copyability_trades_for_wallet", fake_fetch)
    monkeypatch.setattr(discovery, "SIGNAL_WALLET_DISCOVERY_V2_PREFLIGHT_TOP_N", 2)
    monkeypatch.setattr(discovery, "SIGNAL_WALLET_DISCOVERY_V2_MAX_CANDIDATES", 50)

    payload = discovery.build_adaptive_signal_candidate_pool(output_dir=base)

    assert len(calls) == 2
    assert len({row["wallet"] for row in payload["candidates"]}) == len(payload["candidates"])
