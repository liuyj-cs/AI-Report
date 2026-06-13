#!/usr/bin/env python3
"""Discovery-first orchestration for AI-authored daily/weekly reports."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from dotenv import dotenv_values

from archive import archive as archive_html
from discovery import (
    append_run_log,
    build_discovery_manifest,
    compute_daily_window,
    load_profile,
    load_whitelist,
    write_discovery_manifest,
)
from ecosystem import record_ecosystem_repos
from editorial import build_daily_qa_diff, build_weekly_qa_diff, validate_daily_artifacts, validate_weekly_artifacts
from render_html import render
from tracking import active_tracking_events, cleanup_expired_tracking

SCRIPT_DIR = Path(__file__).resolve().parent


def _load_env(env_path: Path) -> dict[str, str]:
    return {k: v for k, v in dotenv_values(env_path).items() if v is not None}


def _validate_email_env(env: dict[str, str]) -> tuple[bool, str]:
    sender = env.get("GMAIL_USER")
    password = env.get("GMAIL_APP_PASSWORD")
    recipients = env.get("REPORT_RECIPIENTS") or env.get("RECIPIENT_EMAIL")
    if not sender or not password or not recipients:
        return False, "GMAIL_USER / GMAIL_APP_PASSWORD / REPORT_RECIPIENTS missing"
    return True, ""


def run_daily_init(
    project_root: Path,
    target_date: str,
    now_iso: str,
    env_path: Path,
) -> tuple[int, str]:
    env = _load_env(env_path)
    ok, message = _validate_email_env(env)
    if not ok:
        return 1, message

    whitelist = load_whitelist()
    window = compute_daily_window(target_date, now_iso)
    cache_dir = project_root / "cache" / target_date
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_log = cache_dir / "run.log"
    append_run_log(
        run_log,
        f"{now_iso} START daily date={target_date} window_start={window['start']} window_end={window['end']}",
    )
    active = [
        {
            "event_slug": event["event_slug"],
            "title": event["title"],
            "expires_on": event["expires_on"],
            "watch_items": event.get("watch_items", []),
        }
        for event in active_tracking_events(project_root, target_date)
    ]
    manifest = build_discovery_manifest(
        target_date, window, whitelist, active_tracking=active, reader_profile=load_profile()
    )
    path = write_discovery_manifest(cache_dir, manifest)
    append_run_log(run_log, f"{now_iso} DISCOVERY manifest={path.name} ready")
    append_run_log(run_log, f"{now_iso} TRACKING active={len(active)}")
    return 0, str(path)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _qa_summary_line(qa_diff: dict[str, Any]) -> str:
    categories = qa_diff.get("summary", {}).get("categories", {})
    ordered = [
        "missed_discovery",
        "downgraded_evidence",
        "duplicate_rejected",
        "weak_evidence_rejected",
        "hard_data_gap",
        "reference_integrity_gap",
    ]
    return "QA findings " + " ".join(f"{name}={categories.get(name, 0)}" for name in ordered)


def _send_mail(project_root: Path, html_path: Path, subject: str, env_path: Path) -> tuple[int, str]:
    script = SCRIPT_DIR / "send_mail.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            str(html_path),
            "--subject",
            subject,
            "--env",
            str(env_path),
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    output = (proc.stdout or proc.stderr).strip()
    return proc.returncode, output


def run_daily_finalize(project_root: Path, target_date: str, dry_run: bool, env_path: Path) -> tuple[int, str]:
    env = _load_env(env_path)
    ok, message = _validate_email_env(env)
    if not ok:
        return 1, message

    cache_dir = project_root / "cache" / target_date
    report_path = cache_dir / "report.json"
    ledger_path = cache_dir / "candidate_ledger.json"
    run_log = cache_dir / "run.log"
    if not report_path.exists() or not ledger_path.exists():
        return 1, "report.json and candidate_ledger.json must exist before finalize"

    report = _load_json(report_path)
    ledger = _load_json(ledger_path)
    whitelist = load_whitelist()
    qa_diff = build_daily_qa_diff(report, ledger, whitelist)
    qa_path = _write_json(cache_dir / "qa_diff.json", qa_diff)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} QA {qa_path.name} ok")
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} {_qa_summary_line(qa_diff)}")
    errors = validate_daily_artifacts(report, ledger, whitelist, project_root, profile=load_profile())
    if errors:
        return 1, "artifact validation failed:\n" + "\n".join(f"- {error}" for error in errors)

    html_path = render(report_path)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} RENDER report.html ok")
    archived_path = archive_html(html_path, "daily", target_date, project_root)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} ARCHIVE {archived_path.relative_to(project_root)} ok")
    removed_tracking = cleanup_expired_tracking(project_root, target_date)
    if removed_tracking:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} TRACKING cleanup removed={removed_tracking}")
    recorded = record_ecosystem_repos(report, project_root, target_date)
    if recorded:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} ECOSYSTEM seen_repos+={recorded}")

    if dry_run:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL skipped (dry-run)")
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=ok")
        return 0, str(archived_path)

    code, send_output = _send_mail(project_root, archived_path, f"AI 日报 · {target_date}", env_path)
    if code != 0:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL failed code={code}")
        return code, send_output
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL {send_output}")
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=ok")
    return 0, str(archived_path)


def _rolling_week_dates(week_end: str) -> list[str]:
    # fromisoformat (py>=3.11) accepts ISO week strings like "2026-W20"; require plain YYYY-MM-DD
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week_end):
        raise ValueError(f"week_end must be YYYY-MM-DD, got {week_end!r}")
    end = datetime.fromisoformat(week_end).date()
    return [(end - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def run_weekly_init(project_root: Path, week_end: str, now_iso: str, env_path: Path) -> tuple[int, str]:
    env = _load_env(env_path)
    ok, message = _validate_email_env(env)
    if not ok:
        return 1, message

    try:
        source_days = _rolling_week_dates(week_end)
    except ValueError:
        return 1, f"invalid --end-date {week_end!r}, expected YYYY-MM-DD"

    cache_dir = project_root / "cache" / "weekly" / week_end
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_log = cache_dir / "run.log"
    append_run_log(run_log, f"{now_iso} START weekly week_end={week_end}")
    payload = {
        "version": "1.0",
        "type": "weekly_input_days",
        "week_end": week_end,
        "source_days": source_days,
    }
    path = cache_dir / "input_days.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_run_log(run_log, f"{now_iso} INPUT_DAYS manifest={path.name} ready")
    return 0, str(path)


def run_weekly_finalize(project_root: Path, week_end: str, dry_run: bool, env_path: Path) -> tuple[int, str]:
    env = _load_env(env_path)
    ok, message = _validate_email_env(env)
    if not ok:
        return 1, message

    cache_dir = project_root / "cache" / "weekly" / week_end
    report_path = cache_dir / "report.json"
    run_log = cache_dir / "run.log"
    if not report_path.exists():
        return 1, "weekly report.json must exist before finalize"

    report = _load_json(report_path)
    if report.get("week_end") != week_end:
        return 1, f"weekly report.json week_end {report.get('week_end')!r} does not match requested {week_end!r}"
    qa_diff = build_weekly_qa_diff(report, project_root)
    qa_path = _write_json(cache_dir / "qa_diff.json", qa_diff)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} QA {qa_path.name} ok")
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} {_qa_summary_line(qa_diff)}")
    errors = validate_weekly_artifacts(report, project_root)
    if errors:
        return 1, "weekly artifact validation failed:\n" + "\n".join(f"- {error}" for error in errors)

    html_path = render(report_path)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} RENDER report.html ok")
    archived_path = archive_html(html_path, "weekly", week_end, project_root)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} ARCHIVE {archived_path.relative_to(project_root)} ok")

    if dry_run:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL skipped (dry-run)")
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END weekly status=ok")
        return 0, str(archived_path)

    week_start = _rolling_week_dates(week_end)[0]
    code, send_output = _send_mail(project_root, archived_path, f"AI 周报 · {week_start} ~ {week_end}", env_path)
    if code != 0:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL failed code={code}")
        return code, send_output
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL {send_output}")
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END weekly status=ok")
    return 0, str(archived_path)


def main(argv: list[str] | None = None, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="AI report deterministic runner")
    parser.add_argument("--project-root", type=Path, default=project_root or Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_daily = subparsers.add_parser("init-daily")
    init_daily.add_argument("--date", required=True)
    init_daily.add_argument("--now", required=True)
    init_daily.add_argument("--env", type=Path, default=Path(".env"))

    finalize_daily = subparsers.add_parser("finalize-daily")
    finalize_daily.add_argument("--date", required=True)
    finalize_daily.add_argument("--env", type=Path, default=Path(".env"))
    finalize_daily.add_argument("--dry-run", action="store_true")

    init_weekly = subparsers.add_parser("init-weekly")
    init_weekly.add_argument("--end-date", required=True, dest="end_date")
    init_weekly.add_argument("--now", required=True)
    init_weekly.add_argument("--env", type=Path, default=Path(".env"))

    finalize_weekly = subparsers.add_parser("finalize-weekly")
    finalize_weekly.add_argument("--end-date", required=True, dest="end_date")
    finalize_weekly.add_argument("--env", type=Path, default=Path(".env"))
    finalize_weekly.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(argv)
    root = args.project_root.resolve()

    if args.command == "init-daily":
        code, message = run_daily_init(root, args.date, args.now, args.env)
    elif args.command == "finalize-daily":
        code, message = run_daily_finalize(root, args.date, args.dry_run, args.env)
    elif args.command == "init-weekly":
        code, message = run_weekly_init(root, args.end_date, args.now, args.env)
    else:
        code, message = run_weekly_finalize(root, args.end_date, args.dry_run, args.env)

    if message:
        stream = sys.stderr if code else sys.stdout
        print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
