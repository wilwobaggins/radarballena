from services.prompt_service import load_prompt, render_prompt


def test_load_deepbrief_master_prompt():
    prompt = load_prompt("deepbrief_master_prompt.txt")

    assert "DeepSignal Engine" in prompt
    assert "STEEP Analysis" in prompt
    assert "Radar Score" in prompt
    assert "{{MERCADO}}" in prompt
    assert "{{CONTEXTO}}" in prompt
    assert "{{METRICAS}}" in prompt


def test_render_prompt_replaces_placeholders():
    template = load_prompt("deepbrief_master_prompt.txt")

    rendered = render_prompt(
        prompt_template=template,
        mercado='{"title": "Test market"}',
        contexto='[{"summary": "Test context"}]',
        metricas='{"radar_score": 66}',
    )

    assert "{{MERCADO}}" not in rendered
    assert "{{CONTEXTO}}" not in rendered
    assert "{{METRICAS}}" not in rendered
    assert "Test market" in rendered
    assert "Test context" in rendered
    assert "66" in rendered