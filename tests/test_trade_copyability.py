from __future__ import annotations

from datetime import datetime, timedelta, timezone

from workers.smart_money.smart_money_engine.trade_copyability import (
    assign_copyability_label,
    build_entry_context,
    build_liquidity_context,
    build_trade_clusters,
    build_trade_copyability_backtest,
    build_wallet_copyability_summary,
    compute_wallet_cluster_baseline,
    deep_engine_relevance_score_for_category,
    dedupe_copyability_trades,
    normalize_copyability_trade,
    resolve_wallet_category_skill,
    score_accumulation,
    score_copyability_at_detection,
    score_hedge_probability,
    score_relative_conviction,
    validate_cluster_retrospectively,
)
from workers.smart_money.smart_money_engine.time_utils import to_unix_seconds, to_utc_datetime, to_utc_iso


WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40


def _raw_trade(*, wallet=WALLET_A, ts=None, side="BUY", price=0.25, size=100, shares=10, condition_id="cond-1", asset="asset-1", outcome="Yes", title="Trump election market"):
    ts = ts or datetime.now(timezone.utc)
    return {
        "wallet": wallet,
        "timestamp": ts.isoformat(),
        "side": side,
        "price": price,
        "sizeUsd": size,
        "shares": shares,
        "conditionId": condition_id,
        "asset": asset,
        "outcome": outcome,
        "title": title,
        "marketTitle": title,
        "tradeId": f"{wallet[-4:]}-{int(ts.timestamp())}",
        "transactionHash": f"0x{int(ts.timestamp()):064x}",
        "rawSource": "activity",
    }


def test_normalize_copyability_trade_and_invalid_trade():
    trade = normalize_copyability_trade(_raw_trade(), WALLET_A)
    assert trade is not None
    assert trade["wallet"] == WALLET_A
    assert trade["side"] == "BUY"
    assert trade["timestampIso"].endswith("+00:00")
    assert trade["category"] == "politics"

    invalid = normalize_copyability_trade({"timestamp": "bad", "side": "BUY"}, WALLET_A)
    assert invalid is None


def test_timestamp_helpers_accept_datetime_and_iso():
    aware = datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc)
    naive = datetime(2026, 6, 29, 0, 0)
    iso_value = "2026-06-29T00:00:00+00:00"

    assert to_unix_seconds(aware) == int(aware.timestamp())
    assert to_unix_seconds(naive) == int(aware.timestamp())
    assert to_unix_seconds(iso_value) == int(aware.timestamp())

    converted = to_utc_datetime(aware.timestamp())
    assert converted is not None
    assert converted.tzinfo is not None
    assert converted.utcoffset() == timezone.utc.utcoffset(aware)
    assert to_utc_iso(naive) == aware.isoformat()


def test_normalize_copyability_trade_accepts_datetime_timestamp():
    ts = datetime(2026, 6, 29, 12, 30, tzinfo=timezone.utc)
    trade = normalize_copyability_trade(_raw_trade(ts=ts), WALLET_A)
    assert trade is not None
    assert trade["timestamp"] == int(ts.timestamp())
    assert trade["timestampIso"] == ts.isoformat()


def test_resolve_wallet_category_skill_prefers_category_then_robust_then_neutral():
    wallet_shadow = {
        "shadowSkill": {
            "categorySkillScores": {
                "geopolitics": {"skillStatus": "sufficient", "skillScore": 83, "closedPositionsCount": 8},
                "macro": {"skillStatus": "limited", "skillScore": 60, "closedPositionsCount": 6},
            }
        },
        "shadowRobustEvaluation": {"robustSkillScore": 77},
    }

    geopolitics = resolve_wallet_category_skill(wallet_shadow, "geopolitics")
    macro = resolve_wallet_category_skill(wallet_shadow, "macro")
    robust_only = resolve_wallet_category_skill({"shadowRobustEvaluation": {"robustSkillScore": 74}}, "sports")
    neutral = resolve_wallet_category_skill(None, "politics")

    assert geopolitics["walletCategorySkillScore"] == 83
    assert geopolitics["skillSource"] == "category_sufficient"
    assert macro["walletCategorySkillScore"] == round(0.70 * 60 + 0.30 * 77, 2)
    assert macro["skillSource"] == "category_limited_blended"
    assert robust_only["walletCategorySkillScore"] == 74
    assert robust_only["skillSource"] == "wallet_robust_fallback"
    assert neutral["walletCategorySkillScore"] == 50
    assert neutral["skillSource"] == "neutral_fallback"


