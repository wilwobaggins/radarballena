import time
import hashlib
import json
import urllib.parse
import urllib.request
import urllib.error
import os

WATCHED_WHALES = {
    "nba_volume": {
        "name": "NBA Volume Trader Theta",
        "wallet": "0x32ed517a571c01b6e9adecf61ba81ca48ff2f960",
        "min_usdc": 200,
    },
    "sports_arb": {
        "name": "Global Sports Arb Lambda",
        "wallet": "0x479e330b07822ee28e20bac5e504f1b7c6b591c3",
        "min_usdc": 500,
    },
    "global_trader": {
        "name": "Everything Trader Zeta",
        "wallet": "0x9d84ce0306f8551e02efef1680475fc0f1dc1344",
        "min_usdc": 300,
    },
    "macro_economics": {
        "name": "Macro Economics Whale",
        "wallet": "0xc8ab97a9089a9ff7e6ef0688e6e591a066946418",
        "min_usdc": 150,
    },
    "geo_macro": {
        "name": "Geopolitical Macro Whale",
        "wallet": "0xbacd00c9080a82ded56f504ee8810af732b0ab35",
        "min_usdc": 150,
    },
    "sports_esports_titan": {
        "name": "Soccer Esports Titan Alpha",
        "wallet": "0x2663daca3cecf3767ca1c3b126002a8578a8ed1f",
        "min_usdc": 175,
    }
}

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
DATA_API = "https://data-api.polymarket.com/activity"
SEEN_FILE = os.getenv("SEEN_FILE", "/data/seen_hashes.json")
MAX_SEEN_HASHES = 10000
MAX_AGE_SECONDS = int(os.getenv("MAX_AGE_SECONDS", "259200"))
MAX_ALERTS_PER_MARKET_PER_RUN = int(os.getenv("MAX_ALERTS_PER_MARKET_PER_RUN", "2"))
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:3000").rstrip("/")
INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

# En producción: True para ignorar lo viejo al arrancar.
SKIP_OLD_ON_START = os.getenv("SKIP_OLD_ON_START", "true").lower() == "true"


def get_json(url, params=None, timeout=45):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "radarballena-whale-worker/1.0"},
    )

    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def safe_float(value, default=0.0):
    """Safely convert value to float with fallback."""
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def make_hash(item):
    raw = (
        f"{item.get('transactionHash')}:"
        f"{item.get('asset')}:"
        f"{item.get('timestamp')}:"
        f"{item.get('side')}:"
        f"{item.get('size')}"
    )
    return hashlib.sha256(raw.encode()).hexdigest()


def load_seen_hashes():
    """Load seen hashes from persistent file."""
    if os.path.exists(SEEN_FILE):
        try:
            with open(SEEN_FILE, 'r') as f:
                return set(json.load(f))
        except Exception as e:
            print(f"[WARN] Failed to load seen hashes: {e}")
    return set()


def save_seen_hashes(seen):
    """Save seen hashes to persistent file, limiting to MAX_SEEN_HASHES."""
    try:
        os.makedirs(os.path.dirname(SEEN_FILE) or ".", exist_ok=True)
        # Keep only the most recent hashes to prevent unbounded growth
        hashes_list = list(seen)[-MAX_SEEN_HASHES:]
        with open(SEEN_FILE, 'w') as f:
            json.dump(hashes_list, f)
    except Exception as e:
        print(f"[WARN] Failed to save seen hashes: {e}")


def fetch_activity(wallet):
    params = {
        "user": wallet,
        "limit": 50,
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC",
    }

    return get_json(DATA_API, params)


