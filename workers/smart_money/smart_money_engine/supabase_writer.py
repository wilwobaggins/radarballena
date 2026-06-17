import os
import uuid
from datetime import datetime, timezone
from typing import Any

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

try:
    from supabase import create_client  # type: ignore
except Exception:  # pragma: no cover - optional dependency for local mode
    create_client = None


_CLIENT = None
_WARNED_DISABLED = False
_WARNED_INIT = False
_MARKET_RESOLUTION_CACHE: dict[str, dict[str, Any]] = {}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _warn(message: str) -> None:
    print(f"SMART_MONEY_SUPABASE_WARNING {message}")


def _is_enabled() -> bool:
    return bool(SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY and create_client)


def _warn_disabled_once() -> None:
    global _WARNED_DISABLED
    if _WARNED_DISABLED:
        return
    _WARNED_DISABLED = True
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        _warn("disabled because SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing")
    elif not create_client:
        _warn("disabled because supabase package is not available")


def _get_client():
    global _CLIENT, _WARNED_INIT

    if not _is_enabled():
        _warn_disabled_once()
        return None

    if _CLIENT is None:
        try:
            _CLIENT = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        except Exception as exc:  # pragma: no cover - defensive
            if not _WARNED_INIT:
                _WARNED_INIT = True
                _warn(f"client init failed: {exc}")
            return None

    return _CLIENT


def _execute(table: str, method: str, *args, **kwargs):
    client = _get_client()
    if client is None:
        return None

    try:
        table_client = client.table(table)
        operation = getattr(table_client, method)
        return operation(*args, **kwargs).execute()
    except Exception as exc:
        _warn(f"{table}.{method} failed: {exc}")
        return None


def _update_by_id(table: str, row_id: str, payload: dict[str, Any]):
    client = _get_client()
    if client is None:
        return None

    try:
        return client.table(table).update(payload).eq("id", row_id).execute()
    except Exception as exc:
        _warn(f"{table}.update failed: {exc}")
        return None


def _resolve_market_binding(source_market_id: str) -> tuple[str | None, str]:
    if not source_market_id:
        return None, source_market_id

    cached = _MARKET_RESOLUTION_CACHE.get(source_market_id)
    if cached is not None:
        return cached.get("marketId"), cached.get("externalMarketId") or source_market_id

    client = _get_client()
    if client is None:
        return None, source_market_id

    try:
        response = (
            client.table("markets")
            .select("id, external_market_id")
            .eq("external_market_id", source_market_id)
            .limit(1)
            .execute()
        )
        rows = getattr(response, "data", None) or []
        if rows:
            row = rows[0]
            market_id = row.get("id")
            external_market_id = row.get("external_market_id") or source_market_id
            _MARKET_RESOLUTION_CACHE[source_market_id] = {
                "marketId": market_id,
                "externalMarketId": external_market_id,
            }
            return market_id, external_market_id
    except Exception as exc:
        _warn(f"market resolution failed for {source_market_id}: {exc}")

    _MARKET_RESOLUTION_CACHE[source_market_id] = {
        "marketId": None,
        "externalMarketId": source_market_id,
    }
    return None, source_market_id


def start_engine_run() -> str:
    local_run_id = f"local-{uuid.uuid4()}"
    client = _get_client()
    if client is None:
        print(f"SMART_MONEY_RUN_STARTED run_id={local_run_id} local_only=true")
        return local_run_id

    payload = {
        "status": "started",
    }
    response = _execute("smart_money_engine_runs", "insert", payload)
    rows = getattr(response, "data", None) if response is not None else None
    if rows:
        run_id = rows[0].get("id")
        if run_id:
            print(f"SMART_MONEY_RUN_STARTED run_id={run_id}")
            return str(run_id)

    _warn("run start insert returned no id; using local run id")
    print(f"SMART_MONEY_RUN_STARTED run_id={local_run_id} local_only=true")
    return local_run_id


