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


def _write_history(path: Path, rows: list[dict[str, object]]):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, ensure_ascii=False, default=str) for row in rows) + "\n", encoding="utf-8")


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

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=6,
        wallet_scores=[],
        shadow_rows=[],
        output_dir=base,
    )
    path = roster.write_adaptive_signal_wallet_roster(payload)

    assert path.exists()
    assert payload["benchmarkWallet"] == BENCHMARK
    assert payload["targetRosterSize"] == 6
    assert payload["candidatesFound"] >= 6
    assert len(payload["selectedWallets"]) == 6
    assert payload["selectedWallets"][0]["wallet"] == BENCHMARK
    assert payload["selectedWallets"][0]["isBenchmark"] is True
    assert payload["selectedWallets"][0]["signalWalletRosterScore"] == 100
    assert all(row["probationaryCandidate"] is False for row in payload["selectedWallets"][1:])
    assert any(row["wallet"] == WALLETS["rejected"] for row in payload["rejectedWallets"])
    rejected = next(row for row in payload["rejectedWallets"] if row["wallet"] == WALLETS["rejected"])
    assert rejected["rejectionReason"] in {"extreme hedge risk", "high concentration penalty", "low copyability", "lower signal score than selected roster", "stale activity verified"}
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

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=6,
        wallet_scores=[],
        shadow_rows=[],
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

    payload = roster.build_adaptive_signal_wallet_roster(
        benchmark_wallet=BENCHMARK,
        target_roster_size=2,
        wallet_scores=[],
        shadow_rows=[],
        output_dir=base,
    )

    macro = next(row for row in payload["selectedWallets"] if row["wallet"] == WALLETS["macro"])
    rejected = next(row for row in payload["rejectedWallets"] if row["wallet"] == WALLETS["rejected"])
    assert macro["signalWalletRosterScore"] > rejected["signalWalletRosterScore"]
    assert rejected["rejectionReason"] in {"extreme hedge risk", "high concentration penalty", "low copyability", "lower signal score than selected roster", "stale activity verified"}
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
    assert len(payload["selectedWallets"]) == 6
    assert payload["selectedWallets"][0]["wallet"] == BENCHMARK
    assert payload["selectedWallets"][0]["rank"] == 1
    assert payload["selectedWallets"][0]["probationaryCandidate"] is False
    assert all(row["probationaryCandidate"] is True for row in payload["selectedWallets"][1:])
    assert all(row["recentActivityStatus"] == "unknown" for row in payload["selectedWallets"][1:])
    assert any(row["staleActivityPenalty"] > 0 for row in payload["selectedWallets"][1:])
    assert any(row["insufficientSamplePenalty"] > 0 for row in payload["selectedWallets"][1:])
    assert payload["selectedWallets"][1]["signalWalletRosterScore"] < 35
    assert "SMART_MONEY_WALLET_ROSTER_FALLBACK_USED" in output
    assert "SMART_MONEY_WALLET_ROSTER_SELECTED count=6" in output
    shutil.rmtree(base, ignore_errors=True)
