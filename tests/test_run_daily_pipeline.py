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


def test_select_top_markets_uses_env_politics_cap(monkeypatch):
    monkeypatch.setenv("DAILY_PIPELINE_TOP_N", "5")
    monkeypatch.setenv("DAILY_PIPELINE_CANDIDATE_POOL", "12")
    monkeypatch.setenv("DEEPENGINE_MAX_POLITICS_PER_RUN", "1")

    markets = [
        build_market("Will Gretchen Whitmer win the election?", "politics", 99),
        build_market("Will Gavin Newsom win the election?", "politics", 98),
        build_market("Will the Fed cut rates in September?", "macro", 97),
        build_market("Will Bitcoin hit 130k this quarter?", "crypto", 96),
        build_market("Will OpenAI launch GPT-6 this year?", "ai", 95),
        build_market("Will Nvidia beat earnings expectations?", "technology", 94),
        build_market("Will a ceasefire hold this month?", "geopolitics", 93),
    ]

    selected = select_top_markets(markets)
    selected_categories = [market["deepengine_category"] for market in selected]

    assert len(selected) == 5
    assert selected_categories.count("politics") == 1


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
        "prediction_audit": {
            "predicted_outcome": "no_call",
            "predicted_probability": None,
            "expected_direction": None,
            "prediction_confidence": "low",
            "prediction_reasoning_summary": "Sin postura clara en el primer intento.",
        },
    }
    second_deepbrief = {
        "lectura_clave": "Lectura 2",
        "radar_score": 68,
        "signal_label": "Directional Edge",
        "deepsignal_verdict": "Verdict 2",
        "confidence_level": "High",
        "prediction_audit": {
            "predicted_outcome": "yes",
            "predicted_probability": 0.68,
            "expected_direction": "yes_up",
            "prediction_confidence": "high",
            "prediction_reasoning_summary": "Catalizador y contexto favorecen el outcome principal.",
        },
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
            "parsed_output": deepbrief.copy(),
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
    assert saved_payloads[0]["deepbrief"]["signal_label"] == "Watchlist"
    assert saved_payloads[0]["raw_output"]["model_signal_label"] == "Directional Edge"
    assert saved_payloads[0]["raw_output"]["normalized_signal_label"] == "Watchlist"
    assert saved_payloads[0]["raw_output"]["parsed_output"]["signal_label"] == "Watchlist"
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
        "prediction_audit": {
            "predicted_outcome": "neutral",
            "predicted_probability": None,
            "expected_direction": "neutral",
            "prediction_confidence": "medium",
            "prediction_reasoning_summary": "El mercado sigue demasiado balanceado.",
        },
    }

    def fake_generate_deepbrief_for_market(**kwargs):
        raw_output = {
            "prompt_source": "deepbrief_master_prompt.txt",
            "provider": "openai",
            "fallback_used": False,
            "market_input": kwargs["market"],
            "parsed_output": anchored_deepbrief.copy(),
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
        "prediction_audit": {
            "predicted_outcome": "no_call",
            "predicted_probability": None,
            "expected_direction": None,
            "prediction_confidence": "low",
            "prediction_reasoning_summary": "Novelty market sin suficiente calidad predictiva.",
        },
    }

    saved_payloads: list[dict] = []

    def fake_generate_deepbrief_for_market(**kwargs):
        raw_output = {
            "prompt_source": "deepbrief_master_prompt.txt",
            "provider": "openai",
            "fallback_used": False,
            "market_input": kwargs["market"],
            "parsed_output": anchored_deepbrief.copy(),
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
    assert saved_payloads[0]["deepbrief"]["signal_label"] == "Low Signal"
    assert saved_payloads[0]["hybrid_score"]["ai_interpretive_score"] == 35
    assert saved_payloads[0]["raw_output"]["model_signal_label"] == "Neutral"
    assert saved_payloads[0]["raw_output"]["normalized_signal_label"] == "Low Signal"
    assert saved_payloads[0]["raw_output"]["parsed_output"]["signal_label"] == "Low Signal"
    assert saved_payloads[0]["raw_output"]["score_adjustment"] == {
        "applied": True,
        "reason": "anti_anchor_postprocess",
        "original_ai_score": 43,
        "adjusted_ai_score": 35,
    }


def test_generate_deepbrief_uses_deterministic_fallback_when_all_llm_providers_fail(monkeypatch):
    market = build_market("Will BTC hit 130k this quarter?", "crypto", 43)
    context_sources = [{"sourceTitle": "source"}] * 3

    monkeypatch.setenv("DETERMINISTIC_FALLBACK_ENABLED", "true")
    monkeypatch.setenv("DETERMINISTIC_FALLBACK_FRESHNESS_HOURS", "24")

    def fake_generate_deepbrief_for_market(**kwargs):
        raise run_daily_pipeline.AllDeepBriefProvidersFailedError(
            "Todos los proveedores LLM fallaron: openai, gemini",
            attempts=[
                {"provider": "openai", "status": "failed", "message": "openai"},
                {"provider": "gemini", "status": "failed", "message": "gemini"},
            ],
            classification="all_llm_providers_unavailable",
        )

    saved_payloads: list[dict] = []

    monkeypatch.setattr(
        run_daily_pipeline,
        "generate_deepbrief_for_market",
        fake_generate_deepbrief_for_market,
    )
    monkeypatch.setattr(run_daily_pipeline, "has_recent_deterministic_fallback", lambda **kwargs: False)
    monkeypatch.setattr(
        run_daily_pipeline,
        "persist_deterministic_deepbrief",
        lambda **kwargs: saved_payloads.append(kwargs) or {
            "id": "deepbrief-deterministic",
            "rawOutput": {"provider": "deterministic", "generation_mode": "deterministic_fallback"},
            "aiInterpretiveScore": None,
            "finalRadarScore": 43,
        },
    )

    result = run_daily_pipeline.generate_deepbrief(
        market=market,
        context_sources=context_sources,
        pipeline_run_id="pipeline-run-4",
    )

    assert result["id"] == "deepbrief-deterministic"
    assert saved_payloads[0]["fallback_reason"] == "all_llm_providers_unavailable"
    assert saved_payloads[0]["pipeline_run_id"] == "pipeline-run-4"


def test_generate_deepbrief_skips_recent_deterministic_fallback(monkeypatch):
    market = build_market("Will BTC hit 130k this quarter?", "crypto", 43)
    context_sources = [{"sourceTitle": "source"}] * 3

    monkeypatch.setenv("DETERMINISTIC_FALLBACK_ENABLED", "true")
    monkeypatch.setattr(
        run_daily_pipeline,
        "generate_deepbrief_for_market",
        lambda **kwargs: (_ for _ in ()).throw(
            run_daily_pipeline.AllDeepBriefProvidersFailedError(
                "Todos los proveedores LLM fallaron: openai, gemini",
                attempts=[],
                classification="all_llm_providers_unavailable",
            )
        ),
    )
    monkeypatch.setattr(run_daily_pipeline, "has_recent_deterministic_fallback", lambda **kwargs: True)
    monkeypatch.setattr(run_daily_pipeline, "persist_deterministic_deepbrief", lambda **kwargs: (_ for _ in ()).throw(AssertionError("no deberia persistir")))

    result = run_daily_pipeline.generate_deepbrief(
        market=market,
        context_sources=context_sources,
        pipeline_run_id="pipeline-run-5",
    )

    assert result["status"] == "skipped"
    assert result["reason"] == "skipped_recent_deterministic"


def test_save_results_persists_deepsignal_prediction(monkeypatch, caplog):
    saved_predictions: list[dict] = []

    class FakeDb:
        def insert_deepbrief(self, **kwargs):
            return {"id": "deepbrief-123"}

        def insert_deepsignal_prediction(self, **kwargs):
            saved_predictions.append(kwargs)
            return {"id": "prediction-123"}

    monkeypatch.setattr(run_daily_pipeline, "db", FakeDb())

    saved = run_daily_pipeline.save_results(
        market={
            "id": "market-123",
            "current_probability": 0.57,
        },
        deepbrief={
            "lectura_clave": "Lectura",
            "radar_score": 61,
            "signal_label": "Watchlist",
            "prediction_audit": {
                "predicted_outcome": "yes",
                "predicted_probability": 0.61,
                "expected_direction": "yes_up",
                "prediction_confidence": "medium",
                "prediction_reasoning_summary": "Lectura direccional moderada.",
            },
        },
        raw_output={"provider": "openai", "pipeline_run_id": "pipeline-123"},
        hybrid_score={"final_radar_score": 64},
        pipeline_run_id="pipeline-123",
    )

    assert saved["id"] == "deepbrief-123"
    assert saved_predictions[0]["deepbrief_id"] == "deepbrief-123"
    assert saved_predictions[0]["market_id"] == "market-123"
    assert (
        saved_predictions[0]["deepbrief_output"]["prediction_audit"]["predicted_outcome"]
        == "yes"
    )
    assert "DEEPSIGNAL_PREDICTION_SAVED" in caplog.text


def test_save_results_logs_prediction_error_without_raising(monkeypatch, caplog):
    class FakeDb:
        def insert_deepbrief(self, **kwargs):
            return {"id": "deepbrief-456"}

        def insert_deepsignal_prediction(self, **kwargs):
            raise RuntimeError("prediction insert failed")

    monkeypatch.setattr(run_daily_pipeline, "db", FakeDb())

    saved = run_daily_pipeline.save_results(
        market={"id": "market-456"},
        deepbrief={
            "lectura_clave": "Lectura",
            "radar_score": 52,
            "signal_label": "Watchlist",
            "prediction_audit": {
                "predicted_outcome": "no_call",
                "predicted_probability": None,
                "expected_direction": None,
                "prediction_confidence": "low",
                "prediction_reasoning_summary": "Ruido excesivo.",
            },
        },
        raw_output={"provider": "openai", "pipeline_run_id": "pipeline-456"},
        hybrid_score={"final_radar_score": 55},
        pipeline_run_id="pipeline-456",
    )

    assert saved["id"] == "deepbrief-456"
    assert "DEEPSIGNAL_PREDICTION_SAVE_ERROR" in caplog.text


def test_main_uses_attempt_pool_and_continues_after_skips(monkeypatch, caplog):
    monkeypatch.setenv("DAILY_PIPELINE_TOP_N", "2")
    monkeypatch.setenv("DAILY_PIPELINE_ATTEMPT_POOL", "4")
    monkeypatch.setenv("DEEPBRIEF_FRESHNESS_HOURS", "12")

    selected_markets = [
        build_market("Recent market", "macro", 99),
        build_market("Thin context market", "crypto", 98),
        build_market("Good market 1", "ai", 97),
        build_market("Good market 2", "geopolitics", 96),
    ]
    attempted_limits: list[int | None] = []
    generated_titles: list[str] = []
    finished_runs: list[dict] = []

    class FakeDb:
        def get_recent_deepbrief(self, market_db_id: str, hours: int):
            if market_db_id == "Recent market":
                return {"id": "deepbrief-recent"}
            return None

        def finish_pipeline_run(self, **kwargs):
            finished_runs.append(kwargs)

    monkeypatch.setattr(run_daily_pipeline, "start_pipeline_run", lambda: {"id": "pipeline-1"})
    monkeypatch.setattr(run_daily_pipeline, "fetch_markets", lambda: selected_markets)
    monkeypatch.setattr(run_daily_pipeline, "save_snapshots", lambda markets: markets)
    monkeypatch.setattr(
        run_daily_pipeline,
        "filter_markets",
        lambda markets: (markets, {"eligible_after_filters": len(markets)}),
    )
    monkeypatch.setattr(run_daily_pipeline, "score_market_batch", lambda markets: markets)

    def fake_select_top_markets(markets, limit=None):
        attempted_limits.append(limit)
        return markets[:limit]

    monkeypatch.setattr(run_daily_pipeline, "select_top_markets", fake_select_top_markets)
    monkeypatch.setattr(run_daily_pipeline, "db", FakeDb())
    monkeypatch.setattr(run_daily_pipeline, "fetch_context", lambda market, min_sources=3: [{"sourceTitle": "s1"}] * (2 if market["id"] == "Thin context market" else 3))
    monkeypatch.setattr(
        run_daily_pipeline,
        "generate_deepbrief",
        lambda market, context_sources, pipeline_run_id: generated_titles.append(market["title"]) or {"id": market["id"]},
    )
    monkeypatch.setattr(run_daily_pipeline, "register_pipeline_error", lambda **kwargs: None)

    run_daily_pipeline.main()

    assert attempted_limits == [4]
    assert generated_titles == ["Good market 1", "Good market 2"]
    assert finished_runs[0]["deepbriefs_generated"] == 2
    assert finished_runs[0]["markets_analyzed"] == 2
    assert "SELECTED_ATTEMPT_POOL_SIZE | selected=4 | requested=4 | target=2" in caplog.text
    assert "SKIPPED_RECENT_DEEPBRIEF_COUNT | count=1" in caplog.text
    assert "SKIPPED_CONTEXT_INSUFFICIENT_COUNT | count=1" in caplog.text
    assert "TARGET_DEEPBRIEFS_GENERATED | generated=2 | target=2" in caplog.text


def test_main_counts_deterministic_fallback_as_generated(monkeypatch):
    monkeypatch.setenv("DAILY_PIPELINE_TOP_N", "1")
    monkeypatch.setenv("DAILY_PIPELINE_ATTEMPT_POOL", "1")
    monkeypatch.setenv("DETERMINISTIC_FALLBACK_ENABLED", "true")

    selected_markets = [build_market("Fallback market", "crypto", 99)]
    finished_runs: list[dict] = []

    class FakeDb:
        def get_recent_deepbrief(self, market_db_id: str, hours: int):
            return None

        def finish_pipeline_run(self, **kwargs):
            finished_runs.append(kwargs)

    def fake_generate_deepbrief_for_market(**kwargs):
        raise run_daily_pipeline.AllDeepBriefProvidersFailedError(
            "Todos los proveedores LLM fallaron: openai, gemini",
            attempts=[],
            classification="all_llm_providers_unavailable",
        )

    monkeypatch.setattr(run_daily_pipeline, "start_pipeline_run", lambda: {"id": "pipeline-2"})
    monkeypatch.setattr(run_daily_pipeline, "fetch_markets", lambda: selected_markets)
    monkeypatch.setattr(run_daily_pipeline, "save_snapshots", lambda markets: markets)
    monkeypatch.setattr(
        run_daily_pipeline,
        "filter_markets",
        lambda markets: (markets, {"eligible_after_filters": len(markets)}),
    )
    monkeypatch.setattr(run_daily_pipeline, "score_market_batch", lambda markets: markets)
    monkeypatch.setattr(run_daily_pipeline, "select_top_markets", lambda markets, limit=None: markets)
    monkeypatch.setattr(run_daily_pipeline, "db", FakeDb())
    monkeypatch.setattr(run_daily_pipeline, "fetch_context", lambda market, min_sources=3: [{"sourceTitle": "s1"}] * 3)
    monkeypatch.setattr(run_daily_pipeline, "generate_deepbrief_for_market", fake_generate_deepbrief_for_market)
    monkeypatch.setattr(run_daily_pipeline, "has_recent_deterministic_fallback", lambda **kwargs: False)
    monkeypatch.setattr(
        run_daily_pipeline,
        "persist_deterministic_deepbrief",
        lambda **kwargs: {
            "id": "deepbrief-deterministic",
            "rawOutput": {"provider": "deterministic", "generation_mode": "deterministic_fallback"},
            "aiInterpretiveScore": None,
            "finalRadarScore": 99,
        },
    )
    monkeypatch.setattr(run_daily_pipeline, "register_pipeline_error", lambda **kwargs: None)

    run_daily_pipeline.main()

    assert finished_runs[0]["deepbriefs_generated"] == 1
    assert finished_runs[0]["markets_analyzed"] == 1
