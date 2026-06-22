from types import SimpleNamespace

from services import closing_recheck_repository as repo


class FakeTable:
    def __init__(self):
        self.calls = []

    def select(self, columns):
        self.calls.append(("select", columns))
        return self

    def eq(self, column, value):
        self.calls.append(("eq", column, value))
        return self

    def gte(self, column, value):
        self.calls.append(("gte", column, value))
        return self

    def order(self, column, desc=False):
        self.calls.append(("order", column, desc))
        return self

    def limit(self, value):
        self.calls.append(("limit", value))
        return self

    def execute(self):
        return SimpleNamespace(data=[{"id": "row-1"}])


class FakeSupabase:
    def __init__(self):
        self.table_ref = FakeTable()
        self.table_name = None

    def table(self, name):
        self.table_name = name
        return self.table_ref


def test_recent_closing_recheck_query_uses_created_at_cutoff(monkeypatch):
    fake_supabase = FakeSupabase()
    monkeypatch.setattr(repo, "get_supabase_client", lambda: fake_supabase)

    row = repo.get_recent_closing_recheck_for_market(
        market_id="market-1",
        hours=12,
    )

    assert row["id"] == "row-1"
    assert fake_supabase.table_name == "closing_recheck_results"
    assert ("eq", "market_id", "market-1") in fake_supabase.table_ref.calls
    assert any(call[0] == "gte" and call[1] == "created_at" for call in fake_supabase.table_ref.calls)

