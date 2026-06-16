from typing import Any


INSUFFICIENT_HISTORY = "INSUFFICIENT_HISTORY"
SIGNAL_WALLET = "SIGNAL_WALLET"
SPECIALIST_WALLET = "SPECIALIST_WALLET"
WHALE_BUT_NOISY = "WHALE_BUT_NOISY"
MARKET_MAKER = "MARKET_MAKER"
ARBITRAGEUR = "ARBITRAGEUR"
SCALPER = "SCALPER"
FARMER = "FARMER"


def classify_wallet(wallet_score: dict[str, Any]) -> str:
    metrics = wallet_score["metrics"]
    sub_scores = wallet_score["subScores"]
    score = wallet_score["walletQualityScore"]

    trade_count = metrics["tradeCount"]
    unique_markets = metrics["uniqueMarkets"]
    total_volume = metrics["totalVolume"]
    avg_size = metrics["avgSize"]
    opposing_ratio = metrics["opposingOutcomeRatio"]
    extreme_ratio = metrics["extremePriceRatio"]
    late_ratio = metrics["lateEntryRatio"]
    sell_ratio = metrics["sellRatio"]
    category_concentration = metrics["categoryConcentration"]
    concentration_risk = metrics["concentrationRisk"]
    anti_noise = sub_scores["antiNoiseScore"]

    if trade_count < 6 or unique_markets < 3:
        return INSUFFICIENT_HISTORY

    if opposing_ratio >= 0.35:
        if sell_ratio >= 0.35:
            return MARKET_MAKER
        return ARBITRAGEUR

    if extreme_ratio >= 0.45 or late_ratio >= 0.6:
        return SCALPER

    if trade_count >= 25 and avg_size <= 150 and total_volume <= 10_000:
        return FARMER

    if total_volume >= 15_000 and (score < 55 or anti_noise < 45 or concentration_risk >= 0.7):
        return WHALE_BUT_NOISY

    if score >= 74 and category_concentration >= 0.65 and anti_noise >= 65:
        return SPECIALIST_WALLET

    if score >= 70 and anti_noise >= 70 and concentration_risk <= 0.45:
        return SIGNAL_WALLET

    if score >= 62 and category_concentration >= 0.7 and anti_noise >= 55:
        return SPECIALIST_WALLET

    if anti_noise < 50 or concentration_risk >= 0.65:
        return WHALE_BUT_NOISY

    return SIGNAL_WALLET if score >= 65 else WHALE_BUT_NOISY
