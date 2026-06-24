from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

try:  # pragma: no cover - support package and script-style imports
    from .market_trail import build_wallet_score_map
except ImportError:  # pragma: no cover
    from market_trail import build_wallet_score_map


STOPWORDS = {
    "a",
    "about",
    "after",
    "against",
    "all",
    "and",
    "any",
    "are",
    "as",
    "at",
    "be",
    "been",
    "before",
    "by",
    "can",
    "for",
    "from",
    "has",
    "have",
    "how",
    "if",
    "in",
    "is",
    "it",
    "its",
    "just",
    "of",
    "on",
    "or",
    "over",
    "s",
    "than",
    "that",
    "the",
    "their",
    "there",
    "this",
    "to",
    "under",
    "up",
    "was",
    "will",
    "with",
    "within",
    "would",
    "yes",
    "no",
}

NO_RELIABLE_TRAIL = "NO_RELIABLE_TRAIL"
INFERRED_RELATED = "INFERRED_RELATED"
REQUIRED_ESTELA_FIELDS = {
    "marketId",
    "title",
    "status",
    "headline",
    "interpretation",
    "confidence",
    "smartBias",
    "qualifiedWalletCount",
    "smartMoneyVolume",
    "riskFlags",
    "events",
    "relatedMarkets",
    "generatedAt",
}


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def normalize_metric(value: float) -> float:
    return round(clamp(value, 0.0, 1.0), 4)


def normalize_status(status: str) -> str:
    value = str(status or "").strip().upper()
    if value in {
        "DIRECT_STRONG",
        "DIRECT_WEAK",
        "CONTRADICTORY_FLOW",
        "INFERRED_RELATED",
        "NO_RELIABLE_TRAIL",
    }:
        return value
    return NO_RELIABLE_TRAIL


def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def tokenize_title(title: str) -> set[str]:
    tokens: set[str] = set()
    normalized = normalize_text(title)

    for raw_token in normalized.replace("/", " ").replace("-", " ").replace("_", " ").split():
        token = "".join(ch for ch in raw_token if ch.isalnum())
        if len(token) < 3:
            continue
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        tokens.add(token)

    return tokens


def title_similarity(left: str, right: str) -> float:
    left_tokens = tokenize_title(left)
    right_tokens = tokenize_title(right)

    if not left_tokens or not right_tokens:
        return 0.0

    overlap = len(left_tokens & right_tokens)
    union = len(left_tokens | right_tokens)
    return normalize_metric(safe_ratio(overlap, union))


def shared_keywords_score(left: str, right: str) -> float:
    left_tokens = tokenize_title(left)
    right_tokens = tokenize_title(right)

    if not left_tokens or not right_tokens:
        return 0.0

    overlap = len(left_tokens & right_tokens)
    denominator = min(len(left_tokens), len(right_tokens))
    return normalize_metric(safe_ratio(overlap, denominator))


def category_match_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return 1.0 if left == right else 0.0


def time_proximity_score(left_timestamp: datetime | None, right_timestamp: datetime | None) -> float:
    if left_timestamp is None or right_timestamp is None:
        return 0.0

    age_hours = abs((left_timestamp - right_timestamp).total_seconds()) / 3600
    if age_hours <= 6:
        return 1.0
    if age_hours <= 24:
        return 0.8
    if age_hours <= 72:
        return 0.5
    if age_hours <= 168:
        return 0.25
    return 0.0


def wallet_overlap_score(left_wallets: set[str], right_wallets: set[str]) -> float:
    if not left_wallets or not right_wallets:
        return 0.0

    overlap = len(left_wallets & right_wallets)
    denominator = min(len(left_wallets), len(right_wallets))
    return normalize_metric(safe_ratio(overlap, denominator))


def market_category(market: dict[str, Any]) -> str:
    category = str(market.get("category") or "").strip().lower()
    if category:
        return category
    return str(market.get("category_guess") or "").strip().lower()


def market_title(market: dict[str, Any]) -> str:
    return str(market.get("title") or "").strip()


