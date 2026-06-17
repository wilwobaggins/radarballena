import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

from noise_filter import build_noise_profile
from wallet_classifier import classify_wallet


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def normalize_metric(value: float) -> float:
    return round(clamp(value, 0.0, 1.0), 4)


def compute_category_concentration(trades: list[dict[str, Any]]) -> tuple[float, str]:
    categories = [
        str(trade.get("category_guess") or "unknown")
        for trade in trades
        if trade.get("category_guess")
    ]

    if not categories:
        return 0.0, "unknown"

    counts = Counter(categories)
    dominant_category, dominant_count = counts.most_common(1)[0]
    return normalize_metric(safe_ratio(dominant_count, len(categories))), dominant_category


def compute_concentration_risk(
    trades: list[dict[str, Any]],
    category_concentration: float,
) -> float:
    if not trades:
        return 1.0

    market_counts = Counter(str(trade.get("market_id") or "unknown") for trade in trades)
    max_market_share = safe_ratio(max(market_counts.values()), len(trades))
    risk = 0.0

    if max_market_share > 0.35:
        risk += min(0.65, (max_market_share - 0.35) / 0.65)

    if category_concentration > 0.8:
        risk += min(0.35, (category_concentration - 0.8) / 0.2)

    return normalize_metric(min(1.0, risk))


def count_opposing_outcome_markets(trades: list[dict[str, Any]]) -> tuple[int, float]:
    by_market: dict[str, set[str]] = defaultdict(set)

    for trade in trades:
        market_id = trade.get("market_id")
        outcome = trade.get("outcome")
        if not market_id or outcome is None:
            continue
        by_market[str(market_id)].add(str(outcome).lower())

    opposing_markets = sum(1 for outcomes in by_market.values() if len(outcomes) >= 2)
    unique_markets = len(by_market)
    return opposing_markets, normalize_metric(safe_ratio(opposing_markets, unique_markets))


def performance_score(_metrics: dict[str, Any]) -> int:
    return 50


def timing_score(metrics: dict[str, Any]) -> int:
    score = 55 + (metrics["earlyEntryRatio"] * 40) - (metrics["lateEntryRatio"] * 45)
    return round(clamp(score))


def directional_clarity_score(metrics: dict[str, Any]) -> int:
    score = (
        82
        - (metrics["opposingOutcomeRatio"] * 60)
        - (metrics["sellRatio"] * 22)
        - (metrics["lateEntryRatio"] * 12)
    )
    return round(clamp(score))


def category_specialization_score(metrics: dict[str, Any]) -> int:
    concentration = metrics["categoryConcentration"]
    distance_from_target = abs(concentration - 0.62)
    score = 84 - (distance_from_target * 120)

    if metrics["uniqueMarkets"] < 3:
        score -= 20

    return round(clamp(score))


def size_score(metrics: dict[str, Any]) -> int:
    total_volume_component = min(65.0, math.log10(metrics["totalVolume"] + 1) * 16)
    avg_size_component = min(35.0, math.log10(metrics["avgSize"] + 1) * 12)
    return round(clamp(total_volume_component + avg_size_component))


def consistency_score(metrics: dict[str, Any]) -> int:
    score = (
        20
        + min(35.0, metrics["tradeCount"] * 2.1)
        + min(25.0, metrics["uniqueMarkets"] * 4.2)
        - (metrics["concentrationRisk"] * 35)
    )
    return round(clamp(score))


def anti_noise_score(metrics: dict[str, Any]) -> int:
    score = (
        100
        - (metrics["extremePriceRatio"] * 35)
        - (metrics["lateEntryRatio"] * 30)
        - (metrics["opposingOutcomeRatio"] * 55)
        - (metrics["concentrationRisk"] * 35)
    )
    return round(clamp(score))


def compute_sub_scores(metrics: dict[str, Any]) -> dict[str, int]:
    return {
        "performanceScore": performance_score(metrics),
        "timingScore": timing_score(metrics),
        "directionalClarityScore": directional_clarity_score(metrics),
        "categorySpecializationScore": category_specialization_score(metrics),
        "sizeScore": size_score(metrics),
        "consistencyScore": consistency_score(metrics),
        "antiNoiseScore": anti_noise_score(metrics),
    }


def compute_wallet_quality_score(sub_scores: dict[str, int]) -> int:
    score = (
        0.25 * sub_scores["performanceScore"]
        + 0.20 * sub_scores["timingScore"]
        + 0.15 * sub_scores["directionalClarityScore"]
        + 0.15 * sub_scores["categorySpecializationScore"]
        + 0.10 * sub_scores["sizeScore"]
        + 0.10 * sub_scores["consistencyScore"]
        + 0.05 * sub_scores["antiNoiseScore"]
    )
    return round(clamp(score))


