from __future__ import annotations

import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workers.smart_money.smart_money_engine import adaptive_wallet_roster as roster


BENCHMARK = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"
WALLETS = {
    "macro": "0x" + "1" * 40,
    "politics": "0x" + "2" * 40,
    "geopolitics": "0x" + "3" * 40,
    "crypto": "0x" + "4" * 40,
    "technology": "0x" + "5" * 40,
    "rejected": "0x" + "6" * 40,
}


def _write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_quality(path: Path, rows: list[dict[str, object]]):
    payload = {
        "runId": "quality-run",
        "generatedAt": datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc).isoformat(),
        "benchmarkWallet": BENCHMARK,
        "walletCount": len(rows),
        "wallets": rows,
        "walletQualityRows": rows,
        "walletResults": rows,
    }
    _write_json(path, payload)


def _write_history(path: Path, rows: list[dict[str, object]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n", encoding="utf-8")


def _normalized_copyability_trade(wallet: str, *, market: str, index: int, category: str, size_usd: float, side: str = "BUY", outcome: str = "yes"):
    ts = int((datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc) - timedelta(minutes=index * 7)).timestamp())
    return {
        "tradeId": f"{wallet}-{market}-{index}",
        "dedupeKey": f"{wallet}-{market}-{index}",
        "transactionHash": None,
        "wallet": wallet,
        "timestamp": ts,
        "timestampIso": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
        "conditionId": market,
        "asset": f"{market}-asset",
        "marketTitle": f"{category} market {market}",
        "eventSlug": f"{category}-{market}",
        "outcome": outcome,
        "side": side,
        "price": 0.5,
        "shares": 1.0,
        "sizeUsd": size_usd,
        "category": category,
        "rawSource": "activity",
    }


def _good_preflight_trades(wallet: str):
    trades = []
    for market_index, market in enumerate(["m1", "m2", "m3", "m4"], start=1):
        for trade_index in range(1, 6):
            trades.append(
                _normalized_copyability_trade(
                    wallet,
                    market=market,
                    index=(market_index - 1) * 5 + trade_index,
                    category="macro",
                    size_usd=240 + market_index * 60,
                )
            )
    return trades


def _weak_preflight_trades(wallet: str):
    trades = []
    for trade_index in range(1, 16):
        trades.append(
            _normalized_copyability_trade(
                wallet,
                market="exact-score-corners-halftime-prop",
                index=trade_index,
                category="sports",
                size_usd=18 + trade_index,
            )
        )
    return trades


def _fake_fetch_copyability_trades_for_wallet_factory(trade_map: dict[str, list[dict[str, object]]]):
    async def _fake_fetch_copyability_trades_for_wallet(wallet, limit, lookback_hours, *, return_details=False, **_kwargs):
        normalized = list(trade_map.get(wallet.lower(), []))[:limit]
        raw_count = len(normalized)
        status = "completed"
        reason = "clusters_generated" if len(normalized) >= 10 else "no_clusters_after_filters"
        result = {
            "wallet": wallet.lower(),
            "status": status,
            "reason": reason if normalized else "no_valid_trades",
            "rawTrades": raw_count,
            "normalizedTrades": len(normalized),
            "trades": normalized,
            "error": None,
        }
        if return_details:
            return result
        return normalized

    return _fake_fetch_copyability_trades_for_wallet


def _candidate_sources(base: Path):
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    general_rankings = [
        {
            "wallet": BENCHMARK,
            "displayName": "Ken",
            "roles": ["active", "benchmark"],
            "profiles": ["mixed"],
            "classification": "WHALE_BUT_NOISY",
            "behaviorQualityScore": 64,
            "robustSkillScore": 77,
            "shadowRobustMetaScore": 69,
            "longitudinalComparisonScore": 62.1,
            "comparisonConfidence": "sufficient",
            "runCount": 9,
            "stabilityScore": 0.0,
            "scoreTrend": "stable",
            "dominantKnownCategory": "geopolitics",
            "knownCategoryCoverageScore": 54,
            "pnlConcentrationLevel": "low",
            "recommendation": "shadow_watch",
            "rank": 1,
        }
    ]
    for index, (category, wallet) in enumerate(WALLETS.items(), start=1):
        general_rankings.append(
            {
                "wallet": wallet,
                "displayName": f"{category.title()} Wallet",
                "roles": ["candidate"],
                "profiles": [category],
                "classification": "SPECIALIST_WALLET",
                "behaviorQualityScore": 80 - index,
                "robustSkillScore": 90 - index * 2,
                "shadowRobustMetaScore": 85 - index * 2,
                "longitudinalComparisonScore": 75 - index,
                "comparisonConfidence": "sufficient",
                "runCount": 8,
                "stabilityScore": 0.0,
                "scoreTrend": "stable",
                "dominantKnownCategory": category,
                "knownCategoryCoverageScore": 80 - index,
                "pnlConcentrationLevel": "low" if category != "rejected" else "extreme",
                "recommendation": "shadow_strong",
                "rank": index + 1,
            }
        )

    category_rankings = {
        "macro": [
            {
                "wallet": WALLETS["macro"],
                "displayName": "Macro Wallet",
                "roles": ["candidate"],
                "profiles": ["macro"],
                "classification": "SPECIALIST_WALLET",
                "closedPositionsCount": 18,
                "totalRealizedPnl": 1200,
                "roi": 0.25,
                "winRate": 0.7,
                "profitFactor": 2.1,
                "payoffRatio": 1.4,
                "categorySkillScore": 88,
                "categorySkillStatus": "sufficient",
                "rankingEligible": True,
                "categorySampleConfidence": 60,
                "categoryRankingScore": 86,
                "rank": 1,
            }
        ],
        "politics": [
            {
                "wallet": WALLETS["politics"],
                "displayName": "Politics Wallet",
                "roles": ["candidate"],
                "profiles": ["politics"],
                "classification": "SPECIALIST_WALLET",
                "closedPositionsCount": 12,
                "totalRealizedPnl": 900,
                "roi": 0.21,
                "winRate": 0.68,
                "profitFactor": 1.9,
                "payoffRatio": 1.2,
                "categorySkillScore": 82,
                "categorySkillStatus": "sufficient",
                "rankingEligible": True,
                "categorySampleConfidence": 40,
                "categoryRankingScore": 77,
                "rank": 1,
            }
        ],
        "geopolitics": [
            {
                "wallet": WALLETS["geopolitics"],
                "displayName": "Geopolitics Wallet",
                "roles": ["candidate"],
                "profiles": ["geopolitics"],
                "classification": "SPECIALIST_WALLET",
                "closedPositionsCount": 22,
                "totalRealizedPnl": 1700,
                "roi": 0.18,
                "winRate": 0.66,
                "profitFactor": 2.3,
                "payoffRatio": 1.3,
                "categorySkillScore": 84,
                "categorySkillStatus": "sufficient",
                "rankingEligible": True,
                "categorySampleConfidence": 73.3,
                "categoryRankingScore": 82,
                "rank": 1,
            }
        ],
        "crypto": [
            {
                "wallet": WALLETS["crypto"],
                "displayName": "Crypto Wallet",
                "roles": ["candidate"],
                "profiles": ["crypto"],
                "classification": "SPECIALIST_WALLET",
                "closedPositionsCount": 15,
                "totalRealizedPnl": 650,
                "roi": 0.19,
                "winRate": 0.64,
                "profitFactor": 1.7,
                "payoffRatio": 1.1,
                "categorySkillScore": 80,
                "categorySkillStatus": "sufficient",
                "rankingEligible": True,
                "categorySampleConfidence": 50,
                "categoryRankingScore": 79,
                "rank": 1,
            }
        ],
        "technology": [
            {
                "wallet": WALLETS["technology"],
                "displayName": "Technology Wallet",
                "roles": ["candidate"],
                "profiles": ["technology"],
                "classification": "SPECIALIST_WALLET",
                "closedPositionsCount": 14,
                "totalRealizedPnl": 700,
                "roi": 0.2,
                "winRate": 0.67,
                "profitFactor": 1.8,
                "payoffRatio": 1.2,
                "categorySkillScore": 81,
                "categorySkillStatus": "sufficient",
                "rankingEligible": True,
                "categorySampleConfidence": 46.67,
                "categoryRankingScore": 78,
                "rank": 1,
            }
        ],
        "sports": [
            {
                "wallet": WALLETS["rejected"],
                "displayName": "Rejected Wallet",
                "roles": ["candidate"],
                "profiles": ["sports"],
                "classification": "WHALE_BUT_NOISY",
                "closedPositionsCount": 4,
                "totalRealizedPnl": 50,
                "roi": 0.01,
                "winRate": 0.25,
                "profitFactor": 0.5,
                "payoffRatio": 0.3,
                "categorySkillScore": 40,
                "categorySkillStatus": "unranked",
                "rankingEligible": False,
                "categorySampleConfidence": 13.33,
                "categoryRankingScore": 28,
                "rank": None,
            }
        ],
    }

    shadow_history = [
        {
            "wallet": wallet,
            "displayName": f"{category.title()} Wallet",
            "roles": ["candidate"],
            "profiles": [category],
            "sources": ["shadow"],
            "classification": "SPECIALIST_WALLET",
            "behaviorQualityScore": 80 - index,
            "shadowSkill": {
                "categorySkillScores": {
                    category: {
                        "closedPositionsCount": 10 + index,
                        "skillStatus": "sufficient",
                        "skillScore": 88 - index,
                    }
                },
                "skillStatus": "sufficient",
                "skillScore": 88 - index,
                "dominantKnownCategory": category,
            },
            "shadowRobustEvaluation": {
                "robustSkillScore": 90 - index * 2,
                "shadowRobustMetaScore": 82 - index,
                "pnlConcentrationLevel": "low" if category != "rejected" else "extreme",
            },
            "behaviorStatus": "sufficient",
            "generatedAt": (now - timedelta(days=index)).isoformat(),
        }
        for index, (category, wallet) in enumerate(WALLETS.items(), start=1)
    ]
    shadow_history.insert(
        0,
        {
            "wallet": BENCHMARK,
            "displayName": "Ken",
            "roles": ["active", "benchmark"],
            "profiles": ["mixed"],
            "sources": ["shadow"],
            "classification": "WHALE_BUT_NOISY",
            "behaviorQualityScore": 64,
            "shadowSkill": {
                "categorySkillScores": {
                    "geopolitics": {
                        "closedPositionsCount": 14,
                        "skillStatus": "limited",
                        "skillScore": 75,
                    }
                },
                "skillStatus": "limited",
                "skillScore": 75,
                "dominantKnownCategory": "geopolitics",
            },
            "shadowRobustEvaluation": {
                "robustSkillScore": 77,
                "shadowRobustMetaScore": 69,
                "pnlConcentrationLevel": "low",
            },
            "behaviorStatus": "sufficient",
            "generatedAt": now.isoformat(),
        },
    )

    copyability_summary = {
        BENCHMARK: {
            "wallet": BENCHMARK,
            "clustersCount": 4,
            "buyClusters": 2,
            "sellClusters": 2,
            "highCopyabilityCount": 0,
            "watchCopyabilityCount": 1,
            "notCopyableCount": 0,
            "reductionSignalCount": 2,
            "accumulationCount": 1,
            "averageDetectionScore": 62,
            "medianDetectionScore": 61,
            "averageValidatedScore": None,
            "hedgeCount70": 0,
            "possibleHedgeCount60": 0,
            "hedgeRate70": 0.0,
            "possibleHedgeRate60": 0.0,
            "hedgeRate": 0.0,
            "bestCategory": "geopolitics",
            "generatedAt": now.isoformat(),
        },
        WALLETS["macro"]: {
            "wallet": WALLETS["macro"],
            "clustersCount": 12,
            "buyClusters": 8,
            "sellClusters": 4,
            "highCopyabilityCount": 3,
            "watchCopyabilityCount": 4,
            "notCopyableCount": 0,
            "reductionSignalCount": 5,
            "accumulationCount": 3,
            "averageDetectionScore": 70,
            "medianDetectionScore": 72,
            "averageValidatedScore": 68,
            "hedgeCount70": 0,
            "possibleHedgeCount60": 1,
            "hedgeRate70": 0.0,
            "possibleHedgeRate60": 0.0833,
            "hedgeRate": 0.0,
            "bestCategory": "macro",
            "generatedAt": now.isoformat(),
        },
        WALLETS["politics"]: {
            "wallet": WALLETS["politics"],
            "clustersCount": 10,
            "buyClusters": 7,
            "sellClusters": 3,
            "highCopyabilityCount": 2,
            "watchCopyabilityCount": 4,
            "notCopyableCount": 1,
            "reductionSignalCount": 3,
            "accumulationCount": 2,
            "averageDetectionScore": 68,
            "medianDetectionScore": 69,
            "averageValidatedScore": 66,
            "hedgeCount70": 0,
            "possibleHedgeCount60": 1,
            "hedgeRate70": 0.0,
            "possibleHedgeRate60": 0.1,
            "hedgeRate": 0.0,
            "bestCategory": "politics",
            "generatedAt": now.isoformat(),
        },
        WALLETS["geopolitics"]: {
            "wallet": WALLETS["geopolitics"],
            "clustersCount": 11,
            "buyClusters": 7,
            "sellClusters": 4,
            "highCopyabilityCount": 2,
            "watchCopyabilityCount": 4,
            "notCopyableCount": 0,
            "reductionSignalCount": 4,
            "accumulationCount": 2,
            "averageDetectionScore": 69,
            "medianDetectionScore": 68,
            "averageValidatedScore": 67,
            "hedgeCount70": 0,
            "possibleHedgeCount60": 1,
            "hedgeRate70": 0.0,
            "possibleHedgeRate60": 0.0909,
            "hedgeRate": 0.0,
            "bestCategory": "geopolitics",
            "generatedAt": now.isoformat(),
        },
        WALLETS["crypto"]: {
            "wallet": WALLETS["crypto"],
            "clustersCount": 9,
            "buyClusters": 6,
            "sellClusters": 3,
            "highCopyabilityCount": 1,
            "watchCopyabilityCount": 3,
            "notCopyableCount": 0,
            "reductionSignalCount": 2,
            "accumulationCount": 1,
            "averageDetectionScore": 64,
            "medianDetectionScore": 63,
            "averageValidatedScore": 61,
            "hedgeCount70": 0,
            "possibleHedgeCount60": 0,
            "hedgeRate70": 0.0,
            "possibleHedgeRate60": 0.0,
            "hedgeRate": 0.0,
            "bestCategory": "crypto",
            "generatedAt": now.isoformat(),
        },
        WALLETS["technology"]: {
            "wallet": WALLETS["technology"],
            "clustersCount": 8,
            "buyClusters": 5,
            "sellClusters": 3,
            "highCopyabilityCount": 1,
            "watchCopyabilityCount": 2,
            "notCopyableCount": 0,
            "reductionSignalCount": 2,
            "accumulationCount": 1,
            "averageDetectionScore": 62,
            "medianDetectionScore": 60,
            "averageValidatedScore": 59,
            "hedgeCount70": 0,
            "possibleHedgeCount60": 0,
            "hedgeRate70": 0.0,
            "possibleHedgeRate60": 0.0,
            "hedgeRate": 0.0,
            "bestCategory": "technology",
            "generatedAt": now.isoformat(),
        },
        WALLETS["rejected"]: {
            "wallet": WALLETS["rejected"],
            "clustersCount": 9,
            "buyClusters": 2,
            "sellClusters": 7,
            "highCopyabilityCount": 0,
            "watchCopyabilityCount": 1,
            "notCopyableCount": 8,
            "reductionSignalCount": 1,
            "accumulationCount": 0,
            "averageDetectionScore": 36,
            "medianDetectionScore": 35,
            "averageValidatedScore": 34,
            "hedgeCount70": 8,
            "possibleHedgeCount60": 8,
            "hedgeRate70": 0.8889,
            "possibleHedgeRate60": 0.8889,
            "hedgeRate": 0.8889,
            "bestCategory": "sports",
            "generatedAt": (now - timedelta(days=120)).isoformat(),
        },
    }

    _write_json(base / "wallet_shadow_rankings.json", general_rankings)
    _write_json(base / "wallet_category_rankings.json", category_rankings)
    _write_history(base / "wallet_shadow_history.jsonl", shadow_history)
    _write_json(base / "wallet_copyability_summary.json", copyability_summary)
    _write_json(base / "wallet_comparison_summary.json", {"comparisons": [], "sufficient": 0})
    _write_json(base / "trade_copyability_shadow.json", {"clusters": [], "walletResults": []})


def _write_low_signal_candidate_sources(base: Path, candidate_count: int = 195):
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    general_rankings = [
        {
            "wallet": BENCHMARK,
            "displayName": "Ken",
            "roles": ["active", "benchmark"],
            "profiles": ["mixed"],
            "classification": "WHALE_BUT_NOISY",
            "behaviorQualityScore": 64,
            "robustSkillScore": 77,
            "shadowRobustMetaScore": 69,
            "longitudinalComparisonScore": 62.1,
            "comparisonConfidence": "sufficient",
            "runCount": 9,
            "stabilityScore": 0.0,
            "scoreTrend": "stable",
            "dominantKnownCategory": "geopolitics",
            "knownCategoryCoverageScore": 54,
            "pnlConcentrationLevel": "low",
            "recommendation": "shadow_watch",
            "rank": 1,
        }
    ]
    for index in range(candidate_count):
        wallet = f"0x{index + 1:040x}"
        general_rankings.append(
            {
                "wallet": wallet,
                "displayName": f"Candidate {index + 1}",
                "roles": ["candidate"],
                "profiles": ["mixed"],
                "classification": "WHALE_BUT_NOISY",
                "behaviorQualityScore": 8,
                "robustSkillScore": 12,
                "shadowRobustMetaScore": 10,
                "longitudinalComparisonScore": 6,
                "comparisonConfidence": "insufficient",
                "runCount": 0,
                "stabilityScore": 0.0,
                "scoreTrend": "stable",
                "dominantKnownCategory": "mixed",
                "knownCategoryCoverageScore": 0,
                "pnlConcentrationLevel": "low",
                "recommendation": "shadow_watch",
                "rank": index + 2,
            }
        )

    _write_json(base / "wallet_shadow_rankings.json", general_rankings)
    _write_json(base / "wallet_category_rankings.json", {})
    _write_history(base / "wallet_shadow_history.jsonl", [])
    _write_json(base / "wallet_copyability_summary.json", {})
    _write_json(base / "wallet_comparison_summary.json", {"comparisons": [], "sufficient": 0})
    _write_json(base / "trade_copyability_shadow.json", {"clusters": [], "walletResults": []})


def test_adaptive_signal_wallet_roster_selects_six_wallets_and_writes_output(monkeypatch):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _candidate_sources(base)

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")
    fetch_map = {
        BENCHMARK: _good_preflight_trades(BENCHMARK),
        WALLETS["macro"]: _good_preflight_trades(WALLETS["macro"]),
        WALLETS["politics"]: _good_preflight_trades(WALLETS["politics"]),
        WALLETS["geopolitics"]: _good_preflight_trades(WALLETS["geopolitics"]),
        WALLETS["crypto"]: _good_preflight_trades(WALLETS["crypto"]),
        WALLETS["technology"]: _good_preflight_trades(WALLETS["technology"]),
        WALLETS["rejected"]: _weak_preflight_trades(WALLETS["rejected"]),
    }
    monkeypatch.setattr(roster, "fetch_copyability_trades_for_wallet", _fake_fetch_copyability_trades_for_wallet_factory(fetch_map))

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=6,
        wallet_scores=[],
        shadow_rows=[],
        copyability_seed_trades=(
            _good_preflight_trades(BENCHMARK)
            + _good_preflight_trades(WALLETS["macro"])
            + _good_preflight_trades(WALLETS["politics"])
            + _good_preflight_trades(WALLETS["geopolitics"])
            + _good_preflight_trades(WALLETS["crypto"])
            + _good_preflight_trades(WALLETS["technology"])
            + _weak_preflight_trades(WALLETS["rejected"])
        ),
        output_dir=base,
    )
    path = roster.write_adaptive_signal_wallet_roster(payload)

    assert path.exists()
    assert payload["benchmarkWallet"] == BENCHMARK
    assert payload["targetRosterSize"] == 6
    assert payload["candidatesFound"] >= 6
    assert len(payload["selectedWallets"]) == 6
    assert len(payload["explorationWallets"]) == 0
    assert len(payload["walletsForCopyability"]) == 3
    assert payload["selectedCount"] == 6
    assert payload["explorationCount"] == 0
    assert payload["walletsForCopyabilityCount"] == 3
    assert payload["needsMoreDiscovery"] is False
    assert payload["diagnosticCandidatesAnalyzed"] == 0
    assert payload["diagnosticPreflightTopN"] == 0
    assert "rejectedReasonSummary" in payload
    assert payload["selectedWallets"][0]["wallet"] == BENCHMARK
    assert payload["selectedWallets"][0]["isBenchmark"] is True
    assert payload["selectedWallets"][0]["signalWalletRosterScore"] == 100
    assert all(row["probationaryCandidate"] is False for row in payload["selectedWallets"][1:])
    assert any(row["wallet"] == WALLETS["rejected"] for row in payload["rejectedWallets"])
    rejected = next(row for row in payload["rejectedWallets"] if row["wallet"] == WALLETS["rejected"])
    assert rejected["rejectionReason"] in {
        "low_actionable_score",
        "low_skill_score",
        "insufficient_live_trades",
        "insufficient_normalized_trades",
        "low_unique_markets",
        "low_cluster_viability",
        "high_routine_rate",
        "high_micro_market_rate",
        "high_hedge_rate",
        "previous_replace_candidate",
        "unknown_quality_no_preflight",
        "missing_required_metrics",
    }
    assert isinstance(rejected["rejectionReasons"], list)
    assert rejected["rejectionReasons"]
    selected_scores = {row["wallet"]: row["signalWalletRosterScore"] for row in payload["selectedWallets"]}
    assert selected_scores[WALLETS["macro"]] > rejected["signalWalletRosterScore"]
    shutil.rmtree(base, ignore_errors=True)


