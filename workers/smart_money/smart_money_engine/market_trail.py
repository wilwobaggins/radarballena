from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

try:  # pragma: no cover - support package and script-style imports
    from .wallet_classifier import (
        SIGNAL_WALLET,
        SPECIALIST_WALLET,
        WHALE_BUT_NOISY,
    )
except ImportError:  # pragma: no cover
    from wallet_classifier import (
        SIGNAL_WALLET,
        SPECIALIST_WALLET,
        WHALE_BUT_NOISY,
    )


QUALIFIED_CLASSIFICATION_WEIGHTS = {
    SIGNAL_WALLET: 1.0,
    SPECIALIST_WALLET: 0.9,
    WHALE_BUT_NOISY: 0.4,
}


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def timing_weight(price: float) -> float:
    if price <= 0.05 or price >= 0.95:
        return 0.35
    if price >= 0.85:
        return 0.55
    if 0.05 < price < 0.65:
        return 1.0
    return 0.75


def freshness_weight(timestamp: datetime | None) -> float:
    if timestamp is None:
        return 0.4

    now = datetime.now(timezone.utc)
    age_hours = max(0.0, (now - timestamp).total_seconds() / 3600)

    if age_hours < 6:
        return 1.0
    if age_hours < 24:
        return 0.8
    if age_hours < 72:
        return 0.6
    return 0.4


def direction_from_trade(trade: dict[str, Any]) -> str | None:
    side = str(trade.get("side") or "").strip().upper()
    outcome = str(trade.get("outcome") or "").strip().lower()

    if side == "BUY" and outcome == "yes":
        return "yes"
    if side == "SELL" and outcome == "no":
        return "yes"
    if side == "BUY" and outcome == "no":
        return "no"
    if side == "SELL" and outcome == "yes":
        return "no"
    return None


def is_wallet_qualified(wallet_score: dict[str, Any]) -> bool:
    classification = wallet_score.get("classification")
    return (
        wallet_score.get("walletQualityScore", 0) >= 60
        and classification in QUALIFIED_CLASSIFICATION_WEIGHTS
    )


def build_wallet_score_map(wallet_scores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(score["wallet"]).lower(): score
        for score in wallet_scores
    }


def average_wallet_quality(qualified_scores: list[dict[str, Any]]) -> float:
    if not qualified_scores:
        return 0.0

    return sum(float(score.get("walletQualityScore", 0)) for score in qualified_scores) / len(
        qualified_scores
    )


def consensus_score(weighted_yes_flow: float, weighted_no_flow: float) -> int:
    total = weighted_yes_flow + weighted_no_flow
    if total <= 0:
        return 0

    dominant_share = max(weighted_yes_flow, weighted_no_flow) / total
    return round(clamp(dominant_share * 100))


def divergence_score(weighted_yes_flow: float, weighted_no_flow: float) -> int:
    total = weighted_yes_flow + weighted_no_flow
    if total <= 0:
        return 0

    balance = 1 - abs(weighted_yes_flow - weighted_no_flow) / total
    return round(clamp(balance * 100))


def conviction_score(
    smart_money_volume: float,
    average_quality: float,
    smart_bias: float,
    qualified_wallet_count: int,
) -> int:
    volume_component = min(40.0, smart_money_volume / 400)
    quality_component = average_quality * 0.35
    bias_component = abs(smart_bias) * 20
    wallet_component = min(12.0, qualified_wallet_count * 4.0)

    return round(clamp(volume_component + quality_component + bias_component + wallet_component))


def freshness_score(weighted_freshness_values: list[tuple[float, float]]) -> int:
    total_weight = sum(weight for _value, weight in weighted_freshness_values)
    if total_weight <= 0:
        return 0

    weighted_average = sum(value * weight for value, weight in weighted_freshness_values) / total_weight
    return round(clamp(weighted_average * 100))


