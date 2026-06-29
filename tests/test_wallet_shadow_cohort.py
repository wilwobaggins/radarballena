
from workers.smart_money.smart_money_engine.wallet_shadow_cohort import build_shadow_wallet_cohort, parse_wallet_specifiers


def test_shadow_cohort_dedupes_roles_and_sources():
    wallet = "0x" + "9" * 40
    cohort = build_shadow_wallet_cohort(
        [],
        active_wallets={
            "global_trader": {
                "name": "Everything Trader Zeta",
                "wallet": wallet,
                "profile": "mixed",
            }
        },
        active_health=[
            {
                "wallet": wallet,
                "whale_id": "global_trader",
                "active_name": "Everything Trader Zeta",
                "active_score": 40,
                "active_status": "degraded",
                "profile": "mixed",
            }
        ],
        benchmark_wallets=f"{wallet}:Ken",
        priority_wallets=wallet,
        global_candidates=[
            {
                "wallet": wallet,
                "score": 84,
                "tier": "candidate_high",
                "category_guess": "sports",
            }
        ],
        replacement_recommendations=[
            {
                "active_whale_id": "global_trader",
                "active_wallet": wallet,
                "replacement_candidate": {
                    "wallet": wallet,
                    "score": 72,
                    "tier": "replacement_candidate",
                    "category_guess": "sports",
                },
            }
        ],
    )

    assert len(cohort) == 1
    row = cohort[0]
    assert row["wallet"] == wallet
    assert set(row["roles"]) == {"active", "benchmark", "candidate", "replacement_candidate"}
    assert row["candidateScore"] == 84
    assert "active_wallet_config" in row["sources"]
    assert "whale_finder_global_candidates" in row["sources"]
    assert "Ken" in row["aliases"]


def test_shadow_cohort_ignores_invalid_wallets():
    cohort = build_shadow_wallet_cohort(
        [],
        include_active_wallets=False,
        benchmark_wallets="not-a-wallet,0x123",
        global_candidates=[{"wallet": "0x123", "score": 1, "tier": "candidate_low"}],
    )

    assert cohort == []


def test_parse_wallet_specifiers_handles_aliases_and_dedupe():
    parsed = parse_wallet_specifiers("0x" + "a" * 40 + ":Ken, 0x" + "a" * 40 + ":Dup, 0x" + "b" * 40)
    assert parsed == [("0x" + "a" * 40, "Ken"), ("0x" + "b" * 40, None)]