def test_adaptive_signal_wallet_roster_keeps_benchmark_when_no_candidates(monkeypatch):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_benchmark_only"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _write_json(base / "wallet_shadow_rankings.json", [])
    _write_json(base / "wallet_category_rankings.json", {})
    _write_history(base / "wallet_shadow_history.jsonl", [])
    _write_json(base / "wallet_copyability_summary.json", {})
    _write_json(base / "wallet_comparison_summary.json", {})
    _write_json(base / "trade_copyability_shadow.json", {})

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")
    fetch_map = {
        BENCHMARK: _good_preflight_trades(BENCHMARK),
        WALLETS["macro"]: _good_preflight_trades(WALLETS["macro"]),
        WALLETS["rejected"]: _weak_preflight_trades(WALLETS["rejected"]),
    }
    monkeypatch.setattr(roster, "fetch_copyability_trades_for_wallet", _fake_fetch_copyability_trades_for_wallet_factory(fetch_map))

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=6,
        wallet_scores=[],
        shadow_rows=[],
        copyability_seed_trades=_good_preflight_trades(BENCHMARK) + _good_preflight_trades(WALLETS["macro"]) + _weak_preflight_trades(WALLETS["rejected"]),
        output_dir=base,
    )

    assert len(payload["selectedWallets"]) == 1
    assert payload["selectedWallets"][0]["wallet"] == BENCHMARK
    assert payload["selectedWallets"][0]["rank"] == 1
    assert payload["selectedWallets"][0]["isBenchmark"] is True
    assert payload["selectedWallets"][0]["signalWalletRosterScore"] == 100.0
    assert payload["selectedWallets"][0]["primaryCategory"] == "mixed"
    assert payload["selectedWallets"][0]["reason"] == "benchmark wallet"
    assert payload["selectedWallets"][0]["selectionReason"] == "benchmark wallet"
    assert payload["selectedWallets"][0]["probationaryCandidate"] is False
    assert payload["selectedCount"] == 1
    assert payload["explorationCount"] == 0
    assert payload["walletsForCopyabilityCount"] == 1
    assert payload["needsMoreDiscovery"] is True
    assert payload["diagnosticCandidatesAnalyzed"] == 0
    assert payload["rejectedWallets"] == []
    shutil.rmtree(base, ignore_errors=True)