def is_relevant_trade(item, whale_id):
    title = (item.get("title") or "").lower()
    event_slug = (item.get("eventSlug") or "").lower()
    text = f"{title} {event_slug}"

    nba_keywords = [
        "nba",
        "lakers", "warriors", "celtics", "knicks", "hawks",
        "cavaliers", "pistons", "spurs", "nuggets", "timberwolves",
        "mavericks", "suns", "bucks", "heat", "sixers",
        "spread", "diferencial", "o/u", "over", "under", "moneyline",
    ]

    sports_arb_keywords = [
        "nba", "mlb", "nhl", "nfl",
        "soccer", "football", "futbol",
        "premier league", "champions league", "la liga", "serie a", "bundesliga",
        "mls", "fifa", "club world cup",
        "tennis", "atp", "wta",
        "ufc", "mma", "boxing",
        "esports", "cs2", "counter-strike", "dota", "valorant", "league of legends",
        "spread", "diferencial", "handicap",
        "o/u", "over", "under",
        "moneyline", "winner", "ganador",
    ]

    macro_keywords = [
        "fed", "fomc", "rate cut", "rate hike",
        "interest rate", "inflation", "cpi", "core cpi",
        "jobs report", "unemployment", "nonfarm",
        "gdp", "recession", "treasury", "powell",
        "dollar", "yield",
    ]

    geo_keywords = [
        "ukraine", "russia", "israel", "iran", "gaza",
        "taiwan", "china", "nato", "ceasefire",
        "sanctions", "tariffs", "trade war",
        "nuclear deal", "war", "strike", "military",
        "syria", "poland",
    ]

    if whale_id == "nba_volume":
        return any(k in text for k in nba_keywords)

    if whale_id == "sports_arb":
        return any(k in text for k in sports_arb_keywords)

    if whale_id == "macro_economics":
        return any(k in text for k in macro_keywords)

    if whale_id == "geo_macro":
        return any(k in text for k in geo_keywords)

    # global_trader: acepta todo
    if whale_id == "global_trader":
        return True

    return True

GAMMA_API = "https://gamma-api.polymarket.com"


def normalize_text(text):
    return " ".join((text or "").lower().replace("?", "").replace(",", "").split())


def get_alert_market_key(alert, item):
    return (
        str(alert.get("market_id") or "").strip()
        or str(item.get("slug") or "").strip()
        or str(item.get("eventSlug") or "").strip()
        or normalize_text(alert.get("market_title") or item.get("title") or "")
        or "unknown_market"
    )


def get_market_id_by_slug(slug):
    if not slug:
        return None

    url = f"{GAMMA_API}/markets/slug/{urllib.parse.quote(slug)}"

    try:
        data = get_json(url, timeout=15)

        if isinstance(data, dict) and data.get("id"):
            print(f"[MARKET_SLUG_MATCH] {slug} -> {data.get('id')}", flush=True)
            return str(data.get("id"))

    except Exception as e:
        print(f"[MARKET_SLUG_ERROR] slug={slug} error={type(e).__name__}: {e}", flush=True)

    return None


def get_market_id_from_event_slug(event_slug, alert_title=None):
    if not event_slug:
        return None

    url = f"{GAMMA_API}/events/slug/{urllib.parse.quote(event_slug)}"

    try:
        data = get_json(url, timeout=15)

        if not isinstance(data, dict):
            return None

        markets = data.get("markets") or []

        if not isinstance(markets, list) or not markets:
            return None

        alert_norm = normalize_text(alert_title)

        best_market = None
        best_score = -1

        for market in markets:
            market_id = market.get("id")
            if not market_id:
                continue

            blob = " ".join([
                str(market.get("title") or ""),
                str(market.get("question") or ""),
                str(market.get("slug") or ""),
                str(market.get("groupItemTitle") or ""),
            ])

            blob_norm = normalize_text(blob)

            score = 0

            if alert_norm and alert_norm in blob_norm:
                score += 20

            alert_words = set(alert_norm.split())
            blob_words = set(blob_norm.split())

            if alert_words and blob_words:
                score += len(alert_words & blob_words)

            if score > best_score:
                best_score = score
                best_market = market

        if best_market and best_market.get("id"):
            print(
                f"[EVENT_SLUG_MATCH] {event_slug} -> {best_market.get('id')} score={best_score}",
                flush=True,
            )
            return str(best_market.get("id"))

    except Exception as e:
        print(f"[EVENT_SLUG_ERROR] slug={event_slug} error={type(e).__name__}: {e}", flush=True)

    return None


