from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

try:  # pragma: no cover - support package and script-style imports
    from ..whale_finder.main import ACTIVE_WALLETS as WHALE_FINDER_ACTIVE_WALLETS
except Exception:  # pragma: no cover
    WHALE_FINDER_ACTIVE_WALLETS = {}


WALLET_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
DEFAULT_WHALE_FINDER_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "whale_finder" / "output"


def _normalize_wallet(value: Any) -> str:
    return str(value or "").strip().lower()


def _is_valid_wallet(value: str) -> bool:
    return bool(WALLET_RE.match(value or ""))


def _dedupe_append(items: list[str], value: str) -> None:
    if value and value not in items:
        items.append(value)


def _ensure_entry(cohort: dict[str, dict[str, Any]], wallet: str) -> dict[str, Any]:
    wallet = _normalize_wallet(wallet)
    entry = cohort.get(wallet)
    if entry is None:
        entry = {
            "_order": len(cohort),
            "wallet": wallet,
            "displayName": wallet,
            "profiles": [],
            "roles": [],
            "sources": [],
            "aliases": [],
            "candidateScore": None,
            "candidateStatus": None,
            "replacementFor": None,
        }
        cohort[wallet] = entry
    return entry


def _add_role(entry: dict[str, Any], role: str) -> None:
    roles = entry.setdefault("roles", [])
    if role not in roles:
        roles.append(role)


def _add_source(entry: dict[str, Any], source: str) -> None:
    sources = entry.setdefault("sources", [])
    if source not in sources:
        sources.append(source)


def _add_profile(entry: dict[str, Any], profile: str | None) -> None:
    if not profile:
        return
    profiles = entry.setdefault("profiles", [])
    if profile not in profiles:
        profiles.append(profile)


def _add_alias(entry: dict[str, Any], alias: str | None) -> None:
    if not alias:
        return
    aliases = entry.setdefault("aliases", [])
    if alias not in aliases:
        aliases.append(alias)


