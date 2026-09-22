#!/usr/bin/env python3
"""Validate explicitly selected research supplements, independently of events."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEEP_DIVE_SCHEMA_PATH = SKILL_ROOT / "schemas" / "deep_dive.schema.json"


def deep_dive_path(project_root: Path, date: str, slug: str) -> Path:
    return project_root / "cache" / date / f"deep_dive_{slug}.json"


def selected_deep_dive_slugs(report: dict[str, Any]) -> list[str]:
    """Only the editor's explicit list selects delivery; files/events never do."""
    schema = json.loads((SKILL_ROOT / "schemas" / "daily_report.schema.json").read_text(encoding="utf-8"))
    slugs = report.get("deep_dive_refs", [])
    errors = list(Draft202012Validator(schema["properties"]["deep_dive_refs"]).iter_errors(slugs))
    if errors:
        raise ValueError(f"deep_dive_refs: {errors[0].message}")
    return slugs


def validate_deep_dives(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    try:
        slugs = selected_deep_dive_slugs(report)
    except ValueError as exc:
        return [str(exc)]
    if not slugs:
        return errors

    schema = json.loads(DEEP_DIVE_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    date = str(report.get("date", ""))
    successful_targets = {
        attempt.get("target")
        for detail in report.get("fetch_status", {}).get("source_details", {}).values()
        for attempt in detail.get("attempts", [])
        if attempt.get("result") == "success"
    }
    for slug in slugs:
        path = deep_dive_path(project_root, date, slug)
        rel = f"cache/{date}/{path.name}"
        if not path.exists():
            errors.append(f"deep_dive_refs selects missing file {rel}")
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
        if payload.get("version") != "1.1":
            errors.append(f"{rel}: selected delivery requires research format 1.1; legacy 1.0 is render-only")
            continue
        if payload.get("event_slug") != slug:
            errors.append(f"{rel}: event_slug {payload.get('event_slug')!r} does not match {slug!r}")
        if payload.get("date") != date:
            errors.append(f"{rel}: date {payload.get('date')!r} does not match report date {date!r}")
        refs = payload["references"]
        ref_ids = [ref["id"] for ref in refs]
        if len(ref_ids) != len(set(ref_ids)):
            errors.append(f"{rel}: duplicate reference id")
        for ref in refs:
            if ref["url"] not in successful_targets:
                errors.append(f"{rel}: reference {ref['id']} lacks a successful exact-URL fetch attempt")
            try:
                observed = datetime.fromisoformat(ref["observed_at"].replace("Z", "+00:00"))
                generated = datetime.fromisoformat(payload["generated_at"].replace("Z", "+00:00"))
                if observed.tzinfo is None or generated.tzinfo is None or observed > generated:
                    raise ValueError("timestamp must have a timezone and precede generation")
            except ValueError:
                errors.append(f"{rel}: reference {ref['id']} has invalid observed_at / generated_at")
        sections = payload["sections"]
        claims = sections["comparisons"] + sections["scenarios"] + [sections["costs_and_constraints"]]
        for index, claim in enumerate(claims):
            missing = set(claim["reference_ids"]) - set(ref_ids)
            if missing:
                errors.append(f"{rel}: claim[{index}] has unresolved references {sorted(missing)}")
    return errors
