import asyncio
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from dotenv import load_dotenv

try:  # pragma: no cover - support package and script-style imports
    from .market_trail import (
        build_market_capital_trails,
        summarize_market_trails,
    )
    from .related_markets import build_estela_capital_by_market
    from .polymarket_profile_client import fetch_closed_positions
    from .storage import save_json
    from .supabase_writer import (
        fail_engine_run,
        finish_engine_run,
        start_engine_run,
        upsert_capital_trails,
        upsert_wallet_scores,
    )
    from .copyability_storage import write_trade_copyability_shadow
    from .adaptive_wallet_roster import (
        build_adaptive_signal_wallet_roster,
        write_adaptive_signal_wallet_roster,
    )
    from .adaptive_wallet_quality import (
        build_adaptive_signal_wallet_quality,
        write_adaptive_signal_wallet_quality,
    )
    from .category_utils import guess_category_from_title
    from .wallet_shadow_cohort import (
        build_shadow_wallet_cohort,
        load_whale_finder_outputs,
    )
    from .wallet_shadow_history import (
        append_shadow_history,
        build_shadow_history_record,
        compute_longitudinal_metrics,
        load_history_file,
        iso_now,
        resolve_history_paths,
        write_shadow_run_snapshot,
    )
    from .wallet_shadow_rankings import (
        build_wallet_category_rankings,
        build_wallet_comparison_summary,
        build_wallet_general_rankings,
    )
    from .trade_copyability import (
        COPYABILITY_MAX_WALLETS_PER_RUN,
        COPYABILITY_SHADOW_ENABLED,
        run_trade_copyability_shadow,
    )
    from .wallet_skill_score import (
        compute_shadow_meta_evaluation,
        compute_shadow_robust_evaluation,
        compute_wallet_skill,
    )
    from .wallet_classifier import (
        INSUFFICIENT_HISTORY,
        SIGNAL_WALLET,
        WHALE_BUT_NOISY,
    )
    from .wallet_metrics import compute_wallet_scores
    from .time_utils import to_utc_datetime
    from .path_utils import resolve_output_dir
except ImportError:  # pragma: no cover
    from market_trail import (
        build_market_capital_trails,
        summarize_market_trails,
    )
    from related_markets import build_estela_capital_by_market
    from polymarket_profile_client import fetch_closed_positions
    from storage import save_json
    from supabase_writer import (
        fail_engine_run,
        finish_engine_run,
        start_engine_run,
        upsert_capital_trails,
        upsert_wallet_scores,
    )
    from copyability_storage import write_trade_copyability_shadow
    from adaptive_wallet_roster import (
        build_adaptive_signal_wallet_roster,
        write_adaptive_signal_wallet_roster,
    )
    from adaptive_wallet_quality import (
        build_adaptive_signal_wallet_quality,
        write_adaptive_signal_wallet_quality,
    )
    from category_utils import guess_category_from_title
    from wallet_shadow_cohort import (
        build_shadow_wallet_cohort,
        load_whale_finder_outputs,
    )
    from wallet_shadow_history import (
        append_shadow_history,
        build_shadow_history_record,
        compute_longitudinal_metrics,
        load_history_file,
        iso_now,
        resolve_history_paths,
        write_shadow_run_snapshot,
    )
    from wallet_shadow_rankings import (
        build_wallet_category_rankings,
        build_wallet_comparison_summary,
        build_wallet_general_rankings,
    )
    from trade_copyability import (
        COPYABILITY_MAX_WALLETS_PER_RUN,
        COPYABILITY_SHADOW_ENABLED,
        run_trade_copyability_shadow,
    )
    from wallet_skill_score import (
        compute_shadow_meta_evaluation,
        compute_shadow_robust_evaluation,
        compute_wallet_skill,
    )
    from wallet_classifier import (
        INSUFFICIENT_HISTORY,
        SIGNAL_WALLET,
        WHALE_BUT_NOISY,
    )
    from wallet_metrics import compute_wallet_scores
    from time_utils import to_utc_datetime
    from path_utils import resolve_output_dir


load_dotenv()
print(
    "SMART_MONEY_OUTPUT_DIR_RESOLVED "
    f"path={resolve_output_dir()} "
    f"source={'COPYABILITY_OUTPUTS_DIR' if os.getenv('COPYABILITY_OUTPUTS_DIR') else 'SMART_MONEY_ENGINE_OUTPUT_DIR' if os.getenv('SMART_MONEY_ENGINE_OUTPUT_DIR') else 'fallback'}"
)

