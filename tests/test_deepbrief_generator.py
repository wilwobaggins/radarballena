from services.deepbrief_generator import build_deepbrief_prompt, build_raw_market_input


def test_build_deepbrief_prompt_uses_master_prompt_placeholders():
    market = {
        "title": "Will BTC close above 100k this month?",
        "description": "Binary crypto market.",
        "category": "crypto",
        "url": "https://polymarket.com/event/test",
        "close_date": "2026-06-30T00:00:00+00:00",
        "current_probability": 0.54,
        "previous_probability_24h": 0.49,
        "probability_change_24h": 0.05,
        "volume": 123456,
        "liquidity": 45678,
        "outcomes": ["Yes", "No"],
        "preliminary_radar_score": 43,
        "score_breakdown": {
            "volume_score": 9,
            "liquidity_score": 18,
            "time_to_close_score": 8,
            "probability_movement_score": 8,
            "resolution_score": 10,
            "narrative_score": 10,
        },
    }
    context_sources = [
        {
            "sourceTitle": "Macro note",
            "sourceUrl": "https://example.com/macro",
            "publishedDate": "2026-06-10T00:00:00+00:00",
            "summary": "Risk assets are repricing after policy headlines.",
            "relevanceScore": 0.82,
        }
    ]

    prompt, prompt_source = build_deepbrief_prompt(
        market=market,
        context_sources=context_sources,
    )

    assert prompt_source == "deepbrief_master_prompt.txt"
    assert "STEEP Analysis" in prompt
    assert "Premortem Analysis" in prompt
    assert '"title": "Will BTC close above 100k this month?"' in prompt
    assert "Macro note" in prompt
    assert '"preliminary_radar_score": 43' in prompt
    assert "{{MERCADO}}" not in prompt
    assert "{{CONTEXTO}}" not in prompt
    assert "{{METRICAS}}" not in prompt


def test_build_deepbrief_prompt_appends_anti_anchor_note():
    prompt, _prompt_source = build_deepbrief_prompt(
        market={"title": "Test market"},
        context_sources=[],
        anti_anchor_note="No copies el preliminary score.",
    )

    assert "VALIDACION SEMANTICA ANTI-ANCLAJE" in prompt
    assert "No copies el preliminary score." in prompt


def test_build_raw_market_input_keeps_relevance_metadata():
    market = {
        "title": "Test market",
        "deepengine_category": "macro",
        "relevance_reasons": ["strategic_context"],
        "novelty_market": False,
        "relevance_exclusion_reason": None,
        "preliminary_radar_score": 43,
    }

    raw_market_input = build_raw_market_input(market)

    assert raw_market_input["deepengine_category"] == "macro"
    assert raw_market_input["relevance_reasons"] == ["strategic_context"]
    assert raw_market_input["novelty_market"] is False
    assert "relevance_exclusion_reason" in raw_market_input
