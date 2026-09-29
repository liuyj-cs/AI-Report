#!/usr/bin/env python3
"""Discovery-first orchestration for AI-authored daily/weekly reports."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

from dotenv import dotenv_values

from archive import TYPE_DIRS, archive as archive_html, cleanup_cache
from deep_dive import deep_dive_path, selected_deep_dive_slugs
from interview import iter_interview_files, interview_already_sent, load_interview_seen, record_interview_sent
from discovery import (
    append_run_log,
    build_discovery_manifest,
    compute_daily_window,
    load_profile,
    load_whitelist,
    rolling_week_dates,
    write_discovery_manifest,
)
from ecosystem import record_ecosystem_repos
from hard_data import SNAPSHOT_FILENAME, compute_hard_data_delta, find_previous_snapshot, load_snapshot
from methodology import load_seen_methodology, record_methodology, validate_methodology_repeats
from agent_editorial import validate_batch_version
from aihot import validate_aihot_discovery
from editorial import build_daily_qa_diff, build_weekly_qa_diff, validate_daily_artifacts, validate_weekly_artifacts
from render_html import render
from send_state import SendStateError, already_sent, load_send_state, record_sent, record_delivery_result
from tracking import cleanup_expired_tracking, is_active_event, load_tracking_events

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


_EMAIL_KIND_PATTERN = re.compile(r"kind=(\S+)\s*$")
# 补发路径映射：kind → (reports 子目录, 文件名模板)；目录名唯一真源是 archive.TYPE_DIRS
_KIND_ARTIFACT = {
    "daily": (TYPE_DIRS["daily"], "{date}.html"),
    "deep_dive": (TYPE_DIRS["deep_dive"], "{date}-{slug}.html"),
    "interview": (TYPE_DIRS["interview"], "{date}-{slug}.html"),
}


def _artifact_path_for_kind(kind: str, day: str) -> str:
    base, _, slug = kind.partition(":")
    directory, template = _KIND_ARTIFACT.get(base, ("daily", "{date}.html"))
    return f"reports/{directory}/{template.format(date=day, slug=slug)}"


def _yesterday_email_statuses(project_root: Path, target_date: str) -> tuple[str, dict[str, str]]:
    """扫描昨日 run.log 的 EMAIL 行，按 kind 返回末态 'ok'|'failed'|'dry_run'。

    日报/深度/访谈发送链各自带 kind= 标签；无标签的历史行按 daily 归类（旧格式兼容）。
    dry-run 单独成态：它不是失败，但也绝不等于"已送达"。
    """
    try:
        yesterday = (date.fromisoformat(target_date) - timedelta(days=1)).isoformat()
    except ValueError:
        return "", {}
    log_path = project_root / "cache" / yesterday / "run.log"
    if not log_path.exists():
        return yesterday, {}
    statuses: dict[str, str] = {}
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if "EMAIL" not in line:
            continue
        match = _EMAIL_KIND_PATTERN.search(line)
        kind = match.group(1) if match else "daily"
        if "EMAIL unknown" in line or "EMAIL blocked" in line:
            statuses[kind] = "unknown"
        elif "EMAIL partial" in line:
            statuses[kind] = "partial"
        elif "EMAIL failed" in line:
            statuses[kind] = "failed"
        elif "EMAIL sent" in line or "EMAIL skip already-sent" in line:
            statuses[kind] = "ok"
        elif "EMAIL skipped" in line:
            # ok/failed 都是具体投递结果，后续 dry-run 排练不覆盖
            statuses.setdefault(kind, "dry_run")
    return yesterday, statuses


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
    try:
        window = compute_daily_window(target_date, now_iso)
    except ValueError as exc:
        return 1, f"invalid --date {target_date!r} or --now {now_iso!r}: {exc}"
    cache_dir = project_root / "cache" / target_date
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_log = cache_dir / "run.log"
    append_run_log(
        run_log,
        f"{now_iso} START daily date={target_date} window_start={window['start']} window_end={window['end']}",
    )
    events, tracking_errors = load_tracking_events(project_root)
    for error in tracking_errors:
        append_run_log(run_log, f"{now_iso} TRACKING warning {error}")
    target = date.fromisoformat(target_date)
    active = [
        {
            "event_slug": event["event_slug"],
            "title": event["title"],
            "expires_on": event["expires_on"],
            "watch_items": event.get("watch_items", []),
        }
        for event in events
        if is_active_event(event, target)
    ]
    manifest = build_discovery_manifest(
        target_date, window, whitelist, active_tracking=active, reader_profile=load_profile()
    )
    path = write_discovery_manifest(cache_dir, manifest)
    append_run_log(run_log, f"{now_iso} DISCOVERY manifest={path.name} ready")
    append_run_log(run_log, f"{now_iso} TRACKING active={len(active)}")
    yesterday, email_statuses = _yesterday_email_statuses(project_root, target_date)
    unknown_kinds = sorted(kind for kind, status in email_statuses.items() if status == "unknown")
    if unknown_kinds:
        append_run_log(run_log, f"{now_iso} DELIVERY_ALERT yesterday_email=unknown date={yesterday}")
        return 0, (f"{path}\nDELIVERY_ALERT: {yesterday} 邮件结果未知（{','.join(unknown_kinds)}）；"
                   "先按 send_state 中的 Message-ID 核实接收情况，禁止自动重发或删除台账。")
    failed_kinds = sorted(kind for kind, status in email_statuses.items() if status in {"failed", "partial"})
    if failed_kinds:
        append_run_log(
            run_log,
            f"{now_iso} DELIVERY_ALERT yesterday_email=failed kinds={','.join(failed_kinds)} date={yesterday}",
        )
        alert = (
            f"DELIVERY_ALERT: {yesterday} 有邮件未发送成功（{','.join(failed_kinds)}），"
            f"且失败点之后的深度/访谈可能从未尝试；优先重跑 "
            f"finalize-daily --date {yesterday} 续发（保持内容和收件人不变，只补明确未接收的）。"
            f"所有发送必须使用同一 send_state；遇到结果未知或台账损坏先核实，不得自动重发。"
        )
        return 0, f"{path}\n{alert}"
    if email_statuses.get("daily") == "dry_run":
        append_run_log(run_log, f"{now_iso} DELIVERY_ALERT yesterday_email=dry_run date={yesterday}")
        alert = (
            f"DELIVERY_ALERT: {yesterday} 只跑了 dry-run，全部邮件未实际投递；"
            f"如需送达请重跑 finalize-daily --date {yesterday}（不带 --dry-run）"
        )
        return 0, f"{path}\n{alert}"
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


def _send_mail(project_root: Path, html_path: Path, subject: str, env_path: Path,
               cache_dir: Path, state_key: str) -> tuple[int, str]:
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
            "--state-dir",
            str(cache_dir),
            "--state-key",
            state_key,
        ],
        capture_output=True,
        text=True,
        cwd=project_root,
    )
    output = (proc.stdout or proc.stderr).strip()
    return proc.returncode, output


def _deliver_mail(project_root: Path, html_path: Path, subject: str, env_path: Path,
                  cache_dir: Path, state_key: str, run_log: Path, timestamp: str) -> tuple[int, str]:
    """SMTP owns its receipt; an exit code alone never proves acceptance."""
    previously_sent = already_sent(cache_dir, state_key)
    code, output = _send_mail(project_root, html_path, subject, env_path, cache_dir, state_key)
    state = load_send_state(cache_dir)
    accepted = bool(state["sent"].get(state_key))
    smtp_status = state.get("deliveries", {}).get(state_key, {}).get("status")
    try:
        response = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        response = {}
    sender_outcome = response.get("outcome") if isinstance(response, dict) else None
    if code == 0 and not accepted:
        code, output = 5, "sender returned without a durable acceptance receipt; delivery blocked"
    outcome = {4: "partial", 5: "unknown"}.get(code, "failed")
    if accepted:
        code = 0
        outcome = "skipped_existing" if previously_sent or sender_outcome == "skipped_existing" else "sent"
    elif smtp_status == "unknown":
        code, outcome = 5, "unknown"
    elif smtp_status == "partial":
        code, outcome = 4, "partial"
    elif code < 0:
        code, outcome = 5, "unknown"
    record_delivery_result(cache_dir, state_key, html_path, outcome)
    log_outcome = "skip already-sent" if outcome == "skipped_existing" else outcome
    append_run_log(run_log, f"{timestamp} EMAIL {log_outcome} code={code} kind={state_key}")
    return code, output


def run_daily_finalize(project_root: Path, target_date: str, dry_run: bool, env_path: Path) -> tuple[int, str]:
    try:
        load_send_state(project_root / "cache" / target_date)
        if iter_interview_files(project_root, target_date):
            load_interview_seen(project_root)
            load_send_state(project_root / "cache" / "delivery_state" / "interviews")
        return _run_daily_finalize(project_root, target_date, dry_run, env_path)
    except SendStateError as exc:
        return 5, str(exc)
    except OSError:
        return 5, "finalize filesystem operation failed; preserve delivery receipts and inspect before retrying"


def _run_daily_finalize(project_root: Path, target_date: str, dry_run: bool, env_path: Path) -> tuple[int, str]:
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
    if report.get("date") != target_date:
        return 1, f"daily report.json date {report.get('date')!r} does not match requested --date {target_date!r}"
    manifest_path = cache_dir / "discovery_manifest.json"
    manifest = _load_json(manifest_path) if manifest_path.exists() else None
    version_errors = validate_batch_version(report, manifest)
    if version_errors:
        return 1, "\n".join(version_errors)
    whitelist = load_whitelist()
    qa_diff = build_daily_qa_diff(report, ledger, whitelist, project_root=project_root)
    qa_path = _write_json(cache_dir / "qa_diff.json", qa_diff)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} QA {qa_path.name} ok")
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} {_qa_summary_line(qa_diff)}")
    errors = validate_daily_artifacts(report, ledger, whitelist, project_root, profile=load_profile(), manifest=manifest)
    errors.extend(validate_aihot_discovery(report, manifest=manifest, cache_dir=cache_dir))
    if errors:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=aborted validation_errors={len(errors)}")
        return 1, "artifact validation failed:\n" + "\n".join(f"- {error}" for error in errors)

    html_path = render(report_path)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} RENDER report.html ok")
    archived_path = archive_html(html_path, "daily", target_date, project_root)
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} ARCHIVE {archived_path.relative_to(project_root)} ok")
    removed_tracking = cleanup_expired_tracking(project_root, target_date)
    if removed_tracking:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} TRACKING cleanup removed={removed_tracking}")
    removed_cache = cleanup_cache(project_root)
    if removed_cache:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} CACHE cleanup removed={removed_cache}")
    # methodology cooldown is advisory only: warn (non-blocking) so a repeated slug is
    # visible, but never let it stop delivery. The seen-ledgers are written AFTER a
    # successful send (below), so dry-run / a failed send never burns a cooldown slot.
    for cooldown_warning in validate_methodology_repeats(
        report, load_seen_methodology(project_root), target_date
    ):
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} METHODOLOGY cooldown(advisory) {cooldown_warning}")

    deep_dive_sends: list[tuple[Path, str, str]] = []
    for slug in selected_deep_dive_slugs(report):
        dd_json_path = deep_dive_path(project_root, target_date, slug)
        dd_html_path = render(dd_json_path)
        dd_archived = archive_html(dd_html_path, "deep_dive", f"{target_date}-{slug}", project_root)
        append_run_log(
            run_log,
            f"{report.get('generated_at', datetime.now().isoformat())} DEEPDIVE {dd_archived.relative_to(project_root)} ok",
        )
        dd_payload = _load_json(dd_json_path)
        deep_dive_sends.append((dd_archived, f"AI 深度 · {dd_payload['title']}", slug))

    interview_sends: list[tuple[Path, str, dict[str, Any]]] = []
    for iv_json_path in iter_interview_files(project_root, target_date):
        iv_payload = _load_json(iv_json_path)
        slug = str(iv_payload.get("slug", ""))
        iv_html_path = render(iv_json_path)
        iv_archived = archive_html(iv_html_path, "interview", f"{target_date}-{slug}", project_root)
        append_run_log(
            run_log,
            f"{report.get('generated_at', datetime.now().isoformat())} INTERVIEW {iv_archived.relative_to(project_root)} ok",
        )
        subject = f"AI 访谈 · {iv_payload.get('person', '')}（{iv_payload.get('org', '')}）"
        interview_sends.append((iv_archived, subject, iv_payload))

    if dry_run:
        record_delivery_result(cache_dir, "daily", archived_path, "dry_run")
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL skipped (dry-run)")
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=ok")
        return 0, str(archived_path)

    daily_subject = f"AI 日报 · {target_date}"
    code, send_output = _deliver_mail(
        project_root, archived_path, daily_subject, env_path, cache_dir, "daily", run_log,
        report.get("generated_at", datetime.now().isoformat()),
    )
    if code != 0:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=email_failed")
        return code, send_output
    # Record seen-ledgers only after the daily body (which carries the ecosystem +
    # methodology content) actually went out, so dry-run / a failed send never burns a
    # cooldown slot（上方两条路径已提前 return）。台账用独立的 "ledger" 幂等键：
    # 首发后、记账前进程被杀 → 键未置，重跑补记；发送成功后重生成 report.json 再重跑
    # → 键已置，不把"读者从未收到"的新内容写进冷却台账。
    sent_hash = load_send_state(cache_dir)["sent"].get("daily", {}).get("html_sha256")
    current_revision_accepted = sent_hash == hashlib.sha256(archived_path.read_bytes()).hexdigest()
    if not already_sent(cache_dir, "ledger") and not current_revision_accepted:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} LEDGER deferred current revision acceptance unconfirmed")
    if not already_sent(cache_dir, "ledger") and current_revision_accepted:
        recorded = record_ecosystem_repos(report, project_root, target_date)
        if recorded:
            append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} ECOSYSTEM seen_repos+={recorded}")
        recorded_methodology = record_methodology(report, project_root, target_date)
        if recorded_methodology:
            append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} METHODOLOGY seen+={recorded_methodology}")
        record_sent(cache_dir, "ledger", "seen-ledgers recorded", artifact_path=None)
    for dd_archived, dd_subject, dd_slug in deep_dive_sends:
        state_key = f"deep_dive:{dd_slug}"
        code, send_output = _deliver_mail(
            project_root, dd_archived, dd_subject, env_path, cache_dir, state_key, run_log,
            report.get("generated_at", datetime.now().isoformat()),
        )
        if code != 0:
            append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=email_failed")
            return code, send_output
    for iv_archived, iv_subject, iv_payload in interview_sends:
        slug = str(iv_payload.get("slug", ""))
        if interview_already_sent(project_root, slug):
            append_run_log(
                run_log,
                f"{report.get('generated_at', datetime.now().isoformat())} INTERVIEW skip already-sent slug={slug}",
            )
            continue
        code, send_output = _deliver_mail(
            project_root, iv_archived, iv_subject, env_path,
            project_root / "cache" / "delivery_state" / "interviews", f"interview:{slug}", run_log,
            report.get("generated_at", datetime.now().isoformat()),
        )
        if code != 0:
            append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=email_failed")
            return code, send_output
        record_interview_sent(
            project_root, iv_payload, target_date, str(iv_archived.relative_to(project_root))
        )
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END daily status=ok")
    return 0, str(archived_path)


def run_weekly_init(project_root: Path, week_end: str, now_iso: str, env_path: Path) -> tuple[int, str]:
    env = _load_env(env_path)
    ok, message = _validate_email_env(env)
    if not ok:
        return 1, message

    try:
        source_days = rolling_week_dates(week_end)
    except ValueError:
        return 1, f"invalid --end-date {week_end!r}, expected YYYY-MM-DD"

    cache_dir = project_root / "cache" / "weekly" / week_end
    cache_dir.mkdir(parents=True, exist_ok=True)
    run_log = cache_dir / "run.log"
    append_run_log(run_log, f"{now_iso} START weekly week_end={week_end}")
    payload = {
        "version": "1.0",
        "type": "weekly_input_days",
        "expected_report_version": "1.1",
        "week_end": week_end,
        "source_days": source_days,
    }
    path = cache_dir / "input_days.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    append_run_log(run_log, f"{now_iso} INPUT_DAYS manifest={path.name} ready")
    return 0, str(path)


def run_weekly_finalize(project_root: Path, week_end: str, dry_run: bool, env_path: Path) -> tuple[int, str]:
    try:
        load_send_state(project_root / "cache" / "weekly" / week_end)
        return _run_weekly_finalize(project_root, week_end, dry_run, env_path)
    except SendStateError as exc:
        return 5, str(exc)
    except OSError:
        return 5, "finalize filesystem operation failed; preserve delivery receipts and inspect before retrying"


def _run_weekly_finalize(project_root: Path, week_end: str, dry_run: bool, env_path: Path) -> tuple[int, str]:
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
    manifest_path = cache_dir / "input_days.json"
    version_errors = validate_batch_version(report, _load_json(manifest_path) if manifest_path.exists() else None)
    if version_errors:
        return 1, "\n".join(version_errors)
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
        record_delivery_result(cache_dir, "weekly", archived_path, "dry_run")
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} EMAIL skipped (dry-run)")
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END weekly status=ok")
        return 0, str(archived_path)

    week_start = rolling_week_dates(week_end)[0]
    weekly_subject = f"AI 周报 · {week_start} ~ {week_end}"
    code, send_output = _deliver_mail(
        project_root, archived_path, weekly_subject, env_path, cache_dir, "weekly", run_log,
        report.get("generated_at", datetime.now().isoformat()),
    )
    if code != 0:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END weekly status=email_failed")
        return code, send_output
    append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} END weekly status=ok")
    return 0, str(archived_path)


def run_hard_data_delta(project_root: Path, target_date: str) -> tuple[int, str]:
    curr = load_snapshot(project_root, target_date)
    if curr is None:
        return 1, f"no hard data snapshot at cache/{target_date}/{SNAPSHOT_FILENAME}"
    previous = find_previous_snapshot(project_root, target_date)
    baseline_date = previous[0] if previous else None
    prev_payload = previous[1] if previous else None
    payload = {
        "date": target_date,
        "baseline_date": baseline_date,
        "deltas": compute_hard_data_delta(prev_payload, curr),
    }
    return 0, json.dumps(payload, ensure_ascii=False, indent=2)


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

    hard_data_delta = subparsers.add_parser("hard-data-delta")
    hard_data_delta.add_argument("--date", required=True)

    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    if args.command == "hard-data-delta":
        code, message = run_hard_data_delta(root, args.date)
        if message:
            print(message, file=sys.stderr if code else sys.stdout)
        return code
    env_path = args.env if args.env.is_absolute() else (root / args.env)

    if args.command == "init-daily":
        code, message = run_daily_init(root, args.date, args.now, env_path)
    elif args.command == "finalize-daily":
        code, message = run_daily_finalize(root, args.date, args.dry_run, env_path)
    elif args.command == "init-weekly":
        code, message = run_weekly_init(root, args.end_date, args.now, env_path)
    else:
        code, message = run_weekly_finalize(root, args.end_date, args.dry_run, env_path)

    if message:
        stream = sys.stderr if code else sys.stdout
        print(message, file=stream)
    return code


if __name__ == "__main__":
    sys.exit(main())