def test_high_hedge_and_not_copyable_penalize_roster_score(monkeypatch):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_penalty"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    _write_json(
        base / "wallet_shadow_rankings.json",
        [
            {
                "wallet": BENCHMARK,
                "displayName": "Ken",
                "roles": ["benchmark"],
                "profiles": ["mixed"],
                "classification": "WHALE_BUT_NOISY",
                "robustSkillScore": 75,
                "shadowRobustMetaScore": 69,
                "longitudinalComparisonScore": 61,
                "comparisonConfidence": "sufficient",
                "runCount": 6,
                "dominantKnownCategory": "geopolitics",
                "knownCategoryCoverageScore": 50,
                "pnlConcentrationLevel": "low",
                "recommendation": "shadow_watch",
                "rank": 1,
            },
            {
                "wallet": WALLETS["macro"],
                "displayName": "Macro Wallet",
                "roles": ["candidate"],
                "profiles": ["macro"],
                "classification": "SPECIALIST_WALLET",
                "robustSkillScore": 90,
                "shadowRobustMetaScore": 84,
                "longitudinalComparisonScore": 79,
                "comparisonConfidence": "sufficient",
                "runCount": 8,
                "dominantKnownCategory": "macro",
                "knownCategoryCoverageScore": 88,
                "pnlConcentrationLevel": "low",
                "recommendation": "shadow_strong",
                "rank": 2,
            },
            {
                "wallet": WALLETS["rejected"],
                "displayName": "Rejected Wallet",
                "roles": ["candidate"],
                "profiles": ["sports"],
                "classification": "WHALE_BUT_NOISY",
                "robustSkillScore": 88,
                "shadowRobustMetaScore": 82,
                "longitudinalComparisonScore": 70,
                "comparisonConfidence": "sufficient",
                "runCount": 8,
                "dominantKnownCategory": "sports",
                "knownCategoryCoverageScore": 90,
                "pnlConcentrationLevel": "extreme",
                "recommendation": "shadow_low",
                "rank": 3,
            },
        ],
    )
    _write_json(
        base / "wallet_category_rankings.json",
        {
            "macro": [
                {
                    "wallet": WALLETS["macro"],
                    "displayName": "Macro Wallet",
                    "roles": ["candidate"],
                    "profiles": ["macro"],
                    "classification": "SPECIALIST_WALLET",
                    "closedPositionsCount": 20,
                    "categorySkillScore": 88,
                    "categorySkillStatus": "sufficient",
                    "rankingEligible": True,
                    "categorySampleConfidence": 66.7,
                    "categoryRankingScore": 86,
                    "rank": 1,
                }
            ],
            "sports": [
                {
                    "wallet": WALLETS["rejected"],
                    "displayName": "Rejected Wallet",
                    "roles": ["candidate"],
                    "profiles": ["sports"],
                    "classification": "WHALE_BUT_NOISY",
                    "closedPositionsCount": 6,
                    "categorySkillScore": 30,
                    "categorySkillStatus": "sufficient",
                    "rankingEligible": True,
                    "categorySampleConfidence": 20,
                    "categoryRankingScore": 30,
                    "rank": 1,
                }
            ],
        },
    )
    _write_history(
        base / "wallet_shadow_history.jsonl",
        [
            {
                "wallet": BENCHMARK,
                "displayName": "Ken",
                "profiles": ["mixed"],
                "roles": ["benchmark"],
                "generatedAt": now.isoformat(),
                "shadowSkill": {"categorySkillScores": {}, "skillStatus": "limited"},
                "shadowRobustEvaluation": {"robustSkillScore": 75, "pnlConcentrationLevel": "low"},
            },
            {
                "wallet": WALLETS["macro"],
                "displayName": "Macro Wallet",
                "profiles": ["macro"],
                "roles": ["candidate"],
                "generatedAt": now.isoformat(),
                "shadowSkill": {"categorySkillScores": {"macro": {"closedPositionsCount": 20, "skillStatus": "sufficient", "skillScore": 88}}, "skillStatus": "sufficient", "skillScore": 88},
                "shadowRobustEvaluation": {"robustSkillScore": 90, "pnlConcentrationLevel": "low"},
            },
            {
                "wallet": WALLETS["rejected"],
                "displayName": "Rejected Wallet",
                "profiles": ["sports"],
                "roles": ["candidate"],
                "generatedAt": (now - timedelta(days=120)).isoformat(),
                "shadowSkill": {"categorySkillScores": {"sports": {"closedPositionsCount": 6, "skillStatus": "sufficient", "skillScore": 30}}, "skillStatus": "sufficient", "skillScore": 30},
                "shadowRobustEvaluation": {"robustSkillScore": 88, "pnlConcentrationLevel": "extreme"},
            },
        ],
    )
    _write_json(
        base / "wallet_copyability_summary.json",
        {
            BENCHMARK: {
                "wallet": BENCHMARK,
                "clustersCount": 3,
                "highCopyabilityCount": 0,
                "watchCopyabilityCount": 1,
                "notCopyableCount": 0,
                "reductionSignalCount": 1,
                "accumulationCount": 0,
                "hedgeCount70": 0,
                "possibleHedgeCount60": 0,
                "hedgeRate70": 0.0,
                "possibleHedgeRate60": 0.0,
                "hedgeRate": 0.0,
            },
            WALLETS["macro"]: {
                "wallet": WALLETS["macro"],
                "clustersCount": 12,
                "highCopyabilityCount": 4,
                "watchCopyabilityCount": 4,
                "notCopyableCount": 0,
                "reductionSignalCount": 5,
                "accumulationCount": 2,
                "hedgeCount70": 0,
                "possibleHedgeCount60": 1,
                "hedgeRate70": 0.0,
                "possibleHedgeRate60": 0.0833,
                "hedgeRate": 0.0,
            },
            WALLETS["rejected"]: {
                "wallet": WALLETS["rejected"],
                "clustersCount": 9,
                "highCopyabilityCount": 0,
                "watchCopyabilityCount": 1,
                "notCopyableCount": 8,
                "reductionSignalCount": 1,
                "accumulationCount": 0,
                "hedgeCount70": 8,
                "possibleHedgeCount60": 8,
                "hedgeRate70": 0.8889,
                "possibleHedgeRate60": 0.8889,
                "hedgeRate": 0.8889,
            },
        },
    )
    _write_json(base / "wallet_comparison_summary.json", {"comparisons": [], "sufficient": 0})
    _write_json(base / "trade_copyability_shadow.json", {"clusters": [], "walletResults": []})

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")
    fetch_map = {
        BENCHMARK: _good_preflight_trades(BENCHMARK),
        **{wallet: _weak_preflight_trades(wallet) for wallet in list(WALLETS.values())},
    }
    monkeypatch.setattr(roster, "fetch_copyability_trades_for_wallet", _fake_fetch_copyability_trades_for_wallet_factory(fetch_map))

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=2,
        wallet_scores=[],
        shadow_rows=[],
        copyability_seed_trades=_good_preflight_trades(BENCHMARK) + _good_preflight_trades(WALLETS["macro"]) + _weak_preflight_trades(WALLETS["rejected"]),
        output_dir=base,
    )

    macro = next(row for row in payload["selectedWallets"] if row["wallet"] == WALLETS["macro"])
    rejected = next(row for row in payload["rejectedWallets"] if row["wallet"] == WALLETS["rejected"])
    assert macro["signalWalletRosterScore"] > rejected["signalWalletRosterScore"]
    assert rejected["rejectionReason"] in {
        "previous_replace_candidate",
        "low_actionable_score",
        "low_skill_score",
        "insufficient_live_trades",
        "insufficient_normalized_trades",
        "low_unique_markets",
        "low_cluster_viability",
        "high_routine_rate",
        "high_micro_market_rate",
        "high_hedge_rate",
        "unknown_quality_no_preflight",
        "missing_required_metrics",
    }
    assert isinstance(rejected["rejectionReasons"], list)
    assert rejected["rejectionReasons"]
    shutil.rmtree(base, ignore_errors=True)


