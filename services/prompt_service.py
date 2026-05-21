from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
PROMPTS_DIR = ROOT_DIR / "prompts"


def load_prompt(prompt_name: str) -> str:
    prompt_path = PROMPTS_DIR / prompt_name

    if not prompt_path.exists():
        raise FileNotFoundError(f"No existe el prompt: {prompt_path}")

    return prompt_path.read_text(encoding="utf-8")


def render_prompt(
    prompt_template: str,
    mercado: str,
    contexto: str,
    metricas: str,
) -> str:
    return (
        prompt_template
        .replace("{{MERCADO}}", mercado)
        .replace("{{CONTEXTO}}", contexto)
        .replace("{{METRICAS}}", metricas)
    )