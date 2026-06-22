from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

load_dotenv(override=True)

from services.closing_recheck_candidates_client import fetch_closing_recheck_candidates
from services.closing_recheck_service import (
    ClosingRecheckQuotaExceeded,
    run_closing_recheck_for_candidate,
    should_skip_due_to_open_market,
)
from services.logger_service import get_logger
from services.scoring_service import days_to_close


logger = get_logger("run_closing_rechecks")


PRIORITY_ORDER = {
    "critical": 2,
    "high": 1,
}


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_text(name: str, default: str) -> str:
    value = os.getenv(name)
    if value is None:
        return default
    text = value.strip()
    return text or default


def priority_rank(candidate: dict[str, Any]) -> int:
    priority = str(
        candidate.get("recheckPriority")
        or candidate.get("recheckCandidate", {}).get("recheckPriority")
        or ""
    ).strip().lower()
    return PRIORITY_ORDER.get(priority, 0)


def candidate_days_to_close(candidate: dict[str, Any]) -> int:
    market = candidate.get("market") or candidate.get("marketSnapshot") or {}
    if isinstance(market, dict):
        days_value = market.get("daysToClose")
        if days_value is not None:
            try:
                return int(days_value)
            except (TypeError, ValueError):
                pass
        if market.get("closingTime"):
            return days_to_close(market)
    return 9999


def is_valid_priority(candidate: dict[str, Any], minimum_priority: str) -> bool:
    return priority_rank(candidate) >= PRIORITY_ORDER.get(
        minimum_priority.strip().lower(),
        PRIORITY_ORDER["high"],
    )


def has_comparable_analyses(candidate: dict[str, Any]) -> bool:
    previous_id = candidate.get("previousAnalysisId")
    latest_id = candidate.get("latestAnalysisId")
    previous = candidate.get("previousAnalysis") or {}
    latest = candidate.get("latestAnalysis") or {}

    if not previous_id or not latest_id:
        return False

    if previous_id == latest_id:
        return False

    if not isinstance(previous, dict) or not isinstance(latest, dict):
        return False

    if not previous.get("analysisId") or not latest.get("analysisId"):
        return False

    if not previous.get("thesis") or not latest.get("thesis"):
        return False

    return True


def evaluate_candidate(
    candidate: dict[str, Any],
    *,
    min_priority: str,
    max_days_to_close: int,
) -> tuple[bool, str | None]:
    market_id = candidate.get("marketId")
    if not market_id:
        return False, "missing_market_id"

    if not is_valid_priority(candidate, min_priority):
        return False, f"{market_id}:priority"

    if should_skip_due_to_open_market(candidate):
        return False, f"{market_id}:closed"

    if not has_comparable_analyses(candidate):
        return False, f"{market_id}:insufficient_history"

    if candidate_days_to_close(candidate) > max_days_to_close:
        return False, f"{market_id}:too_far_from_close"

    return True, None


