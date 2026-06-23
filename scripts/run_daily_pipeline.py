from dotenv import load_dotenv

load_dotenv(override=True)

import os
import re
import time
from collections import Counter
from typing import Any

from services import supabase_service as db
from services.context_client import search_context
from services.deterministic_deepbrief_persistence import (
    has_recent_deterministic_fallback,
    persist_deterministic_deepbrief,
)
from services.deepbrief_generator import (
    AllDeepBriefProvidersFailedError,
    build_raw_market_input,
    generate_deepbrief_for_market,
)
from services.error_types import build_error_record
from services.logger_service import get_logger
from services.market_filter import filter_relevant_markets_with_stats
from services.polymarket_client import get_normalized_active_markets
from services.scoring_service import (
    calculate_hybrid_radar_score,
    days_to_close,
    get_signal_label_for_final_score,
    safe_float,
    score_markets,
    sort_markets_by_score,
)


logger = get_logger("run_daily_pipeline")

ANTI_ANCHOR_NOTE = (
    "REINTENTO OBLIGATORIO POR ANCLAJE DE SCORE:\n"
    "Tu respuesta anterior copio el preliminary_radar_score.\n"
    "Eso no esta permitido.\n"
    "Debes generar un radar_score interpretativo independiente.\n"
    "No uses el mismo numero que preliminary_radar_score salvo que justifiques explicitamente una ambiguedad real.\n"
    "Si el mercado es debil, baja el score a 15-40.\n"
    "Si hay senal real, sube a 60-80.\n"
    "Evita 45-55 salvo evidencia balanceada.\n"
    "Devuelve JSON valido."
)

THEME_VERBS = (
    "win",
    "be",
    "become",
    "reach",
    "hit",
    "pass",
    "approve",
    "launch",
    "release",
    "announce",
)

FAMILY_PATTERNS = (
    "2028 democratic presidential nomination",
    "2028 republican presidential nomination",
    "fed rate",
    "bitcoin",
    "bitcoin 150k",
    "ethereum",
    "openai",
    "openai ipo",
    "openai market cap",
    "nvidia",
    "tariff",
    "ceasefire",
    "fannie mae",
    "freddie mac",
    "colombian presidential election",
    "taiwan blockade",
    "taiwan invasion",
    "netanyahu",
)

PRIORITY_BUCKETS = [
    ["macro", "economy"],
    ["geopolitics"],
    ["crypto"],
    ["technology", "ai"],
    ["regulation", "business"],
    ["politics"],
    ["world_events", "science", "culture"],
]

CANDIDATE_POOL_BUCKET_PRIORITY = [
    ["macro", "economy"],
    ["geopolitics"],
    ["crypto"],
    ["technology", "ai"],
    ["regulation", "business"],
    ["world_events", "science", "culture"],
]


def env_int(name: str, default: int) -> int:
    value = os.getenv(name)

    if not value:
        return default

    try:
        return int(value)
    except ValueError:
        return default


def env_positive_int(name: str, default: int) -> int:
    value = env_int(name, default)
    return value if value > 0 else default


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None or value == "":
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False

    return default


def deterministic_fallback_enabled() -> bool:
    return env_bool("DETERMINISTIC_FALLBACK_ENABLED", False)


def deterministic_fallback_freshness_hours() -> int:
    return env_positive_int("DETERMINISTIC_FALLBACK_FRESHNESS_HOURS", 24)


def maybe_persist_deterministic_fallback(
    *,
    market: dict[str, Any],
    pipeline_run_id: str,
    provider_attempts: list[dict[str, Any]] | None,
    fallback_reason: str,
) -> dict[str, Any]:
    market_id = market.get("id")
    enabled = deterministic_fallback_enabled()
    freshness_hours = deterministic_fallback_freshness_hours()

    logger.info(
        "[DETERMINISTIC_FALLBACK] marketId=%s enabled=%s trigger=%s",
        market_id,
        enabled,
        fallback_reason,
    )

    if not enabled:
        return {"status": "disabled", "reason": "deterministic_fallback_disabled"}

    if market_id and has_recent_deterministic_fallback(
        db=db,
        market_db_id=market_id,
        hours=freshness_hours,
    ):
        logger.info(
            "[DETERMINISTIC_FALLBACK] marketId=%s action=skipped_recent freshnessHours=%s",
            market_id,
            freshness_hours,
        )
        return {
            "status": "skipped",
            "reason": "skipped_recent_deterministic",
            "marketId": market_id,
        }

    try:
        saved_row = persist_deterministic_deepbrief(
            db=db,
            market_db_id=market_id,
            market=market,
            preliminary_score=market.get("preliminary_radar_score"),
            score_breakdown=market.get("score_breakdown") or {},
            selection_reason=market.get("selection_reason"),
            fallback_reason=fallback_reason,
            pipeline_run_id=pipeline_run_id,
            provider_attempts=provider_attempts or [],
        )
        logger.info(
            "[DETERMINISTIC_FALLBACK] marketId=%s action=persisted deepbriefId=%s",
            market_id,
            saved_row.get("id"),
        )
        return {
            "status": "saved",
            "saved_row": saved_row,
            "deepbrief": saved_row,
            "marketId": market_id,
        }
    except Exception as error:
        logger.error(
            "[DETERMINISTIC_FALLBACK] marketId=%s action=failed errorType=persistence_error error=%s",
            market_id,
            error,
        )
        register_pipeline_error(
            error=error,
            market=market,
            stage="deterministic_fallback_persist",
        )
        raise