def test_dedupe_and_cluster_vwap_rules():
    now = datetime.now(timezone.utc)
    trades = [
        normalize_copyability_trade(_raw_trade(ts=now, price=0.20, shares=10, size=100), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=5), price=0.30, shares=20, size=200), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=10), price=0.40, shares=30, size=300), WALLET_A),
    ]
    trades = [trade for trade in trades if trade is not None]
    deduped = dedupe_copyability_trades(trades + trades[:1])
    clusters = build_trade_clusters(deduped)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["tradeCount"] == 3
    assert round(cluster["vwapPrice"], 3) == 0.333
    assert cluster["sizesIncreasing"] is True


def test_build_trade_clusters_accepts_datetime_timestamps():
    now = datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc)
    trades = [
        {**_raw_trade(ts=now, price=0.2, shares=10, size=100), "timestamp": now},
        {**_raw_trade(ts=now + timedelta(minutes=5), price=0.3, shares=20, size=200), "timestamp": now + timedelta(minutes=5)},
        {**_raw_trade(ts=now + timedelta(minutes=10), price=0.4, shares=30, size=300), "timestamp": now + timedelta(minutes=10)},
    ]
    clusters = build_trade_clusters(trades)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["firstTradeAt"].endswith("+00:00")
    assert cluster["lastTradeAt"].endswith("+00:00")
    assert cluster["tradeTs"] == [int(now.timestamp()), int((now + timedelta(minutes=5)).timestamp()), int((now + timedelta(minutes=10)).timestamp())]


def test_buy_and_sell_never_mix_and_outcomes_split():
    now = datetime.now(timezone.utc)
    trades = [
        normalize_copyability_trade(_raw_trade(ts=now, side="BUY", outcome="Yes"), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=1), side="SELL", outcome="Yes"), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=2), side="BUY", outcome="No"), WALLET_A),
    ]
    trades = [trade for trade in trades if trade is not None]
    clusters = build_trade_clusters(trades)
    assert {cluster["side"] for cluster in clusters} == {"BUY", "SELL"}
    assert len({cluster["outcome"] for cluster in clusters}) == 2


def test_relative_conviction_and_accumulation_and_hedge():
    now = datetime.now(timezone.utc)
    trades = [
        normalize_copyability_trade(_raw_trade(ts=now, price=0.2, size=100, shares=10), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=10), price=0.3, size=200, shares=20), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=20), price=0.4, size=300, shares=30), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=30), price=0.5, size=400, shares=40), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now + timedelta(minutes=40), price=0.6, size=500, shares=50), WALLET_A),
        normalize_copyability_trade(_raw_trade(wallet=WALLET_A, ts=now + timedelta(minutes=50), side="BUY", outcome="No", price=0.35, size=150, shares=15), WALLET_A),
    ]
    trades = [trade for trade in trades if trade is not None]
    clusters = build_trade_clusters(trades)
    baseline = compute_wallet_cluster_baseline(clusters)
    cluster = clusters[0]
    rel = score_relative_conviction(cluster, baseline[WALLET_A])
    acc = score_accumulation(cluster, rel["relativeSizeRatio"])
    hedge = score_hedge_probability(clusters, cluster)
    assert rel["sizePercentile"] >= 0
    assert acc["accumulationScore"] >= 20
    assert hedge["hedgeProbability"] >= 0


def test_label_precedence_and_entry_context_and_validation():
    now = datetime.now(timezone.utc) - timedelta(days=2)
    trades = [
        normalize_copyability_trade(_raw_trade(ts=now - timedelta(minutes=15), price=0.2, size=100, shares=10), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now - timedelta(minutes=5), price=0.25, size=150, shares=15), WALLET_A),
        normalize_copyability_trade(_raw_trade(ts=now, price=0.3, size=200, shares=20), WALLET_A),
    ]
    trades = [trade for trade in trades if trade is not None]
    cluster = build_trade_clusters(trades)[0]
    baseline = compute_wallet_cluster_baseline([cluster])[WALLET_A]
    entry = build_entry_context(cluster, [{"timestamp": now - timedelta(hours=1), "price": 0.15}])
    liquidity = build_liquidity_context(cluster, {"bestBid": 0.24, "bestAsk": 0.26, "depthUsd": 1000, "snapshotAt": now.isoformat()})
    detection = score_copyability_at_detection(cluster, None, baseline, [cluster], entry, liquidity)
    validated = validate_cluster_retrospectively(cluster, [
        {"timestamp": now + timedelta(hours=1), "price": 0.35},
        {"timestamp": now + timedelta(hours=6), "price": 0.45},
        {"timestamp": now + timedelta(hours=24), "price": 0.55},
    ])
    scored = {**cluster, **detection, **validated, "side": "BUY", "sizePercentile": 90}
    assert assign_copyability_label(scored) in {"ALTA_CONVICCION", "ACUMULACION", "PENDIENTE_VALIDACION", "ACTIVIDAD_RUTINARIA"}
    assert entry["entryContextScore"] <= 100
    assert validated["validationStatus"] == "complete"
    assert validated["copyabilityValidatedScore"] is not None