def test_adaptive_signal_wallet_roster_fallback_fills_to_target_and_marks_probationary(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_fallback"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _write_low_signal_candidate_sources(base, candidate_count=195)

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=6,
        wallet_scores=[],
        shadow_rows=[],
        output_dir=base,
    )
    output = capsys.readouterr().out

    assert payload["candidatesFound"] == 196
    assert len(payload["selectedWallets"]) == 1
    assert len(payload["explorationWallets"]) == 0
    assert len(payload["walletsForCopyability"]) == 1
    assert payload["selectedWallets"][0]["wallet"] == BENCHMARK
    assert payload["selectedWallets"][0]["rank"] == 1
    assert payload["selectedWallets"][0]["probationaryCandidate"] is False
    assert "SMART_MONEY_WALLET_ROSTER_QUALITY_FEEDBACK_LOADED rows=0" in output
    assert "SMART_MONEY_WALLET_ROSTER_INSUFFICIENT_LIVE_QUALITY" in output
    assert "SMART_MONEY_WALLET_ROSTER_SELECTED_VALID count=1" in output
    assert "SMART_MONEY_WALLET_ROSTER_EXPLORATION_SELECTED count=0" in output
    assert "SMART_MONEY_WALLET_ROSTER_COPYABILITY_WALLETS count=" in output
    assert payload["rejectedReasonSummary"]
    shutil.rmtree(base, ignore_errors=True)