def register_pipeline_error(
    error: Exception,
    market: dict[str, Any] | None = None,
    stage: str = "unknown",
) -> None:
    error_record = build_error_record(
        error=error,
        market=market,
        stage=stage,
    )

    logger.error(
        "Pipeline error | type=%s | stage=%s | market=%s | message=%s",
        error_record["error_type"],
        error_record["stage"],
        error_record.get("market_title"),
        error_record["message"],
    )

    if hasattr(db, "insert_pipeline_error"):
        try:
            db.insert_pipeline_error(error_record)
        except Exception as save_error:
            logger.error("No se pudo guardar pipeline_error: %s", save_error)


def start_pipeline_run() -> dict[str, Any]:
    logger.info("Iniciando pipeline run")
    return db.start_pipeline_run()


def fetch_markets() -> list[dict[str, Any]]:
    limit = env_int("POLYMARKET_LIMIT", 100)

    logger.info("Obteniendo mercados Polymarket | limit=%s", limit)

    markets = get_normalized_active_markets(limit=limit)

    logger.info("Mercados obtenidos: %s", len(markets))

    return markets


def save_snapshots(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saved_markets = []

    logger.info("Guardando markets y snapshots")

    for market in markets:
        try:
            saved_market = db.upsert_market(market)
            db.save_market_snapshot(saved_market["id"], market)

            merged_market = {
                **market,
                **saved_market,
            }

            saved_markets.append(merged_market)

        except Exception as error:
            register_pipeline_error(
                error=error,
                market=market,
                stage="save_snapshots",
            )
            continue

    logger.info("Markets guardados/actualizados: %s", len(saved_markets))

    return saved_markets


def filter_markets(
    markets: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    logger.info("Filtrando mercados relevantes para DeepEngine MVP")

    try:
        filtered, filter_stats = filter_relevant_markets_with_stats(markets)

        logger.info("Mercados filtrados: %s", len(filtered))
        logger.info("Resumen de filtros: %s", filter_stats)

        return filtered, filter_stats

    except Exception as error:
        register_pipeline_error(
            error=error,
            market=None,
            stage="filter_markets",
        )

        logger.error("Fallo el filtro general de mercados")
        return [], {}


def score_market_batch(markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logger.info("Calculando preliminary_radar_score")

    scored = score_markets(markets)

    logger.info("Mercados con score: %s", len(scored))

    return scored


def build_selection_reason(market: dict[str, Any]) -> str:
    breakdown = market.get("score_breakdown") or {}

    parts = [
        f"category={market.get('category') or market.get('deepengine_category')}",
        f"score={market.get('preliminary_radar_score')}",
        f"volume={safe_float(market.get('volume')):.0f}",
        f"liquidity={safe_float(market.get('liquidity')):.0f}",
        f"prob_move_24h={safe_float(market.get('probability_change_24h')):.4f}",
        f"days_to_close={days_to_close(market)}",
    ]

    if breakdown:
        parts.append(f"breakdown={breakdown}")

    return " | ".join(parts)


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def get_diversity_bucket(market: dict[str, Any]) -> str:
    return str(
        market.get("deepengine_category")
        or market.get("category")
        or "category_unknown"
    )


def get_theme_key(market: dict[str, Any]) -> str:
    title = normalize_text(market.get("title"))

    for verb in THEME_VERBS:
        match = re.match(rf"^will\s+.+?\s+{verb}\s+(.+)$", title)
        if match:
            return f"{verb}:{match.group(1)}"

    title = re.sub(r"\b\d{1,4}\b", "#", title)
    return title


def get_family_key(market: dict[str, Any]) -> str:
    title = normalize_text(market.get("title"))

    for pattern in FAMILY_PATTERNS:
        if pattern in title:
            return pattern

    return get_diversity_bucket(market)


def get_bucket_key(market: dict[str, Any]) -> str:
    category = get_diversity_bucket(market)

    for bucket in PRIORITY_BUCKETS:
        if category in bucket:
            return "/".join(bucket)

    return category


def build_candidate_pool(
    sorted_markets: list[dict[str, Any]],
    candidate_pool_size: int,
) -> list[dict[str, Any]]:
    max_politics_per_run = env_int("DEEPENGINE_MAX_POLITICS_PER_RUN", 1)
    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    category_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    politics_cap_hits = 0

    def try_add_market(market: dict[str, Any], allow_politics: bool) -> bool:
        nonlocal politics_cap_hits

        market_identity = id(market)
        if market_identity in selected_ids or len(selected) >= candidate_pool_size:
            return False

        category = get_diversity_bucket(market)
        family_key = get_family_key(market)

        if family_key == "2028 democratic presidential nomination":
            if family_counts[family_key] >= 1:
                return False

        if category == "politics":
            if not allow_politics:
                politics_cap_hits += 1
                return False

            if category_counts["politics"] >= max_politics_per_run:
                politics_cap_hits += 1
                return False

        selected.append(market)
        selected_ids.add(market_identity)
        category_counts[category] += 1
        family_counts[family_key] += 1
        return True

    for bucket in CANDIDATE_POOL_BUCKET_PRIORITY:
        for market in sorted_markets:
            if len(selected) >= candidate_pool_size:
                break

            if get_diversity_bucket(market) not in bucket:
                continue

            try_add_market(market, allow_politics=False)

    for market in sorted_markets:
        if len(selected) >= candidate_pool_size:
            break

        category = get_diversity_bucket(market)
        if category == "politics":
            continue

        try_add_market(market, allow_politics=False)

    if len(selected) < candidate_pool_size:
        for market in sorted_markets:
            if len(selected) >= candidate_pool_size:
                break

            if get_diversity_bucket(market) != "politics":
                continue

            try_add_market(market, allow_politics=True)

    logger.info(
        "CANDIDATE_POOL_CATEGORY_COUNTS | counts=%s",
        dict(category_counts),
    )
    logger.info(
        "POLITICS_CANDIDATE_CAP_APPLIED | max_politics=%s | skipped=%s",
        max_politics_per_run,
        politics_cap_hits,
    )

    return selected


def select_top_markets(
    markets: list[dict[str, Any]],
    limit: int | None = None,
) -> list[dict[str, Any]]:
    selection_limit = limit or env_int("DAILY_PIPELINE_TOP_N", 10)
    candidate_pool_size = env_int("DAILY_PIPELINE_CANDIDATE_POOL", selection_limit * 3)
    max_politics_per_run = env_int("DEEPENGINE_MAX_POLITICS_PER_RUN", 1)

    sorted_markets = sort_markets_by_score(markets)
    candidate_pool = build_candidate_pool(
        sorted_markets=sorted_markets,
        candidate_pool_size=candidate_pool_size,
    )
    selected: list[dict[str, Any]] = []
    theme_counts: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    bucket_counts: Counter[str] = Counter()
    category_counts: Counter[str] = Counter()
    skipped_by_bucket_limit: list[str] = []
    skipped_by_family_limit: list[str] = []
    skipped_by_theme_limit: list[str] = []

    logger.info(
        "Pool de candidatos seleccionado: %s | objetivo_deepbriefs=%s",
        len(candidate_pool),
        selection_limit,
    )

    for market in candidate_pool:
        logger.info(
            "Candidate | title=%s | reason=%s",
            market.get("title"),
            build_selection_reason(market),
        )

    def can_select(market: dict[str, Any]) -> bool:
        bucket_key = get_bucket_key(market)
        category = get_diversity_bucket(market)
        theme_key = get_theme_key(market)
        family_key = get_family_key(market)

        if bucket_counts[bucket_key] >= 1:
            skipped_by_bucket_limit.append(
                f"{market.get('title')} | bucket={bucket_key}"
            )
            return False

        if category == "politics" and category_counts["politics"] >= max_politics_per_run:
            skipped_by_bucket_limit.append(
                f"{market.get('title')} | bucket=politics_max_{max_politics_per_run}"
            )
            return False

        if theme_counts[theme_key] >= 2:
            skipped_by_theme_limit.append(
                f"{market.get('title')} | repeated_theme={theme_key}"
            )
            return False

        family_limit = 1 if family_key == "2028 democratic presidential nomination" else 2
        if family_counts[family_key] >= family_limit:
            skipped_by_family_limit.append(
                f"{market.get('title')} | repeated_family={family_key}"
            )
            return False

        return True

    def can_select_fill(market: dict[str, Any]) -> bool:
        category = get_diversity_bucket(market)
        theme_key = get_theme_key(market)
        family_key = get_family_key(market)

        if category == "politics" and category_counts["politics"] >= max_politics_per_run:
            skipped_by_bucket_limit.append(
                f"{market.get('title')} | bucket=politics_max_{max_politics_per_run}"
            )
            return False

        if theme_counts[theme_key] >= 2:
            skipped_by_theme_limit.append(
                f"{market.get('title')} | repeated_theme={theme_key}"
            )
            return False

        family_limit = 1 if family_key == "2028 democratic presidential nomination" else 2
        if family_counts[family_key] >= family_limit:
            skipped_by_family_limit.append(
                f"{market.get('title')} | repeated_family={family_key}"
            )
            return False

        return True

    def register_selection(market: dict[str, Any], pass_name: str) -> None:
        bucket_key = get_bucket_key(market)
        category = get_diversity_bucket(market)
        theme_key = get_theme_key(market)
        family_key = get_family_key(market)

        selected.append(market)
        bucket_counts[bucket_key] += 1
        category_counts[category] += 1
        theme_counts[theme_key] += 1
        family_counts[family_key] += 1
        logger.info(
            "Selection bucket chosen | pass=%s | bucket=%s | title=%s | preliminary_score=%s | relevance_reasons=%s | family_key=%s",
            pass_name,
            bucket_key,
            market.get("title"),
            market.get("preliminary_radar_score"),
            market.get("relevance_reasons"),
            family_key,
        )

    for bucket in PRIORITY_BUCKETS:
        if len(selected) >= selection_limit:
            break

        for market in candidate_pool:
            if market in selected or get_diversity_bucket(market) not in bucket:
                continue

            if not can_select(market):
                continue

            register_selection(market, pass_name="bucket_first_pass")
            break

    for market in candidate_pool:
        if len(selected) >= selection_limit:
            break

        if market in selected:
            continue

        if not can_select_fill(market):
            continue

        register_selection(market, pass_name="fill_remaining")

    logger.info(
        "Selection diversity bucket | counts=%s",
        dict(bucket_counts),
    )
    logger.info(
        "FINAL_SELECTION_CATEGORY_COUNTS | counts=%s",
        dict(category_counts),
    )
    logger.info(
        "Markets skipped by bucket limit | count=%s | samples=%s",
        len(skipped_by_bucket_limit),
        skipped_by_bucket_limit[:10],
    )
    logger.info(
        "Markets skipped by family limit | count=%s | samples=%s",
        len(skipped_by_family_limit),
        skipped_by_family_limit[:10],
    )
    logger.info(
        "Markets skipped by repeated theme | count=%s | samples=%s",
        len(skipped_by_theme_limit),
        skipped_by_theme_limit[:10],
    )

    if len(selected) < selection_limit:
        logger.warning(
            "Selection diversity warning | selected=%s | target=%s | reason=insufficient_variety",
            len(selected),
            selection_limit,
        )

    return selected


def fetch_context(
    market: dict[str, Any],
    min_sources: int | None = None,
) -> list[dict[str, Any]]:
    min_sources = min_sources or env_int("CONTEXT_MIN_SOURCES", 3)

    existing_context = db.get_market_context(
        market_db_id=market["id"],
        limit=min_sources,
    )

    if len(existing_context) >= min_sources:
        logger.info(
            "Contexto existente suficiente | market=%s | sources=%s",
            market.get("title"),
            len(existing_context),
        )
        return existing_context

    logger.info(
        "Contexto insuficiente | market=%s | existing=%s | buscando nuevas fuentes",
        market.get("title"),
        len(existing_context),
    )

    try:
        new_sources = search_context(
            market=market,
            max_results=min_sources,
        )

        for source in new_sources:
            try:
                db.insert_market_context(
                    market_db_id=market["id"],
                    source=source,
                )
            except Exception as error:
                register_pipeline_error(
                    error=error,
                    market=market,
                    stage="insert_market_context",
                )

        refreshed_context = db.get_market_context(
            market_db_id=market["id"],
            limit=min_sources,
        )

        logger.info(
            "Contexto final | market=%s | sources=%s",
            market.get("title"),
            len(refreshed_context),
        )

        return refreshed_context

    except Exception as error:
        register_pipeline_error(
            error=error,
            market=market,
            stage="fetch_context",
        )

        return existing_context


def generate_deepbrief(
    market: dict[str, Any],
    context_sources: list[dict[str, Any]],
    pipeline_run_id: str,
) -> dict[str, Any]:
    logger.info("Generando DeepBrief | market=%s", market.get("title"))
    logger.info(
        "MARKET_METADATA_DEBUG | title=%s | novelty=%s | reasons=%s | category=%s | prelim=%s",
        market.get("title"),
        market.get("novelty_market"),
        market.get("relevance_reasons"),
        market.get("deepengine_category") or market.get("category"),
        market.get("preliminary_radar_score"),
    )

    try:
        deepbrief, raw_output = generate_deepbrief_for_market(
            market=market,
            context_sources=context_sources,
        )
    except AllDeepBriefProvidersFailedError as error:
        fallback_result = maybe_persist_deterministic_fallback(
            market=market,
            pipeline_run_id=pipeline_run_id,
            provider_attempts=getattr(error, "attempts", []),
            fallback_reason=getattr(error, "classification", "all_llm_providers_unavailable"),
        )

        if fallback_result.get("status") == "saved":
            return fallback_result["saved_row"]

        if fallback_result.get("status") == "skipped":
            return fallback_result

        raise

    logger.info(
        "Prompt usado | market=%s | source=%s | provider=%s | fallback_used=%s",
        market.get("title"),
        raw_output.get("prompt_source", "unknown"),
        raw_output.get("provider", "unknown"),
        raw_output.get("fallback_used", False),
    )

    validate_output(
        deepbrief=deepbrief,
        raw_output=raw_output,
    )

    preliminary_radar_score = market.get("preliminary_radar_score")
    ai_interpretive_score = deepbrief.get("radar_score")

    if ai_interpretive_score == preliminary_radar_score:
        logger.warning(
            "AI_SCORE_ANCHORING_WARNING | market=%s | preliminary=%s | ai=%s | action=semantic_retry",
            market.get("title"),
            preliminary_radar_score,
            ai_interpretive_score,
        )

        deepbrief, raw_output = generate_deepbrief_for_market(
            market=market,
            context_sources=context_sources,
            anti_anchor_note=ANTI_ANCHOR_NOTE,
        )

        logger.info(
            "Prompt anti-anchor usado | market=%s | source=%s | provider=%s | fallback_used=%s",
            market.get("title"),
            raw_output.get("prompt_source", "unknown"),
            raw_output.get("provider", "unknown"),
            raw_output.get("fallback_used", False),
        )

        validate_output(
            deepbrief=deepbrief,
            raw_output=raw_output,
        )

        ai_interpretive_score = deepbrief.get("radar_score")

    probability_move = abs(safe_float(market.get("probability_change_24h")))
    relevance_reasons = market.get("relevance_reasons") or []
    has_strong_context = "strategic_context" in relevance_reasons
    has_real_movement_signal = "probability_move" in relevance_reasons
    ai_original = int(safe_float(ai_interpretive_score))
    ai_adjusted = ai_original
    score_adjustment = {
        "applied": False,
        "reason": None,
        "original_ai_score": ai_original,
        "adjusted_ai_score": ai_original,
    }

    if ai_original == int(safe_float(preliminary_radar_score)):
        if market.get("novelty_market") is True:
            ai_adjusted = min(ai_adjusted, 35)

        if probability_move == 0 and not has_strong_context:
            ai_adjusted = min(ai_adjusted, 44)

        if str(deepbrief.get("signal_label") or "").strip().lower() == "ignore":
            ai_adjusted = min(ai_adjusted, 30)

        if has_real_movement_signal or has_strong_context:
            ai_adjusted = ai_original

        if ai_adjusted != ai_original:
            score_adjustment = {
                "applied": True,
                "reason": "anti_anchor_postprocess",
                "original_ai_score": ai_original,
                "adjusted_ai_score": ai_adjusted,
            }

    ai_interpretive_score = ai_adjusted

    hybrid_score = calculate_hybrid_radar_score(
        preliminary_radar_score=preliminary_radar_score,
        ai_interpretive_score=ai_interpretive_score,
    )

    if score_adjustment["applied"]:
        logger.info(
            "AI_SCORE_POSTPROCESS_APPLIED | market=%s | preliminary=%s | original_ai=%s | adjusted_ai=%s | final=%s",
            market.get("title"),
            preliminary_radar_score,
            ai_original,
            ai_adjusted,
            hybrid_score["final_radar_score"],
        )

    if hybrid_score["preliminary_radar_score"] == hybrid_score["ai_interpretive_score"]:
        logger.warning(
            "AI_SCORE_ANCHORING_PERSISTED | market=%s | preliminary=%s | ai=%s | final=%s",
            market.get("title"),
            hybrid_score["preliminary_radar_score"],
            hybrid_score["ai_interpretive_score"],
            hybrid_score["final_radar_score"],
        )

    original_signal_label = deepbrief.get("signal_label")
    normalized_signal_label = get_signal_label_for_final_score(
        hybrid_score["final_radar_score"]
    )

    if original_signal_label != normalized_signal_label:
        logger.info(
            "SIGNAL_LABEL_NORMALIZED | market=%s | original=%s | normalized=%s | final=%s",
            market.get("title"),
            original_signal_label,
            normalized_signal_label,
            hybrid_score["final_radar_score"],
        )

    deepbrief["signal_label"] = normalized_signal_label

    raw_output["market_input"] = build_raw_market_input(market)
    raw_output["pipeline_run_id"] = pipeline_run_id
    raw_output["score_adjustment"] = score_adjustment
    raw_output["hybrid_score"] = hybrid_score
    raw_output["model_signal_label"] = original_signal_label
    raw_output["normalized_signal_label"] = normalized_signal_label

    parsed_output = raw_output.get("parsed_output")
    if isinstance(parsed_output, dict):
        parsed_output["model_signal_label"] = original_signal_label
        parsed_output["signal_label"] = normalized_signal_label

    saved = save_results(
        market=market,
        deepbrief=deepbrief,
        raw_output=raw_output,
        hybrid_score=hybrid_score,
        pipeline_run_id=pipeline_run_id,
    )

    alerts = create_alerts(
        market=market,
        deepbrief=deepbrief,
        hybrid_score=hybrid_score,
    )

    raw_output["alerts"] = alerts

    logger.info(
        "DeepBrief guardado | id=%s | preliminary=%s | ai=%s | final=%s | alerts=%s",
        saved["id"],
        hybrid_score["preliminary_radar_score"],
        hybrid_score["ai_interpretive_score"],
        hybrid_score["final_radar_score"],
        len(alerts),
    )

    return saved


def validate_output(
    deepbrief: dict[str, Any],
    raw_output: dict[str, Any],
) -> bool:
    """
    Validacion minima post-generacion.

    La validacion fuerte ya ocurre en generate_deepbrief_for_market()
    usando Structured Outputs + Pydantic.
    """
    required_fields = [
        "lectura_clave",
        "radar_score",
        "signal_label",
        "deepsignal_verdict",
        "confidence_level",
        "prediction_audit",
    ]

    for field in required_fields:
        if field not in deepbrief:
            raise ValueError(f"DeepBrief invalido: falta {field}")

    radar_score = deepbrief.get("radar_score")

    if not isinstance(radar_score, int | float):
        raise ValueError("DeepBrief invalido: radar_score no es numerico")

    if radar_score < 0 or radar_score > 100:
        raise ValueError("DeepBrief invalido: radar_score fuera de 0-100")

    if not raw_output:
        raise ValueError("DeepBrief invalido: raw_output vacio")

    return True


def save_results(
    market: dict[str, Any],
    deepbrief: dict[str, Any],
    raw_output: dict[str, Any],
    hybrid_score: dict[str, Any],
    pipeline_run_id: str,
) -> dict[str, Any]:
    """
    Guarda resultado final en Supabase.
    """
    saved = db.insert_deepbrief(
        market_db_id=market["id"],
        deepbrief=deepbrief,
        raw_output=raw_output,
        hybrid_score=hybrid_score,
        pipeline_run_id=pipeline_run_id,
    )

    logger.info("Resultado guardado | deepbrief_id=%s", saved["id"])
    logger.info(
        "DEEPBRIEF_PIPELINE_LINKED | deepbrief_id=%s | pipeline_run_id=%s",
        saved["id"],
        pipeline_run_id,
    )

    prediction_payload = {
        **deepbrief,
        "signalLabel": deepbrief.get("signal_label"),
        "radarScore": deepbrief.get("radar_score"),
        "finalRadarScore": hybrid_score.get("final_radar_score"),
        "hybridScore": hybrid_score,
        "rawOutput": raw_output,
    }

    try:
        prediction_saved = db.insert_deepsignal_prediction(
            deepbrief_id=saved["id"],
            market_id=market["id"],
            deepbrief_output=prediction_payload,
            market_input=market,
        )
        logger.info(
            "DEEPSIGNAL_PREDICTION_SAVED | deepbrief_id=%s | prediction_id=%s | market_id=%s",
            saved["id"],
            prediction_saved.get("id"),
            market["id"],
        )
    except Exception as prediction_error:
        logger.error(
            "DEEPSIGNAL_PREDICTION_SAVE_ERROR | deepbrief_id=%s | market_id=%s | error=%s",
            saved["id"],
            market["id"],
            prediction_error,
        )

    return saved


def create_alerts(
    market: dict[str, Any],
    deepbrief: dict[str, Any],
    hybrid_score: dict[str, Any],
) -> list[dict[str, Any]]:
    """
    MVP: todavia no envia alertas.
    Solo construye alerta candidata si el score final es alto.

    Despues esto puede guardar en tabla alerts o mandar Telegram/email.
    """
    final_score = hybrid_score.get("final_radar_score", 0)

    if final_score < 70:
        return []

    alert = {
        "market_id": market.get("id"),
        "title": market.get("title"),
        "final_radar_score": final_score,
        "signal_label": deepbrief.get("signal_label"),
        "message": (
            f"RadarBallena detecto mercado relevante: "
            f"{market.get('title')} | score={final_score}"
        ),
    }

    logger.info(
        "Alerta candidata creada | market=%s | score=%s",
        market.get("title"),
        final_score,
    )

    return [alert]


def main():
    started_at = time.time()
    pipeline_run = start_pipeline_run()
    pipeline_run_id = pipeline_run["id"]

    markets_fetched = 0
    markets_filtered = 0
    markets_analyzed = 0
    deepbriefs_generated = 0
    skipped_recent_deepbrief_count = 0
    skipped_context_insufficient_count = 0
    errors_count = 0
    filter_stats: dict[str, Any] = {}

    try:
        raw_markets = fetch_markets()
        markets_fetched = len(raw_markets)

        saved_markets = save_snapshots(raw_markets)

        filtered_markets, filter_stats = filter_markets(saved_markets)
        markets_filtered = len(filtered_markets)

        scored_markets = score_market_batch(filtered_markets)

        target_deepbriefs = env_int("DAILY_PIPELINE_TOP_N", 10)
        attempt_pool_size = env_int("DAILY_PIPELINE_ATTEMPT_POOL", 30)
        selected_markets = select_top_markets(
            scored_markets,
            limit=attempt_pool_size,
        )

        logger.info(
            "SELECTED_ATTEMPT_POOL_SIZE | selected=%s | requested=%s | target=%s",
            len(selected_markets),
            attempt_pool_size,
            target_deepbriefs,
        )

        for market in selected_markets:
            if deepbriefs_generated >= target_deepbriefs:
                break

            freshness_hours = env_int("DEEPBRIEF_FRESHNESS_HOURS", 12)

            recent_deepbrief = db.get_recent_deepbrief(
                market_db_id=market["id"],
                hours=freshness_hours,
            )

            if recent_deepbrief:
                logger.info(
                    "DeepBrief reciente existe; saltando | market=%s | deepbrief_id=%s | freshness_hours=%s",
                    market.get("title"),
                    recent_deepbrief.get("id"),
                    freshness_hours,
                )
                skipped_recent_deepbrief_count += 1
                continue

            try:
                logger.info("Evaluando candidato: %s", market.get("title"))
                logger.info(
                    "Selection reason | market=%s | %s",
                    market.get("title"),
                    build_selection_reason(market),
                )

                context_sources = fetch_context(market, min_sources=3)

                if len(context_sources) < 3:
                    logger.info(
                        "Mercado excluido por contexto insuficiente | market=%s | sources=%s",
                        market.get("title"),
                        len(context_sources),
                    )
                    skipped_context_insufficient_count += 1
                    continue

                logger.info(
                    "Fuentes usadas | market=%s | sources=%s",
                    market.get("title"),
                    len(context_sources),
                )

                result = generate_deepbrief(
                    market=market,
                    context_sources=context_sources,
                    pipeline_run_id=pipeline_run_id,
                )

                if isinstance(result, dict) and result.get("status") == "skipped":
                    skipped_recent_deepbrief_count += 1
                    continue

                deepbriefs_generated += 1
                markets_analyzed += 1

            except Exception as error:
                errors_count += 1

                register_pipeline_error(
                    error=error,
                    market=market,
                    stage="generate_deepbrief",
                )

                logger.error(
                    "El pipeline continua con el siguiente mercado | failed_market=%s",
                    market.get("title"),
                )

                continue

        logger.info(
            "SKIPPED_RECENT_DEEPBRIEF_COUNT | count=%s",
            skipped_recent_deepbrief_count,
        )
        logger.info(
            "SKIPPED_CONTEXT_INSUFFICIENT_COUNT | count=%s",
            skipped_context_insufficient_count,
        )
        logger.info(
            "TARGET_DEEPBRIEFS_GENERATED | generated=%s | target=%s",
            deepbriefs_generated,
            target_deepbriefs,
        )

        duration_seconds = round(time.time() - started_at, 2)
        status = "completed" if errors_count == 0 else "completed_with_errors"

        db.finish_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            status=status,
            markets_fetched=markets_fetched,
            markets_filtered=markets_filtered,
            markets_analyzed=markets_analyzed,
            deepbriefs_generated=deepbriefs_generated,
            errors_count=errors_count,
            duration_seconds=duration_seconds,
            error_message=None if errors_count == 0 else f"{errors_count} errores",
        )

        logger.info("Pipeline terminado")
        logger.info("Markets fetched: %s", markets_fetched)
        logger.info(
            "Excluded closed: %s | closed_by_date=%s | closed_by_flag=%s | inactive=%s",
            filter_stats.get("closed_market_excluded", 0),
            filter_stats.get("closed_by_date", 0),
            filter_stats.get("closed_by_flag", 0),
            filter_stats.get("inactive_market_excluded", 0),
        )
        logger.info(
            "Excluded sports: %s | excluded unknown: %s | eligible after filters: %s",
            filter_stats.get("sports_market_excluded", 0),
            filter_stats.get("unknown_market_excluded", 0),
            filter_stats.get("eligible_after_filters", markets_filtered),
        )
        logger.info(
            "Markets skipped by novelty filter: %s | relevance_exclusions=%s",
            filter_stats.get("novelty_market_excluded", 0),
            filter_stats.get("relevance_exclusion_summary", {}),
        )
        logger.info("Markets filtered: %s", markets_filtered)
        logger.info("Markets analyzed: %s", markets_analyzed)
        logger.info("DeepBriefs generated: %s", deepbriefs_generated)
        logger.info("Errors: %s", errors_count)
        logger.info("Duration seconds: %s", duration_seconds)

        print("\nPipeline maestro terminado.")
        print("Markets fetched:", markets_fetched)
        print("Excluded closed:", filter_stats.get("closed_market_excluded", 0))
        print("Closed by date:", filter_stats.get("closed_by_date", 0))
        print("Closed by flag:", filter_stats.get("closed_by_flag", 0))
        print(
            "Inactive excluded:",
            filter_stats.get("inactive_market_excluded", 0),
        )
        print("Excluded sports:", filter_stats.get("sports_market_excluded", 0))
        print("Excluded unknown:", filter_stats.get("unknown_market_excluded", 0))
        print(
            "Eligible after filters:",
            filter_stats.get("eligible_after_filters", markets_filtered),
        )
        print(
            "Markets skipped by novelty filter:",
            filter_stats.get("novelty_market_excluded", 0),
        )
        print("Markets filtered:", markets_filtered)
        print("Markets analyzed:", markets_analyzed)
        print("DeepBriefs generated:", deepbriefs_generated)
        print("Errors:", errors_count)
        print("Duration:", duration_seconds, "seconds")

    except Exception as fatal_error:
        duration_seconds = round(time.time() - started_at, 2)
        errors_count += 1

        register_pipeline_error(
            error=fatal_error,
            market=None,
            stage="run_daily_pipeline",
        )

        db.finish_pipeline_run(
            pipeline_run_id=pipeline_run_id,
            status="failed",
            markets_fetched=markets_fetched,
            markets_filtered=markets_filtered,
            markets_analyzed=markets_analyzed,
            deepbriefs_generated=deepbriefs_generated,
            errors_count=errors_count,
            duration_seconds=duration_seconds,
            error_message=str(fatal_error),
        )

        logger.exception("Pipeline maestro fallo completamente: %s", fatal_error)

        raise


if __name__ == "__main__":
    main()
