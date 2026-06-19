import json
from pathlib import Path
from typing import Any

from services.prompt_service import load_prompt


ROOT_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT_DIR / "prompts"


def _format_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def load_shared_criteria() -> str:
    return load_prompt("shared_deepengine_criteria.txt")


def load_closing_recheck_prompt_template() -> str:
    return load_prompt("closing_recheck_comparative_prompt.txt")


def build_closing_recheck_prompt(
    *,
    market: dict[str, Any],
    previous_analysis: dict[str, Any] | None,
    latest_analysis: dict[str, Any],
    deltas: dict[str, Any],
    recheck_candidate: dict[str, Any],
    capital_trail: Any = None,
    market_snapshot: Any = None,
    repair_note: str | None = None,
) -> tuple[str, str]:
    template = load_closing_recheck_prompt_template()
    shared_criteria = load_shared_criteria()

    rendered = (
        template
        .replace("{{CRITERIA_BLOCK}}", shared_criteria)
        .replace("{{MERCADO}}", _format_json(market))
        .replace("{{PREVIOUS_ANALYSIS}}", _format_json(previous_analysis))
        .replace("{{LATEST_ANALYSIS}}", _format_json(latest_analysis))
        .replace("{{DELTAS}}", _format_json(deltas))
        .replace("{{RECHECK_CANDIDATE}}", _format_json(recheck_candidate))
        .replace("{{CAPITAL_TRAIL}}", _format_json(capital_trail))
        .replace("{{MARKET_SNAPSHOT}}", _format_json(market_snapshot))
    )

    if repair_note:
        rendered = f"{rendered}\n\nMODO REPARACION:\n{repair_note}\n"

    return rendered, "closing_recheck_comparative_prompt.txt"
