#!/usr/bin/env python3
"""Send a rendered HTML report via Gmail SMTP."""
from __future__ import annotations

import argparse
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

from dotenv import dotenv_values

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
# 瞬时网络错误（历史上 code=3 高频复发于清晨）用固定退避重试；认证错误不重试。
RETRY_DELAYS = (5, 20)


def _split_addrs(raw: str) -> list[str]:
    return [a.strip() for a in raw.replace(";", ",").split(",") if a.strip()]


def build_message(
    sender: str,
    recipients: list[str],
    subject: str,
    html_body: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr(("AI Report", sender))
    if len(recipients) == 1:
        msg["To"] = recipients[0]
    else:
        # 多收件人走 Bcc（互不可见）；smtplib.send_message 用 To+Bcc 计算 envelope 并剥离 Bcc 头
        msg["To"] = formataddr(("AI Report", sender))
        msg["Bcc"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=sender.split("@", 1)[-1])
    msg.set_content("This email contains an HTML report. Please use an HTML-capable client.")
    msg.add_alternative(html_body, subtype="html")
    return msg


def send(
    msg: EmailMessage,
    sender: str,
    password: str,
    retry_delays: tuple[int, ...] = RETRY_DELAYS,
    sleep=time.sleep,
) -> int:
    """发送邮件；瞬时 SMTP/网络错误按 retry_delays 重试，返回实际重试次数。"""
    for attempt in range(len(retry_delays) + 1):
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context, timeout=30) as smtp:
                smtp.login(sender, password)
                smtp.send_message(msg)
            return attempt
        except smtplib.SMTPAuthenticationError:
            raise
        except (smtplib.SMTPException, OSError):
            if attempt == len(retry_delays):
                raise
            sleep(retry_delays[attempt])
    raise AssertionError("unreachable")


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a rendered HTML report via Gmail SMTP.")
    parser.add_argument("html_path", type=Path, help="Path to the rendered HTML file")
    parser.add_argument("--subject", required=True, help="Email subject line")
    parser.add_argument(
        "--env",
        type=Path,
        default=Path(".env"),
        help="Path to the .env file (default: ./.env)",
    )
    parser.add_argument(
        "--to",
        help="Override recipients (comma-separated). Defaults to REPORT_RECIPIENTS in .env.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build the message but do not connect to SMTP. Prints recipients and exits.",
    )
    args = parser.parse_args()

    if not args.env.exists():
        print(f"env file not found: {args.env}", file=sys.stderr)
        return 1
    env = {k: v for k, v in dotenv_values(args.env).items() if v is not None}

    sender = env.get("GMAIL_USER")
    password = env.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        print("GMAIL_USER / GMAIL_APP_PASSWORD missing in .env", file=sys.stderr)
        return 1

    raw_recipients = args.to or env.get("REPORT_RECIPIENTS") or env.get("RECIPIENT_EMAIL") or ""
    recipients = _split_addrs(raw_recipients)
    if not recipients:
        print("no recipients: set --to or REPORT_RECIPIENTS / RECIPIENT_EMAIL in .env", file=sys.stderr)
        return 1

    try:
        html_body = args.html_path.read_text(encoding="utf-8")
    except OSError as e:
        print(f"failed to read html: {e}", file=sys.stderr)
        return 1

    msg = build_message(sender, recipients, args.subject, html_body)

    if args.dry_run:
        print(f"DRY-RUN from={sender} to={recipients} subject={args.subject!r} bytes={len(html_body)}")
        return 0

    try:
        retries = send(msg, sender, password)
    except smtplib.SMTPAuthenticationError as e:
        print(f"SMTP auth failed: {e}", file=sys.stderr)
        return 2
    except (smtplib.SMTPException, OSError) as e:
        print(f"SMTP send failed after {len(RETRY_DELAYS) + 1} attempts: {e}", file=sys.stderr)
        return 3

    suffix = f" retries={retries}" if retries else ""
    print(f"sent to={','.join(recipients)} subject={args.subject!r}{suffix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