def market_timestamp(market: dict[str, Any]) -> datetime | None:
    generated_at = market.get("generatedAt")
    if isinstance(generated_at, datetime):
        return generated_at
    if isinstance(generated_at, str):
        try:
            return datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except Exception:
            return None
    return None


def build_market_profiles(
    trades: list[dict[str, Any]],
    market_trails: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    market_profiles: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "marketId": "",
            "title": "",
            "category": "",
            "wallets": set(),
            "keywords": set(),
            "timestamp": None,
            "tradeCount": 0,
            "smartMoneyVolume": 0.0,
        }
    )

    trail_map = {str(trail.get("marketId")): trail for trail in market_trails}

    for trade in trades:
        market_id = trade.get("market_id")
        if not market_id:
            continue

        market_key = str(market_id)
        profile = market_profiles[market_key]
        profile["marketId"] = market_key
        profile["title"] = profile["title"] or str(trade.get("title") or "").strip()
        profile["category"] = profile["category"] or str(trade.get("category_guess") or "").strip().lower()
        profile["wallets"].add(str(trade.get("wallet") or "").lower())
        profile["keywords"].update(tokenize_title(str(trade.get("title") or "")))
        profile["tradeCount"] += 1
        profile["smartMoneyVolume"] += float(trade.get("size_usd") or 0.0)

        timestamp = trade.get("timestamp")
        if isinstance(timestamp, str):
            try:
                timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except Exception:
                timestamp = None
        if isinstance(timestamp, datetime):
            existing = profile["timestamp"]
            if existing is None or timestamp > existing:
                profile["timestamp"] = timestamp

    for market_id, trail in trail_map.items():
        profile = market_profiles[str(market_id)]
        profile["marketId"] = str(market_id)
        profile["title"] = profile["title"] or market_title(trail)
        profile["category"] = profile["category"] or str(trail.get("category") or "").strip().lower()
        if trail.get("generatedAt"):
            profile["timestamp"] = profile["timestamp"] or market_timestamp(trail)

    for profile in market_profiles.values():
        profile["wallets"] = set(profile["wallets"])
        profile["keywords"] = set(profile["keywords"])

    return market_profiles


def related_market_score(
    left_market: dict[str, Any],
    right_market: dict[str, Any],
) -> dict[str, Any]:
    title_component = title_similarity(market_title(left_market), market_title(right_market))
    keyword_component = shared_keywords_score(market_title(left_market), market_title(right_market))
    category_component = category_match_score(
        market_category(left_market),
        market_category(right_market),
    )
    wallet_component = wallet_overlap_score(
        set(left_market.get("wallets") or set()),
        set(right_market.get("wallets") or set()),
    )
    time_component = time_proximity_score(
        market_timestamp(left_market),
        market_timestamp(right_market),
    )

    score = (
        (title_component * 30.0)
        + (keyword_component * 25.0)
        + (category_component * 20.0)
        + (wallet_component * 15.0)
        + (time_component * 10.0)
    )

    return {
        "relatedMarketScore": round(clamp(score)),
        "titleSimilarity": title_component,
        "sharedKeywords": keyword_component,
        "categoryMatch": category_component,
        "sharedWallets": wallet_component,
        "timeProximity": time_component,
    }


def smart_bias_direction(value: float) -> str:
    if value > 0.15:
        return "yes"
    if value < -0.15:
        return "no"
    return "mixed"


def headline_and_interpretation(status: str) -> tuple[str, str]:
    normalized_status = normalize_status(status)

    if normalized_status == "DIRECT_STRONG":
        return (
            "Smart Money activo en este mercado",
            "Hay suficiente capital calificado y flujo directo para considerar una lectura confiable.",
        )

    if normalized_status == "DIRECT_WEAK":
        return (
            "Actividad directa débil de Smart Money",
            "Hay actividad directa en este mercado, pero todavía no alcanza para una confirmación fuerte.",
        )

    if normalized_status == "CONTRADICTORY_FLOW":
        return (
            "Flujo sofisticado dividido",
            "El capital calificado está dividido entre direcciones opuestas, así que la lectura sigue conflictiva.",
        )

    if normalized_status == "INFERRED_RELATED":
        return (
            "Sin estela directa; lectura inferida desde mercados relacionados",
            "No hay flujo directo suficiente en este mercado. Se detectó actividad moderada en mercados relacionados, pero la confirmación de capital sigue siendo limitada.",
        )

    return (
        "No hay trail confiable de Smart Money",
        "No existe suficiente capital calificado o la señal actual es demasiado débil para una lectura confiable.",
    )


