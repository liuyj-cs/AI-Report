#!/usr/bin/env python3
"""Deterministic helpers for the methodology_radar section: cooldown ledger (daily-only)."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

METHODOLOGY_COOLDOWN_DAYS = 30


def _seen_path(project_root: Path) -> Path:
    return project_root / "cache" / "methodology_seen.json"


def load_seen_methodology(project_root: Path) -> dict[str, Any]:
    path = _seen_path(project_root)
    if not path.exists():
        return {"version": "1.0", "methodologies": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "1.0", "methodologies": {}}
    if not isinstance(payload.get("methodologies"), dict):
        return {"version": "1.0", "methodologies": {}}
    return payload


def _methodology_slugs(report: dict[str, Any]) -> list[str]:
    items = report.get("sections", {}).get("methodology_radar", {}).get("items", [])
    return [str(item.get("slug", "")) for item in items if item.get("slug")]


def validate_methodology_repeats(
    report: dict[str, Any],
    seen: dict[str, Any],
    today: str,
    cooldown_days: int = METHODOLOGY_COOLDOWN_DAYS,
) -> list[str]:
    errors: list[str] = []
    try:
        target = date.fromisoformat(today)
    except ValueError:
        return [f"methodology validation date {today!r} is not a valid date"]
    records = seen.get("methodologies", {})
    for slug in _methodology_slugs(report):
        record = records.get(slug)
        if not record:
            continue
        try:
            last = date.fromisoformat(str(record.get("last_emitted", "")))
        except ValueError:
            continue
        delta = (target - last).days
        if 0 < delta <= cooldown_days:
            errors.append(
                f"methodology_radar {slug!r} already emitted on {record.get('last_emitted')} (cooldown {cooldown_days}d)"
            )
    return errors


def record_methodology(report: dict[str, Any], project_root: Path, today: str) -> int:
    slugs = _methodology_slugs(report)
    if not slugs:
        return 0
    seen = load_seen_methodology(project_root)
    for slug in slugs:
        record = seen["methodologies"].setdefault(slug, {"first_seen": today})
        record["last_emitted"] = today
    path = _seen_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(slugs)
