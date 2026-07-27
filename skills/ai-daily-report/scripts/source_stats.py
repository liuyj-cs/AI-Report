#!/usr/bin/env python3
"""Deterministic helpers for the source cadence ledger: per-surface probe outcomes.

Lives at ``cache/source_stats.json`` (cache root, same convention as
``seen_repos.json``) because ``cache/{date}/`` day directories are pruned after
14 days while cadence needs a 30-day window.

Semantics differ from the seen-ledgers on purpose: those record what readers
actually received (written only after a successful send), this records what the
run actually probed — so dry-run writes here too.
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

STATS_RETENTION_DAYS = 45


def source_stats_path(project_root: Path) -> Path:
    return project_root / "cache" / "source_stats.json"


def load_source_stats(project_root: Path) -> dict[str, Any]:
    """Read the ledger; a missing or corrupt file reads as empty (fail-open).

    An empty ledger means every surface falls back to daily probing, i.e. today's
    behaviour — losing the ledger must never block a report.
    """
    path = source_stats_path(project_root)
    if not path.exists():
        return {"version": "1.0", "days": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "1.0", "days": {}}
    if not isinstance(payload.get("days"), dict):
        return {"version": "1.0", "days": {}}
    return payload


def _prune(days: dict[str, Any], today: str) -> dict[str, Any]:
    try:
        cutoff = date.fromisoformat(today) - timedelta(days=STATS_RETENTION_DAYS)
    except ValueError:
        return days
    kept = {}
    for day, payload in days.items():
        try:
            if date.fromisoformat(day) >= cutoff:
                kept[day] = payload
        except ValueError:
            continue
    return kept


def record_source_stats(report: dict[str, Any], project_root: Path, today: str) -> int:
    """Write today's per-surface {attempts, hit} into the ledger, idempotent by date.

    ``hit`` is deterministic: the surface reported success and was not empty. It
    deliberately ignores whether a candidate survived editorial judgement — that
    would make scheduling depend on how faithfully the AI filled the ledger.
    """
    fetch_status = report.get("fetch_status", {})
    succeeded = set(fetch_status.get("succeeded") or [])
    empty = set(fetch_status.get("empty") or [])
    source_details = fetch_status.get("source_details") or {}

    entry = {
        name: {
            "attempts": len(detail.get("attempts") or []),
            "hit": name in succeeded and name not in empty,
        }
        for name, detail in source_details.items()
    }

    stats = load_source_stats(project_root)
    days = _prune(dict(stats.get("days", {})), today)
    days[today] = entry
    payload = {"version": "1.0", "days": days}

    path = source_stats_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(entry)
