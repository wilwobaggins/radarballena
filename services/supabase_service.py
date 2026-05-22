import os
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


def test_supabase_connection() -> dict:
    supabase = get_supabase_client()

    response = (
        supabase
        .table("pipeline_runs")
        .select("*")
        .limit(1)
        .execute()
    )

    return {
        "status": "ok",
        "data": response.data,
    }


def insert_test_pipeline_run() -> dict:
    supabase = get_supabase_client()

    response = (
        supabase
        .table("pipeline_runs")
        .insert({
            "markets_fetched": 0,
            "markets_filtered": 0,
            "markets_analyzed": 0,
            "status": "test_connection",
            "error_message": None,
        })
        .execute()
    )

    return {
        "status": "insert_ok",
        "data": response.data,
    }