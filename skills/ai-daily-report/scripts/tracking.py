#!/usr/bin/env python3
"""Deterministic helpers for major-event tracking files under cache/tracking/."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
TRACKING_SCHEMA_PATH = SKILL_ROOT / "schemas" / "event_tracking.schema.json"
MAX_TRACKING_DAYS = 5


def tracking_dir(project_root: Path) -> Path:
    return project_root / "cache" / "tracking"


def load_tracking_events(project_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    directory = tracking_dir(project_root)
    if not directory.exists():
        return events, errors

    schema = json.loads(TRACKING_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cache/tracking/{path.name}: cannot load ({exc})")
            continue
        schema_errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
        if schema_errors:
            errors.append(f"cache/tracking/{path.name}: {schema_errors[0].message}")
            continue
        if payload["event_slug"] != path.stem:
            errors.append(f"cache/tracking/{path.name}: event_slug {payload['event_slug']!r} does not match filename")
            continue
        try:
            opened = date.fromisoformat(payload["opened_date"])
            expires = date.fromisoformat(payload["expires_on"])
        except ValueError as exc:
            errors.append(f"cache/tracking/{path.name}: invalid date ({exc})")
            continue
        if expires < opened or (expires - opened).days > MAX_TRACKING_DAYS:
            errors.append(f"cache/tracking/{path.name}: tracking window must be 0-{MAX_TRACKING_DAYS} days")
            continue
        events.append(payload)
    return events, errors


def active_tracking_events(project_root: Path, target_date: str) -> list[dict[str, Any]]:
    events, _ = load_tracking_events(project_root)
    target = date.fromisoformat(target_date)
    return [
        event
        for event in events
        if date.fromisoformat(event["opened_date"]) <= target <= date.fromisoformat(event["expires_on"])
    ]


def validate_tracking_refs(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    events, load_errors = load_tracking_events(project_root)
    errors.extend(load_errors)
    target_date = str(report.get("date", ""))
    try:
        target = date.fromisoformat(target_date)
    except ValueError:
        errors.append(f"report date {target_date!r} is not a valid date")
        return errors

    active = {
        event["event_slug"]
        for event in events
        if date.fromisoformat(event["opened_date"]) <= target <= date.fromisoformat(event["expires_on"])
    }
    for section_name in ("frontier_models", "coding_agents", "general_agents"):
        for index, item in enumerate(report.get("sections", {}).get(section_name, {}).get("items", [])):
            slug = item.get("tracking_ref")
            if slug and slug not in active:
                errors.append(f"{section_name}[{index}] tracking_ref {slug!r} has no active tracking file")
    return errors


def cleanup_expired_tracking(project_root: Path, today: str, grace_days: int = 7) -> int:
    directory = tracking_dir(project_root)
    if not directory.exists():
        return 0
    cutoff = date.fromisoformat(today) - timedelta(days=grace_days)
    removed = 0
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expires = date.fromisoformat(payload["expires_on"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        if expires < cutoff:
            path.unlink()
            removed += 1
    return removed