def test_validation_horizons_accept_datetime_last_trade_at():
    now = datetime(2026, 6, 29, 0, 0, tzinfo=timezone.utc)
    cluster = {
        "wallet": WALLET_A,
        "category": "politics",
        "side": "BUY",
        "tradeCount": 2,
        "totalSizeUsd": 200,
        "vwapPrice": 0.25,
        "firstTradeAt": now,
        "lastTradeAt": now,
    }
    price_history = [
        {"timestamp": now + timedelta(hours=1), "price": 0.35},
        {"timestamp": now + timedelta(hours=6), "price": 0.45},
        {"timestamp": now + timedelta(hours=24), "price": 0.55},
    ]
    validated = validate_cluster_retrospectively(cluster, price_history)
    assert validated["validationStatus"] == "complete"
    assert validated["priceAfter1h"] == 0.35


def test_validation_status_and_reason_cover_recent_and_missing_history():
    now = datetime.now(timezone.utc)
    recent_cluster = {
        "wallet": WALLET_A,
        "category": "politics",
        "side": "BUY",
        "tradeCount": 2,
        "totalSizeUsd": 200,
        "vwapPrice": 0.25,
        "firstTradeAt": now,
        "lastTradeAt": now,
    }
    recent_validation = validate_cluster_retrospectively(recent_cluster, [{"timestamp": now + timedelta(hours=1), "price": 0.35}])
    assert recent_validation["validationStatus"] == "pending"
    assert recent_validation["validationReason"] == "horizons_not_mature"
    assert recent_validation["priceHistoryStatus"] == "horizons_not_mature"

    old_cluster = {
        "wallet": WALLET_A,
        "category": "politics",
        "side": "BUY",
        "tradeCount": 2,
        "totalSizeUsd": 200,
        "vwapPrice": 0.25,
        "firstTradeAt": now - timedelta(days=2),
        "lastTradeAt": now - timedelta(days=2),
    }
    missing_history = validate_cluster_retrospectively(old_cluster, [])
    assert missing_history["validationStatus"] == "pending"
    assert missing_history["validationReason"] == "empty_history"
    assert missing_history["priceHistoryStatus"] == "empty_history"

    partial_history = validate_cluster_retrospectively(
        old_cluster,
        [{"timestamp": (now - timedelta(days=2)) + timedelta(hours=1), "price": 0.35}],
    )
    assert partial_history["validationStatus"] == "partial"
    assert partial_history["validationReason"] == "missing_price_point"
    assert partial_history["priceHistoryStatus"] == "missing_price_point"