def test_adaptive_signal_wallet_roster_diagnostic_preflight_respects_top_n(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_diagnostic"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _write_low_signal_candidate_sources(base, candidate_count=20)

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")
    monkeypatch.setattr(roster, "SIGNAL_WALLET_DIAGNOSTIC_PREFLIGHT_TOP_N", 2)
    fetch_map = {
        BENCHMARK: _good_preflight_trades(BENCHMARK),
        **{
            f"0x{index + 1:040x}": _weak_preflight_trades(f"0x{index + 1:040x}")
            for index in range(20)
        },
    }
    monkeypatch.setattr(roster, "fetch_copyability_trades_for_wallet", _fake_fetch_copyability_trades_for_wallet_factory(fetch_map))

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=6,
        wallet_scores=[],
        shadow_rows=[],
        output_dir=base,
    )
    output = capsys.readouterr().out

    assert payload["diagnosticPreflightTopN"] == 2
    assert payload["diagnosticCandidatesAnalyzed"] == 2
    assert "SMART_MONEY_WALLET_ROSTER_DIAGNOSTIC_PREFLIGHT_STARTED topN=2" in output
    assert "SMART_MONEY_WALLET_ROSTER_DIAGNOSTIC_PREFLIGHT_COMPLETED analyzed=2" in output
    assert sum(1 for row in payload["rejectedWallets"] if row["diagnosticPreflightAnalyzed"]) == 2
    shutil.rmtree(base, ignore_errors=True)


