"""The runner must report durable SMTP evidence, even after races or interruption."""
import json

import report_runner
from send_state import delivery_attempt


def test_concurrent_sender_skip_is_not_logged_as_new_submission(tmp_path, monkeypatch):
    html = tmp_path / "report.html"
    html.write_text("report", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()

    def concurrent_sender(root, path, subject, env, state_dir, key):
        # Another process accepted the message after the runner's initial read.
        with delivery_attempt(state_dir, key, subject, path.read_bytes(),
                              "sender@example.com", ["reader@example.com"]) as attempt:
            attempt.submitting()
            attempt.record_result({"reader@example.com": "accepted"},
                                  retries=0, error=None, smtp_codes={})
        return 0, json.dumps({"outcome": "skipped_existing"})

    monkeypatch.setattr(report_runner, "_send_mail", concurrent_sender)
    code, _ = report_runner._deliver_mail(tmp_path, html, "subject", tmp_path / ".env",
                                         cache, "daily", cache / "run.log", "2026-09-29")
    assert code == 0
    assert json.loads((cache / "delivery_result.json").read_text())["outcome"] == "skipped_existing"
    assert "EMAIL skip already-sent" in (cache / "run.log").read_text()


def test_killed_sender_preserves_unknown_in_runner_result(tmp_path, monkeypatch):
    html = tmp_path / "report.html"
    html.write_text("report", encoding="utf-8")
    cache = tmp_path / "cache"
    cache.mkdir()

    def interrupted_sender(root, path, subject, env, state_dir, key):
        with delivery_attempt(state_dir, key, subject, path.read_bytes(),
                              "sender@example.com", ["reader@example.com"]) as attempt:
            attempt.submitting()
        return -9, ""

    monkeypatch.setattr(report_runner, "_send_mail", interrupted_sender)
    code, _ = report_runner._deliver_mail(tmp_path, html, "subject", tmp_path / ".env",
                                         cache, "daily", cache / "run.log", "2026-09-29")
    assert code == 5
    result = json.loads((cache / "delivery_result.json").read_text())
    assert result["outcome"] == result["smtp_status"] == "unknown"
    assert "EMAIL unknown" in (cache / "run.log").read_text()