def compute_wallet_scores(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trades:
        return []

    grouped_trades: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for trade in trades:
        wallet = trade.get("wallet")
        if not wallet:
            continue
        grouped_trades[str(wallet)].append(trade)

    generated_at = datetime.now(timezone.utc).isoformat()
    scored_wallets: list[dict[str, Any]] = []

    for wallet, wallet_trades in grouped_trades.items():
        trade_count = len(wallet_trades)
        total_volume = float(sum(float(trade.get("size_usd") or 0.0) for trade in wallet_trades))
        unique_markets = len(
            {
                str(trade.get("market_id"))
                for trade in wallet_trades
                if trade.get("market_id") is not None
            }
        )
        avg_size = safe_ratio(total_volume, trade_count)

        early_entry_ratio = safe_ratio(
            sum(1 for trade in wallet_trades if 0.05 < float(trade.get("price") or 0.0) < 0.65),
            trade_count,
        )
        late_entry_ratio = safe_ratio(
            sum(1 for trade in wallet_trades if float(trade.get("price") or 0.0) >= 0.85),
            trade_count,
        )
        extreme_price_ratio = safe_ratio(
            sum(
                1
                for trade in wallet_trades
                if float(trade.get("price") or 0.0) <= 0.05
                or float(trade.get("price") or 0.0) >= 0.95
            ),
            trade_count,
        )
        sell_ratio = safe_ratio(
            sum(1 for trade in wallet_trades if str(trade.get("side") or "").upper() == "SELL"),
            trade_count,
        )
        opposing_count, opposing_ratio = count_opposing_outcome_markets(wallet_trades)
        category_concentration, _dominant_category = compute_category_concentration(wallet_trades)
        concentration_risk = compute_concentration_risk(wallet_trades, category_concentration)

        metrics = {
            "totalVolume": round(total_volume, 2),
            "tradeCount": trade_count,
            "uniqueMarkets": unique_markets,
            "avgSize": round(avg_size, 2),
            "earlyEntryRatio": normalize_metric(early_entry_ratio),
            "lateEntryRatio": normalize_metric(late_entry_ratio),
            "opposingOutcomeRatio": opposing_ratio,
            "extremePriceRatio": normalize_metric(extreme_price_ratio),
            "sellRatio": normalize_metric(sell_ratio),
            "categoryConcentration": normalize_metric(category_concentration),
            "concentrationRisk": normalize_metric(concentration_risk),
        }

        sub_scores = compute_sub_scores(metrics)
        wallet_score = compute_wallet_quality_score(sub_scores)
        noise_profile = build_noise_profile(wallet_trades, metrics)
        record = {
            "wallet": wallet,
            "walletQualityScore": wallet_score,
            "classification": "INSUFFICIENT_HISTORY",
            "metrics": metrics,
            "subScores": sub_scores,
            "noiseScore": noise_profile["noiseScore"],
            "noiseLevel": noise_profile["noiseLevel"],
            "riskFlags": [],
            "generatedAt": generated_at,
            "opposingMarketCount": opposing_count,
        }
        legacy_flags: list[str] = []
        if metrics["tradeCount"] < 6:
            legacy_flags.append("low_trade_count")
        if metrics["uniqueMarkets"] < 3:
            legacy_flags.append("low_market_diversity")
        if metrics["sellRatio"] >= 0.55:
            legacy_flags.append("sell_heavy")
        if sub_scores["antiNoiseScore"] < 45:
            legacy_flags.append("high_noise_profile")

        combined_flags: list[str] = []
        for flag in [*legacy_flags, *noise_profile["riskFlags"]]:
            if flag not in combined_flags:
                combined_flags.append(flag)

        record["riskFlags"] = combined_flags
        record["classification"] = classify_wallet(record)
        scored_wallets.append(record)

    cleaned_wallets = []
    for record in scored_wallets:
        cleaned_wallets.append(
            {
                "wallet": record["wallet"],
                "walletQualityScore": record["walletQualityScore"],
                "classification": record["classification"],
                "metrics": record["metrics"],
                "subScores": record["subScores"],
                "noiseScore": record["noiseScore"],
                "noiseLevel": record["noiseLevel"],
                "riskFlags": record["riskFlags"],
                "generatedAt": record["generatedAt"],
            }
        )

    return sorted(
        cleaned_wallets,
        key=lambda item: (item["walletQualityScore"], item["metrics"]["totalVolume"]),
        reverse=True,
    )
