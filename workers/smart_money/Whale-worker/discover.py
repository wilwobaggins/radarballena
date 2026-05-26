import json
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import os

GAMMA_MARKETS = "https://gamma-api.polymarket.com/markets"
GAMMA_EVENTS = "https://gamma-api.polymarket.com/events"
DATA_TRADES = "https://data-api.polymarket.com/trades"

MIN_TRADE_USD = 20
MARKETS_PER_TERM = 100
TRADES_PER_MARKET = 2000

# Selection thresholds (temporarily lowered for broader coverage)
MIN_TERMS = 1
MIN_MARKETS = 1
MIN_TRADES = 1

CATEGORIES = {
    "macro_economics": [
        "fomc",
        "fed decision",
        "jerome powell",
        "rate cut",
        "rate hike",
        "cpi",
        "core cpi",
        "inflation",
        "jobs report",  
        "unemployment",
        "nonfarm payrolls",
        "gdp",
        "recession",
        "treasury",
        "dollar",
        "global economy",
        "core pce",
        "pce inflation",
        "fed funds",
        "interest rates",
        "treasury yields",
        "10 year treasury",
        "initial jobless claims",
        "retail sales",
        "consumer confidence",
        "ism manufacturing",
        "government shutdown",
        "debt ceiling",
        "tariffs",
        "oil prices",
        "opec",
    ],
    "geo_macro": [
        "world events",
        "geopolitics",
        "ukraine",
        "russia ukraine",
        "israel iran",
        "israel gaza",
        "gaza ceasefire",
        "iran nuclear",
        "china taiwan",
        "taiwan",
        "nato",
        "sanctions",
        "tariffs",
        "trade war",
        "middle east",
    ],
    "esports": [
        "esports",
        "esports tournament",
        "dota 2",
        "dota2",
        "the international",
        "league of legends",
        "lol",
        "worlds",
        "csgo",
        "counter-strike",
        "valorant",
        "overwatch",
        "esl",
        "dreamhack",
        "riot games",
        "rocket league",
        "call of duty",
        "fifa esports",
    ],
}

# Keywords used to validate whether a market is truly macro-related
MACRO_KEYWORDS = {
    "fed", "fomc", "powell", "rate", "rates",
    "cpi", "inflation", "pce", "gdp", "recession",
    "treasury", "yield", "yields", "dollar",
    "jobs", "payrolls", "unemployment", "jobless",
    "retail", "consumer", "ism",
    "debt", "shutdown",
    # Important tariff/trade keywords
    "tariff", "tariffs", "trade war", "china", "imports", "exports",
    # Energy keywords
    "oil", "crude", "brent", "wti", "gas", "gasoline", "energy",
    "opec", "opec+",
}

# Category-specific keyword hints for non-macro categories
CATEGORY_KEYWORDS = {
    "esports": {
        "esports",
        "esports tournament",
        "dota",
        "dota 2",
        "dota2",
        "the international",
        "league",
        "league of legends",
        "lol",
        "worlds",
        "csgo",
        "counter-strike",
        "valorant",
        "overwatch",
        "esl",
        "dreamhack",
        "riot",
        "rocket league",
        "call of duty",
        "fifa",
        "tournament",
        "match",
        "final",
    },
}


def normalize_text(text):
    return " ".join((text or "").lower().replace("?", "").replace(",", "").replace(".", "").split())


def market_blob(market):
    """Extract all searchable text from a market object."""
    parts = [
        market.get("title"),
        market.get("question"),
        market.get("slug"),
        market.get("groupItemTitle"),
        market.get("description"),
        market.get("eventSlug"),
        market.get("category"),
        market.get("_eventTitle"),
        market.get("_eventDescription"),
    ]

    tags = market.get("tags") or []
    if isinstance(tags, list):
        for tag in tags:
            if isinstance(tag, dict):
                parts.append(tag.get("label") or tag.get("slug") or tag.get("name"))
            else:
                parts.append(str(tag))

    return normalize_text(" ".join([str(x) for x in parts if x]))


def is_relevant_market(market, term, extra_keywords=None, include_macro=True):
    """Check if a market is relevant to the search term or global/category keywords.

    If `include_macro` is False the global `MACRO_KEYWORDS` set is not used,
    allowing category-specific searches (e.g., `esports`) to avoid macro noise.
    """
    blob = market_blob(market)
    term_norm = normalize_text(term)

    term_variants = {
        term_norm,
        term_norm.rstrip("s"),
        term_norm.replace("prices", "price"),
    }

    if any(v and v in blob for v in term_variants):
        return True

    # Build keyword set based on include_macro flag and any category-specific hints
    keywords = set()
    if include_macro:
        keywords |= set(MACRO_KEYWORDS)
    if extra_keywords:
        keywords |= set(extra_keywords)

    if not keywords:
        return False

    return any(k in blob for k in keywords)