def test_adaptive_signal_wallet_roster_uses_discovery_v2_candidate_pool(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_discovery_v2"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
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
            }
        ],
    )
    _write_json(base / "wallet_category_rankings.json", {})
    _write_history(base / "wallet_shadow_history.jsonl", [])
    _write_json(base / "wallet_copyability_summary.json", {})
    _write_json(base / "wallet_comparison_summary.json", {"comparisons": [], "sufficient": 0})
    _write_json(base / "trade_copyability_shadow.json", {"clusters": [], "walletResults": []})
    _write_json(base / "adaptive_signal_wallet_quality.json", {"wallets": [], "walletQualityRows": [], "walletResults": []})
    _write_json(
        base / "adaptive_signal_candidate_pool.json",
        {
            "generatedAt": "2026-06-29T00:00:00+00:00",
            "sourceStatus": "ok",
            "candidateCount": 2,
            "strongCandidateCount": 1,
            "watchlistCandidateCount": 0,
            "weakCandidateCount": 0,
            "rejectedCandidateCount": 1,
            "candidates": [
                {
                    "wallet": WALLETS["macro"],
                    "candidateQualityScore": 78,
                    "candidateRecommendation": "STRONG_CANDIDATE",
                    "discoverySources": ["wallet_shadow_rankings", "market_seeded_copyability"],
                    "sourceCount": 2,
                    "seenInPreviousRoster": False,
                    "candidateReasons": ["sufficient_recent_activity", "multi_market_activity"],
                    "candidateRisks": [],
                },
                {
                    "wallet": WALLETS["rejected"],
                    "candidateQualityScore": 14,
                    "candidateRecommendation": "REJECT",
                    "discoverySources": ["wallet_shadow_rankings"],
                    "sourceCount": 1,
                    "seenInPreviousRoster": True,
                    "candidateReasons": ["low_skill_score"],
                    "candidateRisks": ["previous_replace_candidate"],
                },
            ],
            "rejectedCandidates": [],
            "reasonSummary": {"sufficient_recent_activity": 1},
        },
    )

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")
    monkeypatch.setattr(roster, "SIGNAL_WALLET_DIAGNOSTIC_PREFLIGHT_TOP_N", 0)
    monkeypatch.setattr(
        roster,
        "fetch_copyability_trades_for_wallet",
        _fake_fetch_copyability_trades_for_wallet_factory(
            {
                WALLETS["macro"]: _good_preflight_trades(WALLETS["macro"]),
            }
        ),
    )

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=2,
        wallet_scores=[],
        shadow_rows=[],
        output_dir=base,
    )
    output = capsys.readouterr().out

    selected_wallets = [row["wallet"] for row in payload["selectedWallets"]]
    assert BENCHMARK in selected_wallets
    assert WALLETS["macro"] in selected_wallets
    assert WALLETS["rejected"] not in selected_wallets
    assert payload["discoveryV2Enabled"] is True
    assert payload["discoveryV2CandidateCount"] == 2
    assert payload["discoveryV2CandidatesUsed"] >= 1
    assert "SMART_MONEY_WALLET_ROSTER_DISCOVERY_V2_LOADED candidates=2" in output
    assert f"SMART_MONEY_WALLET_ROSTER_DISCOVERY_V2_USED wallet={WALLETS['macro']}" in output
    shutil.rmtree(base, ignore_errors=True)