DATA_API = "https://data-api.polymarket.com"
MIN_TRADE_USD = float(os.getenv("MIN_TRADE_USD", "250"))
LOOKBACK_HOURS = int(os.getenv("LOOKBACK_HOURS", "168"))
PAGE_LIMIT = int(os.getenv("PAGE_LIMIT", "1000"))
MAX_OFFSET = int(os.getenv("MAX_OFFSET", "4000"))
SKILL_SHADOW_ENABLED = os.getenv("SKILL_SHADOW_ENABLED", "true").lower() == "true"
SKILL_MAX_WALLETS_PER_RUN = int(os.getenv("SKILL_MAX_WALLETS_PER_RUN", "25"))
SKILL_MAX_CLOSED_POSITIONS = int(os.getenv("SKILL_MAX_CLOSED_POSITIONS", "500"))
SKILL_HTTP_CONCURRENCY = int(os.getenv("SKILL_HTTP_CONCURRENCY", "4"))
SKILL_PRIORITY_WALLETS = os.getenv("SKILL_PRIORITY_WALLETS", "")
SHADOW_COHORT_ENABLED = os.getenv("SHADOW_COHORT_ENABLED", "true").lower() == "true"
SHADOW_INCLUDE_ACTIVE_WALLETS = os.getenv("SHADOW_INCLUDE_ACTIVE_WALLETS", "true").lower() == "true"
SHADOW_INCLUDE_PRIORITY_WALLETS = os.getenv("SHADOW_INCLUDE_PRIORITY_WALLETS", "true").lower() == "true"
SHADOW_INCLUDE_WHALE_FINDER_CANDIDATES = os.getenv("SHADOW_INCLUDE_WHALE_FINDER_CANDIDATES", "true").lower() == "true"
SHADOW_BENCHMARK_WALLETS = os.getenv("SHADOW_BENCHMARK_WALLETS", "")
SHADOW_MAX_CANDIDATES_PER_RUN = int(os.getenv("SHADOW_MAX_CANDIDATES_PER_RUN", "10"))
SHADOW_MAX_TOTAL_WALLETS_PER_RUN = int(os.getenv("SHADOW_MAX_TOTAL_WALLETS_PER_RUN", "20"))
SHADOW_MIN_CANDIDATE_SCORE = float(os.getenv("SHADOW_MIN_CANDIDATE_SCORE", "0"))
SIGNAL_WALLET_ROSTER_ENABLED = os.getenv("SIGNAL_WALLET_ROSTER_ENABLED", "false").lower() == "true"
SIGNAL_WALLET_ROSTER_SIZE = int(os.getenv("SIGNAL_WALLET_ROSTER_SIZE", "6"))
SIGNAL_WALLET_BENCHMARK_WALLET = os.getenv("SIGNAL_WALLET_BENCHMARK_WALLET", "0x9d84ce0306f8551e02efef1680475fc0f1dc1344")


def parse_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def pick_wallet(activity: dict[str, Any]) -> Optional[str]:
    for key in ["proxyWallet", "wallet", "user", "address", "trader"]:
        value = activity.get(key)
        if isinstance(value, str) and value.startswith("0x"):
            return value.lower()
    return None


def pick_market_id(activity: dict[str, Any]) -> Optional[str]:
    for key in ["market", "marketId", "conditionId", "condition_id"]:
        value = activity.get(key)
        if value:
            return str(value)
    return None


def pick_timestamp(activity: dict[str, Any]) -> Optional[datetime]:
    value = activity.get("timestamp") or activity.get("time") or activity.get("createdAt")
    return to_utc_datetime(value)


def normalize_title(title: Optional[str]) -> str:
    return (title or "").strip()


def is_short_term_noise_market(title: str) -> bool:
    lowered = title.lower()

    if "up or down" in lowered:
        return True

    time_window_tokens = [
        "am-",
        "pm-",
        ":00-",
        ":05-",
        ":10-",
        ":15-",
        ":20-",
        ":25-",
        ":30-",
        ":35-",
        ":40-",
        ":45-",
        ":50-",
        ":55-",
    ]

    if any(token in lowered for token in time_window_tokens) and (
        "bitcoin" in lowered or "ethereum" in lowered or "btc" in lowered or "eth" in lowered
    ):
        return True

    return False


def normalize_activity(row: dict[str, Any]) -> Optional[dict[str, Any]]:
    wallet = pick_wallet(row)
    if not wallet:
        return None

    size_usd = (
        parse_float(row.get("usdcSize"))
        or parse_float(row.get("size"))
        or parse_float(row.get("amount"))
        or parse_float(row.get("value"))
    )

    price = parse_float(row.get("price"), default=0.0)
    timestamp = pick_timestamp(row)
    title = normalize_title(row.get("title") or row.get("marketTitle") or row.get("slug"))

    if is_short_term_noise_market(title):
        return None

    return {
        "wallet": wallet,
        "market_id": pick_market_id(row),
        "side": row.get("side") or row.get("type") or row.get("action"),
        "outcome": row.get("outcome") or row.get("answer"),
        "title": title,
        "category_guess": guess_category_from_title(title),
        "size_usd": size_usd,
        "price": price,
        "timestamp": timestamp,
        "raw": row,
    }


async def fetch_recent_activity() -> list[dict[str, Any]]:
    all_items: list[dict[str, Any]] = []

    async with httpx.AsyncClient(timeout=25) as http:
        for offset in range(0, MAX_OFFSET, PAGE_LIMIT):
            params = {
                "limit": PAGE_LIMIT,
                "offset": offset,
                "takerOnly": False,
            }

            try:
                response = await http.get(f"{DATA_API}/trades", params=params)
            except httpx.HTTPError as exc:
                print(f"Stopping pagination: request error at offset={offset}: {exc}")
                break

            if response.status_code == 400:
                print(f"Stopping pagination: 400 at offset={offset}")
                break

            try:
                response.raise_for_status()
            except httpx.HTTPError as exc:
                print(f"Stopping pagination: response error at offset={offset}: {exc}")
                break
            data = response.json()

            if isinstance(data, dict):
                items = data.get("data") or data.get("items") or data.get("trades") or []
            else:
                items = data

            print(f"offset={offset} raw_items={len(items)}")

            if not items:
                break

            all_items.extend(items)

    normalized: list[dict[str, Any]] = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)

    for item in all_items:
        row = normalize_activity(item)
        if not row:
            continue
        if row["timestamp"] and row["timestamp"] < cutoff:
            continue
        if row["size_usd"] < MIN_TRADE_USD:
            continue
        normalized.append(row)

    return normalized


