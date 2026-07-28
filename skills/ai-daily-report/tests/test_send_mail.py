import smtplib

import pytest

import send_mail
from send_mail import build_message, send


class _FakeSMTP:
    """Context-manager fake for smtplib.SMTP_SSL; behavior driven by a shared script list."""

    calls: list[str] = []
    script: list[Exception | None] = []

    def __init__(self, host, port, context=None, timeout=None):
        type(self).calls.append("connect")
        action = type(self).script.pop(0)
        if action is not None:
            raise action

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def login(self, sender, password):
        pass

    def send_message(self, msg):
        type(self).calls.append("send")


@pytest.fixture
def fake_smtp(monkeypatch):
    _FakeSMTP.calls = []
    _FakeSMTP.script = []
    monkeypatch.setattr(send_mail.smtplib, "SMTP_SSL", _FakeSMTP)
    return _FakeSMTP


def _msg():
    return build_message("me@example.com", ["a@example.com"], "subj", "<p>hi</p>")


def test_send_retries_transient_error_then_succeeds(fake_smtp):
    fake_smtp.script = [OSError("net down"), OSError("net down"), None]
    sleeps: list[int] = []
    retries = send(_msg(), "me@example.com", "pw", sleep=sleeps.append)
    assert retries == 2
    assert sleeps == [5, 20]
    assert fake_smtp.calls.count("connect") == 3


def test_send_gives_up_after_all_retries(fake_smtp):
    fake_smtp.script = [OSError("x"), OSError("x"), OSError("x")]
    with pytest.raises(OSError):
        send(_msg(), "me@example.com", "pw", sleep=lambda _s: None)
    assert fake_smtp.calls.count("connect") == 3


def test_send_does_not_retry_auth_error(fake_smtp):
    fake_smtp.script = [smtplib.SMTPAuthenticationError(535, b"bad credentials")]
    with pytest.raises(smtplib.SMTPAuthenticationError):
        send(_msg(), "me@example.com", "pw", sleep=lambda _s: None)
    assert fake_smtp.calls.count("connect") == 1


def test_build_message_single_recipient_uses_to_header():
    msg = build_message("me@example.com", ["a@example.com"], "s", "<p>x</p>")
    assert msg["To"] == "a@example.com"
    assert msg["Bcc"] is None


def test_build_message_multi_recipient_uses_bcc():
    msg = build_message("me@example.com", ["a@example.com", "b@example.com"], "s", "<p>x</p>")
    assert "me@example.com" in msg["To"]
    assert msg["Bcc"] == "a@example.com, b@example.com"


def test_send_does_not_retry_recipients_refused(fake_smtp):
    fake_smtp.script = [smtplib.SMTPRecipientsRefused({"a@example.com": (550, b"user unknown")})]
    with pytest.raises(smtplib.SMTPRecipientsRefused):
        send(_msg(), "me@example.com", "pw", sleep=lambda _s: None)
    assert fake_smtp.calls.count("connect") == 1


def test_main_reports_recipients_refused_without_retry_wording(tmp_path, monkeypatch, capsys):
    import sys

    html = tmp_path / "r.html"
    html.write_text("<p>x</p>", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(
        "GMAIL_USER=a@b.com\nGMAIL_APP_PASSWORD=x\nREPORT_RECIPIENTS=c@d.com\n", encoding="utf-8"
    )

    def _raise(*_a, **_k):
        raise smtplib.SMTPRecipientsRefused({"c@d.com": (550, b"user unknown")})

    monkeypatch.setattr(send_mail, "send", _raise)
    monkeypatch.setattr(sys, "argv", ["send_mail.py", str(html), "--subject", "s", "--env", str(env)])

    assert send_mail.main() == 3
    err = capsys.readouterr().err
    assert "refused" in err
    assert "attempts" not in err
    assert "c@d.com" not in err


@pytest.mark.parametrize("dry_run", [False, True])
def test_main_does_not_print_configured_addresses(tmp_path, monkeypatch, capsys, dry_run):
    import sys

    html = tmp_path / "r.html"
    html.write_text("<p>x</p>", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text(
        "GMAIL_USER=sender@example.com\n"
        "GMAIL_APP_PASSWORD=x\n"
        "REPORT_RECIPIENTS=one@example.com,two@example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(send_mail, "send", lambda *_a, **_k: 0)
    argv = ["send_mail.py", str(html), "--subject", "s", "--env", str(env)]
    if dry_run:
        argv.append("--dry-run")
    monkeypatch.setattr(sys, "argv", argv)

    assert send_mail.main() == 0
    output = capsys.readouterr().out
    assert "recipients=2" in output
    assert "sender@example.com" not in output
    assert "one@example.com" not in output
    assert "two@example.com" not in output
