import os
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client


load_dotenv()


def required_env(name: str) -> str:
    value = os.getenv(name)

    if not value:
        raise RuntimeError(f"Falta variable de entorno: {name}")

    return value


def get_supabase_client() -> Client:
    url = required_env("SUPABASE_URL")
    key = required_env("SUPABASE_SERVICE_ROLE_KEY")

    return create_client(url, key)


def insert_market(market: dict[str, Any]) -> dict[str, Any]:
    """
    Inserta o actualiza un mercado usando platform + external_market_id.
    Devuelve el registro guardado.
    """
    supabase = get_supabase_client()

    external_market_id = str(
        market.get("external_market_id")
        or market.get("marketId")
        or ""
    )

    if not external_market_id:
        raise ValueError("market necesita external_market_id o marketId")

    platform = market.get("platform", "polymarket")

    existing = (
        supabase
        .table("markets")
        .select("*")
        .eq("external_market_id", external_market_id)
        .eq("platform", platform)
        .limit(1)
        .execute()
    )

    payload = {
        "external_market_id": external_market_id,
        "platform": platform,
        "title": market.get("title"),
        "description": market.get("description"),
        "category": market.get("category"),
        "url": market.get("url"),
        "close_date": market.get("close_date"),
        "current_probability": market.get("current_probability"),
        "previous_probability_24h": market.get("previous_probability_24h"),
        "probability_change_24h": market.get("probability_change_24h"),
        "volume": market.get("volume"),
        "liquidity": market.get("liquidity"),
        "outcomes": market.get("outcomes", []),
        "last_updated": market.get("last_updated"),
    }

    if existing.data:
        marketId = existing.data[0]["id"]

        response = (
            supabase
            .table("markets")
            .update(payload)
            .eq("id", marketId)
            .execute()
        )
    else:
        response = (
            supabase
            .table("markets")
            .insert(payload)
            .execute()
        )

    if not response.data:
        raise RuntimeError("No se pudo guardar market")

    return response.data[0]


def insert_snapshot(market_db_id: str, market: dict[str, Any]) -> dict[str, Any]:
    """
    Guarda snapshot cuantitativo del mercado.
    """
    supabase = get_supabase_client()

    payload = {
    "marketId": market_db_id,
    "current_probability": market.get("current_probability"),
    "previous_probability_24h": market.get("previous_probability_24h"),
    "probability_change_24h": market.get("probability_change_24h"),
    "volume": market.get("volume"),
    "liquidity": market.get("liquidity"),
    }

    response = (
        supabase
        .table("market_snapshots")
        .insert(payload)
        .execute()
    )

    if not response.data:
        raise RuntimeError("No se pudo guardar market_snapshot")

    return response.data[0]


def insert_deepbrief(
    market_db_id: str,
    deepbrief: dict[str, Any],
    raw_output: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Guarda DeepBrief asociado a un market.
    """
    supabase = get_supabase_client()

    payload = {
        "marketId": market_db_id,
        "lecturaClave": deepbrief.get("lectura_clave"),
        "radarScore": deepbrief.get("radar_score"),
        "radarScoreBreakdown": deepbrief.get("radar_score_breakdown"),
        "signalLabel": deepbrief.get("signal_label"),
        "estelaDeCapital": deepbrief.get("estela_de_capital"),
        "entornoDeSenal": deepbrief.get("entorno_de_senal"),
        "corrienteNarrativa": deepbrief.get("corriente_narrativa"),
        "filtroDeRuido": deepbrief.get("filtro_de_ruido"),
        "premortem": deepbrief.get("premortem"),
        "mapaDeRuptura": deepbrief.get("mapa_de_ruptura"),
        "mapaDeEscenarios": deepbrief.get("mapa_de_escenarios"),
        "actualizacionBayesiana": deepbrief.get("actualizacion_bayesiana"),
        "deepsignalVerdict": deepbrief.get("deepsignal_verdict"),
        "confidenceLevel": deepbrief.get("confidence_level"),
        "watchTriggers": deepbrief.get("watch_triggers"),
        "rawOutput": raw_output or deepbrief,
    }

    response = (
        supabase
        .table("deepbriefs")
        .insert(payload)
        .execute()
    )

    if not response.data:
        raise RuntimeError("No se pudo guardar deepbrief")

    return response.data[0]