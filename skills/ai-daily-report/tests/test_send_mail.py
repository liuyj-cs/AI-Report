import json
import smtplib
import sys

import pytest

import send_mail
from send_mail import build_message, send
from send_state import SendStateError, already_sent, delivery_attempt, load_send_state


class FakeSMTP:
    calls = []
    connects = []
    login_error = None
    result = {}
    quit_error = None

    def __init__(self, *_args, **_kwargs):
        self.calls.append("connect")
        if self.connects:
            action = self.connects.pop(0)
            if action:
                raise action

    def login(self, *_args):
        self.calls.append("login")
        if self.login_error:
            raise self.login_error

    def send_message(self, msg, *, from_addr, to_addrs):
        self.calls.append(("send", list(to_addrs), str(msg["Message-ID"])))
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result

    def quit(self):
        self.calls.append("quit")
        if self.quit_error:
            raise self.quit_error

    def close(self):
        self.calls.append("close")


@pytest.fixture
def smtp(monkeypatch):
    FakeSMTP.calls, FakeSMTP.connects = [], []
    FakeSMTP.login_error = FakeSMTP.quit_error = None
    FakeSMTP.result = {}
    monkeypatch.setattr(send_mail.smtplib, "SMTP_SSL", FakeSMTP)
    return FakeSMTP


def deliver(path, recipients=None, **kwargs):
    recipients = ["a@example.com", "b@example.com"] if recipients is None else recipients
    with delivery_attempt(path, "daily", "subject", b"<p>hello</p>", "sender@example.com", recipients) as delivery:
        if delivery is None:
            return "skipped_existing"
        msg = build_message("sender@example.com", delivery.recipients, "subject", "<p>hello</p>",
                            message_id=delivery.message_id)
        return send(msg, "sender@example.com", "password", delivery=delivery, **kwargs)


def test_connection_errors_retry_before_submission(tmp_path, smtp):
    smtp.connects = [OSError("network"), OSError("network"), None]
    sleeps = []
    assert deliver(tmp_path, sleep=sleeps.append) == "sent"
    assert sleeps == [5, 20]
    assert smtp.calls.count("connect") == 3
    assert len([call for call in smtp.calls if isinstance(call, tuple)]) == 1
    assert already_sent(tmp_path, "daily")


def test_pre_submission_failure_is_safe_to_retry_later(tmp_path, smtp):
    smtp.connects = [OSError("network")] * 3
    assert deliver(tmp_path, sleep=lambda _: None) == "not_submitted"
    assert not already_sent(tmp_path, "daily")
    assert deliver(tmp_path) == "sent"
    assert len(load_send_state(tmp_path)["deliveries"]["daily"]["attempts"]) == 2


def test_auth_failure_does_not_retry(tmp_path, smtp):
    smtp.login_error = smtplib.SMTPAuthenticationError(535, b"sender@example.com secret")
    assert deliver(tmp_path) == "not_submitted"
    assert smtp.calls.count("connect") == 1
    assert not any(isinstance(call, tuple) for call in smtp.calls)


def test_partial_acceptance_retries_only_refused_with_same_id(tmp_path, smtp):
    smtp.result = {"b@example.com": (550, b"recipient rejected")}
    assert deliver(tmp_path) == "partial"
    assert not already_sent(tmp_path, "daily")
    smtp.result = {}
    assert deliver(tmp_path) == "sent"
    sends = [call for call in smtp.calls if isinstance(call, tuple)]
    assert sends[0][1] == ["a@example.com", "b@example.com"]
    assert sends[1][1] == ["b@example.com"]
    assert sends[0][2] == sends[1][2]
    assert deliver(tmp_path) == "skipped_existing"
    assert len([call for call in smtp.calls if isinstance(call, tuple)]) == 2
    receipt = (tmp_path / "send_state.json").read_text()
    assert "a@example.com" not in receipt
    assert "b@example.com" not in receipt


def test_all_recipients_refused_does_not_retry_in_same_invocation(tmp_path, smtp):
    smtp.result = smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"no"), "b@example.com": (550, b"no")})
    assert deliver(tmp_path) == "not_submitted"
    assert smtp.calls.count("connect") == 1
    assert set(load_send_state(tmp_path)["deliveries"]["daily"]["recipients"].values()) == {"refused"}


def test_submission_timeout_is_unknown_and_blocks_next_invocation(tmp_path, smtp):
    smtp.result = TimeoutError("DATA reply lost with recipient@example.com")
    assert deliver(tmp_path) == "unknown"
    assert smtp.calls.count("connect") == 1
    with pytest.raises(SendStateError, match="outcome unknown"):
        deliver(tmp_path)
    assert smtp.calls.count("connect") == 1
    assert not already_sent(tmp_path, "daily")


def test_process_interruption_inside_submission_stays_unknown(tmp_path, smtp):
    smtp.result = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        deliver(tmp_path)
    assert load_send_state(tmp_path)["deliveries"]["daily"]["status"] == "unknown"
    with pytest.raises(SendStateError, match="outcome unknown"):
        deliver(tmp_path)


