"""Validate daily publication times against the locked discovery window."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo

from discovery import compute_daily_window


NEWS_SECTIONS = ("frontier_models", "coding_agents", "general_agents", "policy_risk")
SHANGHAI = ZoneInfo("Asia/Shanghai")
DATE_ONLY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _aware_time(value: Any) -> datetime:
    if not isinstance(value, str) or DATE_ONLY.fullmatch(value):
        raise ValueError("must be an ISO timestamp with explicit timezone")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("must include an explicit timezone")
    return parsed.astimezone(SHANGHAI)


def _normalized_window(window: Any) -> dict[str, str]:
    if not isinstance(window, dict):
        raise ValueError("missing window")
    # UTC+08:00 was emitted by the previous pure helper. Its label is an alias,
    # not permission to accept a different wall-clock window.
    if window.get("timezone") not in {"Asia/Shanghai", "UTC+08:00"}:
        raise ValueError("timezone must be Asia/Shanghai (legacy UTC+08:00 accepted)")
    return {
        "start": _aware_time(window.get("start")).isoformat(),
        "end": _aware_time(window.get("end")).isoformat(),
        "timezone": "Asia/Shanghai",
    }


def _publication_time(value: Any, start: datetime, end: datetime, label: str) -> tuple[Any, list[str]]:
    """Keep date precision; never invent midnight as an event's timestamp."""
    if isinstance(value, str) and DATE_ONLY.fullmatch(value):
        try:
            day = date.fromisoformat(value)
            lower = datetime.combine(day, time.min, tzinfo=SHANGHAI)
            upper = lower + timedelta(days=1)
        except ValueError as exc:
            return None, [f"{label}.published_at invalid date: {exc}"]
        if upper <= start or lower > end:
            return day, [f"{label}.published_at outside locked daily window"]
        if lower < start or upper > end:
            return day, [
                f"{label}.published_at date-only overlaps a window boundary; verify the actual event time "
                "or an evidenced first mention (inferred, confidence <= medium); do not invent midnight"
            ]
        return day, []
    try:
        published = _aware_time(value)
    except (TypeError, ValueError) as exc:
        return None, [f"{label}.published_at {exc}"]
    if not start <= published <= end:
        return published, [f"{label}.published_at outside locked daily window"]
    return published, []


def validate_daily_time_window(
    report: dict[str, Any], ledger: dict[str, Any], manifest: dict[str, Any] | None,
) -> list[str]:
    """Recompute both windows, then enforce selected-news time consistency.

    A manifest with just date/window is sufficient for historical formats; a
    missing manifest never disables these checks for an older report version.
    """
    if not isinstance(manifest, dict):
        return ["daily time validation requires discovery_manifest with date and window"]
    errors: list[str] = []
    try:
        locked = _normalized_window(manifest.get("window"))
        expected = compute_daily_window(manifest.get("date"), locked["end"])
    except (TypeError, ValueError) as exc:
        return [f"discovery_manifest daily window invalid: {exc}"]
    if locked != expected:
        errors.append("discovery_manifest.window does not match recomputed daily window")
    for name, payload in (("report", report), ("candidate_ledger", ledger)):
        if payload.get("date") != manifest.get("date"):
            errors.append(f"{name}.date does not match discovery_manifest.date")
    try:
        if _normalized_window(report.get("window")) != expected:
            errors.append("report.window does not match recomputed discovery_manifest daily window")
    except (TypeError, ValueError) as exc:
        errors.append(f"report.window invalid: {exc}")

    start, end = _aware_time(expected["start"]), _aware_time(expected["end"])
    selected: dict[tuple[Any, Any], tuple[dict[str, Any], Any]] = {}
    for index, item in enumerate(ledger.get("items", [])):
        if item.get("decision") not in {"selected_core", "selected_watch"}:
            continue
        label = f"candidate_ledger.items[{index}]"
        parsed, time_errors = _publication_time(item.get("published_at"), start, end, label)
        errors.extend(time_errors)
        key = (item.get("proposed_section"), item.get("headline"))
        if key in selected:
            errors.append(f"{label} duplicate selected news identity prevents time alignment")
        selected[key] = (item, parsed)

    for section in NEWS_SECTIONS:
        for index, item in enumerate(report.get("sections", {}).get(section, {}).get("items", [])):
            label = f"{section}[{index}]"
            parsed, time_errors = _publication_time(item.get("published_at"), start, end, label)
            errors.extend(time_errors)
            key = (section, item.get("headline"))
            record, ledger_time = selected.get(key, ({}, None))
            if not record:
                errors.append(f"{label} missing selected candidate ledger record for publication time alignment")
            if record and parsed is not None and ledger_time is not None and parsed != ledger_time:
                errors.append(f"{label}.published_at differs from selected candidate ledger")
            precision = item.get("published_at_confidence")
            if precision not in {"exact", "approximate", "inferred"}:
                errors.append(f"{label}.published_at_confidence must be exact, approximate or inferred")
            inferred = precision == "inferred" or record.get("date_basis") == "inferred_from_search"
            if inferred and item.get("confidence") not in {"medium", "low"}:
                errors.append(f"{label} inferred publication time requires confidence <= medium")
            if record.get("date_basis") == "inferred_from_search" and precision != "inferred":
                errors.append(f"{label} inferred_from_search requires published_at_confidence=inferred")
    return errors
