import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workers.smart_money.smart_money_engine import main as smart_money_main
from workers.smart_money.smart_money_engine import supabase_writer
from workers.smart_money.smart_money_engine.market_trail import build_market_capital_trails
from workers.smart_money.smart_money_engine.related_markets import build_related_market_inferences
from workers.smart_money.smart_money_engine.wallet_classifier import (
    INSUFFICIENT_HISTORY,
    SIGNAL_WALLET,
    SPECIALIST_WALLET,
    WHALE_BUT_NOISY,
)
from workers.smart_money.smart_money_engine.wallet_metrics import compute_wallet_scores


def build_trade(
    wallet: str,
    market_id: str,
    *,
    price: float,
    size_usd: float,
    side: str = "BUY",
    outcome: str = "Yes",
    category_guess: str = "macro",
):
    return {
        "wallet": wallet,
        "market_id": market_id,
        "side": side,
        "outcome": outcome,
        "title": f"{category_guess} market {market_id}",
        "category_guess": category_guess,
        "size_usd": size_usd,
        "price": price,
        "timestamp": datetime.now(timezone.utc) - timedelta(hours=1),
        "raw": {},
    }


def test_compute_wallet_scores_generates_expected_shape():
    trades = [
        build_trade("0xsignal", "m1", price=0.22, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal", "m2", price=0.28, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal", "m3", price=0.35, size_usd=1800, category_guess="macro"),
        build_trade("0xsignal", "m4", price=0.4, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal", "m5", price=0.18, size_usd=1700, category_guess="macro"),
        build_trade("0xsignal", "m6", price=0.3, size_usd=2300, category_guess="politics"),
        build_trade("0xthin", "m7", price=0.91, size_usd=300, category_guess="crypto"),
        build_trade("0xthin", "m8", price=0.97, size_usd=200, category_guess="crypto"),
    ]

    scores = compute_wallet_scores(trades)

    assert len(scores) == 2
    assert 0 <= scores[0]["walletQualityScore"] <= 100
    assert "classification" in scores[0]
    assert scores[0]["classification"] in {SIGNAL_WALLET, SPECIALIST_WALLET}
    assert scores[0]["metrics"]["tradeCount"] == 6
    assert scores[0]["metrics"]["uniqueMarkets"] == 6
    assert "noiseScore" in scores[0]
    assert "noiseLevel" in scores[0]
    assert isinstance(scores[0]["riskFlags"], list)
    assert scores[1]["classification"] == INSUFFICIENT_HISTORY


def test_main_run_writes_wallet_scores_json(monkeypatch):
    trades = [
        build_trade("0xabc", "m1", price=0.2, size_usd=1200, category_guess="macro"),
        build_trade("0xabc", "m2", price=0.25, size_usd=1500, category_guess="macro"),
        build_trade("0xabc", "m3", price=0.3, size_usd=900, category_guess="macro"),
        build_trade("0xabc", "m4", price=0.55, size_usd=1100, category_guess="macro"),
        build_trade("0xabc", "m5", price=0.45, size_usd=1000, category_guess="macro"),
        build_trade("0xabc", "m6", price=0.5, size_usd=1300, category_guess="macro"),
    ]
    output_wallet_file = Path("workers/smart_money/smart_money_engine/outputs/test_wallet_scores.json")
    output_noise_file = Path("workers/smart_money/smart_money_engine/outputs/test_noise_scores.json")
    output_trails_file = Path("workers/smart_money/smart_money_engine/outputs/test_market_capital_trails.json")
    output_estela_file = Path("workers/smart_money/smart_money_engine/outputs/test_estela_capital_by_market.json")

    async def fake_fetch_recent_activity():
        return trades

    def fake_save_json(filename: str, data):
        if filename == "wallet_scores.json":
            target = output_wallet_file
        elif filename == "noise_scores.json":
            target = output_noise_file
        elif filename == "estela_capital_by_market.json":
            target = output_estela_file
        else:
            target = output_trails_file
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    monkeypatch.setattr(smart_money_main, "fetch_recent_activity", fake_fetch_recent_activity)
    monkeypatch.setattr(smart_money_main, "dedupe_trades", lambda items: items)
    monkeypatch.setattr(smart_money_main, "save_json", fake_save_json)

    wallet_scores = smart_money_main.asyncio.run(smart_money_main.run())

    assert len(wallet_scores) == 1
    payload = json.loads(output_wallet_file.read_text(encoding="utf-8"))
    assert payload[0]["wallet"] == "0xabc"
    assert 0 <= payload[0]["walletQualityScore"] <= 100
    assert "subScores" in payload[0]
    assert "noiseScore" in payload[0]
    assert "noiseLevel" in payload[0]
    trail_payload = json.loads(output_trails_file.read_text(encoding="utf-8"))
    assert len(trail_payload) == 6
    assert all("status" in item for item in trail_payload)
    noise_payload = json.loads(output_noise_file.read_text(encoding="utf-8"))
    assert len(noise_payload) == 1
    assert noise_payload[0]["wallet"] == "0xabc"
    assert "noiseScore" in noise_payload[0]
    estela_payload = json.loads(output_estela_file.read_text(encoding="utf-8"))
    assert len(estela_payload) == 6
    assert all(item["status"] == "DIRECT_WEAK" for item in estela_payload)


def test_high_noise_high_volume_wallet_is_demoted_to_whale_but_noisy():
    trades = [
        build_trade("0xnoisy", "m1", price=0.96, size_usd=4000, category_guess="crypto"),
        build_trade("0xnoisy", "m2", price=0.94, size_usd=3800, category_guess="crypto"),
        build_trade("0xnoisy", "m3", price=0.92, size_usd=4200, category_guess="crypto"),
        build_trade("0xnoisy", "m4", price=0.89, size_usd=4100, category_guess="crypto"),
        build_trade("0xnoisy", "m1", price=0.97, size_usd=3600, category_guess="politics"),
        build_trade("0xnoisy", "m2", price=0.95, size_usd=3900, category_guess="macro"),
        build_trade("0xnoisy", "m3", price=0.99, size_usd=4050, category_guess="politics"),
        build_trade("0xnoisy", "m4", price=0.93, size_usd=3950, category_guess="macro"),
        build_trade("0xnoisy", "m1", price=0.98, size_usd=4150, category_guess="crypto"),
        build_trade("0xnoisy", "m2", price=0.91, size_usd=3850, category_guess="politics"),
        build_trade("0xnoisy", "m3", price=0.96, size_usd=3750, category_guess="macro"),
        build_trade("0xnoisy", "m4", price=0.94, size_usd=4300, category_guess="crypto"),
        build_trade("0xsignal", "m10", price=0.24, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal", "m11", price=0.26, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal", "m12", price=0.28, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal", "m13", price=0.31, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal", "m14", price=0.22, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal", "m15", price=0.27, size_usd=2300, category_guess="macro"),
    ]

    scores = compute_wallet_scores(trades)
    by_wallet = {item["wallet"]: item for item in scores}

    assert by_wallet["0xnoisy"]["noiseLevel"] == "HIGH_NOISE"
    assert by_wallet["0xnoisy"]["noiseScore"] >= 70
    assert by_wallet["0xnoisy"]["classification"] == WHALE_BUT_NOISY
    assert by_wallet["0xsignal"]["classification"] in {SIGNAL_WALLET, SPECIALIST_WALLET}


def test_related_market_inference_fills_no_reliable_trail():
    trades = [
        build_trade("0xsignal1", "m1", price=0.22, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal1", "m2", price=0.24, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal1", "m3", price=0.27, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal1", "m4", price=0.29, size_usd=2300, category_guess="macro"),
        build_trade("0xsignal1", "m5", price=0.25, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal1", "m6", price=0.23, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal2", "m1", price=0.31, size_usd=2800, category_guess="macro"),
        build_trade("0xsignal2", "m2", price=0.28, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal2", "m3", price=0.33, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal2", "m4", price=0.30, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal2", "m5", price=0.26, size_usd=2000, category_guess="macro"),
        build_trade("0xsignal2", "m6", price=0.32, size_usd=2300, category_guess="macro"),
        build_trade("0xnoise", "m11", price=0.97, size_usd=350, category_guess="macro"),
    ]

    wallet_scores = compute_wallet_scores(trades)
    market_trails = build_market_capital_trails(trades, wallet_scores)
    estela = build_related_market_inferences(trades, market_trails)
    by_market = {item["marketId"]: item for item in estela}

    assert by_market["m1"]["status"] == "DIRECT_STRONG"
    assert by_market["m6"]["status"] in {"DIRECT_WEAK", "DIRECT_STRONG"}
    assert by_market["m11"]["status"] == "INFERRED_RELATED"
    assert by_market["m11"]["confidence"] <= 60
    assert by_market["m11"]["relatedMarketsUsed"] >= 2
    assert "relatedMarkets" in by_market["m11"]
    assert all(isinstance(item["confidence"], int) for item in estela)
    assert all(0 <= item["confidence"] <= 100 for item in estela)
    assert all("headline" in item for item in estela)
    assert all("interpretation" in item for item in estela)
    assert all(isinstance(item["riskFlags"], list) for item in estela)
    assert all(isinstance(item["events"], list) for item in estela)


def test_estela_no_reliable_trail_uses_fallback_shape():
    trades = [
        build_trade("0xsignal", "sports-1", price=0.24, size_usd=2800, category_guess="sports"),
        build_trade("0xsignal", "sports-2", price=0.29, size_usd=2600, category_guess="sports"),
        build_trade("0xsignal", "sports-3", price=0.27, size_usd=2400, category_guess="sports"),
        build_trade("0xsignal", "sports-1", price=0.26, size_usd=2200, category_guess="sports"),
        build_trade("0xsignal", "sports-2", price=0.31, size_usd=2100, category_guess="sports"),
        build_trade("0xsignal", "sports-3", price=0.28, size_usd=2300, category_guess="sports"),
        build_trade("0xnoise", "finance-1", price=0.96, size_usd=300, category_guess="macro"),
    ]

    wallet_scores = compute_wallet_scores(trades)
    market_trails = build_market_capital_trails(trades, wallet_scores)
    estela = build_related_market_inferences(trades, market_trails, wallet_scores)
    by_market = {item["marketId"]: item for item in estela}

    assert by_market["sports-1"]["status"] in {"DIRECT_STRONG", "DIRECT_WEAK"}
    assert by_market["finance-1"]["status"] == "NO_RELIABLE_TRAIL"
    assert by_market["finance-1"]["headline"] == "No hay trail confiable de Smart Money"
    assert by_market["finance-1"]["interpretation"] == (
        "No existe suficiente capital calificado o la señal actual es demasiado débil para una lectura confiable."
    )
    assert by_market["finance-1"]["confidence"] >= 20
    assert by_market["finance-1"]["confidence"] <= 35
    assert by_market["finance-1"]["events"] == []
    assert isinstance(by_market["finance-1"]["riskFlags"], list)
    assert "low_wallet_count" in by_market["finance-1"]["riskFlags"]


def test_build_market_capital_trails_generates_strong_and_no_reliable_statuses():
    trades = [
        build_trade("0xsignal1", "m1", price=0.22, size_usd=2500, category_guess="macro"),
        build_trade("0xsignal1", "m1", price=0.28, size_usd=2200, category_guess="macro"),
        build_trade("0xsignal1", "m2", price=0.26, size_usd=1800, category_guess="macro"),
        build_trade("0xsignal1", "m3", price=0.31, size_usd=1700, category_guess="macro"),
        build_trade("0xsignal1", "m4", price=0.24, size_usd=2000, category_guess="macro"),
        build_trade("0xsignal1", "m5", price=0.21, size_usd=1900, category_guess="macro"),
        build_trade("0xsignal2", "m1", price=0.33, size_usd=2600, category_guess="macro"),
        build_trade("0xsignal2", "m1", price=0.3, size_usd=2400, category_guess="macro"),
        build_trade("0xsignal2", "m6", price=0.34, size_usd=2300, category_guess="macro"),
        build_trade("0xsignal2", "m7", price=0.29, size_usd=2100, category_guess="macro"),
        build_trade("0xsignal2", "m8", price=0.27, size_usd=1800, category_guess="macro"),
        build_trade("0xsignal2", "m9", price=0.25, size_usd=2000, category_guess="macro"),
        build_trade("0xnoise", "m10", price=0.97, size_usd=500, category_guess="crypto"),
        build_trade("0xnoise", "m10", price=0.96, size_usd=400, category_guess="crypto"),
    ]

    wallet_scores = compute_wallet_scores(trades)
    trails = build_market_capital_trails(trades, wallet_scores)
    by_market = {item["marketId"]: item for item in trails}

    assert by_market["m1"]["qualifiedWalletCount"] >= 2
    assert by_market["m1"]["smartMoneyVolume"] > 0
    assert by_market["m1"]["smartBias"] > 0.35
    assert by_market["m1"]["status"] == "DIRECT_STRONG"
    assert by_market["m10"]["qualifiedWalletCount"] == 0
    assert by_market["m10"]["status"] == "NO_RELIABLE_TRAIL"


def test_upsert_capital_trails_preserves_existing_mapping_and_resolves_market_matches(monkeypatch):
    class FakeResult:
        def __init__(self, data):
            self.data = data

    class FakeQuery:
        def __init__(self, client, table_name):
            self.client = client
            self.table_name = table_name
            self.operation = "select"
            self.filters = {}
            self.payload = None

        def select(self, *_args, **_kwargs):
            self.operation = "select"
            return self

        def eq(self, field, value):
            self.filters[field] = value
            return self

        def limit(self, *_args, **_kwargs):
            return self

        def upsert(self, payload, **_kwargs):
            self.operation = "upsert"
            self.payload = payload
            self.client.last_upsert_payload = payload
            return self

        def execute(self):
            if self.table_name == "markets":
                return FakeResult(self.client.markets_rows)

            if self.table_name == "smart_money_capital_trails" and self.operation == "select":
                source_market_id = self.filters.get("sourceMarketId")
                rows = [
                    row
                    for row in self.client.existing_trails
                    if row.get("sourceMarketId") == source_market_id
                ]
                return FakeResult(rows[:1])

            return FakeResult([])

    class FakeClient:
        def __init__(self):
            self.markets_rows = [
                {
                    "id": "market-1",
                    "title": "Crypto Market 1",
                    "external_market_id": "source-1",
                },
                {
                    "id": "market-2",
                    "title": "Title Match Market",
                    "externalMarketId": "source-2",
                },
            ]
            self.existing_trails = [
                {
                    "sourceMarketId": "source-3",
                    "marketId": "market-existing",
                    "externalMarketId": "source-3-existing",
                },
                {
                    "sourceMarketId": "source-4",
                    "marketId": None,
                    "externalMarketId": "source-4-old",
                },
            ]
            self.last_upsert_payload = None

        def table(self, table_name):
            return FakeQuery(self, table_name)

    fake_client = FakeClient()

    monkeypatch.setattr(supabase_writer, "_get_client", lambda: fake_client)
    supabase_writer._MARKETS_CACHE = None
    supabase_writer._CAPITAL_TRAIL_CACHE.clear()
    supabase_writer._MARKET_RESOLUTION_CACHE.clear()

    trails = [
        {
            "marketId": "source-1",
            "title": "Some unrelated title",
            "status": "DIRECT_WEAK",
            "headline": "Matched by id",
            "interpretation": "id",
            "confidence": 10,
            "smartBias": 0.1,
            "qualifiedWalletCount": 1,
            "smartMoneyVolume": 100,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
        {
            "marketId": "source-2",
            "title": "title match market",
            "status": "DIRECT_WEAK",
            "headline": "Matched by title",
            "interpretation": "title",
            "confidence": 20,
            "smartBias": 0.2,
            "qualifiedWalletCount": 2,
            "smartMoneyVolume": 200,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
        {
            "marketId": "source-3",
            "title": "No match but preserve",
            "status": "DIRECT_WEAK",
            "headline": "Preserve",
            "interpretation": "preserve",
            "confidence": 30,
            "smartBias": 0.3,
            "qualifiedWalletCount": 3,
            "smartMoneyVolume": 300,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
        {
            "marketId": "source-4",
            "title": "Still unmapped",
            "status": "DIRECT_WEAK",
            "headline": "Unmapped",
            "interpretation": "unmapped",
            "confidence": 40,
            "smartBias": 0.4,
            "qualifiedWalletCount": 4,
            "smartMoneyVolume": 400,
            "riskFlags": [],
            "events": [],
            "relatedMarkets": [],
            "generatedAt": "2026-06-18T00:00:00Z",
        },
    ]

    supabase_writer.upsert_capital_trails("run-1", trails)

    payload = fake_client.last_upsert_payload
    by_source = {row["sourceMarketId"]: row for row in payload}

    assert by_source["source-1"]["marketId"] == "market-1"
    assert by_source["source-1"]["externalMarketId"] == "source-1"
    assert by_source["source-2"]["marketId"] == "market-2"
    assert by_source["source-2"]["externalMarketId"] == "source-2"
    assert by_source["source-3"]["marketId"] == "market-existing"
    assert by_source["source-3"]["externalMarketId"] == "source-3-existing"
    assert by_source["source-4"]["marketId"] is None
    assert by_source["source-4"]["externalMarketId"] == "source-4"