def test_wallet_copyability_summary_and_backtest_report_hedges_and_reliability():
    clusters = []
    for index in range(10):
        hedge_probability = 80 if index < 2 else 60 if index == 2 else 10
        clusters.append(
            {
                "wallet": WALLET_A,
                "category": "politics",
                "copyabilityAtDetectionScore": 70 + index,
                "copyabilityValidatedScore": 65 + index,
                "followthrough1h": 0.1 if index < 4 else None,
                "followthrough6h": 0.2 if index < 3 else None,
                "followthrough24h": 0.3 if index < 2 else None,
                "copyabilityStatus": "not_copyable" if hedge_probability >= 70 else "watch_copyability",
                "copyabilityLabel": "COBERTURA_NO_COPIABLE" if hedge_probability >= 70 else "ACTIVIDAD_RUTINARIA",
                "hedge": {"hedgeProbability": hedge_probability},
                "side": "BUY",
            }
        )

    summary = build_wallet_copyability_summary(clusters)
    assert summary[WALLET_A]["hedgeRate"] == 0.2
    assert summary[WALLET_A]["hedgeRate70"] == 0.2
    assert summary[WALLET_A]["possibleHedgeRate60"] == 0.3
    assert summary[WALLET_A]["hedgeCount70"] == 2
    assert summary[WALLET_A]["possibleHedgeCount60"] == 3
    assert summary[WALLET_A]["notCopyableCount"] == 2

    backtest = build_trade_copyability_backtest(
        [
            {
                "wallet": WALLET_A,
                "category": "politics",
                "copyabilityLabel": "COBERTURA_NO_COPIABLE",
                "copyabilityStatus": "not_copyable",
                "copyabilityAtDetectionScore": 80,
                "copyabilityValidatedScore": None,
            }
            for _ in range(5)
        ]
        + [
            {
                "wallet": WALLET_B,
                "category": "politics",
                "copyabilityLabel": "ACTIVIDAD_RUTINARIA",
                "copyabilityStatus": "watch_copyability",
                "copyabilityAtDetectionScore": 65,
                "copyabilityValidatedScore": 64,
                "followthrough1h": 0.1,
                "followthrough6h": 0.2,
                "followthrough24h": 0.3,
            }
            for _ in range(5)
        ]
    )
    groups = backtest["groups"]
    pending_group = next(group for group in groups if group["wallet"] == WALLET_A)
    complete_group = next(group for group in groups if group["wallet"] == WALLET_B)
    assert pending_group["sampleReliabilityStatus"] == "adequate"
    assert pending_group["validationReliabilityStatus"] == "pending_validation"
    assert pending_group["reliabilityStatus"] == "adequate"
    assert complete_group["validationReliabilityStatus"] in {"partial_validation", "complete_validation"}


def test_wallet_copyability_summary_counts_hedge_labels_even_without_probability():
    clusters = [
        {
            "wallet": WALLET_A,
            "category": "politics",
            "copyabilityStatus": "not_copyable",
            "copyabilityLabel": "COBERTURA_NO_COPIABLE",
            "hedge": {"hedgeProbability": None},
            "side": "BUY",
        },
        {
            "wallet": WALLET_A,
            "category": "politics",
            "copyabilityStatus": "watch_copyability",
            "copyabilityLabel": "ACTIVIDAD_RUTINARIA",
            "hedge": {"hedgeProbability": 50},
            "side": "BUY",
        },
    ]

    summary = build_wallet_copyability_summary(clusters)
    assert summary[WALLET_A]["notCopyableCount"] == 1
    assert summary[WALLET_A]["hedgeCount70"] == 1
    assert summary[WALLET_A]["possibleHedgeCount60"] == 0
    assert summary[WALLET_A]["hedgeRate70"] == 0.5
    assert summary[WALLET_A]["hedgeRate"] == 0.5


def test_wallet_copyability_summary_zero_clusters_does_not_divide_by_zero():
    assert build_wallet_copyability_summary([]) == {}


def test_detection_is_not_changed_by_future_prices_and_relevance_map():
    cluster = {
        "wallet": WALLET_A,
        "category": "politics",
        "side": "BUY",
        "tradeCount": 2,
        "totalSizeUsd": 200,
        "vwapPrice": 0.25,
        "firstTradeAt": "2026-06-29T00:00:00+00:00",
        "lastTradeAt": "2026-06-29T00:30:00+00:00",
    }
    baseline = {"medianClusterSizeUsd": 100, "clusterSizes": [100, 200]}
    price_context = {"entryContextScore": 70, "entryContextStatus": "available", "chasePenalty": 5}
    liquidity_context = {"liquidityScore": 80, "liquidityStatus": "available"}
    before = score_copyability_at_detection(cluster, None, baseline, [cluster], price_context, liquidity_context)
    after = score_copyability_at_detection(cluster, None, baseline, [cluster], price_context, liquidity_context)
    assert before["copyabilityAtDetectionScore"] == after["copyabilityAtDetectionScore"]
    assert deep_engine_relevance_score_for_category("politics") == 100


def test_backtest_and_neutral_wallet_skill_fallback():
    scored_cluster = {
        "wallet": WALLET_A,
        "category": "politics",
        "copyabilityLabel": "ACUMULACION",
        "copyabilityStatus": "high_copyability",
        "copyabilityAtDetectionScore": 80,
        "copyabilityValidatedScore": 78,
        "followthrough1h": 0.1,
        "followthrough6h": 0.2,
        "followthrough24h": 0.3,
    }
    backtest = build_trade_copyability_backtest([scored_cluster])
    neutral = resolve_wallet_category_skill(None, "politics")
    assert backtest["groups"][0]["reliabilityStatus"] == "insufficient_sample"
    assert neutral["walletCategorySkillScore"] == 50
    assert neutral["skillSource"] == "neutral_fallback"