def clamp_confidence(value: float, lower: float, upper: float) -> int:
    return round(clamp(value, lower, upper))


def confidence_for_status(record: dict[str, Any]) -> int:
    status = normalize_status(record.get("status") or "")
    consensus = float(record.get("consensusScore") or 0.0)
    conviction = float(record.get("convictionScore") or 0.0)
    freshness = float(record.get("freshnessScore") or 0.0)
    smart_money_volume = float(record.get("smartMoneyVolume") or 0.0)
    qualified_wallet_count = float(record.get("qualifiedWalletCount") or 0.0)
    divergence = float(record.get("divergenceScore") or 0.0)
    events = record.get("events") or []
    related_markets = record.get("relatedMarkets") or []

    if status == "DIRECT_STRONG":
        strength = (
            (consensus / 100.0) * 0.4
            + (conviction / 100.0) * 0.35
            + min(smart_money_volume / 5000.0, 1.0) * 0.25
        )
        return clamp_confidence(65.0 + strength * 25.0, 65.0, 90.0)

    if status == "DIRECT_WEAK":
        strength = (
            (consensus / 100.0) * 0.35
            + (conviction / 100.0) * 0.3
            + min(smart_money_volume / 2500.0, 1.0) * 0.2
            + min(qualified_wallet_count / 2.0, 1.0) * 0.15
        )
        return clamp_confidence(35.0 + strength * 25.0, 35.0, 60.0)

    if status == "CONTRADICTORY_FLOW":
        strength = (
            (divergence / 100.0) * 0.45
            + (freshness / 100.0) * 0.25
            + min(smart_money_volume / 3500.0, 1.0) * 0.15
            + min(len(events) / 4.0, 1.0) * 0.15
        )
        return clamp_confidence(35.0 + strength * 30.0, 35.0, 65.0)

    if status == "INFERRED_RELATED":
        raw_confidence = float(record.get("confidence") or 0.0)
        if raw_confidence <= 0 and related_markets:
            avg_related = sum(float(item.get("relatedMarketScore") or 0.0) for item in related_markets) / len(
                related_markets
            )
            raw_confidence = 30.0 + min(avg_related, 60.0) * 0.4
        return clamp_confidence(raw_confidence, 0.0, 60.0)

    if smart_money_volume > 0 or qualified_wallet_count > 0 or events:
        residual_strength = (
            min(smart_money_volume / 2500.0, 1.0) * 0.45
            + min(qualified_wallet_count / 2.0, 1.0) * 0.3
            + min(conviction / 50.0, 1.0) * 0.15
            + min(len(events) / 3.0, 1.0) * 0.1
        )
        return clamp_confidence(30.0 + residual_strength * 5.0, 30.0, 35.0)

    fallback_strength = min(freshness / 100.0, 1.0) * 0.5
    return clamp_confidence(20.0 + fallback_strength * 5.0, 20.0, 25.0)


def normalize_risk_flags(status: str, risk_flags: list[str], record: dict[str, Any]) -> list[str]:
    flags: list[str] = []

    for flag in risk_flags:
        if flag and flag not in flags:
            flags.append(flag)

    normalized_status = normalize_status(status)
    qualified_wallet_count = int(record.get("qualifiedWalletCount") or 0)
    consensus = int(record.get("consensusScore") or 0)
    smart_money_volume = float(record.get("smartMoneyVolume") or 0.0)

    if normalized_status == "NO_RELIABLE_TRAIL":
        fallback_flags = []
        if qualified_wallet_count <= 0:
            fallback_flags.append("low_wallet_count")
        if consensus <= 0:
            fallback_flags.append("low_consensus")
        if smart_money_volume <= 0:
            fallback_flags.append("no_qualified_flow")
        fallback_flags.append("no_reliable_signal")
        for flag in fallback_flags:
            if flag not in flags:
                flags.append(flag)

    return flags


