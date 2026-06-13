import sys
import types


fake_tavily = types.ModuleType("tavily")
fake_tavily.TavilyClient = object
sys.modules.setdefault("tavily", fake_tavily)

import scripts.run_daily_pipeline as run_daily_pipeline
from scripts.run_daily_pipeline import (
    build_candidate_pool,
    generate_deepbrief,
    select_top_markets,
)


def build_market(
    title: str,
    category: str,
    score: int,
) -> dict:
    return {
        "id": title,
        "title": title,
        "category": category,
        "deepengine_category": category,
        "preliminary_radar_score": score,
        "probability_change_24h": 0.05,
        "volume": 200_000,
        "liquidity": 80_000,
        "score_breakdown": {},
    }


def test_select_top_markets_limits_repeated_theme_and_family(monkeypatch):
    monkeypatch.setenv("DAILY_PIPELINE_TOP_N", "5")
    monkeypatch.setenv("DAILY_PIPELINE_CANDIDATE_POOL", "10")

    markets = [
        build_market(
            "Will Jon Ossoff win the 2028 Democratic presidential nomination?",
            "politics",
            95,
        ),
        build_market(
            "Will Gavin Newsom win the 2028 Democratic presidential nomination?",
            "politics",
            94,
        ),
        build_market(
            "Will Pete Buttigieg win the 2028 Democratic presidential nomination?",
            "politics",
            93,
        ),
        build_market("Will Bitcoin hit 130k this quarter?", "crypto", 92),
        build_market("Will the Fed cut rates in September?", "macro", 91),
        build_market("Will OpenAI launch GPT-6 this year?", "ai", 90),
        build_market("Will Nvidia beat earnings expectations?", "technology", 89),
    ]

    selected = select_top_markets(markets)
    selected_titles = [market["title"] for market in selected]

    nomination_markets = [
        title
        for title in selected_titles
        if "2028 Democratic presidential nomination" in title
    ]

    assert len(selected) == 5
    assert len(nomination_markets) <= 1
    assert "Will Bitcoin hit 130k this quarter?" in selected_titles
    assert "Will the Fed cut rates in September?" in selected_titles


def test_select_top_markets_prefers_vertical_buckets_before_global_fill(monkeypatch):
    monkeypatch.setenv("DAILY_PIPELINE_TOP_N", "4")
    monkeypatch.setenv("DAILY_PIPELINE_CANDIDATE_POOL", "12")

    markets = [
        build_market("Will Gretchen Whitmer win the election?", "politics", 99),
        build_market("Will Gavin Newsom win the election?", "politics", 98),
        build_market("Will the Fed cut rates in September?", "macro", 80),
        build_market("Will Bitcoin hit 130k this quarter?", "crypto", 79),
        build_market("Will OpenAI launch GPT-6 this year?", "ai", 78),
        build_market("Will a ceasefire hold this month?", "geopolitics", 77),
    ]

    selected = select_top_markets(markets)
    selected_categories = [market["deepengine_category"] for market in selected]

    assert len(selected) == 4
    assert "macro" in selected_categories
    assert "geopolitics" in selected_categories
    assert "crypto" in selected_categories
    assert "ai" in selected_categories
    assert "politics" not in selected_categories


def test_build_candidate_pool_caps_politics_before_selection(monkeypatch):
    monkeypatch.setenv("DEEPENGINE_MAX_POLITICS_PER_RUN", "1")

    sorted_markets = [
        build_market("Will Gretchen Whitmer win the election?", "politics", 99),
        build_market("Will Gavin Newsom win the election?", "politics", 98),
        build_market("Will the Fed cut rates in September?", "macro", 97),
        build_market("Will Bitcoin hit 130k this quarter?", "crypto", 96),
        build_market("Will OpenAI launch GPT-6 this year?", "ai", 95),
        build_market("Will a ceasefire hold this month?", "geopolitics", 94),
        build_market("Will a new FDA rule pass this quarter?", "regulation", 93),
    ]

    candidate_pool = build_candidate_pool(sorted_markets, candidate_pool_size=6)
    categories = [market["deepengine_category"] for market in candidate_pool]

    assert categories.count("politics") == 1
    assert "macro" in categories
    assert "crypto" in categories
    assert "ai" in categories


def test_build_candidate_pool_caps_2028_democratic_nomination_to_one(monkeypatch):
    monkeypatch.setenv("DEEPENGINE_MAX_POLITICS_PER_RUN", "2")

    sorted_markets = [
        build_market(
            "Will Jon Ossoff win the 2028 Democratic presidential nomination?",
            "politics",
            99,
        ),
        build_market(
            "Will Gavin Newsom win the 2028 Democratic presidential nomination?",
            "politics",
            98,
        ),
        build_market("Will the Fed cut rates in September?", "macro", 97),
        build_market("Will Bitcoin hit 130k this quarter?", "crypto", 96),
        build_market("Will OpenAI launch GPT-6 this year?", "ai", 95),
    ]

    candidate_pool = build_candidate_pool(sorted_markets, candidate_pool_size=5)
    nomination_titles = [
        market["title"]
        for market in candidate_pool
        if "2028 Democratic presidential nomination" in market["title"]
    ]

    assert len(nomination_titles) == 1