def dedupe_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    clean: list[dict[str, Any]] = []

    for trade in trades:
        key = (
            trade.get("wallet"),
            trade.get("market_id"),
            trade.get("side"),
            trade.get("outcome"),
            round(float(trade.get("size_usd") or 0.0), 4),
            round(float(trade.get("price") or 0.0), 6),
        )

        if key in seen:
            continue

        seen.add(key)
        clean.append(trade)

    return clean


def _normalize_wallet(value: Any) -> str:
    return str(value or "").strip().lower()


def _parse_priority_wallets() -> list[str]:
    seen: set[str] = set()
    wallets: list[str] = []
    for wallet in SKILL_PRIORITY_WALLETS.split(","):
        normalized = _normalize_wallet(wallet)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        wallets.append(normalized)
    return wallets


def _score_wallet_selection_key(score: dict[str, Any]) -> tuple[float, float]:
    metrics = score.get("metrics") or {}
    return (
        float(score.get("walletQualityScore") or 0),
        float(metrics.get("totalVolume") or 0),
    )


def select_shadow_wallets(wallet_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not wallet_scores:
        return []

    by_wallet = {_normalize_wallet(score.get("wallet")): score for score in wallet_scores if score.get("wallet")}
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for wallet in _parse_priority_wallets():
        score = by_wallet.get(wallet)
        if score and wallet not in seen:
            selected.append(score)
            seen.add(wallet)

    remaining = [
        score
        for score in wallet_scores
        if _normalize_wallet(score.get("wallet")) not in seen
    ]
    remaining.sort(key=_score_wallet_selection_key, reverse=True)

    for score in remaining:
        if len(selected) >= SKILL_MAX_WALLETS_PER_RUN:
            break
        wallet = _normalize_wallet(score.get("wallet"))
        if wallet in seen:
            continue
        selected.append(score)
        seen.add(wallet)

    return selected[:SKILL_MAX_WALLETS_PER_RUN]


def build_shadow_wallet_targets(wallet_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_wallet = {
        _normalize_wallet(score.get("wallet")): score
        for score in wallet_scores
        if score.get("wallet")
    }
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()

    for wallet in _parse_priority_wallets():
        if wallet in seen:
            continue
        seen.add(wallet)
        score = by_wallet.get(wallet)
        if score:
            targets.append(
                {
                    "wallet": wallet,
                    "source": "global_wallet_scores",
                    "walletScore": score,
                }
            )
        else:
            print(
                "SMART_MONEY_SKILL_PRIORITY_TARGETED "
                f"wallet={wallet} "
                "reason=missing_from_global_wallet_scores"
            )
            targets.append(
                {
                    "wallet": wallet,
                    "source": "targeted_wallet_activity",
                    "walletScore": None,
                }
            )

    remaining_budget = max(0, SKILL_MAX_WALLETS_PER_RUN - len(targets))
    if remaining_budget <= 0:
        return targets[:SKILL_MAX_WALLETS_PER_RUN]

    remaining = [
        score
        for score in wallet_scores
        if _normalize_wallet(score.get("wallet")) not in seen
    ]
    remaining.sort(key=_score_wallet_selection_key, reverse=True)

    for score in remaining:
        if len(targets) >= SKILL_MAX_WALLETS_PER_RUN:
            break
        wallet = _normalize_wallet(score.get("wallet"))
        if wallet in seen:
            continue
        seen.add(wallet)
        targets.append(
            {
                "wallet": wallet,
                "source": "global_wallet_scores",
                "walletScore": score,
            }
        )

    return targets[:SKILL_MAX_WALLETS_PER_RUN]


def _safe_error_message(error: Exception) -> str:
    message = str(error).strip()
    if not message:
        message = error.__class__.__name__
    return " ".join(message.split())[:240]


async def _fetch_shadow_positions(
    selected_wallets: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not selected_wallets:
        return {}

    print(f"SMART_MONEY_SKILL_SHADOW_STARTED wallets={len(selected_wallets)}")
    semaphore = asyncio.Semaphore(max(1, SKILL_HTTP_CONCURRENCY))
    results: dict[str, dict[str, Any]] = {}
    selected_wallet_set = {_normalize_wallet(score.get("wallet")) for score in selected_wallets}

    async def _load_one(score: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        wallet = _normalize_wallet(score.get("wallet"))
        try:
            async with semaphore:
                positions = await fetch_closed_positions(wallet, max_positions=SKILL_MAX_CLOSED_POSITIONS)
            print(f"SMART_MONEY_SKILL_FETCHED wallet={wallet} closed_positions={len(positions)}")
            return wallet, {
                "wallet": wallet,
                "closed_positions": positions,
            }
        except Exception as error:
            print(
                "SMART_MONEY_SKILL_FAILED "
                f"wallet={wallet} "
                f"error={_safe_error_message(error)}"
            )
            return wallet, {
                "wallet": wallet,
                "closed_positions": [],
                "error": _safe_error_message(error),
            }

    tasks = [asyncio.create_task(_load_one(score)) for score in selected_wallets]
    for task in asyncio.as_completed(tasks):
        wallet, payload = await task
        results[wallet] = payload

    # keep a stable map for wallets we never selected
    for wallet in selected_wallet_set:
        results.setdefault(wallet, {"wallet": wallet, "closed_positions": []})

    return results


async def _fetch_targeted_activity_for_wallet(wallet: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_events: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=float(os.getenv("SKILL_HTTP_TIMEOUT_SECONDS", "25"))) as http:
            for offset in range(0, SKILL_MAX_CLOSED_POSITIONS, 50):
                response = await http.get(
                    f"{DATA_API}/trades",
                    params={
                        "user": wallet,
                        "limit": 50,
                        "offset": offset,
                        "takerOnly": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                if isinstance(data, dict):
                    items = data.get("data") or data.get("items") or data.get("trades") or []
                else:
                    items = data
                if not isinstance(items, list) or not items:
                    break
                raw_events.extend(item for item in items if isinstance(item, dict))
                if len(items) < 50:
                    break
    except Exception as error:
        print(
            "SMART_MONEY_SKILL_TARGETED_ACTIVITY_FAILED "
            f"wallet={wallet} "
            f"error={_safe_error_message(error)}"
        )
        return [], []

    normalized = []
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    for item in raw_events:
        row = normalize_activity(item)
        if not row:
            continue
        if row["timestamp"] and row["timestamp"] < cutoff:
            continue
        if row["size_usd"] < MIN_TRADE_USD:
            continue
        normalized.append(row)

    return raw_events, dedupe_trades(normalized)


async def _fetch_targeted_wallet_behaviors(
    target_wallets: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    if not target_wallets:
        return {}

    semaphore = asyncio.Semaphore(max(1, SKILL_HTTP_CONCURRENCY))
    results: dict[str, dict[str, Any]] = {}

    async def _load_one(target: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        wallet = _normalize_wallet(target.get("wallet"))
        async with semaphore:
            raw_events, normalized_trades = await _fetch_targeted_activity_for_wallet(wallet)
        print(
            "SMART_MONEY_SKILL_TARGETED_ACTIVITY_FETCHED "
            f"wallet={wallet} "
            f"events={len(raw_events)} "
            f"normalized_trades={len(normalized_trades)}"
        )
        if not normalized_trades:
            return wallet, {
                "wallet": wallet,
                "behaviorStatus": "insufficient_recent_activity",
                "walletScore": None,
                "rawEvents": raw_events,
                "normalizedTrades": normalized_trades,
            }

        temp_scores = compute_wallet_scores(normalized_trades)
        temp_score = next(
            (
                score
                for score in temp_scores
                if _normalize_wallet(score.get("wallet")) == wallet
            ),
            None,
        )
        if temp_score is None:
            return wallet, {
                "wallet": wallet,
                "behaviorStatus": "insufficient_recent_activity",
                "walletScore": None,
                "rawEvents": raw_events,
                "normalizedTrades": normalized_trades,
            }

        return wallet, {
            "wallet": wallet,
            "behaviorStatus": "sufficient",
            "walletScore": temp_score,
            "rawEvents": raw_events,
            "normalizedTrades": normalized_trades,
        }

    tasks = [asyncio.create_task(_load_one(target)) for target in target_wallets]
    for task in asyncio.as_completed(tasks):
        wallet, payload = await task
        results[wallet] = payload

    return results


def _attach_shadow_outputs(
    wallet_scores: list[dict[str, Any]],
    shadow_targets: list[dict[str, Any]],
    shadow_positions: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched: list[dict[str, Any]] = []
    shadow_rows: list[dict[str, Any]] = []
    wallet_score_map = {
        _normalize_wallet(score.get("wallet")): score
        for score in wallet_scores
        if score.get("wallet")
    }

    for target in shadow_targets:
        wallet = _normalize_wallet(target.get("wallet"))
        shadow_source = target.get("source") or "global_wallet_scores"
        score = target.get("walletScore") or wallet_score_map.get(wallet)
        shadow_payload = shadow_positions.get(wallet)
        if shadow_payload is None:
            continue

        closed_positions = shadow_payload.get("closed_positions") or []
        shadow_error = shadow_payload.get("error")
        behavior_status = target.get("behaviorStatus") or "sufficient"
        if shadow_error:
            shadow_skill = {
                "wallet": wallet,
                "skillStatus": "error",
                "error": shadow_error,
            }
            shadow_robust = None
            shadow_rows.append(
                {
                    "wallet": wallet,
                    "walletQualityScore": score.get("walletQualityScore") if score else None,
                    "classification": score.get("classification") if score else None,
                    "shadowSource": shadow_source,
                    "shadowSkill": shadow_skill,
                    "shadowMetaEvaluation": None,
                    "shadowRobustEvaluation": None,
                    "behaviorStatus": "error",
                    "generatedAt": (score.get("generatedAt") if score else None) or datetime.now(timezone.utc).isoformat(),
                }
            )
            continue

        if not closed_positions:
            shadow_skill = {"skillStatus": "insufficient"}
            shadow_meta = (
                None
                if shadow_source == "targeted_wallet_activity" and behavior_status == "insufficient_recent_activity"
                else (
                    compute_shadow_meta_evaluation(int(score.get("walletQualityScore") or 0), shadow_skill)
                    if score is not None
                    else None
                )
            )
            behavior_status = target.get("behaviorStatus") or (
                "insufficient_recent_activity" if shadow_source == "targeted_wallet_activity" else "insufficient"
            )
        else:
            try:
                shadow_skill = compute_wallet_skill(wallet, closed_positions)
            except Exception as error:
                shadow_skill = {
                    "wallet": wallet,
                    "skillStatus": "error",
                    "error": _safe_error_message(error),
                }
                shadow_meta = None
                behavior_status = "error"
            else:
                behavior_score = int(score.get("walletQualityScore") or 0) if score else 0
                shadow_meta = (
                    compute_shadow_meta_evaluation(behavior_score, shadow_skill)
                    if score is not None
                    else None
                )
                behavior_status = target.get("behaviorStatus") or ("sufficient" if shadow_skill.get("skillStatus") == "sufficient" else "limited")

        behavior_score = int(score.get("walletQualityScore") or 0) if score else 0
        try:
            shadow_robust = compute_shadow_robust_evaluation(behavior_score, shadow_skill)
        except Exception:
            shadow_robust = None

        if shadow_robust is not None:
            print(
                "SMART_MONEY_SKILL_SCORED "
                f"wallet={wallet} "
                f"behavior={behavior_score} "
                f"skill={shadow_skill.get('skillScore', 0)} "
                f"meta={shadow_meta.get('shadowMetaScore', 0) if shadow_meta else 0} "
                f"status={shadow_skill.get('skillStatus')} "
                f"recommendation={shadow_meta.get('shadowRecommendation') if shadow_meta else 'none'}"
            )
            print(
                "SMART_MONEY_SKILL_ROBUST_SCORED "
                f"wallet={wallet} "
                f"raw_skill={shadow_skill.get('skillScore', 0)} "
                f"robust_skill={shadow_robust.get('robustSkillScore', 0)} "
                f"without_top={shadow_robust.get('skillScoreWithoutTopWinner', 0)} "
                f"concentration={shadow_robust.get('pnlConcentrationLevel')} "
                f"robust_meta={shadow_robust.get('shadowRobustMetaScore', 0)} "
                f"recommendation={shadow_robust.get('shadowRobustRecommendation')}"
            )

        shadow_rows.append(
            {
                "wallet": wallet,
                "walletQualityScore": score.get("walletQualityScore") if score else None,
                "classification": score.get("classification") if score else None,
                "shadowSource": shadow_source,
                "shadowSkill": shadow_skill,
                "shadowMetaEvaluation": shadow_meta,
                "shadowRobustEvaluation": shadow_robust,
                "behaviorStatus": behavior_status,
                "generatedAt": (score.get("generatedAt") if score else None) or datetime.now(timezone.utc).isoformat(),
            }
        )

    return wallet_scores, shadow_rows


async def _run_shadow_cohort_phase(
    *,
    run_id: str,
    wallet_scores: list[dict[str, Any]],
    phase_one_shadow_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    if not SHADOW_COHORT_ENABLED:
        return {}

    source_payloads = load_whale_finder_outputs()
    cohort = build_shadow_wallet_cohort(
        wallet_scores,
        active_health=source_payloads.get("active_wallet_health") or [],
        benchmark_wallets=SHADOW_BENCHMARK_WALLETS,
        priority_wallets=SKILL_PRIORITY_WALLETS if SHADOW_INCLUDE_PRIORITY_WALLETS else "",
        global_candidates=source_payloads.get("global_candidates") or [],
        replacement_recommendations=source_payloads.get("replacement_recommendations") or [],
        include_active_wallets=SHADOW_INCLUDE_ACTIVE_WALLETS,
        include_priority_wallets=SHADOW_INCLUDE_PRIORITY_WALLETS,
        include_w_finder_candidates=SHADOW_INCLUDE_WHALE_FINDER_CANDIDATES,
        max_candidates_per_run=SHADOW_MAX_CANDIDATES_PER_RUN,
        max_total_wallets_per_run=SHADOW_MAX_TOTAL_WALLETS_PER_RUN,
        min_candidate_score=SHADOW_MIN_CANDIDATE_SCORE,
    )

    active_count = sum(1 for item in cohort if "active" in (item.get("roles") or []))
    benchmark_count = sum(1 for item in cohort if "benchmark" in (item.get("roles") or []))
    candidate_count = sum(
        1
        for item in cohort
        if "candidate" in (item.get("roles") or []) or "replacement_candidate" in (item.get("roles") or [])
    )
    print(
        "SMART_MONEY_SHADOW_COHORT_BUILT "
        f"active={active_count} "
        f"benchmark={benchmark_count} "
        f"candidate={candidate_count} "
        f"unique={len(cohort)}"
    )

    wallet_score_map = {
        _normalize_wallet(score.get("wallet")): score
        for score in wallet_scores
        if score.get("wallet")
    }
    shadow_one_map = {
        _normalize_wallet(row.get("wallet")): row
        for row in phase_one_shadow_rows
        if row.get("wallet")
    }

    missing_wallets = [
        row
        for row in cohort
        if _normalize_wallet(row.get("wallet")) not in wallet_score_map
        and _normalize_wallet(row.get("wallet")) not in shadow_one_map
    ]
    targeted_behaviors = await _fetch_targeted_wallet_behaviors(missing_wallets)

    for row in cohort:
        wallet = _normalize_wallet(row.get("wallet"))
        if wallet in wallet_score_map:
            row["behaviorQualityScore"] = wallet_score_map[wallet].get("walletQualityScore")
            row["classification"] = wallet_score_map[wallet].get("classification")
            row["behaviorStatus"] = "sufficient"
            row["walletScore"] = wallet_score_map[wallet]
        elif wallet in targeted_behaviors:
            payload = targeted_behaviors[wallet]
            row["behaviorQualityScore"] = (
                payload.get("walletScore", {}) or {}
            ).get("walletQualityScore")
            row["classification"] = (
                payload.get("walletScore", {}) or {}
            ).get("classification")
            row["behaviorStatus"] = payload.get("behaviorStatus") or "insufficient_recent_activity"
            row["walletScore"] = payload.get("walletScore")
        elif wallet in shadow_one_map:
            phase_one_row = shadow_one_map[wallet]
            row["behaviorQualityScore"] = phase_one_row.get("walletQualityScore")
            row["classification"] = phase_one_row.get("classification")
            row["behaviorStatus"] = phase_one_row.get("behaviorStatus")
            row["walletScore"] = {
                "walletQualityScore": phase_one_row.get("walletQualityScore"),
                "classification": phase_one_row.get("classification"),
                "generatedAt": phase_one_row.get("generatedAt"),
            }
        else:
            row["behaviorStatus"] = row.get("behaviorStatus") or "insufficient_recent_activity"
            row["walletScore"] = None

    selected_wallets = [
        {
            "wallet": row.get("wallet"),
            "walletScore": row.get("walletScore"),
            "behaviorStatus": row.get("behaviorStatus"),
            "source": (
                "global_wallet_scores"
                if row.get("wallet") in wallet_score_map
                else "targeted_wallet_activity"
            ),
        }
        for row in cohort
    ]
    shadow_positions = await _fetch_shadow_positions(selected_wallets)

    shadow_rows: list[dict[str, Any]] = []
    for row in cohort:
        wallet = _normalize_wallet(row.get("wallet"))
        score_record = wallet_score_map.get(wallet)
        targeted_payload = targeted_behaviors.get(wallet) or {}
        behavior_score = int(
            (score_record or {}).get("walletQualityScore")
            or ((targeted_payload.get("walletScore") or {}).get("walletQualityScore"))
            or row.get("behaviorQualityScore")
            or 0
        )
        closed_payload = shadow_positions.get(wallet) or {}
        closed_positions = closed_payload.get("closed_positions") or []
        print(
            "SMART_MONEY_SHADOW_WALLET_STARTED "
            f"wallet={wallet} "
            f"roles={','.join(row.get('roles') or [])} "
            f"source={','.join(row.get('sources') or [])}"
        )
        try:
            shadow_skill = compute_wallet_skill(wallet, closed_positions)
        except Exception as error:
            shadow_rows.append(
                {
                    "wallet": wallet,
                    "displayName": row.get("displayName"),
                    "roles": row.get("roles") or [],
                    "profiles": row.get("profiles") or [],
                    "sources": row.get("sources") or [],
                    "aliases": row.get("aliases") or [],
                    "classification": row.get("classification"),
                    "behaviorQualityScore": behavior_score,
                    "shadowSource": "global_wallet_scores" if score_record else "targeted_wallet_activity",
                    "shadowSkill": {
                        "wallet": wallet,
                        "skillStatus": "error",
                        "error": _safe_error_message(error),
                    },
                    "shadowMetaEvaluation": None,
                    "shadowRobustEvaluation": None,
                    "behaviorStatus": "error",
                    "generatedAt": iso_now(),
                    "candidateScore": row.get("candidateScore"),
                    "candidateStatus": row.get("candidateStatus"),
                    "replacementFor": row.get("replacementFor"),
                }
            )
            print(
                "SMART_MONEY_SHADOW_WALLET_FAILED "
                f"wallet={wallet} "
                f"error={error.__class__.__name__}"
            )
            continue

        shadow_meta = compute_shadow_meta_evaluation(behavior_score, shadow_skill)
        shadow_robust = compute_shadow_robust_evaluation(behavior_score, shadow_skill)
        shadow_rows.append(
            {
                "wallet": wallet,
                "displayName": row.get("displayName"),
                "roles": row.get("roles") or [],
                "profiles": row.get("profiles") or [],
                "sources": row.get("sources") or [],
                "aliases": row.get("aliases") or [],
                "classification": row.get("classification"),
                "behaviorQualityScore": behavior_score,
                "shadowSource": "global_wallet_scores" if score_record else "targeted_wallet_activity",
                "shadowSkill": shadow_skill,
                "shadowMetaEvaluation": shadow_meta,
                "shadowRobustEvaluation": shadow_robust,
                "behaviorStatus": row.get("behaviorStatus") or "sufficient",
                "generatedAt": (
                    (score_record or {}).get("generatedAt")
                    or ((targeted_behaviors.get(wallet) or {}).get("walletScore") or {}).get("generatedAt")
                    or iso_now()
                ),
                "candidateScore": row.get("candidateScore"),
                "candidateStatus": row.get("candidateStatus"),
                "replacementFor": row.get("replacementFor"),
            }
        )

    history_paths = resolve_history_paths()
    if history_paths["history_file"]:
        history_records = [
            build_shadow_history_record(run_id=run_id, wallet_row=row)
            for row in shadow_rows
        ]
        append_shadow_history(history_paths["history_file"], history_records)
        write_shadow_run_snapshot(
            history_paths["runs_dir"],
            run_id,
            {
                "runId": run_id,
                "generatedAt": iso_now(),
                "engineVersion": "smart_money_shadow_v1",
                "walletsRequested": len(cohort),
                "walletsCompleted": sum(1 for row in shadow_rows if (row.get("shadowSkill") or {}).get("skillStatus") != "error"),
                "walletsFailed": sum(1 for row in shadow_rows if (row.get("shadowSkill") or {}).get("skillStatus") == "error"),
                "config": {
                    "maxWallets": SHADOW_MAX_TOTAL_WALLETS_PER_RUN,
                    "maxClosedPositions": SKILL_MAX_CLOSED_POSITIONS,
                    "maxCandidates": SHADOW_MAX_CANDIDATES_PER_RUN,
                },
                "wallets": shadow_rows,
            },
        )
        print(
            "SMART_MONEY_SHADOW_HISTORY_WRITTEN "
            f"path={history_paths['history_file']} "
            f"rows={len(history_records)}"
        )

    longitudinal = compute_longitudinal_metrics(load_history_file(history_paths["history_file"]))
    for row in shadow_rows:
        wallet = _normalize_wallet(row.get("wallet"))
        metrics = longitudinal.get(wallet) or {}
        print(
            "SMART_MONEY_SHADOW_WALLET_COMPLETED "
            f"wallet={wallet} "
            f"robust_meta={(row.get('shadowRobustEvaluation') or {}).get('shadowRobustMetaScore', 0)} "
            f"longitudinal={metrics.get('longitudinalComparisonScore')} "
            f"runs={metrics.get('runCount', 0)}"
        )

    general_rankings = build_wallet_general_rankings(shadow_rows, longitudinal)
    category_rankings = build_wallet_category_rankings(shadow_rows)
    comparison_summary = build_wallet_comparison_summary(shadow_rows, longitudinal)

    save_json("wallet_shadow_rankings.json", general_rankings)
    save_json("wallet_category_rankings.json", category_rankings)
    save_json("wallet_comparison_summary.json", comparison_summary)
    print(
        "SMART_MONEY_SHADOW_RANKINGS_WRITTEN "
        f"general={len(general_rankings)} "
        f"categories={sum(len(rows) for rows in category_rankings.values())}"
    )
    print(
        "SMART_MONEY_SHADOW_COMPARISONS_WRITTEN "
        f"comparisons={len(comparison_summary.get('comparisons') or [])} "
        f"sufficient={comparison_summary.get('sufficient', 0)}"
    )

    return {
        "cohort": cohort,
        "shadow_rows": shadow_rows,
        "longitudinal": longitudinal,
        "general_rankings": general_rankings,
        "category_rankings": category_rankings,
        "comparison_summary": comparison_summary,
    }


def build_noise_scores(wallet_scores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "wallet": score["wallet"],
            "noiseScore": score.get("noiseScore", 0),
            "noiseLevel": score.get("noiseLevel", "LOW_NOISE"),
            "riskFlags": score.get("riskFlags", []),
            "generatedAt": score.get("generatedAt"),
        }
        for score in wallet_scores
    ]


def build_run_summary(
    *,
    trades_fetched: int,
    trades_deduped: int,
    wallet_scores: list[dict[str, Any]],
    market_trails: list[dict[str, Any]],
) -> dict[str, Any]:
    summary = {
        "tradesFetched": trades_fetched,
        "tradesDeduped": trades_deduped,
        "walletsScored": len(wallet_scores),
        "marketsScored": len(market_trails),
    }
    summary["rawSummary"] = {
        "walletsScored": len(wallet_scores),
        "marketsScored": len(market_trails),
        "walletClassificationCounts": dict(Counter(score["classification"] for score in wallet_scores)),
        "marketStatusCounts": dict(Counter(item["status"] for item in market_trails)),
    }
    return summary


async def execute_engine() -> dict[str, Any]:
    trades = await fetch_recent_activity()
    deduped_trades = dedupe_trades(trades)
    wallet_scores = compute_wallet_scores(deduped_trades)
    save_json("wallet_scores.json", wallet_scores)

    noise_scores = build_noise_scores(wallet_scores)
    save_json("noise_scores.json", noise_scores)

    shadow_rows: list[dict[str, Any]] = []
    if SKILL_SHADOW_ENABLED:
        shadow_targets = build_shadow_wallet_targets(wallet_scores)
        targeted_wallets = [target for target in shadow_targets if target.get("source") == "targeted_wallet_activity"]
        targeted_behaviors = await _fetch_targeted_wallet_behaviors(targeted_wallets)
        for target in shadow_targets:
            wallet = _normalize_wallet(target.get("wallet"))
            if target.get("source") == "targeted_wallet_activity":
                targeted_payload = targeted_behaviors.get(wallet) or {}
                target["behaviorStatus"] = targeted_payload.get("behaviorStatus") or "insufficient_recent_activity"
                target["walletScore"] = targeted_payload.get("walletScore")
            else:
                target["behaviorStatus"] = "sufficient"

        selected_wallets = shadow_targets
        shadow_positions = await _fetch_shadow_positions(selected_wallets)
        wallet_scores, shadow_rows = _attach_shadow_outputs(wallet_scores, selected_wallets, shadow_positions)
        save_json("wallet_scores.json", wallet_scores)
        save_json("wallet_skill_shadow.json", shadow_rows)
        scored_count = sum(1 for row in shadow_rows if row.get("shadowMetaEvaluation") is not None)
        failed_count = sum(1 for row in shadow_rows if (row.get("shadowSkill") or {}).get("skillStatus") == "error")
        print(
            "SMART_MONEY_SKILL_SHADOW_COMPLETED "
            f"requested={len(selected_wallets)} "
            f"scored={scored_count} "
            f"failed={failed_count}"
        )

    market_trails = build_market_capital_trails(
        trades=deduped_trades,
        wallet_scores=wallet_scores,
    )
    save_json("market_capital_trails.json", market_trails)

    estela_capital = build_estela_capital_by_market(
        trades=deduped_trades,
        market_trails=market_trails,
        wallet_scores=wallet_scores,
    )
    save_json("estela_capital_by_market.json", estela_capital)

    return {
        "trades": trades,
        "deduped_trades": deduped_trades,
        "wallet_scores": wallet_scores,
        "noise_scores": noise_scores,
        "shadow_rows": shadow_rows,
        "market_trails": market_trails,
        "estela_capital": estela_capital,
    }


async def run() -> list[dict]:
    result = await execute_engine()
    return result["wallet_scores"]


def log_summary(wallet_scores: list[dict]) -> None:
    counts = Counter(score["classification"] for score in wallet_scores)
    noise_counts = Counter(score.get("noiseLevel", "LOW_NOISE") for score in wallet_scores)
    print("wallets_scored:", len(wallet_scores))
    print("wallets_noise_scored:", len(wallet_scores))
    print("low_noise:", noise_counts.get("LOW_NOISE", 0))
    print("medium_noise:", noise_counts.get("MEDIUM_NOISE", 0))
    print("high_noise:", noise_counts.get("HIGH_NOISE", 0))
    print("signal_wallets:", counts.get(SIGNAL_WALLET, 0))
    print("noisy_wallets:", counts.get(WHALE_BUT_NOISY, 0))
    print("insufficient_history:", counts.get(INSUFFICIENT_HISTORY, 0))


def log_market_trail_summary(market_trails: list[dict]) -> None:
    summary = summarize_market_trails(market_trails)
    print("markets_scored:", summary["markets_scored"])
    print("direct_strong:", summary["direct_strong"])
    print("direct_weak:", summary["direct_weak"])
    print("contradictory_flow:", summary["contradictory_flow"])
    print("no_reliable_trail:", summary["no_reliable_trail"])


async def main() -> None:
    run_id = start_engine_run()

    try:
        result = await execute_engine()
        try:
            shadow_phase = await _run_shadow_cohort_phase(
                run_id=run_id,
                wallet_scores=result["wallet_scores"],
                phase_one_shadow_rows=result["shadow_rows"],
            )
            result["shadow_phase"] = shadow_phase
        except Exception as shadow_exc:
            print(f"SMART_MONEY_SHADOW_COHORT_FAILED error={_safe_error_message(shadow_exc)}")
        adaptive_signal_wallet_roster = None
        if COPYABILITY_SHADOW_ENABLED and SIGNAL_WALLET_ROSTER_ENABLED:
            adaptive_signal_wallet_roster = await asyncio.to_thread(
                build_adaptive_signal_wallet_roster,
                benchmark_wallet=SIGNAL_WALLET_BENCHMARK_WALLET,
                target_roster_size=SIGNAL_WALLET_ROSTER_SIZE,
                priority_wallets=SKILL_PRIORITY_WALLETS,
                wallet_scores=result["wallet_scores"],
                shadow_rows=(result.get("shadow_phase") or {}).get("shadow_rows") or result.get("shadow_rows") or [],
                copyability_seed_trades=result["deduped_trades"],
                output_dir=resolve_output_dir(),
            )
            write_adaptive_signal_wallet_roster(adaptive_signal_wallet_roster)
            if COPYABILITY_MAX_WALLETS_PER_RUN < SIGNAL_WALLET_ROSTER_SIZE:
                print(
                    "SMART_MONEY_WALLET_ROSTER_LIMIT_WARNING "
                    f"copyability_max={COPYABILITY_MAX_WALLETS_PER_RUN} "
                    f"roster_size={SIGNAL_WALLET_ROSTER_SIZE}"
                )
        if COPYABILITY_SHADOW_ENABLED:
            try:
                copyability_phase = await run_trade_copyability_shadow(
                    run_id=run_id,
                    wallet_scores=result["wallet_scores"],
                    shadow_phase=result.get("shadow_phase"),
                    deduped_trades=result["deduped_trades"],
                    wallet_roster=adaptive_signal_wallet_roster,
                )
                result["copyability_phase"] = copyability_phase
                try:
                    copyability_quality = await asyncio.to_thread(
                        build_adaptive_signal_wallet_quality,
                        copyability_phase=copyability_phase,
                        wallet_roster=adaptive_signal_wallet_roster,
                        benchmark_wallet=SIGNAL_WALLET_BENCHMARK_WALLET,
                        output_dir=resolve_output_dir(),
                    )
                    write_adaptive_signal_wallet_quality(copyability_quality)
                    result["copyability_quality_phase"] = copyability_quality
                except Exception as quality_exc:
                    print(
                        "SMART_MONEY_WALLET_QUALITY_FAILED "
                        f"error={_safe_error_message(quality_exc)} "
                        f"run_id={run_id}"
                    )
                    result["copyability_quality_phase"] = {
                        "runId": run_id,
                        "generatedAt": datetime.now(timezone.utc).isoformat(),
                        "benchmarkWallet": SIGNAL_WALLET_BENCHMARK_WALLET,
                        "walletCount": 0,
                        "walletQualityRows": [],
                        "walletResults": [],
                        "status": "failed",
                        "error": _safe_error_message(quality_exc),
                    }
            except Exception as copyability_exc:
                print(
                    "SMART_MONEY_COPYABILITY_FAILED "
                    f"error={copyability_exc.__class__.__name__} "
                    f"run_id={run_id}"
                )
                copyability_shadow = {
                    "runId": run_id,
                    "generatedAt": datetime.now(timezone.utc).isoformat(),
                    "phase": "2_full_shadow",
                    "status": "failed",
                    "error": _safe_error_message(copyability_exc),
                    "walletsRequested": len((result.get("shadow_phase") or {}).get("cohort") or result.get("wallet_scores") or []),
                    "walletsCompleted": 0,
                    "walletsFailed": 0,
                    "walletResults": [],
                    "clusters": [],
                }
                write_trade_copyability_shadow(copyability_shadow)
        wallet_scores = result["wallet_scores"]
        market_trails = result["market_trails"]
        summary = build_run_summary(
            trades_fetched=len(result["trades"]),
            trades_deduped=len(result["deduped_trades"]),
            wallet_scores=wallet_scores,
            market_trails=market_trails,
        )
        upsert_wallet_scores(run_id, wallet_scores)
        upsert_capital_trails(run_id, result["estela_capital"])
        finish_engine_run(run_id, summary)
        log_summary(wallet_scores)
        log_market_trail_summary(market_trails)
    except Exception as exc:
        fail_engine_run(run_id, str(exc))
        raise


if __name__ == "__main__":
    asyncio.run(main())