def get_json(url, params=None, timeout=15):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)

    req = urllib.request.Request(
        url,
        headers={"User-Agent": "radarballena-wallet-discovery/1.0"},
    )

    with urllib.request.urlopen(req, timeout=timeout) as res:
        return json.loads(res.read().decode("utf-8"))


def safe_float(value):
    try:
        return float(value or 0)
    except Exception:
        return 0.0


def search_markets(term, include_macro=True, extra_keywords=None):
    markets = []

    # First try events (often groups relevant markets together)
    try:
        params = {
            "search": term,
            "active": "true",
            "closed": "false",
            "limit": MARKETS_PER_TERM,
        }

        events = get_json(GAMMA_EVENTS, params)

        if isinstance(events, list):
            for ev in events:
                ev_title = ev.get("title") or ev.get("ticker") or ""
                ev_desc = ev.get("description") or ""
                blob = normalize_text(" ".join([ev_title, ev_desc]))
                term_norm = normalize_text(term)

                # Only include events that match the term, category-specific keywords,
                # or (optionally) macro keywords. This avoids bringing in macro events
                # when searching non-macro categories like esports.
                matches_event = False
                if term_norm in blob:
                    matches_event = True
                if extra_keywords and any(k in blob for k in extra_keywords):
                    matches_event = True
                if include_macro and any(k in blob for k in MACRO_KEYWORDS):
                    matches_event = True

                if matches_event:
                    ev_markets = ev.get("markets") or ev.get("marketIds") or ev.get("marketsList") or []
                    if isinstance(ev_markets, list):
                        for m in ev_markets:
                            if isinstance(m, dict):
                                m["_eventTitle"] = ev_title
                                m["_eventDescription"] = ev_desc
                                markets.append(m)
                            else:
                                try:
                                    mdata = get_json(GAMMA_MARKETS, {"id": m})
                                    if isinstance(mdata, dict):
                                        mdata["_eventTitle"] = ev_title
                                        mdata["_eventDescription"] = ev_desc
                                        markets.append(mdata)
                                    elif isinstance(mdata, list):
                                        for item in mdata:
                                            item["_eventTitle"] = ev_title
                                            item["_eventDescription"] = ev_desc
                                        markets.extend(mdata)
                                except Exception:
                                    continue

                if len(markets) >= MARKETS_PER_TERM:
                    break

    except Exception as e:
        print(f"[EVENTS_SEARCH_ERROR] term={term} error={e}")

    # If events didn't return many markets, fall back to searching markets directly
    if len(markets) < MARKETS_PER_TERM:
        try:
            data = get_json(
                GAMMA_MARKETS,
                {
                    "search": term,
                    "limit": MARKETS_PER_TERM,
                    "active": "true",
                    "closed": "false",
                },
            )

            if isinstance(data, list):
                # only add those not already included
                existing_ids = {m.get("id") for m in markets}
                for m in data:
                    if m.get("id") not in existing_ids:
                        m["_eventTitle"] = None
                        m["_eventDescription"] = None
                        markets.append(m)

        except Exception as e:
            print(f"[MARKET_SEARCH_ERROR] term={term} error={e}")

    return markets[:MARKETS_PER_TERM]


def fetch_trades(condition_id):
    try:
        data = get_json(
            DATA_TRADES,
            {
                "market": condition_id,
                "limit": TRADES_PER_MARKET,
                "takerOnly": "false",
                "filterType": "CASH",
                "filterAmount": MIN_TRADE_USD,
            },
        )

        if isinstance(data, list):
            return data

        return []

    except Exception as e:
        print(f"[TRADES_ERROR] conditionId={condition_id} error={e}")
        return []


