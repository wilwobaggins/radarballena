from __future__ import annotations

import asyncio
import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any

import httpx

try:  # pragma: no cover - support package and script-style imports
    from .category_utils import guess_category_from_title
except ImportError:  # pragma: no cover
    from category_utils import guess_category_from_title


WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")


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


def _infer_category(position: dict[str, Any]) -> str:
    title = _clean_text(position.get("title"))
    return guess_category_from_title(title) if title else "unknown"


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


def _build_category_scores(groups: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    category_scores: dict[str, dict[str, Any]] = {}
    for category in ("sports", "politics", "macro", "crypto", "unknown"):
        positions = groups.get(category, [])
        skill = _compute_skill_from_positions(positions)
        category_scores[category] = {
            "closedPositionsCount": skill["closedPositionsCount"],
            "totalCostBasis": skill["totalCostBasis"],
            "totalRealizedPnl": skill["totalRealizedPnl"],
            "roi": skill["roi"],
            "winRate": skill["winRate"],
            "profitFactor": skill["profitFactor"],
            "payoffRatio": skill["payoffRatio"],
            "skillScore": skill["skillScore"],
            "skillStatus": skill["skillStatus"] if skill["closedPositionsCount"] >= 5 else "insufficient",
        }
    return category_scores


def _compute_skill_from_positions(closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    closed_positions_count = len(closed_positions)
    total_cost_basis = 0.0
    total_realized_pnl = 0.0
    profitable_positions = 0
    losing_positions = 0
    breakeven_positions = 0
    pnls: list[float] = []
    wins: list[float] = []
    losses: list[float] = []

    category_counts: Counter[str] = Counter()
    for position in closed_positions:
        total_cost_basis += _position_cost_basis(position)
        pnl = _position_pnl(position)
        total_realized_pnl += pnl
        pnls.append(pnl)
        category_counts[_infer_category(position)] += 1

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
    if average_loss > 0:
        payoff_ratio = min(average_win / average_loss, 5.0) if average_win > 0 else 0.0

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

    dominant_category = "unknown"
    category_consistency = 0.0
    if closed_positions_count > 0:
        dominant_category, dominant_count = category_counts.most_common(1)[0]
        category_consistency = dominant_count / closed_positions_count

    category_skill_scores = {
        "roiScore": round(roi_score),
        "profitFactorScore": round(profit_factor_score),
        "payoffScore": round(payoff_score),
        "winRateScore": round(win_rate_score),
        "sampleConfidenceScore": round(sample_confidence_score),
    }

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
        "wallet": None,
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
        "sampleConfidence": round(sample_confidence, 2),
        "dominantCategory": dominant_category,
        "categoryConsistency": round(category_consistency, 6),
        "categoryConsistencyScore": round(category_consistency * 100.0),
        "categorySkillScores": category_skill_scores,
        "skillStatus": skill_status,
        "skillScore": skill_score,
        "noLossesObserved": no_losses_observed,
    }


def compute_wallet_skill(wallet: str, closed_positions: list[dict[str, Any]]) -> dict[str, Any]:
    valid_wallet = _normalize_wallet(wallet)
    if not _is_valid_wallet(valid_wallet):
        return {
            "wallet": valid_wallet or wallet,
            "skillStatus": "error",
            "error": "invalid_wallet",
        }

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for position in closed_positions:
        category = _infer_category(position)
        grouped[category].append(position)

    overall = _compute_skill_from_positions(closed_positions)
    overall["wallet"] = valid_wallet
    overall["categorySkillScores"] = _build_category_scores(grouped)
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
