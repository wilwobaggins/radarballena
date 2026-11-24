from __future__ import annotations

import json

import pytest

from workers.smart_money.whale_worker import whale_worker


def test_dry_run_does_not_send_or_report_alert_as_sent(monkeypatch, capsys):
    monkeypatch.setattr(whale_worker, "DRY_RUN", True)

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("DRY_RUN must not perform an HTTP request")

    monkeypatch.setattr(whale_worker.urllib.request, "urlopen", fail_if_called)

    result = whale_worker.post_alert({"market_title": "synthetic test"})

    assert result is None
    assert "[DRY_RUN] Would POST" in capsys.readouterr().out


def test_dry_run_does_not_modify_checkpoint(tmp_path, monkeypatch):
    checkpoint = tmp_path / "seen.json"
    original = '["previously-seen"]\n'
    checkpoint.write_text(original, encoding="utf-8")
    monkeypatch.setattr(whale_worker, "SEEN_FILE", str(checkpoint))
    monkeypatch.setattr(whale_worker, "DRY_RUN", True)

    assert whale_worker.persist_seen_hashes({"previously-seen", "simulated-alert"}) is False

    assert checkpoint.read_text(encoding="utf-8") == original


def test_checkpoint_round_trip_preserves_deduplication_after_restart(tmp_path, monkeypatch):
    checkpoint = tmp_path / "seen.json"
    monkeypatch.setattr(whale_worker, "SEEN_FILE", str(checkpoint))
    transaction = {
        "transaction_hash": "fixture-tx",
        "token_id": "fixture-token",
        "timestamp": 1_700_000_000,
        "side": "BUY",
        "size": 25,
    }
    transaction_hash = whale_worker.make_hash(transaction)

    assert whale_worker.save_seen_hashes({transaction_hash}) is True

    # A new load after process restart still filters the same transaction.
    reloaded_seen = whale_worker.load_seen_hashes()
    assert transaction_hash in reloaded_seen
    assert transaction_hash in whale_worker.load_seen_hashes()


@pytest.mark.parametrize("failure_point", ["serialize", "replace"])
def test_checkpoint_write_error_keeps_previous_file_intact(
    tmp_path, monkeypatch, failure_point
):
    checkpoint = tmp_path / "seen.json"
    original = '["previously-seen"]\n'
    checkpoint.write_text(original, encoding="utf-8")
    monkeypatch.setattr(whale_worker, "SEEN_FILE", str(checkpoint))

    def fail(*_args, **_kwargs):
        raise OSError("synthetic write failure")

    if failure_point == "serialize":
        monkeypatch.setattr(whale_worker.json, "dump", fail)
    else:
        monkeypatch.setattr(whale_worker.os, "replace", fail)

    assert whale_worker.save_seen_hashes({"new-entry"}) is False

    assert checkpoint.read_text(encoding="utf-8") == original
    assert list(tmp_path.iterdir()) == [checkpoint]


def test_normal_send_still_posts_alert(monkeypatch):
    monkeypatch.setattr(whale_worker, "DRY_RUN", False)
    monkeypatch.setattr(whale_worker, "INTERNAL_API_KEY", "test-key")
    monkeypatch.setattr(whale_worker, "BACKEND_URL", "https://backend.invalid")
    calls = []

    class FakeResponse:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"accepted":true}'

    def fake_urlopen(request, timeout):
        calls.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(whale_worker.urllib.request, "urlopen", fake_urlopen)
    alert = {"market_title": "synthetic test", "market_id": "fixture-market"}

    assert whale_worker.post_alert(alert) is True
    assert len(calls) == 1
    request, timeout = calls[0]
    assert request.get_method() == "POST"
    assert request.full_url == "https://backend.invalid/api/alerts"
    assert json.loads(request.data) == alert
    assert timeout == 30