def test_explicit_data_rejection_is_known_not_submitted(tmp_path, smtp):
    smtp.result = smtplib.SMTPDataError(554, b"rejected")
    assert deliver(tmp_path) == "not_submitted"
    assert smtp.calls.count("connect") == 1
    smtp.result = {}
    assert deliver(tmp_path) == "sent"


def test_quit_failure_cannot_change_confirmed_acceptance(tmp_path, smtp):
    smtp.quit_error = TimeoutError("QUIT response lost")
    assert deliver(tmp_path) == "sent"
    assert already_sent(tmp_path, "daily")
    assert deliver(tmp_path) == "skipped_existing"
    assert smtp.calls.count("connect") == 1


def test_receipt_write_failure_after_acceptance_preserves_unknown(tmp_path, smtp, monkeypatch):
    import send_state
    real_write = send_state.atomic_write_json

    def fail_completed(path, payload):
        if payload.get("sent", {}).get("daily"):
            raise OSError("disk full")
        real_write(path, payload)

    monkeypatch.setattr(send_state, "atomic_write_json", fail_completed)
    with pytest.raises(OSError, match="disk full"):
        deliver(tmp_path)
    assert load_send_state(tmp_path)["deliveries"]["daily"]["status"] == "unknown"
    with pytest.raises(SendStateError, match="outcome unknown"):
        deliver(tmp_path)
    assert smtp.calls.count("connect") == 1


def test_pre_submission_write_failure_prevents_network_submission(tmp_path, smtp, monkeypatch):
    import send_state
    real_write = send_state.atomic_write_json

    def fail_unknown(path, payload):
        if payload.get("deliveries", {}).get("daily", {}).get("status") == "unknown":
            raise OSError("disk full")
        real_write(path, payload)

    monkeypatch.setattr(send_state, "atomic_write_json", fail_unknown)
    with pytest.raises(OSError, match="disk full"):
        deliver(tmp_path)
    assert not any(isinstance(call, tuple) for call in smtp.calls)
    assert load_send_state(tmp_path)["deliveries"]["daily"]["status"] == "not_submitted"


def test_message_bcc_and_stable_id():
    msg = build_message("sender@example.com", ["a@example.com", "b@example.com"], "subj", "html",
                        message_id="<stable@reports.local>")
    assert msg["To"] == "AI Report <sender@example.com>"
    assert msg["Bcc"] == "a@example.com, b@example.com"
    assert msg["Message-ID"] == "<stable@reports.local>"
    single = build_message("sender@example.com", ["a@example.com"], "subj", "html", message_id=None)
    assert single["To"] == "a@example.com"
    assert single["Bcc"] is None


def cli_files(tmp_path, monkeypatch, extra=()):
    html = tmp_path / "r.html"
    html.write_text("<p>hello</p>", encoding="utf-8")
    env = tmp_path / "test.env"
    env.write_text("GMAIL_USER=sender@example.com\nGMAIL_APP_PASSWORD=fake-test-secret\n"
                   "REPORT_RECIPIENTS=a@example.com,b@example.com\n", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["send_mail.py", str(html), "--subject", "subj", "--env", str(env), *extra])


@pytest.mark.parametrize("mode,code,outcome", [("success", 0, "sent"), ("partial", 4, "partial"),
                                             ("unknown", 5, "unknown"), ("auth", 2, "failed")])
def test_cli_structured_outcome_and_no_address_or_secret_output(tmp_path, monkeypatch, capsys, smtp, mode, code, outcome):
    if mode == "partial":
        smtp.result = {"b@example.com": (550, b"b@example.com fake-test-secret")}
    elif mode == "unknown":
        smtp.result = OSError("b@example.com fake-test-secret")
    elif mode == "auth":
        smtp.login_error = smtplib.SMTPAuthenticationError(535, b"sender@example.com fake-test-secret")
    cli_files(tmp_path, monkeypatch, ["--state-dir", str(tmp_path), "--state-key", "daily"])
    assert send_mail.main() == code
    captured = capsys.readouterr()
    assert json.loads(captured.out)["outcome"] == outcome
    assert "@example.com" not in captured.out + captured.err
    assert "fake-test-secret" not in captured.out + captured.err


def test_cli_rejects_missing_ledger_before_connect(tmp_path, monkeypatch, smtp):
    cli_files(tmp_path, monkeypatch)
    assert send_mail.main() == 1
    assert smtp.calls == []


def test_cli_dry_run_has_no_ledger_or_network(tmp_path, monkeypatch, smtp, capsys):
    cli_files(tmp_path, monkeypatch, ["--dry-run"])
    assert send_mail.main() == 0
    assert json.loads(capsys.readouterr().out) == {"outcome": "dry_run", "counts": {"recipients": 2}}
    assert not (tmp_path / "send_state.json").exists()
    assert smtp.calls == []


def test_concurrent_same_delivery_submits_once(tmp_path, smtp):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: deliver(tmp_path), range(2)))
    assert sorted(outcomes) == ["sent", "skipped_existing"]
    assert smtp.calls.count("connect") == 1