def test_generate_deepbrief_retries_when_ai_score_is_anchored(monkeypatch):
    market = build_market("Will BTC hit 130k this quarter?", "crypto", 43)
    market["relevance_reasons"] = ["probability_move"]
    market["novelty_market"] = False
    context_sources = [{"sourceTitle": "source"}] * 3

    first_deepbrief = {
        "lectura_clave": "Lectura 1",
        "radar_score": 43,
        "signal_label": "Neutral",
        "deepsignal_verdict": "Verdict 1",
        "confidence_level": "Medium",
    }
    second_deepbrief = {
        "lectura_clave": "Lectura 2",
        "radar_score": 68,
        "signal_label": "Directional Edge",
        "deepsignal_verdict": "Verdict 2",
        "confidence_level": "High",
    }

    calls: list[dict] = []

    def fake_generate_deepbrief_for_market(**kwargs):
        calls.append(kwargs)
        deepbrief = first_deepbrief if len(calls) == 1 else second_deepbrief
        raw_output = {
            "prompt_source": "deepbrief_master_prompt.txt",
            "provider": "openai",
            "fallback_used": False,
            "market_input": kwargs["market"],
        }
        return deepbrief, raw_output

    saved_payloads: list[dict] = []

    monkeypatch.setattr(
        run_daily_pipeline,
        "generate_deepbrief_for_market",
        fake_generate_deepbrief_for_market,
    )
    monkeypatch.setattr(
        run_daily_pipeline,
        "save_results",
        lambda **kwargs: saved_payloads.append(kwargs) or {"id": "deepbrief-1"},
    )
    monkeypatch.setattr(
        run_daily_pipeline,
        "create_alerts",
        lambda **kwargs: [],
    )

    saved = generate_deepbrief(
        market=market,
        context_sources=context_sources,
        pipeline_run_id="pipeline-run-1",
    )

    assert saved["id"] == "deepbrief-1"
    assert len(calls) == 2
    assert calls[0].get("anti_anchor_note") is None
    assert calls[1]["anti_anchor_note"] == run_daily_pipeline.ANTI_ANCHOR_NOTE
    assert saved_payloads[0]["pipeline_run_id"] == "pipeline-run-1"
    assert saved_payloads[0]["raw_output"]["pipeline_run_id"] == "pipeline-run-1"
    assert saved_payloads[0]["raw_output"]["market_input"]["novelty_market"] is False
    assert saved_payloads[0]["raw_output"]["market_input"]["relevance_reasons"] == [
        "probability_move"
    ]
    assert saved_payloads[0]["raw_output"]["score_adjustment"]["applied"] is False


def test_generate_deepbrief_logs_persisted_when_retry_stays_anchored(monkeypatch, caplog):
    market = build_market("Will BTC hit 130k this quarter?", "crypto", 43)
    market["relevance_reasons"] = []
    market["novelty_market"] = False
    market["probability_change_24h"] = 0.0
    context_sources = [{"sourceTitle": "source"}] * 3

    anchored_deepbrief = {
        "lectura_clave": "Lectura",
        "radar_score": 43,
        "signal_label": "Neutral",
        "deepsignal_verdict": "Verdict",
        "confidence_level": "Medium",
    }

    def fake_generate_deepbrief_for_market(**kwargs):
        raw_output = {
            "prompt_source": "deepbrief_master_prompt.txt",
            "provider": "openai",
            "fallback_used": False,
            "market_input": kwargs["market"],
        }
        return anchored_deepbrief, raw_output

    monkeypatch.setattr(
        run_daily_pipeline,
        "generate_deepbrief_for_market",
        fake_generate_deepbrief_for_market,
    )
    monkeypatch.setattr(
        run_daily_pipeline,
        "save_results",
        lambda **kwargs: {"id": "deepbrief-2"},
    )
    monkeypatch.setattr(
        run_daily_pipeline,
        "create_alerts",
        lambda **kwargs: [],
    )

    generate_deepbrief(
        market=market,
        context_sources=context_sources,
        pipeline_run_id="pipeline-run-2",
    )

    assert "MARKET_METADATA_DEBUG" in caplog.text
    assert "AI_SCORE_ANCHORING_PERSISTED" in caplog.text


def test_generate_deepbrief_applies_postprocess_for_novelty_anchor(monkeypatch, caplog):
    market = build_market("Will BTC hit 130k this quarter?", "crypto", 43)
    market["relevance_reasons"] = []
    market["novelty_market"] = True
    market["probability_change_24h"] = 0.0
    context_sources = [{"sourceTitle": "source"}] * 3

    anchored_deepbrief = {
        "lectura_clave": "Lectura",
        "radar_score": 43,
        "signal_label": "Neutral",
        "deepsignal_verdict": "Verdict",
        "confidence_level": "Medium",
    }

    saved_payloads: list[dict] = []

    def fake_generate_deepbrief_for_market(**kwargs):
        raw_output = {
            "prompt_source": "deepbrief_master_prompt.txt",
            "provider": "openai",
            "fallback_used": False,
            "market_input": kwargs["market"],
        }
        return anchored_deepbrief, raw_output

    monkeypatch.setattr(
        run_daily_pipeline,
        "generate_deepbrief_for_market",
        fake_generate_deepbrief_for_market,
    )
    monkeypatch.setattr(
        run_daily_pipeline,
        "save_results",
        lambda **kwargs: saved_payloads.append(kwargs) or {"id": "deepbrief-3"},
    )
    monkeypatch.setattr(
        run_daily_pipeline,
        "create_alerts",
        lambda **kwargs: [],
    )

    generate_deepbrief(
        market=market,
        context_sources=context_sources,
        pipeline_run_id="pipeline-run-3",
    )

    assert "AI_SCORE_POSTPROCESS_APPLIED" in caplog.text
    assert saved_payloads[0]["hybrid_score"]["ai_interpretive_score"] == 35
    assert saved_payloads[0]["raw_output"]["score_adjustment"] == {
        "applied": True,
        "reason": "anti_anchor_postprocess",
        "original_ai_score": 43,
        "adjusted_ai_score": 35,
    }
