#!/usr/bin/env python3
"""Deterministic helpers for the agent_ecosystem section: seen-repos cooldown ledger."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

ECOSYSTEM_COOLDOWN_DAYS = 30


def _seen_repos_path(project_root: Path) -> Path:
    return project_root / "cache" / "seen_repos.json"


def load_seen_repos(project_root: Path) -> dict[str, Any]:
    path = _seen_repos_path(project_root)
    if not path.exists():
        return {"version": "1.0", "repos": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "1.0", "repos": {}}
    if not isinstance(payload.get("repos"), dict):
        return {"version": "1.0", "repos": {}}
    return payload


def _trending_repo_slugs(report: dict[str, Any]) -> list[str]:
    items = report.get("sections", {}).get("agent_ecosystem", {}).get("items", [])
    return [
        str(item.get("repo_slug", ""))
        for item in items
        if item.get("item_type") == "trending_repo" and item.get("repo_slug")
    ]


def validate_ecosystem_repeats(
    report: dict[str, Any],
    seen: dict[str, Any],
    today: str,
    cooldown_days: int = ECOSYSTEM_COOLDOWN_DAYS,
) -> list[str]:
    errors: list[str] = []
    try:
        target = date.fromisoformat(today)
    except ValueError:
        return [f"ecosystem validation date {today!r} is not a valid date"]
    repos = seen.get("repos", {})
    for slug in _trending_repo_slugs(report):
        record = repos.get(slug)
        if not record:
            continue
        try:
            last_listed = date.fromisoformat(str(record.get("last_listed", "")))
        except ValueError:
            continue
        delta = (target - last_listed).days
        if 0 < delta <= cooldown_days:
            errors.append(
                f"agent_ecosystem repo {slug!r} already listed on {record.get('last_listed')} (cooldown {cooldown_days}d)"
            )
    return errors


def record_ecosystem_repos(report: dict[str, Any], project_root: Path, today: str) -> int:
    slugs = _trending_repo_slugs(report)
    if not slugs:
        return 0
    seen = load_seen_repos(project_root)
    for slug in slugs:
        record = seen["repos"].setdefault(slug, {"first_seen": today})
        record["last_listed"] = today
    path = _seen_repos_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(slugs)