def finish_engine_run(run_id: str, summary: dict[str, Any]) -> None:
    payload = {
        "status": "completed",
        "finishedAt": _utc_now(),
        "tradesFetched": summary.get("tradesFetched"),
        "tradesDeduped": summary.get("tradesDeduped"),
        "walletsScored": summary.get("walletsScored"),
        "marketsScored": summary.get("marketsScored"),
        "rawSummary": summary.get("rawSummary", summary),
    }
    response = _update_by_id("smart_money_engine_runs", run_id, payload)
    if response is None:
        print(f"SMART_MONEY_RUN_COMPLETED run_id={run_id} local_only=true")
    else:
        print(f"SMART_MONEY_RUN_COMPLETED run_id={run_id}")


def fail_engine_run(run_id: str, error: str) -> None:
    payload = {
        "status": "failed",
        "finishedAt": _utc_now(),
        "errorMessage": error,
    }
    response = _update_by_id("smart_money_engine_runs", run_id, payload)
    if response is None:
        print(f"SMART_MONEY_RUN_FAILED run_id={run_id} local_only=true")
    else:
        print(f"SMART_MONEY_RUN_FAILED run_id={run_id}")


def upsert_wallet_scores(run_id: str, wallet_scores: list[dict[str, Any]]) -> None:
    if not wallet_scores:
        print("SMART_MONEY_WALLET_SCORES_UPSERTED count=0")
        return

    payload: list[dict[str, Any]] = []
    for score in wallet_scores:
        metrics = score.get("metrics") or {}
        payload.append(
            {
                "wallet": score.get("wallet"),
                "classification": score.get("classification"),
                "walletQualityScore": score.get("walletQualityScore"),
                "noiseScore": score.get("noiseScore"),
                "noiseLevel": score.get("noiseLevel"),
                "tradeCount": metrics.get("tradeCount"),
                "totalVolume": metrics.get("totalVolume"),
                "uniqueMarkets": metrics.get("uniqueMarkets"),
                "riskFlags": score.get("riskFlags") or [],
                "rawOutput": score,
                "generatedAt": score.get("generatedAt") or _utc_now(),
                "runId": run_id,
            }
        )

    response = _execute("smart_money_wallet_scores", "upsert", payload, on_conflict="wallet")
    if response is None:
        print(f"SMART_MONEY_WALLET_SCORES_UPSERTED count={len(payload)} local_only=true")
    else:
        print(f"SMART_MONEY_WALLET_SCORES_UPSERTED count={len(payload)}")


def upsert_capital_trails(run_id: str, estela_capital: list[dict[str, Any]]) -> None:
    if not estela_capital:
        print("SMART_MONEY_CAPITAL_TRAILS_UPSERTED count=0")
        return

    payload: list[dict[str, Any]] = []
    for trail in estela_capital:
        source_market_id = str(trail.get("marketId") or "")
        market_id, external_market_id = _resolve_market_binding(source_market_id)
        payload.append(
            {
                "sourceMarketId": source_market_id,
                "marketId": market_id,
                "externalMarketId": external_market_id,
                "marketTitle": trail.get("title") or "",
                "status": trail.get("status"),
                "headline": trail.get("headline"),
                "interpretation": trail.get("interpretation"),
                "confidence": trail.get("confidence"),
                "smartBias": trail.get("smartBias"),
                "qualifiedWalletCount": trail.get("qualifiedWalletCount"),
                "smartMoneyVolume": trail.get("smartMoneyVolume"),
                "riskFlags": trail.get("riskFlags") or [],
                "events": trail.get("events") or [],
                "relatedMarkets": trail.get("relatedMarkets") or [],
                "rawOutput": trail,
                "generatedAt": trail.get("generatedAt") or _utc_now(),
                "runId": run_id,
            }
        )

    response = _execute(
        "smart_money_capital_trails",
        "upsert",
        payload,
        on_conflict="sourceMarketId",
    )
    if response is None:
        print(f"SMART_MONEY_CAPITAL_TRAILS_UPSERTED count={len(payload)} local_only=true")
    else:
        print(f"SMART_MONEY_CAPITAL_TRAILS_UPSERTED count={len(payload)}")
