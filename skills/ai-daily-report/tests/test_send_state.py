import hashlib
import json

import pytest

from send_state import (SendStateError, already_sent, delivery_attempt, load_send_state,
                        record_delivery_result, record_sent)


def test_fresh_state_nothing_sent(tmp_path):
    assert already_sent(tmp_path, "daily") is False
    assert load_send_state(tmp_path) == {"version": "1.0", "sent": {}}


def test_record_then_already_sent(tmp_path):
    record_sent(tmp_path, "daily", "AI 日报 · 2026-07-07", artifact_path=None)
    record_sent(tmp_path, "deep_dive:claude-x", "AI 深度 · X", artifact_path=None)
    assert already_sent(tmp_path, "daily") is True
    assert already_sent(tmp_path, "deep_dive:claude-x") is True
    assert already_sent(tmp_path, "deep_dive:other") is False


@pytest.mark.parametrize("raw", ["{broken", "null", "[]", '{}', '{"version":"1.0","sent":[]}',
                                 '{"version":"1.0","sent":{"daily":false}}',
                                 '{"version":[],"sent":{}}', '{"version":"2.0","sent":{}}',
                                 '{"version":"1.0","sent":{"daily":{"subject":"s","html_sha256":null}}}'])
def test_corrupt_state_blocks_instead_of_treating_as_empty(tmp_path, raw):
    path = tmp_path / "send_state.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(SendStateError):
        already_sent(tmp_path, "daily")
    with pytest.raises(SendStateError):
        record_sent(tmp_path, "daily", "test", artifact_path=None)
    assert path.read_text() == raw


def test_regenerated_report_keeps_original_delivery_hash(tmp_path):
    html = tmp_path / "report.html"
    html.write_text("old accepted HTML")
    record_sent(tmp_path, "daily", "daily", artifact_path=html)
    accepted = hashlib.sha256(html.read_bytes()).hexdigest()
    html.write_text("new local HTML")
    result = record_delivery_result(tmp_path, "daily", html, "skipped_existing")
    assert result["sent_html_sha256"] == accepted
    assert result["current_revision_delivered"] is False
    assert load_send_state(tmp_path)["sent"]["daily"]["html_sha256"] == accepted
    record_sent(tmp_path, "daily", "new daily", artifact_path=html)
    assert load_send_state(tmp_path)["sent"]["daily"]["html_sha256"] == accepted


def test_legacy_receipt_does_not_backfill_hash(tmp_path):
    html = tmp_path / "report.html"
    html.write_text("regenerated")
    record_sent(tmp_path, "daily", "daily", artifact_path=None)
    record_sent(tmp_path, "daily", "daily", artifact_path=html)
    assert "html_sha256" not in load_send_state(tmp_path)["sent"]["daily"]
    assert record_delivery_result(tmp_path, "daily", html, "skipped_existing")["current_revision_delivered"] is None


def test_atomic_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    import send_state
    record_sent(tmp_path, "daily", "daily", artifact_path=None)
    original = (tmp_path / "send_state.json").read_bytes()

    def fail_replace(*_args):
        raise OSError("disk full")

    monkeypatch.setattr(send_state.os, "replace", fail_replace)
    with pytest.raises(OSError):
        record_sent(tmp_path, "weekly", "weekly", artifact_path=None)
    assert (tmp_path / "send_state.json").read_bytes() == original
    assert not list(tmp_path.glob(".send_state.json.*"))


def test_concurrent_record_updates_do_not_lose_keys(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: record_sent(tmp_path, str(n), "test", artifact_path=None), range(12)))
    assert set(load_send_state(tmp_path)["sent"]) == {str(n) for n in range(12)}


@pytest.mark.parametrize("change", ["html", "recipients", "sender", "subject"])
def test_partial_delivery_cannot_be_mixed_with_changed_revision(tmp_path, change):
    kwargs = dict(cache_dir=tmp_path, key="daily", subject="subject", html_bytes=b"v1",
                  sender="sender@example.com", recipients=["a@example.com", "b@example.com"])
    with delivery_attempt(**kwargs) as attempt:
        attempt.record_result({"a@example.com": "accepted", "b@example.com": "refused"},
                              retries=0, error="recipients_refused", smtp_codes={"b@example.com": 550})
    if change == "html":
        kwargs["html_bytes"] = b"v2"
    elif change == "recipients":
        kwargs["recipients"] = ["a@example.com", "c@example.com"]
    else:
        kwargs[change] = "different"
    with pytest.raises(SendStateError, match="revision or envelope changed"):
        with delivery_attempt(**kwargs):
            pass


def test_record_sent_cannot_override_unknown_receipt(tmp_path):
    with delivery_attempt(tmp_path, "daily", "subject", b"v1", "sender@example.com", ["a@example.com"]) as attempt:
        attempt.submitting()
    with pytest.raises(SendStateError, match="completed by the sender"):
        record_sent(tmp_path, "daily", "subject", artifact_path=None)
    assert load_send_state(tmp_path)["deliveries"]["daily"]["status"] == "unknown"


def test_inconsistent_receipts_block_delivery(tmp_path):
    with delivery_attempt(tmp_path, "daily", "subject", b"v1", "sender@example.com", ["a@example.com"]) as attempt:
        attempt.submitting()
    path = tmp_path / "send_state.json"
    payload = json.loads(path.read_text())
    payload["deliveries"]["daily"]["status"] = "sent"
    path.write_text(json.dumps(payload))
    with pytest.raises(SendStateError):
        load_send_state(tmp_path)


@pytest.mark.parametrize("outcome", ["partial", "unknown"])
def test_unresolved_delivery_result_is_not_delivered(tmp_path, outcome):
    html = tmp_path / "report.html"
    html.write_text("v1")
    with delivery_attempt(tmp_path, "daily", "subject", b"v1", "sender@example.com", ["a@example.com"]) as attempt:
        attempt.submitting()
    result = record_delivery_result(tmp_path, "daily", html, outcome)
    assert result["outcome"] == outcome
    assert result["smtp_status"] == "unknown"
    assert result["current_revision_delivered"] is None


def test_side_delivery_does_not_overwrite_main_delivery_result(tmp_path):
    html = tmp_path / "report.html"
    html.write_text("report")
    main = record_delivery_result(tmp_path, "daily", html, "dry_run")
    side = record_delivery_result(tmp_path, "deep_dive:../special/topic", html, "partial")
    assert json.loads((tmp_path / "delivery_result.json").read_text()) == main
    side_path = tmp_path / "delivery_results" / (hashlib.sha256(b"deep_dive:../special/topic").hexdigest() + ".json")
    assert json.loads(side_path.read_text()) == side
    assert side["kind"] == "deep_dive:../special/topic"