def resolve_market_id(item, market_title):
    market_slug = item.get("slug")
    event_slug = item.get("eventSlug")

    market_id = get_market_id_by_slug(market_slug)

    if market_id:
        return market_id

    market_id = get_market_id_from_event_slug(event_slug, market_title)

    if market_id:
        return market_id

    print(
        f"[NO_MARKET_ID] title={market_title} market_slug={market_slug} event_slug={event_slug}",
        flush=True,
    )

    return None


def parse_alert(item, whale_id, whale_name):
    price = safe_float(item.get("price"))
    size_usd = safe_float(item.get("usdcSize"))
    shares = safe_float(item.get("size"))

    event_slug = item.get("eventSlug")

    action = item.get("side") or ""
    answer = item.get("outcome") or ""
    market_title = item.get("title") or ""

    market_id = resolve_market_id(item, market_title)

    polymarket_url = (
        f"https://polymarket.com/event/{event_slug}"
        if event_slug
        else None
    )

    raw_text = (
        f"🐋 WHALE ALERT\n\n"
        f"👤 {whale_name}\n"
        f"📈 {action} {answer}\n"
        f"📊 \"{market_title}\"\n\n"
        f"💰 Size: ${size_usd:,.2f}\n"
        f"💲 Price: {int(round(price * 100))}¢ ({int(round(shares))} shares)\n"
        + (f"\n🔗 {polymarket_url}" if polymarket_url else "")
    )

    payload = {
        "whale_id": whale_id,
        "whale_name": whale_name,
        "action": action,
        "answer": answer,
        "market_title": market_title,
        "event_slug": event_slug,
        "polymarket_url": polymarket_url,
        "size_usd": size_usd,
        "price_cents": int(round(price * 100)),
        "shares": int(round(shares)),
        "raw_text": raw_text,
    }

    if market_id:
        payload["market_id"] = market_id

    return payload


def post_alert(alert):
    if DRY_RUN:
        print("[DRY_RUN] Would POST alert to backend", flush=True)
        print(json.dumps(alert, indent=2, ensure_ascii=False), flush=True)
        return True

    if not INTERNAL_API_KEY:
        print("[ERROR] INTERNAL_API_KEY is missing", flush=True)
        return False

    url = f"{BACKEND_URL}/api/alerts"
    body = json.dumps(alert).encode("utf-8")

    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-api-key": INTERNAL_API_KEY,
            "User-Agent": "radarballena-whale-worker/1.0",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            response_body = res.read().decode("utf-8")
            print(f"[POST_OK] status={res.status} response={response_body}", flush=True)
            return 200 <= res.status < 300
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8")
        print(f"[POST_ERROR] status={e.code} body={error_body}", flush=True)
        return False
    except Exception as e:
        print(f"[POST_ERROR] {type(e).__name__}: {e}", flush=True)
        return False


