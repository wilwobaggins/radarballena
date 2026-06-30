from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from workers.smart_money.smart_money_engine import adaptive_wallet_quality as quality


BENCHMARK = "0x9d84ce0306f8551e02efef1680475fc0f1dc1344"
GOOD = "0x" + "1" * 40
RUTINE = "0x" + "2" * 40


def _cluster(
    wallet: str,
    *,
    score: float,
    label: str,
    status: str,
    title: str,
    category: str = "macro",
    size_usd: float = 500.0,
    duration_minutes: int = 120,
    hedge_probability: float = 10.0,
    detection_score: float | None = None,
):
    return {
        "wallet": wallet,
        "marketTitle": title,
        "category": category,
        "tradeCount": 3,
        "durationMinutes": duration_minutes,
        "totalSizeUsd": size_usd,
        "relativeConvictionScore": 70,
        "accumulationScore": 75,
        "hedgeProbability": hedge_probability,
        "walletCategorySkillScore": 75,
        "robustSkillScore": 72,
        "entryContextStatus": "available",
        "priceHistoryStatus": "available",
        "validationStatus": "complete",
        "copyabilityAtDetectionScore": score,
        "copyabilityValidatedScore": score - 3,
        "copyabilityLabel": label,
        "copyabilityStatus": status,
        "detectionScore": detection_score if detection_score is not None else score + 200,
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


def test_build_adaptive_signal_wallet_quality_uses_copyability_score_and_detects_micro_markets(capsys):
    copyability_phase = {
        "runId": "run-quality",
        "walletResults": [
            {"wallet": BENCHMARK, "rawTrades": 4, "normalizedTrades": 4, "clusters": 1, "reason": "clusters_generated"},
            {"wallet": GOOD, "rawTrades": 6, "normalizedTrades": 6, "clusters": 3, "reason": "clusters_generated"},
            {"wallet": RUTINE, "rawTrades": 8, "normalizedTrades": 8, "clusters": 4, "reason": "no_clusters_after_filters"},
        ],
        "clusters": [
            _cluster(
                BENCHMARK,
                score=82,
                label="ACUMULACION",
                status="high_copyability",
                title="Geopolitics event",
                category="geopolitics",
                size_usd=1200,
                duration_minutes=180,
            ),
            _cluster(
                GOOD,
                score=90,
                label="ALTA_CONVICCION",
                status="high_copyability",
                title="Macro futures event",
                category="macro",
                size_usd=1500,
                duration_minutes=240,
                detection_score=999,
            ),
            _cluster(
                GOOD,
                score=80,
                label="ACUMULACION",
                status="watch_copyability",
                title="Politics future event",
                category="politics",
                size_usd=1000,
                duration_minutes=180,
                detection_score=888,
            ),
            _cluster(
                GOOD,
                score=70,
                label="ACTIVIDAD_RUTINARIA",
                status="watch_copyability",
                title="Geopolitics future event",
                category="geopolitics",
                size_usd=900,
                duration_minutes=120,
                detection_score=777,
            ),
            _cluster(
                RUTINE,
                score=20,
                label="ACTIVIDAD_RUTINARIA",
                status="low_copyability",
                title="Bitcoin Up or Down - June 29, 4:50PM-4:55PM ET",
                category="crypto",
                size_usd=75,
                duration_minutes=5,
                hedge_probability=15,
                detection_score=666,
            ),
            _cluster(
                RUTINE,
                score=30,
                label="ACTIVIDAD_RUTINARIA",
                status="low_copyability",
                title="Routine macro market",
                category="unknown",
                size_usd=80,
                duration_minutes=8,
                hedge_probability=80,
            ),
            _cluster(
                RUTINE,
                score=28,
                label="ACTIVIDAD_RUTINARIA",
                status="low_copyability",
                title="Routine macro market 2",
                category="unknown",
                size_usd=70,
                duration_minutes=8,
                hedge_probability=85,
            ),
            _cluster(
                RUTINE,
                score=26,
                label="COBERTURA_NO_COPIABLE",
                status="not_copyable",
                title="Routine hedge market",
                category="unknown",
                size_usd=60,
                duration_minutes=6,
                hedge_probability=95,
            ),
            _cluster(
                RUTINE,
                score=24,
                label="ACTIVIDAD_RUTINARIA",
                status="low_copyability",
                title="Routine market 4",
                category="unknown",
                size_usd=55,
                duration_minutes=6,
                hedge_probability=10,
            ),
            _cluster(
                RUTINE,
                score=23,
                label="COBERTURA_NO_COPIABLE",
                status="not_copyable",
                title="Routine hedge market duplicate",
                category="unknown",
                size_usd=65,
                duration_minutes=6,
                hedge_probability=92,
            ),
        ],
    }

    wallet_roster = {
        "selectedWallets": [
            {"wallet": BENCHMARK, "displayName": "Ken", "isBenchmark": True, "probationaryCandidate": False},
            {"wallet": GOOD, "displayName": "Good Wallet", "isBenchmark": False, "probationaryCandidate": False},
            {"wallet": RUTINE, "displayName": "Routine Wallet", "isBenchmark": False, "probationaryCandidate": True},
        ]
    }

    payload = quality.build_adaptive_signal_wallet_quality(
        copyability_phase=copyability_phase,
        wallet_roster=wallet_roster,
        benchmark_wallet=BENCHMARK,
        output_dir=Path("ignored"),
    )

    captured = capsys.readouterr().out
    assert "SMART_MONEY_WALLET_QUALITY_SUMMARY wallet=0x" in captured
    rows = payload["walletQualityRows"]
    assert len(rows) == 3
    assert payload["wallets"] == rows
    assert payload["walletResults"] == rows

    benchmark_row = next(row for row in rows if row["wallet"] == BENCHMARK)
    good_row = next(row for row in rows if row["wallet"] == GOOD)
    routine_row = next(row for row in rows if row["wallet"] == RUTINE)

    assert benchmark_row["keepInRosterRecommendation"] == "KEEP_BENCHMARK"
    assert good_row["highCopyabilityCount"] == 1
    assert good_row["watchCopyabilityCount"] == 2
    assert good_row["accumulationCount"] == 1
    assert good_row["actionableClusterCount"] > good_row["highCopyabilityCount"]
    assert good_row["averageCopyabilityAtDetectionScore"] == 80.0
    assert good_row["medianCopyabilityAtDetectionScore"] == 80
    assert good_row["microMarketClusterCount"] == 0
    assert good_row["microMarketPenalty"] == 0
    assert good_row["keepInRosterRecommendation"] == "KEEP_CANDIDATE"
    assert routine_row["routineActivityCount"] >= 3
    assert routine_row["microMarketClusterCount"] == 1
    assert routine_row["microMarketPenalty"] > 0
    assert routine_row["keepInRosterRecommendation"] in {"WATCHLIST", "REPLACE_CANDIDATE"}
    assert routine_row["unknownCategoryPenalty"] > 0
    assert routine_row["notCopyableCount"] == 2
    assert good_row["bestCategory"] in {"macro", "politics"}
    _assert_no_nan_or_infinity(payload)


def test_write_adaptive_signal_wallet_quality_writes_json(monkeypatch):
    output_dir = Path.cwd() / "tests" / "_adaptive_wallet_quality_tmp" / "outputs"
    shutil.rmtree(output_dir.parent, ignore_errors=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(quality, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(quality, "ADAPTIVE_SIGNAL_WALLET_QUALITY_FILE", output_dir / "adaptive_signal_wallet_quality.json")

    payload = {
        "runId": "run-1",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "benchmarkWallet": BENCHMARK,
        "walletCount": 1,
        "walletQualityRows": [
            {
                "wallet": BENCHMARK,
                "displayName": "Ken",
                "clustersCount": 1,
                "highCopyabilityCount": 1,
                "watchCopyabilityCount": 0,
                "accumulationCount": 1,
                "reductionSignalCount": 0,
                "routineActivityCount": 0,
                "notCopyableCount": 0,
                "hedgeRate": 0.0,
                "averageCopyabilityAtDetectionScore": 82.0,
                "medianCopyabilityAtDetectionScore": 82.0,
                "bestCategory": "macro",
                "actionableClusterCount": 1,
                "actionableClusterRate": 1.0,
                "routineClusterRate": 0.0,
                "microMarketClusterCount": 0,
                "microMarketClusterRate": 0.0,
                "strategicMarketClusterCount": 1,
                "strategicMarketRate": 1.0,
                "microMarketPenalty": 0.0,
                "routinePenalty": 0.0,
                "hedgePenalty": 0.0,
                "unknownCategoryPenalty": 0.0,
                "actionableSignalScore": 91.0,
                "keepInRosterRecommendation": "KEEP_BENCHMARK",
            }
        ],
        "wallets": [
            {
                "wallet": BENCHMARK,
                "displayName": "Ken",
                "clustersCount": 1,
                "highCopyabilityCount": 1,
                "watchCopyabilityCount": 0,
                "accumulationCount": 1,
                "reductionSignalCount": 0,
                "routineActivityCount": 0,
                "notCopyableCount": 0,
                "hedgeRate": 0.0,
                "averageCopyabilityAtDetectionScore": 82.0,
                "medianCopyabilityAtDetectionScore": 82.0,
                "bestCategory": "macro",
                "actionableClusterCount": 1,
                "actionableClusterRate": 1.0,
                "routineClusterRate": 0.0,
                "microMarketClusterCount": 0,
                "microMarketClusterRate": 0.0,
                "strategicMarketClusterCount": 1,
                "strategicMarketRate": 1.0,
                "microMarketPenalty": 0.0,
                "routinePenalty": 0.0,
                "hedgePenalty": 0.0,
                "unknownCategoryPenalty": 0.0,
                "actionableSignalScore": 91.0,
                "keepInRosterRecommendation": "KEEP_BENCHMARK",
            }
        ],
        "walletResults": [],
    }

    written_path = quality.write_adaptive_signal_wallet_quality(payload)
    assert written_path.exists()
    written = json.loads(written_path.read_text(encoding="utf-8"))
    assert written["walletCount"] == 1
    assert written["wallets"] == written["walletQualityRows"]
    assert written["walletResults"] == written["walletQualityRows"]
    assert written["walletQualityRows"][0]["keepInRosterRecommendation"] == "KEEP_BENCHMARK"
    _assert_no_nan_or_infinity(written)

    shutil.rmtree(output_dir.parent, ignore_errors=True)