def discover_category(category_name, terms):
    seen_markets = set()

    wallets = defaultdict(
        lambda: {
            "total_usd": 0.0,
            "trade_count": 0,
            "big_trades": 0,
            "markets": set(),
            "terms": set(),
            "examples": [],
        }
    )
    lock = threading.Lock()
    MAX_WORKERS = 6
    category_keywords = CATEGORY_KEYWORDS.get(category_name, set())
    # Only include macro keywords for macro categories
    include_macro = category_name in ("macro_economics", "geo_macro")

    print(f"\n==============================")
    print(f"SEARCHING CATEGORY: {category_name}")
    print(f"==============================")

    def process_market(market, term):
        condition_id = market.get("conditionId")
        market_id = market.get("id")
        title = market.get("question") or market.get("title") or ""

        if not is_relevant_market(market, term, category_keywords, include_macro=include_macro):
            print(f"[SKIP_IRRELEVANT] {market_id} term={term} title={title[:80]}")
            return

        if not condition_id:
            return

        with lock:
            if condition_id in seen_markets:
                return
            seen_markets.add(condition_id)

        print(f"[MARKET] {market_id} {title[:100]}")

        trades = fetch_trades(condition_id)

        for trade in trades:
            wallet = trade.get("proxyWallet")
            if not wallet:
                continue

            price = safe_float(trade.get("price"))
            size = safe_float(trade.get("size"))

            approx_usd = price * size
            if approx_usd < MIN_TRADE_USD:
                continue

            with lock:
                wallets[wallet]["total_usd"] += approx_usd
                wallets[wallet]["trade_count"] += 1
                wallets[wallet]["big_trades"] += 1
                wallets[wallet]["markets"].add(condition_id)
                wallets[wallet]["terms"].add(term)

                if len(wallets[wallet]["examples"]) < 6:
                    wallets[wallet]["examples"].append(
                        {
                            "term": term,
                            "market": title,
                            "side": trade.get("side"),
                            "outcome": trade.get("outcome"),
                            "price": trade.get("price"),
                            "size": trade.get("size"),
                            "approx_usd": round(approx_usd, 2),
                            "tx": trade.get("transactionHash"),
                        }
                    )

    # Process terms one-by-one but fetch trades for markets in parallel
    for term in terms:
        print(f"\n[SEARCH] {term}")
        markets = search_markets(term, include_macro=include_macro, extra_keywords=category_keywords)
        to_process = [m for m in markets if m.get("conditionId")]

        if not to_process:
            continue

        workers = min(MAX_WORKERS, len(to_process))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(process_market, m, term) for m in to_process]
            for f in as_completed(futures):
                try:
                    f.result()
                except Exception as e:
                    print(f"[WORKER_ERROR] {e}")

    ranked = sorted(
        wallets.items(),
        key=lambda x: (
            len(x[1]["markets"]),
            len(x[1]["terms"]),
            x[1]["trade_count"],
            x[1]["total_usd"],
        ),
        reverse=True,
    )

    # Filter out wallets that don't meet minimum coverage criteria
    filtered = [
        (wallet, info)
        for wallet, info in ranked
        if len(info["terms"]) >= MIN_TERMS
        and len(info["markets"]) >= MIN_MARKETS
        and info["trade_count"] >= MIN_TRADES
    ]

    print(f"\n=== TOP WALLETS: {category_name} (filtered) ===\n")

    if not filtered:
        print("No wallets meet the filter criteria for this category.\n")
        return filtered

    for wallet, info in filtered[:20]:
        m_count = len(info['markets'])
        t_count = len(info['terms'])
        tr_count = info['trade_count']

        if m_count >= 10 and t_count >= 4 and tr_count >= 20:
            strength = "Very Strong"
        elif m_count >= 6 and t_count >= 3 and tr_count >= 10:
            strength = "Strong"
        elif m_count >= 3 and t_count >= 2 and tr_count >= 5:
            strength = "Acceptable"
        else:
            strength = "Weak"

        print(
            f"{wallet} | "
            f"markets={m_count} | "
            f"terms={t_count} | "
            f"trades={tr_count} | "
            f"total_usd~${round(info['total_usd'], 2)} | "
            f"strength={strength}"
        )

        for ex in info["examples"]:
            print(
                f"  - [{ex['term']}] "
                f"${ex['approx_usd']} "
                f"{ex['side']} {ex['outcome']} | "
                f"{ex['market'][:95]} | "
                f"tx={ex['tx']}"
            )

        print()

    return filtered


def main():
    final = {}

    only = os.getenv("ONLY_CATEGORY", "").strip()
    if only:
        if only in CATEGORIES:
            to_iter = {only: CATEGORIES[only]}
        else:
            print(f"[WARN] ONLY_CATEGORY={only} not found; running all categories")
            to_iter = CATEGORIES
    else:
        # Default to only macro_economics to honor user's request (override with ONLY_CATEGORY)
        print("[INFO] Running only 'macro_economics'. Set ONLY_CATEGORY to override.")
        to_iter = {"macro_economics": CATEGORIES["macro_economics"]}

    for category_name, terms in to_iter.items():
        final[category_name] = discover_category(category_name, terms)

    print("\n==============================")
    print("FINAL SUMMARY")
    print("==============================\n")

    for category_name, filtered in final.items():
        print(f"{category_name}:")

        # final[category_name] contains filtered results
        for wallet, info in filtered[:5]:
            print(
                f"  {wallet} | "
                f"markets={len(info['markets'])} | "
                f"terms={len(info['terms'])} | "
                f"trades={info['trade_count']} | "
                f"total_usd~${round(info['total_usd'], 2)}"
            )

        print()


if __name__ == "__main__":
    main()