def trail_status(
    qualified_wallet_count: int,
    smart_money_volume: float,
    consensus: int,
    divergence: int,
    conviction: int,
    weighted_yes_flow: float,
    weighted_no_flow: float,
) -> str:
    total_directional_flow = weighted_yes_flow + weighted_no_flow

    if qualified_wallet_count == 0 or total_directional_flow <= 0 or smart_money_volume <= 0:
        return "NO_RELIABLE_TRAIL"

    if weighted_yes_flow > 0 and weighted_no_flow > 0 and divergence >= 55:
        return "CONTRADICTORY_FLOW"

    if (
        qualified_wallet_count >= 2
        and smart_money_volume >= 2500
        and consensus >= 65
        and conviction >= 60
    ):
        return "DIRECT_STRONG"

    return "DIRECT_WEAK"


def headline_and_interpretation(status: str, smart_bias: float) -> tuple[str, str]:
    if status == "DIRECT_STRONG":
        if smart_bias > 0.35:
            return (
                "Actividad directa fuerte de Smart Money hacia YES",
                "Hay varias wallets calificadas empujando flujo direccional hacia YES con convicción suficiente.",
            )
        if smart_bias < -0.35:
            return (
                "Actividad directa fuerte de Smart Money hacia NO",
                "Hay varias wallets calificadas empujando flujo direccional hacia NO con convicción suficiente.",
            )
        return (
            "Actividad directa fuerte pero mixta de Smart Money",
            "Existe capital calificado relevante, aunque el sesgo final todavía no es completamente limpio.",
        )

    if status == "DIRECT_WEAK":
        return (
            "Actividad directa débil de Smart Money",
            "Hay actividad directa en este mercado, pero el consenso todavía no es suficientemente fuerte.",
        )

    if status == "CONTRADICTORY_FLOW":
        return (
            "Flujo contradictorio de Smart Money",
            "El capital calificado está dividido entre YES y NO, así que la lectura todavía es conflictiva.",
        )

    return (
        "No hay trail confiable de Smart Money",
        "No existe suficiente capital calificado o la señal actual es demasiado débil para una lectura confiable.",
    )


def build_risk_flags(
    status: str,
    qualified_wallet_count: int,
    consensus: int,
    divergence: int,
    conviction: int,
    freshness: int,
    neutral_event_count: int,
) -> list[str]:
    flags: list[str] = []

    if qualified_wallet_count < 2:
        flags.append("low_wallet_count")
    if consensus < 65:
        flags.append("low_consensus")
    if divergence >= 55:
        flags.append("high_divergence")
    if conviction < 60:
        flags.append("low_conviction")
    if freshness < 55:
        flags.append("stale_flow")
    if neutral_event_count > 0:
        flags.append("neutral_events_present")
    if status == "NO_RELIABLE_TRAIL":
        flags.append("no_reliable_signal")

    deduped_flags: list[str] = []
    for flag in flags:
        if flag not in deduped_flags:
            deduped_flags.append(flag)
    return deduped_flags


