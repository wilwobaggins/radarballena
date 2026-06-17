import math
from collections import defaultdict
from typing import Any


LOW_NOISE = "LOW_NOISE"
MEDIUM_NOISE = "MEDIUM_NOISE"
HIGH_NOISE = "HIGH_NOISE"


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def normalize_metric(value: float) -> float:
    return round(clamp(value, 0.0, 1.0), 4)


def _normalize_outcome(value: Any) -> str | None:
    outcome = str(value or "").strip().lower()
    if outcome in {"yes", "y", "1", "true"}:
        return "yes"
    if outcome in {"no", "n", "0", "false"}:
        return "no"
    return None


def _normalize_side(value: Any) -> str | None:
    side = str(value or "").strip().upper()
    if side in {"BUY", "SELL"}:
        return side
    return None


def _direction_from_trade(trade: dict[str, Any]) -> str | None:
    side = _normalize_side(trade.get("side"))
    outcome = _normalize_outcome(trade.get("outcome"))

    if side == "BUY" and outcome == "yes":
        return "yes"
    if side == "SELL" and outcome == "no":
        return "yes"
    if side == "BUY" and outcome == "no":
        return "no"
    if side == "SELL" and outcome == "yes":
        return "no"
    return None


def _market_trade_profile(trades: list[dict[str, Any]]) -> dict[str, Any]:
    by_market: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "directions": set(),
            "buy_outcomes": set(),
            "outcome_sides": defaultdict(set),
        }
    )

    for trade in trades:
        market_id = trade.get("market_id")
        if not market_id:
            continue

        market_key = str(market_id)
        profile = by_market[market_key]

        direction = _direction_from_trade(trade)
        if direction:
            profile["directions"].add(direction)

        side = _normalize_side(trade.get("side"))
        outcome = _normalize_outcome(trade.get("outcome"))
        if side and outcome:
            profile["outcome_sides"][outcome].add(side)
            if side == "BUY":
                profile["buy_outcomes"].add(outcome)

    unique_markets = len(by_market)
    opposing_markets = 0
    directional_contradiction_markets = 0
    possible_hedge_markets = 0

    for profile in by_market.values():
        if len(profile["directions"]) >= 2:
            opposing_markets += 1

        if {"yes", "no"}.issubset(profile["buy_outcomes"]):
            directional_contradiction_markets += 1

        # BUY/SELL on the same outcome can be a hedge, exit, or market-making;
        # keep this signal weak and conservative in v1.
        if any(len(sides) >= 2 for sides in profile["outcome_sides"].values()):
            possible_hedge_markets += 1

    return {
        "uniqueMarkets": unique_markets,
        "opposingOutcomeRatio": normalize_metric(
            safe_ratio(opposing_markets, unique_markets)
        ),
        "directionalContradictionRatio": normalize_metric(
            safe_ratio(directional_contradiction_markets, unique_markets)
        ),
        "possibleHedgeRatio": normalize_metric(
            safe_ratio(possible_hedge_markets, unique_markets)
        ),
        "opposingMarketCount": opposing_markets,
        "directionalContradictionMarketCount": directional_contradiction_markets,
        "possibleHedgeMarketCount": possible_hedge_markets,
    }


def _category_randomness_score(metrics: dict[str, Any], trades: list[dict[str, Any]]) -> float:
    categories = [
        str(trade.get("category_guess") or "unknown").strip().lower()
        for trade in trades
        if str(trade.get("category_guess") or "").strip()
    ]

    if not categories:
        return 0.0

    unique_categories = len(set(categories))
    if unique_categories < 4 or metrics["tradeCount"] < 10:
        return 0.0

    return normalize_metric(1.0 - metrics["categoryConcentration"])


def _micro_trade_spam_score(trades: list[dict[str, Any]], metrics: dict[str, Any]) -> float:
    if metrics["tradeCount"] < 8:
        return 0.0

    small_trade_threshold = 375.0
    small_trade_count = sum(
        1 for trade in trades if float(trade.get("size_usd") or 0.0) <= small_trade_threshold
    )
    return normalize_metric(safe_ratio(small_trade_count, metrics["tradeCount"]))


def _noise_level(noise_score: int) -> str:
    if noise_score >= 60:
        return HIGH_NOISE
    if noise_score >= 30:
        return MEDIUM_NOISE
    return LOW_NOISE