def test_adaptive_signal_wallet_roster_prefers_copyability_seed_source_over_api(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_parity"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)

    _write_json(
        base / "wallet_shadow_rankings.json",
        [
            {
                "wallet": BENCHMARK,
                "displayName": "Ken",
                "roles": ["benchmark"],
                "profiles": ["mixed"],
                "classification": "WHALE_BUT_NOISY",
                "robustSkillScore": 75,
                "shadowRobustMetaScore": 69,
                "longitudinalComparisonScore": 61,
                "comparisonConfidence": "sufficient",
                "runCount": 6,
                "dominantKnownCategory": "geopolitics",
                "knownCategoryCoverageScore": 50,
                "pnlConcentrationLevel": "low",
                "recommendation": "shadow_watch",
                "rank": 1,
            },
            {
                "wallet": WALLETS["macro"],
                "displayName": "Macro Wallet",
                "roles": ["candidate"],
                "profiles": ["macro"],
                "classification": "SPECIALIST_WALLET",
                "robustSkillScore": 88,
                "shadowRobustMetaScore": 84,
                "longitudinalComparisonScore": 79,
                "comparisonConfidence": "sufficient",
                "runCount": 8,
                "dominantKnownCategory": "macro",
                "knownCategoryCoverageScore": 88,
                "pnlConcentrationLevel": "low",
                "recommendation": "shadow_strong",
                "rank": 2,
            },
        ],
    )
    _write_json(base / "wallet_category_rankings.json", {})
    _write_history(base / "wallet_shadow_history.jsonl", [])
    _write_json(base / "wallet_copyability_summary.json", {})
    _write_json(base / "wallet_comparison_summary.json", {"comparisons": [], "sufficient": 0})
    _write_json(base / "trade_copyability_shadow.json", {"clusters": [], "walletResults": []})

    async def fake_fetch_copyability_trades_for_wallet(wallet, limit, lookback_hours, *, return_details=False, **_kwargs):
        normalized = [_normalized_copyability_trade(wallet, market="m1", index=1, category="macro", size_usd=500)]
        payload = {
            "wallet": wallet,
            "status": "completed",
            "reason": "clusters_generated",
            "fetchSource": "wallet_api_fetch",
            "rawTrades": len(normalized),
            "normalizedTrades": len(normalized),
            "trades": normalized,
            "error": None,
        }
        return payload if return_details else normalized

    monkeypatch.setattr(roster, "fetch_copyability_trades_for_wallet", fake_fetch_copyability_trades_for_wallet)
    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")

    seed_trades = [_normalized_copyability_trade(BENCHMARK, market=f"m{i}", index=i, category="macro", size_usd=500) for i in range(1, 101)]
    seed_trades.append(_normalized_copyability_trade(WALLETS["macro"], market="m1", index=1, category="macro", size_usd=500))

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=2,
        wallet_scores=[],
        shadow_rows=[],
        copyability_seed_trades=seed_trades,
        output_dir=base,
    )
    output = capsys.readouterr().out

    assert len(payload["selectedWallets"]) == 1
    assert payload["selectedWallets"][0]["wallet"] == BENCHMARK
    assert "SMART_MONEY_WALLET_ROSTER_PREFLIGHT_SOURCE source=copyability_seed_trades" in output
    assert f"SMART_MONEY_WALLET_ROSTER_PREFLIGHT_COPYABILITY_PARITY wallet={WALLETS['macro']} preflightRaw=1 copyabilityRawEstimate=1" in output
    shutil.rmtree(base, ignore_errors=True)