def build_market_capital_trails(
    trades: list[dict[str, Any]],
    wallet_scores: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    wallet_score_map = build_wallet_score_map(wallet_scores)
    trades_by_market: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for trade in trades:
        market_id = trade.get("market_id")
        if not market_id:
            continue
        trades_by_market[str(market_id)].append(trade)

    generated_at = datetime.now(timezone.utc).isoformat()
    trails: list[dict[str, Any]] = []

    for market_id, market_trades in trades_by_market.items():
        title_counter = Counter(
            str(trade.get("title") or "").strip()
            for trade in market_trades
            if str(trade.get("title") or "").strip()
        )
        title = title_counter.most_common(1)[0][0] if title_counter else ""

        qualified_wallets: dict[str, dict[str, Any]] = {}
        qualified_scores: list[dict[str, Any]] = []
        smart_money_volume = 0.0
        weighted_yes_flow = 0.0
        weighted_no_flow = 0.0
        weighted_freshness_values: list[tuple[float, float]] = []
        neutral_event_count = 0

        for trade in market_trades:
            wallet = str(trade.get("wallet") or "").lower()
            wallet_score = wallet_score_map.get(wallet)

            if not wallet_score or not is_wallet_qualified(wallet_score):
                continue

            classification = wallet_score["classification"]
            classification_weight = QUALIFIED_CLASSIFICATION_WEIGHTS[classification]
            size_usd = float(trade.get("size_usd") or 0.0)
            trade_price = float(trade.get("price") or 0.0)
            time_weight = timing_weight(trade_price)
            fresh_weight = freshness_weight(trade.get("timestamp"))
            quality_weight = float(wallet_score.get("walletQualityScore", 0)) / 100.0
            weighted_value = size_usd * quality_weight * classification_weight * time_weight * fresh_weight

            qualified_wallets[wallet] = wallet_score
            smart_money_volume += size_usd
            weighted_freshness_values.append((fresh_weight, max(weighted_value, 1.0)))

            direction = direction_from_trade(trade)
            if direction == "yes":
                weighted_yes_flow += weighted_value
            elif direction == "no":
                weighted_no_flow += weighted_value
            else:
                neutral_event_count += 1

        qualified_scores = list(qualified_wallets.values())
        qualified_wallet_count = len(qualified_wallets)
        smart_bias = safe_ratio(
            weighted_yes_flow - weighted_no_flow,
            max(weighted_yes_flow + weighted_no_flow, 1.0),
        )
        consensus = consensus_score(weighted_yes_flow, weighted_no_flow)
        divergence = divergence_score(weighted_yes_flow, weighted_no_flow)
        conviction = conviction_score(
            smart_money_volume=smart_money_volume,
            average_quality=average_wallet_quality(qualified_scores),
            smart_bias=smart_bias,
            qualified_wallet_count=qualified_wallet_count,
        )
        freshness = freshness_score(weighted_freshness_values)
        status = trail_status(
            qualified_wallet_count=qualified_wallet_count,
            smart_money_volume=smart_money_volume,
            consensus=consensus,
            divergence=divergence,
            conviction=conviction,
            weighted_yes_flow=weighted_yes_flow,
            weighted_no_flow=weighted_no_flow,
        )
        headline, interpretation = headline_and_interpretation(status, smart_bias)
        risk_flags = build_risk_flags(
            status=status,
            qualified_wallet_count=qualified_wallet_count,
            consensus=consensus,
            divergence=divergence,
            conviction=conviction,
            freshness=freshness,
            neutral_event_count=neutral_event_count,
        )

        trails.append(
            {
                "marketId": market_id,
                "title": title,
                "qualifiedWalletCount": qualified_wallet_count,
                "smartMoneyVolume": round(smart_money_volume, 2),
                "weightedYesFlow": round(weighted_yes_flow, 2),
                "weightedNoFlow": round(weighted_no_flow, 2),
                "smartBias": round(smart_bias, 3),
                "consensusScore": consensus,
                "divergenceScore": divergence,
                "convictionScore": conviction,
                "freshnessScore": freshness,
                "status": status,
                "headline": headline,
                "interpretation": interpretation,
                "riskFlags": risk_flags,
                "events": [],
                "generatedAt": generated_at,
            }
        )

    return sorted(
        trails,
        key=lambda trail: (
            trail["status"] == "DIRECT_STRONG",
            trail["status"] == "DIRECT_WEAK",
            trail["smartMoneyVolume"],
            abs(trail["smartBias"]),
        ),
        reverse=True,
    )


def summarize_market_trails(market_trails: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(trail["status"] for trail in market_trails)
    return {
        "markets_scored": len(market_trails),
        "direct_strong": counts.get("DIRECT_STRONG", 0),
        "direct_weak": counts.get("DIRECT_WEAK", 0),
        "contradictory_flow": counts.get("CONTRADICTORY_FLOW", 0),
        "no_reliable_trail": counts.get("NO_RELIABLE_TRAIL", 0),
    }