def _safe_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def load_whale_finder_outputs(output_dir: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    base = Path(output_dir) if output_dir else DEFAULT_WHALE_FINDER_OUTPUT_DIR
    return {
        "active_wallet_health": _load_json(base / "active_wallet_health.json", []),
        "global_candidates": _load_json(base / "global_candidates.json", []),
        "replacement_recommendations": _load_json(base / "replacement_recommendations.json", []),
    }


def parse_wallet_specifiers(value: str | list[str] | None) -> list[tuple[str, str | None]]:
    if value is None:
        return []
    if isinstance(value, list):
        raw_items = value
    else:
        raw_items = [part.strip() for part in str(value).split(",")]

    parsed: list[tuple[str, str | None]] = []
    seen: set[str] = set()
    for item in raw_items:
        if not item:
            continue
        wallet, alias = item, None
        if ":" in item:
            wallet, alias = item.split(":", 1)
        wallet = _normalize_wallet(wallet)
        alias = alias.strip() if alias else None
        if not _is_valid_wallet(wallet) or wallet in seen:
            continue
        seen.add(wallet)
        parsed.append((wallet, alias))
    return parsed


def build_shadow_wallet_cohort(
    wallet_scores: list[dict[str, Any]],
    *,
    active_wallets: dict[str, dict[str, Any]] | None = None,
    active_health: list[dict[str, Any]] | None = None,
    benchmark_wallets: str | list[str] | None = None,
    priority_wallets: str | list[str] | None = None,
    global_candidates: list[dict[str, Any]] | None = None,
    replacement_recommendations: list[dict[str, Any]] | None = None,
    include_active_wallets: bool = True,
    include_priority_wallets: bool = True,
    include_w_finder_candidates: bool = True,
    max_candidates_per_run: int = 10,
    max_total_wallets_per_run: int = 20,
    min_candidate_score: float = 0,
) -> list[dict[str, Any]]:
    active_wallets = active_wallets or WHALE_FINDER_ACTIVE_WALLETS
    active_health = active_health or []
    global_candidates = global_candidates or []
    replacement_recommendations = replacement_recommendations or []

    cohort: dict[str, dict[str, Any]] = {}
    wallet_score_map = {
        _normalize_wallet(score.get("wallet")): score
        for score in wallet_scores
        if score.get("wallet")
    }

    def add_wallet(
        *,
        wallet: str,
        role: str,
        source: str,
        display_name: str | None = None,
        profile: str | None = None,
        alias: str | None = None,
        candidate_score: int | None = None,
        candidate_status: str | None = None,
        replacement_for: str | None = None,
    ) -> dict[str, Any] | None:
        wallet = _normalize_wallet(wallet)
        if not _is_valid_wallet(wallet):
            return None
        entry = _ensure_entry(cohort, wallet)
        _add_role(entry, role)
        _add_source(entry, source)
        if display_name and entry.get("displayName") in {None, "", wallet}:
            entry["displayName"] = display_name
        _add_profile(entry, profile)
        _add_alias(entry, alias)
        if candidate_score is not None:
            entry["candidateScore"] = candidate_score
        if candidate_status is not None:
            entry["candidateStatus"] = candidate_status
        if replacement_for is not None:
            entry["replacementFor"] = replacement_for
        return entry

    if include_active_wallets:
        for alias, cfg in active_wallets.items():
            wallet = _normalize_wallet(cfg.get("wallet"))
            add_wallet(
                wallet=wallet,
                role="active",
                source="active_wallet_config",
                display_name=str(cfg.get("name") or wallet),
                profile=str(cfg.get("profile") or "mixed"),
                alias=alias,
            )

        for row in active_health:
            wallet = _normalize_wallet(row.get("wallet"))
            entry = add_wallet(
                wallet=wallet,
                role="active",
                source="whale_finder_active_health",
                display_name=str(row.get("name") or row.get("active_name") or wallet),
                profile=str(row.get("profile") or row.get("category_guess") or "mixed"),
                alias=str(row.get("whale_id") or row.get("active_whale_id") or "") or None,
                candidate_score=_safe_int(row.get("score") or row.get("active_score")),
                candidate_status=str(row.get("status") or row.get("active_status") or "") or None,
            )
            if entry is not None and row.get("hard_flags"):
                entry.setdefault("activeFlags", [])
                for flag in row.get("hard_flags") or []:
                    _dedupe_append(entry["activeFlags"], str(flag))

    for spec_wallet, alias in parse_wallet_specifiers(benchmark_wallets):
        add_wallet(
            wallet=spec_wallet,
            role="benchmark",
            source="shadow_benchmark_wallets",
            display_name=alias or spec_wallet,
            profile="benchmark",
            alias=alias,
        )

    if include_priority_wallets:
        for spec_wallet, alias in parse_wallet_specifiers(priority_wallets):
            add_wallet(
                wallet=spec_wallet,
                role="benchmark",
                source="skill_priority_wallets",
                display_name=alias or spec_wallet,
                profile="priority",
                alias=alias,
            )

    if include_w_finder_candidates:
        scored_candidate_count = 0
        for row in replacement_recommendations:
            if scored_candidate_count >= max_candidates_per_run:
                break
            replacement = row.get("replacement_candidate")
            if not isinstance(replacement, dict):
                continue
            wallet = _normalize_wallet(replacement.get("wallet"))
            if not wallet:
                continue
            add_wallet(
                wallet=wallet,
                role="replacement_candidate",
                source="whale_finder_replacement_recommendations",
                display_name=str(replacement.get("name") or wallet),
                profile=str(replacement.get("profile") or replacement.get("category_guess") or "mixed"),
                candidate_score=_safe_int(replacement.get("score")),
                candidate_status=str(replacement.get("status") or replacement.get("tier") or "") or None,
                replacement_for=str(row.get("active_whale_id") or row.get("active_wallet") or "") or None,
            )
            scored_candidate_count += 1

        for row in global_candidates:
            if scored_candidate_count >= max_candidates_per_run:
                break
            wallet = _normalize_wallet(row.get("wallet"))
            score = _safe_int(row.get("score"))
            if score is not None and score < min_candidate_score:
                continue
            if not wallet:
                continue
            add_wallet(
                wallet=wallet,
                role="candidate",
                source="whale_finder_global_candidates",
                display_name=str(row.get("name") or wallet),
                profile=str(row.get("category_guess") or row.get("profile") or "candidate"),
                candidate_score=score,
                candidate_status=str(row.get("tier") or row.get("status") or "") or None,
            )
            scored_candidate_count += 1

    role_priority = {
        "benchmark": 0,
        "active": 1,
        "replacement_candidate": 2,
        "candidate": 3,
    }
    ordered = sorted(
        cohort.values(),
        key=lambda entry: (
            min((role_priority.get(role, 99) for role in entry.get("roles", [])), default=99),
            int(entry.get("_order", 0)),
        ),
    )

    if len(ordered) > max_total_wallets_per_run:
        ordered = ordered[:max_total_wallets_per_run]

    for entry in ordered:
        wallet = _normalize_wallet(entry.get("wallet"))
        score_record = wallet_score_map.get(wallet)
        if score_record:
            entry.setdefault("behaviorQualityScore", score_record.get("walletQualityScore"))
            entry.setdefault("classification", score_record.get("classification"))
            entry.setdefault("walletScoreSource", "global_wallet_scores")
        entry.pop("_order", None)

    return ordered