def main():
    seen = load_seen_hashes()
    first_run = True
    cycle = 0

    print("Watching whales:")
    for whale_id, cfg in WATCHED_WHALES.items():
        print(f"- {whale_id}: {cfg['name']} / {cfg['wallet']}")
    print(f"\nConfig: POLL_SECONDS={POLL_SECONDS}, SKIP_OLD_ON_START={SKIP_OLD_ON_START}, MAX_AGE_SECONDS={MAX_AGE_SECONDS}")
    print(f"Loaded {len(seen)} seen hashes from {SEEN_FILE}\n")

    while True:
        cycle += 1
        cycle_start = time.time()
        alerts_by_market = {}
        skipped_duplicate_market_alerts = 0
        markets_limited = set()

        print(f"\n========== START CYCLE #{cycle} ==========", flush=True)

        for whale_id, cfg in WATCHED_WHALES.items():
            try:
                activity = fetch_activity(cfg["wallet"])
                
                # Track discard reasons
                total = len(activity)
                non_trades = 0
                below_min = 0
                irrelevant = 0
                too_old = 0
                duplicate = 0
                printed = 0
                market_limited = 0

                for item in reversed(activity):
                    if item.get("type") != "TRADE":
                        non_trades += 1
                        continue

                    size_usd = safe_float(item.get("usdcSize"))

                    if size_usd < cfg["min_usdc"]:
                        below_min += 1
                        continue

                    if not is_relevant_trade(item, whale_id):
                        irrelevant += 1
                        print(
                            f"[IRRELEVANT] {whale_id} title={item.get('title')} eventSlug={item.get('eventSlug')}",
                            flush=True
                        )
                        continue

                    # Check if trade is too old
                    timestamp = item.get("timestamp")
                    if timestamp:
                        try:
                            from datetime import datetime
                            trade_time = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).timestamp()
                            age = time.time() - trade_time
                            if age > MAX_AGE_SECONDS:
                                too_old += 1
                                continue
                        except Exception:
                            pass

                    alert_hash = make_hash(item)

                    if alert_hash in seen:
                        duplicate += 1
                        continue

                    if first_run and SKIP_OLD_ON_START:
                        seen.add(alert_hash)
                        continue

                    alert = parse_alert(item, whale_id, cfg["name"])
                    market_key = get_alert_market_key(alert, item)
                    current_market_count = alerts_by_market.get(market_key, 0)

                    if current_market_count >= MAX_ALERTS_PER_MARKET_PER_RUN:
                        market_limited += 1
                        skipped_duplicate_market_alerts += 1
                        markets_limited.add(market_key)

                        # Como esta alert se está omitiendo intencionalmente por límite de mercado,
                        # marcarla como seen para no reprocesarla en cada ciclo.
                        seen.add(alert_hash)

                        print(
                            f"[MARKET_LIMIT_SKIP] whale={whale_id} market_key={market_key} "
                            f"limit={MAX_ALERTS_PER_MARKET_PER_RUN} title={item.get('title')}",
                            flush=True,
                        )
                        continue

                    alerts_by_market[market_key] = current_market_count + 1

                    print("\n🐋 WHALE ALERT DETECTADA", flush=True)
                    print(json.dumps(alert, indent=2, ensure_ascii=False), flush=True)

                    sent_ok = post_alert(alert)

                    if sent_ok:
                        seen.add(alert_hash)
                        printed += 1
                    else:
                        print("[WARN] Alert not marked as seen because POST failed", flush=True)

                print(
                    f"[{whale_id}] fetched={total} trades={total-non_trades} "
                    f"below_min={below_min} irrelevant={irrelevant} too_old={too_old} "
                    f"duplicate={duplicate} printed={printed} market_limited={market_limited}"
                )

            except Exception as e:
                print(f"[ERROR] {whale_id}: {type(e).__name__}: {e}")
                continue

        print(
            f"[CYCLE_MARKET_LIMITS] max_alerts_per_market_per_run={MAX_ALERTS_PER_MARKET_PER_RUN} "
            f"skipped_duplicate_market_alerts={skipped_duplicate_market_alerts} "
            f"markets_limited={len(markets_limited)} "
            f"accepted_market_counts={json.dumps(alerts_by_market, ensure_ascii=False)}",
            flush=True,
        )

        # Save seen hashes periodically
        save_seen_hashes(seen)
        first_run = False

        elapsed = round(time.time() - cycle_start, 2)
        print(f"========== END CYCLE #{cycle} | elapsed={elapsed}s | sleeping={POLL_SECONDS}s ==========\n", flush=True)

        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
