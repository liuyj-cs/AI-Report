#!/usr/bin/env python3
"""Deterministic helpers for leader-interview briefs (standalone email artifacts)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from send_state import SendStateError, atomic_write_json, locked_ledger

SKILL_ROOT = Path(__file__).resolve().parent.parent
INTERVIEW_SCHEMA_PATH = SKILL_ROOT / "schemas" / "interview_brief.schema.json"


def iter_interview_files(project_root: Path, date: str) -> list[Path]:
    cache_dir = project_root / "cache" / date
    if not cache_dir.exists():
        return []
    return sorted(cache_dir.glob("interview_*.json"))


def validate_interviews(report_date: str, project_root: Path) -> list[str]:
    errors: list[str] = []
    files = iter_interview_files(project_root, report_date)
    if not files:
        return errors
    schema = json.loads(INTERVIEW_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for path in files:
        rel = f"cache/{report_date}/{path.name}"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{rel}: cannot load ({exc})")
            continue
        schema_errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
        if schema_errors:
            errors.append(f"{rel}: {schema_errors[0].message}")
            continue
        if payload.get("date") != report_date:
            errors.append(f"{rel}: date {payload.get('date')!r} does not match report date {report_date!r}")
        expected_name = f"interview_{payload.get('slug')}.json"
        if path.name != expected_name:
            errors.append(f"{rel}: filename does not match slug {payload.get('slug')!r} (expected {expected_name})")
        mode = payload.get("mode")
        if mode == "self_translated_full" and not payload.get("full_translation"):
            errors.append(f"{rel}: mode=self_translated_full requires non-empty full_translation")
        if mode == "linked_zh_transcript" and not (payload.get("chinese_transcript") or {}).get("url"):
            errors.append(f"{rel}: mode=linked_zh_transcript requires chinese_transcript.url")
    return errors


def _interview_seen_path(project_root: Path) -> Path:
    return project_root / "cache" / "interview_seen.json"


def load_interview_seen(project_root: Path) -> dict[str, Any]:
    path = _interview_seen_path(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"version": "1.0", "interviews": {}}
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SendStateError("interview_seen cannot be read; interview delivery blocked") from exc
    if (not isinstance(payload, dict) or payload.get("version") != "1.0"
            or not isinstance(payload.get("interviews"), dict)
            or not all(isinstance(entry, dict) and isinstance(entry.get("sent_date"), str)
                       and entry["sent_date"] for entry in payload["interviews"].values())):
        raise SendStateError("interview_seen has an invalid structure; interview delivery blocked")
    return payload


def record_interview_sent(project_root: Path, payload: dict[str, Any], sent_date: str, report_path: str) -> None:
    slug = str(payload.get("slug", ""))
    if not slug:
        return
    path = _interview_seen_path(project_root)
    with locked_ledger(path):
        seen = load_interview_seen(project_root)
        if slug in seen["interviews"]:
            return
        seen["interviews"][slug] = {
            "person": payload.get("person", ""),
            "org": payload.get("org", ""),
            "original_url": payload.get("original_url", ""),
            "title": payload.get("interview_title", ""),
            "first_seen_date": payload.get("first_seen_date", ""),
            "published_at": payload.get("published_at", ""),
            "sent_date": sent_date,
            "mode": payload.get("mode", ""),
            "report_path": report_path,
        }
        atomic_write_json(path, seen)


def interview_already_sent(project_root: Path, slug: str) -> bool:
    record = load_interview_seen(project_root).get("interviews", {}).get(slug)
    return bool(record and record.get("sent_date"))