def normalize_events(
    status: str,
    events: list[dict[str, Any]] | None,
    trades: list[dict[str, Any]],
    wallet_scores: list[dict[str, Any]],
    market_id: str,
) -> list[dict[str, Any]]:
    normalized_status = normalize_status(status)
    if normalized_status == "NO_RELIABLE_TRAIL":
        return []

    if events:
        cleaned_events: list[dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            cleaned_events.append(
                {
                    "wallet": event.get("wallet"),
                    "walletQualityScore": int(event.get("walletQualityScore") or 0),
                    "classification": event.get("classification") or "INSUFFICIENT_HISTORY",
                    "side": event.get("side"),
                    "outcome": event.get("outcome"),
                    "sizeUsd": round(float(event.get("sizeUsd") or 0.0), 2),
                    "price": round(float(event.get("price") or 0.0), 4),
                    "timestamp": event.get("timestamp"),
                }
            )
        if cleaned_events:
            return cleaned_events

    wallet_score_map = build_wallet_score_map(wallet_scores)
    qualifying_events: list[dict[str, Any]] = []

    for trade in trades:
        if str(trade.get("market_id") or "") != market_id:
            continue

        wallet = str(trade.get("wallet") or "").lower()
        wallet_score = wallet_score_map.get(wallet)
        if not wallet_score:
            continue

        wallet_quality = int(wallet_score.get("walletQualityScore") or 0)
        if wallet_quality < 60:
            continue

        timestamp = trade.get("timestamp")
        if isinstance(timestamp, datetime):
            timestamp_value = timestamp.isoformat()
        else:
            timestamp_value = str(timestamp) if timestamp else None

        qualifying_events.append(
            {
                "wallet": wallet,
                "walletQualityScore": wallet_quality,
                "classification": wallet_score.get("classification") or "INSUFFICIENT_HISTORY",
                "side": str(trade.get("side") or "").upper() or None,
                "outcome": str(trade.get("outcome") or "").upper() or None,
                "sizeUsd": round(float(trade.get("size_usd") or 0.0), 2),
                "price": round(float(trade.get("price") or 0.0), 4),
                "timestamp": timestamp_value,
            }
        )

    qualifying_events.sort(
        key=lambda item: (
            item["walletQualityScore"],
            item["sizeUsd"],
            item["timestamp"] or "",
        ),
        reverse=True,
    )

    return qualifying_events[:5]


def build_base_record(
    trail: dict[str, Any],
    *,
    status: str,
    confidence: int,
    headline: str,
    interpretation: str,
    risk_flags: list[str],
    events: list[dict[str, Any]],
    related_markets: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    record = {
        "marketId": trail.get("marketId"),
        "title": trail.get("title") or "",
        "status": normalize_status(status),
        "headline": headline,
        "interpretation": interpretation,
        "confidence": int(confidence),
        "smartBias": round(float(trail.get("smartBias") or 0.0), 3),
        "qualifiedWalletCount": int(trail.get("qualifiedWalletCount") or 0),
        "smartMoneyVolume": round(float(trail.get("smartMoneyVolume") or 0.0), 2),
        "weightedYesFlow": round(float(trail.get("weightedYesFlow") or 0.0), 2),
        "weightedNoFlow": round(float(trail.get("weightedNoFlow") or 0.0), 2),
        "consensusScore": int(trail.get("consensusScore") or 0),
        "divergenceScore": int(trail.get("divergenceScore") or 0),
        "convictionScore": int(trail.get("convictionScore") or 0),
        "freshnessScore": int(trail.get("freshnessScore") or 0),
        "riskFlags": risk_flags,
        "events": events,
        "relatedMarkets": related_markets,
        "generatedAt": generated_at,
    }

    if "relatedMarketsUsed" in trail or related_markets:
        record["relatedMarketsUsed"] = int(trail.get("relatedMarketsUsed") or len(related_markets))

    return record


def validate_estela_output(records: list[dict[str, Any]]) -> None:
    for index, record in enumerate(records):
        missing = REQUIRED_ESTELA_FIELDS - set(record)
        if missing:
            raise ValueError(
                f"estela_capital_by_market record {index} is missing fields: {sorted(missing)}"
            )
        if not isinstance(record["confidence"], int):
            raise ValueError(f"estela_capital_by_market record {index} has non-numeric confidence")
        if not isinstance(record["riskFlags"], list):
            raise ValueError(f"estela_capital_by_market record {index} has non-array riskFlags")
        if not isinstance(record["events"], list):
            raise ValueError(f"estela_capital_by_market record {index} has non-array events")
        if not isinstance(record["relatedMarkets"], list):
            raise ValueError(
                f"estela_capital_by_market record {index} has non-array relatedMarkets"
            )


def build_related_market_inferences(
    trades: list[dict[str, Any]],
    market_trails: list[dict[str, Any]],
    wallet_scores: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    generated_at = datetime.now(timezone.utc).isoformat()
    profile_map = build_market_profiles(trades, market_trails)
    trail_map = {str(trail.get("marketId")): trail for trail in market_trails}
    wallet_scores = wallet_scores or []

    output: list[dict[str, Any]] = []

    for market_id, trail in trail_map.items():
        base_record = dict(trail)
        status = normalize_status(base_record.get("status") or NO_RELIABLE_TRAIL)
        headline, interpretation = headline_and_interpretation(status)
        events = normalize_events(status, base_record.get("events") or [], trades, wallet_scores, market_id)
        related_markets = list(base_record.get("relatedMarkets") or [])
        confidence = confidence_for_status({**base_record, "status": status, "events": events, "relatedMarkets": related_markets})
        risk_flags = normalize_risk_flags(status, list(base_record.get("riskFlags") or []), base_record)

        if status in {"DIRECT_STRONG", "DIRECT_WEAK", "CONTRADICTORY_FLOW"}:
            output.append(
                build_base_record(
                    base_record,
                    status=status,
                    confidence=confidence,
                    headline=headline,
                    interpretation=interpretation,
                    risk_flags=risk_flags,
                    events=events,
                    related_markets=[],
                    generated_at=generated_at,
                )
            )
            continue

        if status != NO_RELIABLE_TRAIL:
            output.append(
                build_base_record(
                    base_record,
                    status=status,
                    confidence=confidence,
                    headline=headline,
                    interpretation=interpretation,
                    risk_flags=risk_flags,
                    events=events,
                    related_markets=related_markets,
                    generated_at=generated_at,
                )
            )
            continue

        left_market = profile_map.get(market_id, {})
        candidates: list[dict[str, Any]] = []

        for candidate_id, candidate_trail in trail_map.items():
            if candidate_id == market_id:
                continue
            if candidate_trail.get("status") not in {"DIRECT_WEAK", "DIRECT_STRONG"}:
                continue

            candidate_market = profile_map.get(candidate_id, {})
            score_details = related_market_score(left_market, candidate_market)
            related_score = score_details["relatedMarketScore"]

            if related_score <= 0:
                continue

            candidates.append(
                {
                    "marketId": candidate_id,
                    "title": candidate_trail.get("title") or "",
                    "status": candidate_trail.get("status"),
                    "relatedMarketScore": related_score,
                    "smartBias": candidate_trail.get("smartBias", 0.0),
                    "smartMoneyVolume": candidate_trail.get("smartMoneyVolume", 0.0),
                }
            )

        candidates.sort(
            key=lambda item: (
                item["relatedMarketScore"],
                item["smartMoneyVolume"],
                abs(float(item.get("smartBias") or 0.0)),
            ),
            reverse=True,
        )

        top_candidates = candidates[:4]
        if len(top_candidates) < 2:
            output.append(
                build_base_record(
                    base_record,
                    status=NO_RELIABLE_TRAIL,
                    confidence=confidence,
                    headline=headline,
                    interpretation=interpretation,
                    risk_flags=risk_flags,
                    events=[],
                    related_markets=[],
                    generated_at=generated_at,
                )
            )
            continue

        average_score = sum(item["relatedMarketScore"] for item in top_candidates) / len(top_candidates)
        if average_score < 40:
            output.append(
                build_base_record(
                    base_record,
                    status=NO_RELIABLE_TRAIL,
                    confidence=confidence,
                    headline=headline,
                    interpretation=interpretation,
                    risk_flags=risk_flags,
                    events=[],
                    related_markets=[],
                    generated_at=generated_at,
                )
            )
            continue

        directional_votes = Counter(
            smart_bias_direction(float(item.get("smartBias") or 0.0))
            for item in top_candidates
            if item.get("status") in {"DIRECT_WEAK", "DIRECT_STRONG"}
        )
        directional_votes.pop("mixed", None)
        mixed_flow = bool(directional_votes.get("yes", 0) > 0 and directional_votes.get("no", 0) > 0)

        inferred_confidence = round(clamp(average_score * 0.9))
        inferred_confidence = min(inferred_confidence, 60)
        if inferred_confidence < 30:
            output.append(
                build_base_record(
                    base_record,
                    status=NO_RELIABLE_TRAIL,
                    confidence=confidence_for_status({**base_record, "status": NO_RELIABLE_TRAIL}),
                    headline=headline,
                    interpretation=interpretation,
                    risk_flags=normalize_risk_flags(NO_RELIABLE_TRAIL, list(base_record.get("riskFlags") or []), base_record),
                    events=[],
                    related_markets=[],
                    generated_at=generated_at,
                )
            )
            continue

        inferred_headline, inferred_interpretation = headline_and_interpretation(INFERRED_RELATED)
        if inferred_confidence < 35:
            inferred_interpretation = "No hay confirmación directa ni indirecta suficiente de Smart Money."

        inferred_risk_flags = normalize_risk_flags(
            INFERRED_RELATED,
            ["inferred_signal", "low_direct_activity"],
            {**base_record, "qualifiedWalletCount": 0, "smartMoneyVolume": 0.0},
        )
        if mixed_flow and "mixed_related_flow" not in inferred_risk_flags:
            inferred_risk_flags.append("mixed_related_flow")

        output.append(
            build_base_record(
                base_record,
                status=INFERRED_RELATED,
                confidence=inferred_confidence,
                headline=inferred_headline,
                interpretation=inferred_interpretation,
                risk_flags=inferred_risk_flags,
                events=normalize_events(INFERRED_RELATED, base_record.get("events") or [], trades, wallet_scores, market_id),
                related_markets=[
                    {
                        "marketId": item["marketId"],
                        "title": item["title"],
                        "status": item["status"],
                        "relatedMarketScore": item["relatedMarketScore"],
                        "smartBias": item["smartBias"],
                        "smartMoneyVolume": item["smartMoneyVolume"],
                    }
                    for item in top_candidates
                ],
                generated_at=generated_at,
            )
        )

    seen = set()
    merged: list[dict[str, Any]] = []
    for record in output:
        market_id = str(record.get("marketId") or "")
        if market_id in seen:
            continue
        seen.add(market_id)
        merged.append(record)

    final_records = sorted(
        merged,
        key=lambda trail: (
            normalize_status(trail.get("status")) == "DIRECT_STRONG",
            normalize_status(trail.get("status")) == "DIRECT_WEAK",
            normalize_status(trail.get("status")) == "INFERRED_RELATED",
            float(trail.get("smartMoneyVolume") or 0.0),
            abs(float(trail.get("smartBias") or 0.0)),
        ),
        reverse=True,
    )

    validate_estela_output(final_records)
    return final_records


def build_estela_capital_by_market(
    trades: list[dict[str, Any]],
    market_trails: list[dict[str, Any]],
    wallet_scores: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return build_related_market_inferences(
        trades=trades,
        market_trails=market_trails,
        wallet_scores=wallet_scores,
    )
