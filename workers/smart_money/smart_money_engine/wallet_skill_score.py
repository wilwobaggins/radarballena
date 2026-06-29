from __future__ import annotations

import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from statistics import median
from typing import Any, Callable

import httpx

try:  # pragma: no cover - support package and script-style imports
    from .category_utils import guess_category_from_title, guess_skill_category_from_title
except ImportError:  # pragma: no cover
    from category_utils import guess_category_from_title, guess_skill_category_from_title


WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
SKILL_CATEGORIES = (
    "sports",
    "esports",
    "politics",
    "geopolitics",
    "macro",
    "crypto",
    "culture_awards",
    "technology",
    "unknown",
)


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    if math.isnan(value) or math.isinf(value):
        return lower
    return max(lower, min(upper, value))


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return default
        return result
    except Exception:
        return default


def _normalize_wallet(wallet: str) -> str:
    return str(wallet or "").strip().lower()


def _is_valid_wallet(wallet: str) -> bool:
    return bool(WALLET_RE.match(wallet or ""))


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_title_for_skill(title: str) -> str:
    text = unicodedata.normalize("NFKD", str(title or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"([a-z])([0-9])", r"\1 \2", text)
    text = re.sub(r"([0-9])([a-z])", r"\1 \2", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split()).strip()


def _position_cost_basis(position: dict[str, Any]) -> float:
    return safe_float(position.get("avgPrice")) * safe_float(position.get("totalBought"))


def _position_pnl(position: dict[str, Any]) -> float:
    return safe_float(position.get("realizedPnl"))


def _bounded_ratio(numerator: float, denominator: float, *, upper: float | None = None) -> float:
    if denominator <= 0:
        return 0.0
    value = numerator / denominator
    if upper is not None:
        return min(value, upper)
    return value


def _infer_category(position: dict[str, Any]) -> str:
    title = _clean_text(position.get("title"))
    return guess_skill_category_from_title(title) if title else "unknown"


def _summarize_positions(closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    closed_positions_count = len(closed_positions)
    pnls: list[float] = []
    wins: list[float] = []
    losses: list[float] = []

    total_cost_basis = 0.0
    total_realized_pnl = 0.0
    profitable_positions = 0
    losing_positions = 0
    breakeven_positions = 0

    for position in closed_positions:
        pnl = _position_pnl(position)
        total_cost_basis += _position_cost_basis(position)
        total_realized_pnl += pnl
        pnls.append(pnl)

        if pnl > 0:
            profitable_positions += 1
            wins.append(pnl)
        elif pnl < 0:
            losing_positions += 1
            losses.append(abs(pnl))
        else:
            breakeven_positions += 1

    roi = _bounded_ratio(total_realized_pnl, total_cost_basis)
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    if gross_loss <= 0 and gross_profit > 0:
        profit_factor = 5.0
        no_losses_observed = True
    else:
        profit_factor = _bounded_ratio(gross_profit, gross_loss, upper=5.0)
        no_losses_observed = False

    if profitable_positions + losing_positions > 0:
        win_rate = profitable_positions / (profitable_positions + losing_positions)
    else:
        win_rate = 0.0

    average_win = sum(wins) / len(wins) if wins else 0.0
    average_loss = sum(losses) / len(losses) if losses else 0.0
    payoff_ratio = 0.0
    if average_loss > 0 and average_win > 0:
        payoff_ratio = min(average_win / average_loss, 5.0)

    best_position_pnl = max(pnls) if pnls else 0.0
    worst_position_pnl = min(pnls) if pnls else 0.0
    sample_confidence = min(100.0, (closed_positions_count / 30.0) * 100.0)

    roi_score = clamp(50.0 + roi * 100.0)
    profit_factor_score = clamp(profit_factor * 50.0)
    payoff_score = clamp(50.0 + (payoff_ratio - 1.0) * 25.0)
    win_rate_score = clamp(win_rate * 100.0)
    sample_confidence_score = clamp(sample_confidence)

    if closed_positions_count < 5:
        skill_status = "insufficient"
    elif closed_positions_count < 20:
        skill_status = "limited"
    else:
        skill_status = "sufficient"

    skill_score = round(
        clamp(
            0.30 * roi_score
            + 0.25 * profit_factor_score
            + 0.20 * payoff_score
            + 0.15 * win_rate_score
            + 0.10 * sample_confidence_score
        )
    )

    return {
        "closedPositionsCount": closed_positions_count,
        "totalCostBasis": round(total_cost_basis, 6),
        "totalRealizedPnl": round(total_realized_pnl, 6),
        "roi": round(roi, 6),
        "roiPct": round(roi * 100.0, 2),
        "profitablePositions": profitable_positions,
        "losingPositions": losing_positions,
        "breakevenPositions": breakeven_positions,
        "winRate": round(win_rate, 6),
        "grossProfit": round(gross_profit, 6),
        "grossLoss": round(gross_loss, 6),
        "profitFactor": round(profit_factor, 6),
        "averageWin": round(average_win, 6),
        "averageLoss": round(average_loss, 6),
        "payoffRatio": round(payoff_ratio, 6),
        "bestPositionPnl": round(best_position_pnl, 6),
        "worstPositionPnl": round(worst_position_pnl, 6),
        "medianPositionPnl": round(median(pnls), 6) if pnls else 0.0,
        "sampleConfidence": round(sample_confidence, 2),
        "skillStatus": skill_status,
        "skillScore": skill_score,
        "noLossesObserved": no_losses_observed,
    }


def _compute_skill_from_positions(
    closed_positions: list[dict[str, Any]],
    *,
    category_fn: Callable[[dict[str, Any]], str] = _infer_category,
) -> dict[str, Any]:
    summary = _summarize_positions(closed_positions)
    closed_positions_count = summary["closedPositionsCount"]
    category_counts: Counter[str] = Counter()
    category_positions: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for position in closed_positions:
        category = category_fn(position)
        category_counts[category] += 1
        category_positions[category].append(position)

    known_category_count = sum(
        count for category, count in category_counts.items() if category != "unknown"
    )
    unknown_category_count = category_counts.get("unknown", 0)
    known_category_coverage = _bounded_ratio(known_category_count, closed_positions_count)
    known_category_coverage_score = round(known_category_coverage * 100.0)

    dominant_known_category = "unknown"
    known_category_consistency = 0.0
    if known_category_count > 0:
        known_counts = {
            category: count
            for category, count in category_counts.items()
            if category != "unknown"
        }
        dominant_known_category, dominant_count = max(known_counts.items(), key=lambda item: item[1])
        known_category_consistency = _bounded_ratio(dominant_count, known_category_count)
    known_category_consistency_score = round(known_category_consistency * 100.0)

    dominant_category = dominant_known_category
    category_consistency = known_category_consistency
    category_consistency_score = known_category_consistency_score
    if dominant_known_category == "unknown":
        category_consistency = 0.0
        category_consistency_score = 0

    category_skill_scores: dict[str, dict[str, Any]] = {}
    for category in SKILL_CATEGORIES:
        positions = category_positions.get(category, [])
        sub_skill = _summarize_positions(positions) if positions else _summarize_positions([])
        category_skill_scores[category] = {
            "closedPositionsCount": sub_skill["closedPositionsCount"],
            "totalCostBasis": sub_skill["totalCostBasis"],
            "totalRealizedPnl": sub_skill["totalRealizedPnl"],
            "roi": sub_skill["roi"],
            "winRate": sub_skill["winRate"],
            "profitFactor": sub_skill["profitFactor"],
            "payoffRatio": sub_skill["payoffRatio"],
            "skillScore": sub_skill["skillScore"],
            "skillStatus": "insufficient" if sub_skill["closedPositionsCount"] < 5 else sub_skill["skillStatus"],
        }

    return {
        "wallet": None,
        "closedPositionsCount": summary["closedPositionsCount"],
        "totalCostBasis": summary["totalCostBasis"],
        "totalRealizedPnl": summary["totalRealizedPnl"],
        "roi": summary["roi"],
        "roiPct": summary["roiPct"],
        "profitablePositions": summary["profitablePositions"],
        "losingPositions": summary["losingPositions"],
        "breakevenPositions": summary["breakevenPositions"],
        "winRate": summary["winRate"],
        "grossProfit": summary["grossProfit"],
        "grossLoss": summary["grossLoss"],
        "profitFactor": summary["profitFactor"],
        "averageWin": summary["averageWin"],
        "averageLoss": summary["averageLoss"],
        "payoffRatio": summary["payoffRatio"],
        "bestPositionPnl": summary["bestPositionPnl"],
        "worstPositionPnl": summary["worstPositionPnl"],
        "medianPositionPnl": summary["medianPositionPnl"],
        "sampleConfidence": summary["sampleConfidence"],
        "dominantCategory": dominant_category,
        "categoryConsistency": round(category_consistency, 6),
        "categoryConsistencyScore": category_consistency_score,
        "knownCategoryCount": known_category_count,
        "unknownCategoryCount": unknown_category_count,
        "knownCategoryCoverage": round(known_category_coverage, 6),
        "knownCategoryCoverageScore": known_category_coverage_score,
        "dominantKnownCategory": dominant_known_category,
        "knownCategoryConsistency": round(known_category_consistency, 6),
        "knownCategoryConsistencyScore": known_category_consistency_score,
        "categorySkillScores": category_skill_scores,
        "skillStatus": summary["skillStatus"],
        "skillScore": summary["skillScore"],
        "noLossesObserved": summary["noLossesObserved"],
    }


def _skill_score_without_top_winner(closed_positions: list[dict[str, Any]]) -> tuple[int, str, dict[str, Any]]:
    if len(closed_positions) < 2:
        skill = _compute_skill_from_positions(closed_positions, category_fn=_infer_category)
        return skill["skillScore"], skill["skillStatus"], skill

    top_index = max(range(len(closed_positions)), key=lambda idx: _position_pnl(closed_positions[idx]))
    remainder = [position for idx, position in enumerate(closed_positions) if idx != top_index]
    skill = _compute_skill_from_positions(remainder, category_fn=_infer_category)
    return skill["skillScore"], skill["skillStatus"], skill


def _build_robustness_metrics(closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    pnls = [_position_pnl(position) for position in closed_positions]
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    positive_pnls = sorted((pnl for pnl in pnls if pnl > 0), reverse=True)
    top1 = positive_pnls[0] if positive_pnls else 0.0
    top5 = sum(positive_pnls[:5]) if positive_pnls else 0.0
    if gross_profit > 0:
        top1_share = clamp(top1 / gross_profit, 0.0, 1.0)
        top5_share = clamp(top5 / gross_profit, 0.0, 1.0)
    else:
        top1_share = 0.0
        top5_share = 0.0

    if top1_share >= 0.60:
        pnl_concentration_level = "extreme"
    elif top1_share >= 0.40 or top5_share >= 0.80:
        pnl_concentration_level = "high"
    elif top1_share >= 0.25 or top5_share >= 0.65:
        pnl_concentration_level = "moderate"
    else:
        pnl_concentration_level = "low"

    concentration_penalty = (
        max(0.0, top1_share - 0.25) * 30.0
        + max(0.0, top5_share - 0.60) * 15.0
    )
    concentration_penalty = clamp(concentration_penalty, 0.0, 20.0)

    closed_positions_count = len(closed_positions)
    known_category_count = sum(
        1 for position in closed_positions if guess_skill_category_from_title(_clean_text(position.get("title"))) != "unknown"
    )
    known_category_coverage = _bounded_ratio(known_category_count, closed_positions_count)
    category_coverage_multiplier = clamp(0.85 + (0.15 * known_category_coverage), 0.85, 1.0)

    skill_without_top_winner, skill_without_status, _ = _skill_score_without_top_winner(closed_positions)
    base_skill = _compute_skill_from_positions(closed_positions, category_fn=_infer_category)
    if base_skill["skillStatus"] == "insufficient":
        robust_skill_score = base_skill["skillScore"]
    else:
        robust_skill_score = round(
            clamp(
                (
                    0.55 * skill_without_top_winner
                    + 0.45 * base_skill["skillScore"]
                    - concentration_penalty
                )
                * category_coverage_multiplier
            )
        )

    return {
        "top1PositionPnl": round(top1, 6),
        "top5PositionsPnl": round(top5, 6),
        "top1PositionPnlShare": round(top1_share, 6),
        "top5PositionsPnlShare": round(top5_share, 6),
        "pnlConcentrationLevel": pnl_concentration_level,
        "concentrationPenalty": round(concentration_penalty, 6),
        "categoryCoverageMultiplier": round(category_coverage_multiplier, 6),
        "skillScoreWithoutTopWinner": skill_without_top_winner,
        "skillWithoutTopWinnerStatus": skill_without_status,
        "robustSkillScore": robust_skill_score,
    }


def compute_wallet_skill(wallet: str, closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    valid_wallet = _normalize_wallet(wallet)
    if not _is_valid_wallet(valid_wallet):
        return {
            "wallet": valid_wallet or wallet,
            "skillStatus": "error",
            "error": "invalid_wallet",
        }

    overall = _compute_skill_from_positions(closed_positions, category_fn=_infer_category)
    robust = _build_robustness_metrics(closed_positions)
    skill_without_top_winner, skill_without_top_status, _ = _skill_score_without_top_winner(closed_positions)
    overall.update(robust)
    overall["wallet"] = valid_wallet
    overall["categorySkillScores"] = overall.get("categorySkillScores") or {}
    overall["skillScoreWithoutTopWinner"] = skill_without_top_winner
    overall["skillWithoutTopWinnerStatus"] = skill_without_top_status
    return overall


def compute_shadow_meta_evaluation(
    behavior_quality_score: int,
    skill_analysis: dict[str, Any],
) -> dict[str, Any]:
    skill_status = str(skill_analysis.get("skillStatus") or "insufficient")
    skill_score = int(skill_analysis.get("skillScore", 0) or 0)
    sample_confidence = safe_float(skill_analysis.get("sampleConfidence"))
    category_consistency_score = int(skill_analysis.get("categoryConsistencyScore", 0) or 0)

    if skill_status == "insufficient":
        shadow_meta_score = int(behavior_quality_score)
        used_skill_score = False
    elif skill_status == "limited":
        shadow_meta_score = round(
            0.25 * skill_score
            + 0.55 * behavior_quality_score
            + 0.10 * sample_confidence
            + 0.10 * category_consistency_score
        )
        used_skill_score = True
    else:
        shadow_meta_score = round(
            0.45 * skill_score
            + 0.35 * behavior_quality_score
            + 0.10 * sample_confidence
            + 0.10 * category_consistency_score
        )
        used_skill_score = True

    if shadow_meta_score >= 75:
        recommendation = "shadow_high"
    elif shadow_meta_score >= 60:
        recommendation = "shadow_watch"
    else:
        recommendation = "shadow_low"

    return {
        "behaviorQualityScore": int(behavior_quality_score),
        "skillScore": skill_score,
        "sampleConfidence": sample_confidence,
        "categoryConsistencyScore": category_consistency_score,
        "shadowMetaScore": int(clamp(float(shadow_meta_score))),
        "skillStatus": skill_status,
        "usedSkillScore": used_skill_score,
        "shadowRecommendation": recommendation,
    }


def compute_shadow_robust_evaluation(
    behavior_quality_score: int,
    skill_analysis: dict[str, Any],
) -> dict[str, Any]:
    skill_status = str(skill_analysis.get("skillStatus") or "insufficient")
    skill_score = int(skill_analysis.get("skillScore", 0) or 0)
    robust_skill_score = int(skill_analysis.get("robustSkillScore", skill_score) or skill_score)
    skill_score_without_top_winner = int(skill_analysis.get("skillScoreWithoutTopWinner", skill_score) or skill_score)
    sample_confidence = safe_float(skill_analysis.get("sampleConfidence"))
    known_category_coverage_score = int(skill_analysis.get("knownCategoryCoverageScore", 0) or 0)
    known_category_consistency_score = int(skill_analysis.get("knownCategoryConsistencyScore", 0) or 0)
    concentration_penalty = safe_float(skill_analysis.get("concentrationPenalty"))
    pnl_concentration_level = str(skill_analysis.get("pnlConcentrationLevel") or "low")

    if skill_status == "insufficient":
        shadow_robust_meta_score = int(behavior_quality_score)
        used_robust_skill_score = False
    elif skill_status == "limited":
        shadow_robust_meta_score = round(
            0.25 * robust_skill_score
            + 0.45 * behavior_quality_score
            + 0.10 * sample_confidence
            + 0.10 * known_category_coverage_score
            + 0.10 * known_category_consistency_score
        )
        used_robust_skill_score = True
    else:
        shadow_robust_meta_score = round(
            0.40 * robust_skill_score
            + 0.30 * behavior_quality_score
            + 0.10 * sample_confidence
            + 0.10 * known_category_coverage_score
            + 0.10 * known_category_consistency_score
        )
        used_robust_skill_score = True

    if shadow_robust_meta_score >= 75:
        recommendation = "robust_shadow_high"
    elif shadow_robust_meta_score >= 60:
        recommendation = "robust_shadow_watch"
    else:
        recommendation = "robust_shadow_low"

    return {
        "behaviorQualityScore": int(behavior_quality_score),
        "skillScore": skill_score,
        "robustSkillScore": robust_skill_score,
        "skillScoreWithoutTopWinner": skill_score_without_top_winner,
        "sampleConfidence": sample_confidence,
        "knownCategoryCoverageScore": known_category_coverage_score,
        "knownCategoryConsistencyScore": known_category_consistency_score,
        "concentrationPenalty": concentration_penalty,
        "pnlConcentrationLevel": pnl_concentration_level,
        "shadowRobustMetaScore": int(clamp(float(shadow_robust_meta_score))),
        "skillStatus": skill_status,
        "usedRobustSkillScore": used_robust_skill_score,
        "shadowRobustRecommendation": recommendation,
    }