def build_noise_profile(trades: list[dict[str, Any]], metrics: dict[str, Any]) -> dict[str, Any]:
    if not trades:
        return {
            "noiseScore": 0,
            "noiseLevel": LOW_NOISE,
            "riskFlags": [],
        }

    market_profile = _market_trade_profile(trades)
    trade_count = int(metrics.get("tradeCount", 0))
    unique_markets = int(metrics.get("uniqueMarkets", 0))
    total_volume = float(metrics.get("totalVolume", 0.0))
    avg_size = float(metrics.get("avgSize", 0.0))
    late_entry_ratio = float(metrics.get("lateEntryRatio", 0.0))
    extreme_price_ratio = float(metrics.get("extremePriceRatio", 0.0))
    sell_ratio = float(metrics.get("sellRatio", 0.0))
    category_concentration = float(metrics.get("categoryConcentration", 0.0))
    concentration_risk = float(metrics.get("concentrationRisk", 0.0))
    opposing_outcome_ratio = float(metrics.get("opposingOutcomeRatio", 0.0))

    risk_flags: list[str] = []
    penalties: list[float] = []

    if trade_count < 6:
        risk_flags.append("low_trade_count")
    if unique_markets < 3:
        risk_flags.append("low_market_diversity")

    if opposing_outcome_ratio >= 0.2:
        risk_flags.append("opposing_outcomes")
        penalties.append(opposing_outcome_ratio * 32.0)

    directional_contradiction_ratio = market_profile["directionalContradictionRatio"]
    if directional_contradiction_ratio > 0:
        risk_flags.append("directional_contradiction")
        penalties.append(max(10.0, directional_contradiction_ratio * 34.0))

    possible_hedge_ratio = market_profile["possibleHedgeRatio"]
    if possible_hedge_ratio > 0:
        risk_flags.append("possible_hedge")
        penalties.append(max(6.0, possible_hedge_ratio * 14.0))

    if sell_ratio >= 0.35 and (opposing_outcome_ratio > 0 or directional_contradiction_ratio > 0):
        risk_flags.append("market_maker_pattern")
        penalties.append(10.0 + min(8.0, sell_ratio * 10.0))

    if late_entry_ratio >= 0.45:
        risk_flags.append("late_chaser")
        penalties.append(late_entry_ratio * 36.0)

    if extreme_price_ratio >= 0.35:
        risk_flags.append("extreme_price_behavior")
        penalties.append(extreme_price_ratio * 34.0)

    if concentration_risk >= 0.65:
        risk_flags.append("concentration_risk")
        penalties.append(concentration_risk * 24.0)

    micro_trade_spam_ratio = _micro_trade_spam_score(trades, metrics)
    if micro_trade_spam_ratio >= 0.45:
        risk_flags.append("micro_trade_spam")
        penalties.append(micro_trade_spam_ratio * 18.0)

    category_randomness_score = _category_randomness_score(metrics, trades)
    if category_randomness_score >= 0.2:
        risk_flags.append("category_randomness")
        penalties.append(category_randomness_score * 14.0)

    if total_volume >= 8_000:
        penalties.append(min(12.0, math.log10(total_volume + 1.0) * 2.4))

    if avg_size >= 500:
        penalties.append(min(10.0, math.log10(avg_size + 1.0) * 2.4))

    if avg_size <= 350 and trade_count >= 8:
        penalties.append(4.0)

    if total_volume >= 25_000:
        penalties.append(4.0)
    elif total_volume >= 10_000:
        penalties.append(2.0)

    noise_score = round(clamp(sum(penalties)))

    if trade_count < 6 or unique_markets < 3:
        noise_score = min(noise_score, 29)
    elif trade_count < 10 or unique_markets < 4:
        noise_score = min(noise_score, 45)

    if total_volume >= 15_000 and noise_score >= 70:
        noise_score = min(100, noise_score + 6)

    noise_level = _noise_level(noise_score)

    deduped_flags: list[str] = []
    for flag in risk_flags:
        if flag not in deduped_flags:
            deduped_flags.append(flag)

    return {
        "noiseScore": noise_score,
        "noiseLevel": noise_level,
        "riskFlags": deduped_flags,
        "opposingOutcomeRatio": opposing_outcome_ratio,
        "directionalContradictionRatio": directional_contradiction_ratio,
        "possibleHedgeRatio": possible_hedge_ratio,
        "microTradeSpamRatio": micro_trade_spam_ratio,
        "categoryRandomnessScore": category_randomness_score,
        "marketProfile": market_profile,
    }
