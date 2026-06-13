#!/usr/bin/env python3
"""Deterministic helpers for major-event deep-dive supplements."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEEP_DIVE_SCHEMA_PATH = SKILL_ROOT / "schemas" / "deep_dive.schema.json"


def deep_dive_path(project_root: Path, date: str, slug: str) -> Path:
    return project_root / "cache" / date / f"deep_dive_{slug}.json"


def major_event_slugs(report: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (section_label, tracking_ref) for every major_event item."""
    pairs: list[tuple[str, str]] = []
    for section_name in ("frontier_models", "coding_agents", "general_agents"):
        for index, item in enumerate(report.get("sections", {}).get(section_name, {}).get("items", [])):
            if item.get("major_event"):
                pairs.append((f"{section_name}[{index}]", str(item.get("tracking_ref") or "")))
    return pairs


def validate_deep_dives(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    pairs = major_event_slugs(report)
    if not pairs:
        return errors

    schema = json.loads(DEEP_DIVE_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    date = str(report.get("date", ""))
    for label, slug in pairs:
        if not slug:
            continue  # 缺 tracking_ref 由 validate_major_event_consistency 报错
        path = deep_dive_path(project_root, date, slug)
        rel = f"cache/{date}/{path.name}"
        if not path.exists():
            errors.append(f"{label} major_event requires deep dive file {rel}")
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{rel}: cannot load ({exc})")
            continue
        schema_errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
        if schema_errors:
            errors.append(f"{rel}: {schema_errors[0].message}")
            continue
        if payload.get("event_slug") != slug:
            errors.append(f"{rel}: event_slug {payload.get('event_slug')!r} does not match {slug!r}")
        if payload.get("date") != date:
            errors.append(f"{rel}: date {payload.get('date')!r} does not match report date {date!r}")
    return errors