def filter_candidates(
    candidates: list[dict[str, Any]],
    *,
    min_priority: str,
    max_days_to_close: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    selected: list[dict[str, Any]] = []
    skipped: list[str] = []

    for candidate in candidates:
        keep, reason = evaluate_candidate(
            candidate,
            min_priority=min_priority,
            max_days_to_close=max_days_to_close,
        )
        if keep:
            selected.append(candidate)
        elif reason:
            skipped.append(reason)

    return selected, skipped


def select_candidates(
    candidates: list[dict[str, Any]],
    *,
    min_priority: str,
    max_days_to_close: int,
    max_per_run: int,
) -> list[dict[str, Any]]:
    selected, _skipped = filter_candidates(
        candidates,
        min_priority=min_priority,
        max_days_to_close=max_days_to_close,
    )

    selected.sort(
        key=lambda item: (
            -priority_rank(item),
            -float(item.get("recheckScore") or 0),
            candidate_days_to_close(item),
        )
    )

    return selected[:max_per_run]


def format_candidate(candidate: dict[str, Any]) -> str:
    market = candidate.get("market") or {}
    return (
        f"marketId={candidate.get('marketId')} | "
        f"latestAnalysisId={candidate.get('latestAnalysisId')} | "
        f"priority={candidate.get('recheckPriority') or candidate.get('recheckCandidate', {}).get('recheckPriority')} | "
        f"daysToClose={candidate_days_to_close(candidate)} | "
        f"title={market.get('title')}"
    )


def run_closing_rechecks_cycle(*, dry_run: bool = False) -> dict[str, Any]:
    logger.info("Closing recheck cycle started")
    print("[CLOSING_RECHECK_RUN] started")

    enabled = env_bool("CLOSING_RECHECK_ENABLED", False)
    if not enabled and not dry_run:
        summary = {
            "candidates": 0,
            "selected": 0,
            "saved": 0,
            "skipped": 0,
            "errors": 0,
            "disabled": True,
        }
        print("[CLOSING_RECHECK_SKIP] reason=disabled")
        print(
            "[CLOSING_RECHECK_RUN] finished "
            "candidates=0 selected=0 saved=0 skipped=0 errors=0"
        )
        return summary

    days = env_int("CLOSING_RECHECK_MAX_DAYS_TO_CLOSE", 3)
    max_per_run = env_int("CLOSING_RECHECK_MAX_PER_RUN", 2)
    max_per_category = env_int("CLOSING_RECHECK_MAX_PER_CATEGORY", 2)
    freshness_hours = env_int("CLOSING_RECHECK_FRESHNESS_HOURS", 12)
    max_retries = env_int("CLOSING_RECHECK_MAX_RETRIES", 2)
    request_timeout_seconds = env_int("CLOSING_RECHECK_REQUEST_TIMEOUT_SECONDS", 30)
    min_priority = env_text("CLOSING_RECHECK_MIN_PRIORITY", "HIGH")

    try:
        candidates = fetch_closing_recheck_candidates(
            days=days,
            limit=max_per_run * 5,
            max_per_category=max_per_category,
            timeout_seconds=request_timeout_seconds,
        )
    except Exception as error:
        print(f"[CLOSING_RECHECK_ERROR] marketId=unknown error={error}")
        raise

    filtered_candidates, skipped_reasons = filter_candidates(
        candidates,
        min_priority=min_priority,
        max_days_to_close=days,
    )

    selected = select_candidates(
        filtered_candidates,
        min_priority=min_priority,
        max_days_to_close=days,
        max_per_run=max_per_run,
    )

    print(
        f"[CLOSING_RECHECK_RUN] candidates={len(candidates)} selected={len(selected)} "
        f"dry_run={dry_run} max_per_run={max_per_run}"
    )

    for reason in skipped_reasons:
        print(f"[CLOSING_RECHECK_SKIP] reason={reason}")

    for candidate in selected:
        print(f"[CLOSING_RECHECK_CANDIDATE] selected {format_candidate(candidate)}")

    if dry_run:
        print(
            f"[CLOSING_RECHECK_RUN] finished candidates={len(candidates)} "
            f"selected={len(selected)} saved=0 skipped={len(candidates) - len(selected)} errors=0"
        )
        return {
            "candidates": len(candidates),
            "selected": len(selected),
            "saved": 0,
            "skipped": len(candidates) - len(selected),
            "errors": 0,
            "dry_run": True,
        }

    saved = 0
    skipped = len(candidates) - len(selected)
    errors = 0

    for candidate in selected:
        market_id = candidate.get("marketId") or "unknown"
        try:
            result = run_closing_recheck_for_candidate(
                candidate,
                freshness_hours=freshness_hours,
                max_retries=max_retries,
                source="automatic_worker",
                persist=True,
            )

            if result.get("status") == "skipped":
                skipped += 1
                print(
                    f"[CLOSING_RECHECK_SKIP] reason={result.get('reason')} marketId={market_id}"
                )
                continue

            saved += 1
            print(
                f"[CLOSING_RECHECK_MODEL] provider={result.get('provider')} "
                f"model={result.get('model')} fallback_used={result.get('fallback_used')}"
            )
            saved_row = result.get("saved_row") or {}
            print(f"[CLOSING_RECHECK_PERSIST] saved id={saved_row.get('id')}")
        except ClosingRecheckQuotaExceeded as error:
            errors += 1
            print(f"[CLOSING_RECHECK_ERROR] marketId={market_id} error={error}")
            logger.error("Quota error detected, stopping cycle: %s", error)
            break
        except Exception as error:
            errors += 1
            print(f"[CLOSING_RECHECK_ERROR] marketId={market_id} error={error}")
            logger.error("Candidate failed but cycle continues: %s", error)
            continue

    print(
        f"[CLOSING_RECHECK_RUN] finished candidates={len(candidates)} "
        f"selected={len(selected)} saved={saved} skipped={skipped} errors={errors}"
    )

    return {
        "candidates": len(candidates),
        "selected": len(selected),
        "saved": saved,
        "skipped": skipped,
        "errors": errors,
        "dry_run": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run closing rechecks as a separate DeepEngine job."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Select and print candidates without calling the model or persisting.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle explicitly. This is the default behavior.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_closing_rechecks_cycle(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
