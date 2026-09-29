#!/usr/bin/env python3
"""Send HTML through a durable per-recipient SMTP ledger."""
from __future__ import annotations

import argparse
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
import json
from pathlib import Path
import smtplib
import ssl
import sys
import time

from dotenv import dotenv_values
from send_state import DeliveryAttempt, SendStateError, delivery_attempt

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
# Only failures before send_message can be retried automatically.
RETRY_DELAYS = (5, 20)


def _split_addrs(raw: str) -> list[str]:
    return list(dict.fromkeys(a.strip() for a in raw.replace(";", ",").split(",") if a.strip()))


def build_message(sender: str, recipients: list[str], subject: str, html_body: str,
                  *, message_id: str | None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr(("AI Report", sender))
    if len(recipients) == 1:
        msg["To"] = recipients[0]
    else:
        msg["To"] = formataddr(("AI Report", sender))
        msg["Bcc"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = message_id or make_msgid(domain="reports.local")
    msg.set_content("This email contains an HTML report. Please use an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")
    return msg


def _close(smtp) -> None:
    # QUIT is connection cleanup. A failure here cannot undo a confirmed DATA reply.
    try:
        smtp.quit()
    except (smtplib.SMTPException, OSError):
        pass
    finally:
        try:
            smtp.close()
        except (smtplib.SMTPException, OSError):
            pass


def send(msg: EmailMessage, sender: str, password: str, *, delivery: DeliveryAttempt,
         retry_delays: tuple[int, ...] = RETRY_DELAYS, sleep=time.sleep) -> str:
    """Persist the SMTP result before cleanup; return the aggregate delivery state."""
    def finish(status: str, retries: int, error: str | None, codes: dict[str, int]) -> str:
        delivery.record_result({address: status for address in delivery.recipients},
                               retries=retries, error=error, smtp_codes=codes)
        return delivery.entry["status"]

    for attempt in range(len(retry_delays) + 1):
        smtp = None
        try:
            try:
                smtp = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ssl.create_default_context(), timeout=30)
                smtp.login(sender, password)
            except smtplib.SMTPAuthenticationError:
                return finish("not_submitted", attempt, "authentication_failed", {})
            except (smtplib.SMTPException, OSError):
                if attempt == len(retry_delays):
                    return finish("not_submitted", attempt, "connection_failed", {})
                if smtp is not None:
                    _close(smtp)
                    smtp = None
                sleep(retry_delays[attempt])
                continue

            # This durable write is deliberately outside the transport exception
            # handler: a disk failure is never a known SMTP rejection.
            delivery.submitting()
            try:
                refused = smtp.send_message(msg, from_addr=sender, to_addrs=delivery.recipients)
            except smtplib.SMTPRecipientsRefused as exc:
                codes = {address: value[0] for address, value in exc.recipients.items()
                         if address in delivery.recipients}
                return finish("refused", attempt, "recipients_refused", codes)
            except (smtplib.SMTPSenderRefused, smtplib.SMTPDataError, smtplib.SMTPNotSupportedError):
                return finish("not_submitted", attempt, "smtp_rejected", {})
            except (smtplib.SMTPException, OSError):
                # The server may have accepted DATA before the connection vanished.
                return finish("unknown", attempt, "submission_result_unknown", {})
            if not isinstance(refused, dict) or not set(refused) <= set(delivery.recipients):
                return finish("unknown", attempt, "invalid_submission_result", {})
            statuses = {address: "refused" if address in refused else "accepted"
                        for address in delivery.recipients}
            delivery.record_result(statuses, retries=attempt,
                                   error="recipients_refused" if refused else None,
                                   smtp_codes={address: value[0] for address, value in refused.items()})
            return delivery.entry["status"]
        finally:
            if smtp is not None:
                _close(smtp)
    raise AssertionError("unreachable")


def _print_result(outcome: str, counts: dict[str, int]) -> None:
    print(json.dumps({"outcome": outcome, "counts": counts}, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a rendered HTML report via Gmail SMTP.")
    parser.add_argument("html_path", type=Path)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--to", help="Override recipients (comma-separated).")
    parser.add_argument("--state-dir", type=Path, help="Cache directory containing send_state.json.")
    parser.add_argument("--state-key", help="Stable delivery key: daily, weekly, deep_dive:slug, interview:slug.")
    parser.add_argument("--dry-run", action="store_true", help="Build without contacting SMTP or writing send state.")
    args = parser.parse_args()
    if not args.dry_run and (args.state_dir is None or not args.state_key):
        print("--state-dir and --state-key are required for delivery", file=sys.stderr)
        return 1
    if not args.env.exists():
        print("env file not found", file=sys.stderr)
        return 1
    env = {k: v for k, v in dotenv_values(args.env).items() if v is not None}
    sender, password = env.get("GMAIL_USER"), env.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        print("GMAIL_USER / GMAIL_APP_PASSWORD missing in .env", file=sys.stderr)
        return 1
    recipients = _split_addrs(args.to or env.get("REPORT_RECIPIENTS") or env.get("RECIPIENT_EMAIL") or "")
    if not recipients:
        print("no recipients configured", file=sys.stderr)
        return 1
    try:
        html_bytes = args.html_path.read_bytes()
        html_body = html_bytes.decode("utf-8")
    except (OSError, UnicodeError):
        print("failed to read HTML", file=sys.stderr)
        return 1
    if args.dry_run:
        build_message(sender, recipients, args.subject, html_body, message_id=None)
        _print_result("dry_run", {"recipients": len(recipients)})
        return 0
    try:
        with delivery_attempt(args.state_dir, args.state_key, args.subject, html_bytes, sender, recipients) as delivery:
            if delivery is None:
                _print_result("skipped_existing", {})
                return 0
            msg = build_message(sender, delivery.recipients, args.subject, html_body, message_id=delivery.message_id)
            status = send(msg, sender, password, delivery=delivery)
            counts = {value: list(delivery.entry["recipients"].values()).count(value)
                      for value in ("accepted", "refused", "unknown", "not_submitted")}
            _print_result("failed" if status == "not_submitted" else status, counts)
            if status == "not_submitted" and delivery.entry["attempts"][-1].get("error") == "authentication_failed":
                return 2
            return {"sent": 0, "partial": 4, "unknown": 5, "not_submitted": 3}[status]
    except SendStateError as exc:
        # These are our fixed messages, never SMTP exceptions containing addresses.
        print(str(exc), file=sys.stderr)
        _print_result("blocked", {})
        return 5
    except OSError:
        print("delivery state could not be persisted; inspect the existing receipt before retrying", file=sys.stderr)
        _print_result("unknown", {})
        return 5


if __name__ == "__main__":
    sys.exit(main())