def test_adaptive_signal_wallet_roster_skips_replacement_candidate_when_alternatives_exist(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_quality_skip"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _candidate_sources(base)
    _write_quality(
        base / "adaptive_signal_wallet_quality.json",
        [
            {
                "wallet": BENCHMARK,
                "actionableSignalScore": 88,
                "keepInRosterRecommendation": "KEEP_BENCHMARK",
                "routineClusterRate": 0.0,
                "microMarketClusterRate": 0.0,
            },
            *[
                {
                    "wallet": wallet,
                    "actionableSignalScore": 82,
                    "keepInRosterRecommendation": "KEEP_CANDIDATE",
                    "routineClusterRate": 0.1,
                    "microMarketClusterRate": 0.0,
                }
                for wallet in [WALLETS["macro"], WALLETS["politics"], WALLETS["geopolitics"], WALLETS["crypto"], WALLETS["technology"]]
            ],
            {
                "wallet": WALLETS["rejected"],
                "actionableSignalScore": 18,
                "keepInRosterRecommendation": "REPLACE_CANDIDATE",
                "routineClusterRate": 0.75,
                "microMarketClusterRate": 0.5,
            },
        ],
    )

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=6,
        wallet_scores=[],
        shadow_rows=[],
        output_dir=base,
    )
    output = capsys.readouterr().out

    selected_wallets = [row["wallet"] for row in payload["selectedWallets"]]
    assert len(selected_wallets) == 6
    assert BENCHMARK in selected_wallets
    assert WALLETS["rejected"] not in selected_wallets
    assert "SMART_MONEY_WALLET_ROSTER_QUALITY_FEEDBACK_LOADED rows=7" in output
    assert f"SMART_MONEY_WALLET_ROSTER_QUALITY_PENALTY wallet={WALLETS['rejected']} recommendation=REPLACE_CANDIDATE" in output
    assert f"SMART_MONEY_WALLET_ROSTER_REPLACE_CANDIDATE_SKIPPED wallet={WALLETS['rejected']}" in output
    rejected = next(row for row in payload["rejectedWallets"] if row["wallet"] == WALLETS["rejected"])
    assert rejected["previousQualityRecommendation"] == "REPLACE_CANDIDATE"
    assert rejected["qualityPenaltyApplied"] > 0
    shutil.rmtree(base, ignore_errors=True)


def test_adaptive_signal_wallet_roster_reuses_replacement_candidate_only_when_needed(monkeypatch, capsys):
    base = Path.cwd() / "tests" / "_adaptive_wallet_roster_tmp_quality_reuse"
    shutil.rmtree(base, ignore_errors=True)
    base.mkdir(parents=True, exist_ok=True)
    _write_json(
        base / "wallet_shadow_rankings.json",
        [
            {
                "wallet": BENCHMARK,
                "displayName": "Ken",
                "roles": ["benchmark"],
                "profiles": ["mixed"],
                "classification": "WHALE_BUT_NOISY",
                "robustSkillScore": 75,
                "shadowRobustMetaScore": 69,
                "longitudinalComparisonScore": 61,
                "comparisonConfidence": "sufficient",
                "runCount": 6,
                "dominantKnownCategory": "geopolitics",
                "knownCategoryCoverageScore": 50,
                "pnlConcentrationLevel": "low",
                "recommendation": "shadow_watch",
                "rank": 1,
            },
            {
                "wallet": WALLETS["macro"],
                "displayName": "Macro Wallet",
                "roles": ["candidate"],
                "profiles": ["macro"],
                "classification": "SPECIALIST_WALLET",
                "robustSkillScore": 88,
                "shadowRobustMetaScore": 84,
                "longitudinalComparisonScore": 79,
                "comparisonConfidence": "sufficient",
                "runCount": 8,
                "dominantKnownCategory": "macro",
                "knownCategoryCoverageScore": 88,
                "pnlConcentrationLevel": "low",
                "recommendation": "shadow_strong",
                "rank": 2,
            },
        ],
    )
    _write_json(base / "wallet_category_rankings.json", {})
    _write_history(base / "wallet_shadow_history.jsonl", [])
    _write_json(base / "wallet_copyability_summary.json", {})
    _write_json(base / "wallet_comparison_summary.json", {"comparisons": [], "sufficient": 0})
    _write_json(base / "trade_copyability_shadow.json", {"clusters": [], "walletResults": []})
    _write_quality(
        base / "adaptive_signal_wallet_quality.json",
        [
            {
                "wallet": BENCHMARK,
                "actionableSignalScore": 90,
                "keepInRosterRecommendation": "KEEP_BENCHMARK",
                "routineClusterRate": 0.0,
                "microMarketClusterRate": 0.0,
            },
            {
                "wallet": WALLETS["macro"],
                "actionableSignalScore": 18,
                "keepInRosterRecommendation": "REPLACE_CANDIDATE",
                "routineClusterRate": 0.7,
                "microMarketClusterRate": 0.4,
            },
        ],
    )

    monkeypatch.setattr(roster, "OUTPUT_DIR", base)
    monkeypatch.setattr(roster, "ADAPTIVE_SIGNAL_WALLET_ROSTER_FILE", base / "adaptive_signal_wallet_roster.json")

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=2,
        wallet_scores=[],
        shadow_rows=[],
        output_dir=base,
    )
    output = capsys.readouterr().out

    assert len(payload["selectedWallets"]) == 1
    assert len(payload["explorationWallets"]) == 1
    assert len(payload["walletsForCopyability"]) == 2
    selected = payload["explorationWallets"][0]
    assert selected["wallet"] == WALLETS["macro"]
    assert selected["probationaryCandidate"] is True
    assert selected["explorationReason"] == "fallback reused despite previous REPLACE_CANDIDATE"
    assert selected["previousQualityRecommendation"] == "REPLACE_CANDIDATE"
    assert selected["qualityPenaltyApplied"] > 0
    assert "SMART_MONEY_WALLET_ROSTER_REPLACE_CANDIDATE_SKIPPED wallet=" in output
    shutil.rmtree(base, ignore_errors=True)
