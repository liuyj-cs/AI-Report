#!/usr/bin/env python3
"""Deterministic editorial validation helpers."""
from __future__ import annotations

from collections import Counter
import json
from datetime import datetime, timedelta
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator

from discovery import RECALL_PROBE_SURFACE_NAME, missing_fetch_status_coverage, required_source_family_names
from ecosystem import load_seen_repos, validate_ecosystem_repeats
from tracking import validate_tracking_refs

DAILY_REFERENCE_SECTIONS = ("frontier_models", "coding_agents", "general_agents")
ITEM_REF_PATTERN = re.compile(r"^(?P<section>frontier_models|coding_agents|general_agents)\[(?P<index>\d+)\]$")
SKILL_ROOT = Path(__file__).resolve().parent.parent

LEDGER_TO_REPORT_SECTION = {
    "frontier_models": "frontier_models",
    "coding_agents": "coding_agents",
    "general_agents": "general_agents",
    "unverified": "unverified",
}
QA_CATEGORIES = (
    "missed_discovery",
    "downgraded_evidence",
    "duplicate_rejected",
    "weak_evidence_rejected",
    "hard_data_gap",
    "reference_integrity_gap",
)
HARD_DATA_KEYWORDS = (
    "benchmark",
    "leaderboard",
    "arena elo",
    "elo",
    "score snapshot",
    "pricing",
    "price",
    "mtok",
    "math-500",
    "aime",
    "swe-bench",
    "benchmark",
    "榜单",
    "评分",
    "基准",
    "跑分",
    "定价",
    "价格",
    "测评",
    "付费席位",
    "席位数",
    "周活跃",
    "采用率",
    "商业化指标",
    "商业化数据",
    "商业化采用率",
)
HARD_DATA_PATTERNS = (
    re.compile(r"\bpaid seats?\b"),
    re.compile(r"\bseat count\b"),
    re.compile(r"\bcopilot seats?\b"),
    re.compile(r"\bai\s+arr\b"),
    re.compile(r"\bannual recurring revenue\b"),
    re.compile(r"\bweekly engagement\b"),
    re.compile(r"\bweekly active\b"),
    re.compile(r"\busage share\b"),
    re.compile(r"\badoption rate\b"),
    re.compile(r"\bcustomer count\b"),
)


def eligible_action_refs(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item.get("decision") in {"selected_core", "selected_watch"} and item.get("editorial_tier") in {"core", "watch"}
    ]


def _report_headlines(report: dict[str, Any], section_name: str) -> set[str]:
    section = report.get("sections", {}).get(section_name, {})
    return {item.get("headline", "") for item in section.get("items", [])}


def validate_action_item_references(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    action_items = report.get("sections", {}).get("action_items", {}).get("items", [])
    for index, item in enumerate(action_items):
        refs = item.get("references")
        if not refs:
            errors.append(f"action_items[{index}] missing references")
            continue
        for ref in refs:
            section_name = ref.get("section")
            if section_name not in {"frontier_models", "coding_agents", "general_agents"}:
                errors.append(f"action_items[{index}] reference has invalid section {section_name!r}")
                continue
            if ref.get("editorial_tier") not in {"core", "watch"}:
                errors.append(f"action_items[{index}] reference {ref.get('headline', '')!r} is not core/watch")
                continue
            if ref.get("headline") not in _report_headlines(report, section_name):
                errors.append(f"action_items[{index}] reference headline {ref.get('headline', '')!r} not found in {section_name}")
    return errors


def validate_candidate_ledger_alignment(report: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    ledger_items = ledger.get("items", [])

    expected = {
        (item.get("proposed_section"), item.get("headline")): item
        for item in ledger_items
        if item.get("decision") in {"selected_core", "selected_watch", "selected_unverified"}
    }

    for section_name in ("frontier_models", "coding_agents", "general_agents"):
        for item in report.get("sections", {}).get(section_name, {}).get("items", []):
            key = (section_name, item.get("headline"))
            if key not in expected:
                errors.append(f"{section_name} headline {item.get('headline', '')!r} missing from candidate ledger")
    for item in report.get("sections", {}).get("unverified", {}).get("items", []):
        key = ("unverified", item.get("headline"))
        if key not in expected:
            errors.append(f"unverified headline {item.get('headline', '')!r} missing from candidate ledger")

    return errors


def validate_source_closure(report: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    indexed = {
        (item.get("proposed_section"), item.get("headline")): item
        for item in ledger.get("items", [])
    }

    for section_name in ("frontier_models", "coding_agents", "general_agents"):
        for item in report.get("sections", {}).get(section_name, {}).get("items", []):
            key = (section_name, item.get("headline"))
            record = indexed.get(key)
            if not record or not record.get("source_attempt_refs"):
                errors.append(f"{section_name} headline {item.get('headline', '')!r} lacks source_attempt_refs in ledger")
    return errors


def validate_fetch_status_integrity(report: dict[str, Any], whitelist: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    fetch_status = report.get("fetch_status", {})
    source_details = fetch_status.get("source_details", {})
    advisory_surfaces = set(required_source_family_names(whitelist))

    for missing_name in missing_fetch_status_coverage(report, whitelist):
        if missing_name in advisory_surfaces:
            continue
        errors.append(f"fetch_status.source_details missing {missing_name}")

    for name, detail in source_details.items():
        if not isinstance(detail.get("final_layer_index"), int):
            errors.append(f"fetch_status.source_details[{name}] missing final_layer_index")
        if not detail.get("final_layer_type"):
            errors.append(f"fetch_status.source_details[{name}] missing final_layer_type")
        attempts = detail.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            errors.append(f"fetch_status.source_details[{name}] missing attempts")
            continue
        for index, attempt in enumerate(attempts):
            if attempt.get("reason") == "pending discovery":
                errors.append(f"fetch_status.source_details[{name}].attempts[{index}] still pending discovery")
            for field in ("layer_index", "layer_type", "target", "result"):
                if field not in attempt:
                    errors.append(f"fetch_status.source_details[{name}].attempts[{index}] missing {field}")
    return errors


def validate_source_attempt_refs(report: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    source_details = report.get("fetch_status", {}).get("source_details", {})
    pattern = re.compile(r"^(?P<source>.+)\.attempts\[(?P<index>\d+)\]$")

    for item_index, item in enumerate(ledger.get("items", [])):
        refs = item.get("source_attempt_refs")
        if not refs:
            errors.append(f"candidate_ledger.items[{item_index}] missing source_attempt_refs")
            continue
        for ref in refs:
            match = pattern.match(ref or "")
            if not match:
                errors.append(f"candidate_ledger.items[{item_index}] has invalid source_attempt_ref {ref!r}")
                continue
            source_name = match.group("source")
            attempt_index = int(match.group("index"))
            attempts = source_details.get(source_name, {}).get("attempts", [])
            if attempt_index >= len(attempts):
                errors.append(f"candidate_ledger.items[{item_index}] source_attempt_ref {ref!r} cannot be resolved")
    return errors


def _schema_error_path(path_parts: Any) -> str:
    location = "candidate_ledger"
    for part in path_parts:
        if isinstance(part, int):
            location += f"[{part}]"
        else:
            location += f".{part}"
    return location


def validate_candidate_ledger_schema(ledger: dict[str, Any]) -> list[str]:
    schema_path = SKILL_ROOT / "schemas" / "candidate_ledger.schema.json"
    schema = _read_json(schema_path)
    validator = Draft202012Validator(schema)
    errors = []
    for error in sorted(validator.iter_errors(ledger), key=lambda item: list(item.path)):
        errors.append(f"{_schema_error_path(error.path)} schema error: {error.message}")
    return errors


def validate_candidate_ledger_semantics(ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, item in enumerate(ledger.get("items", [])):
        decision = item.get("decision")
        date_basis = item.get("date_basis")
        evidence_path = item.get("evidence_path")
        action_eligibility = item.get("action_eligibility")
        label = f"candidate_ledger.items[{index}] {item.get('headline', '')!r}"

        if decision in {"selected_core", "selected_watch"} and date_basis == "page_updated_at":
            errors.append(f"{label} date_basis=page_updated_at cannot support {decision}")
        if decision == "selected_core" and evidence_path != "primary":
            errors.append(f"{label} selected_core requires evidence_path='primary'")
        if decision == "selected_unverified" and action_eligibility != "none":
            errors.append(f"{label} selected_unverified must have action_eligibility='none'")
        if (
            decision in {"selected_core", "selected_watch", "selected_unverified"}
            and evidence_path in {"media_only", "community_snapshot", "search_only"}
            and action_eligibility != "none"
        ):
            errors.append(f"{label} evidence_path={evidence_path!r} cannot have action_eligibility={action_eligibility!r}")
        if (
            decision in {"selected_core", "selected_watch", "selected_unverified"}
            and evidence_path == "media_plus_official_one_hop"
            and action_eligibility == "full_action"
        ):
            errors.append(f"{label} evidence_path={evidence_path!r} cannot have action_eligibility='full_action'")
    return errors


def validate_major_event_consistency(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section_name in DAILY_REFERENCE_SECTIONS:
        for index, item in enumerate(report.get("sections", {}).get(section_name, {}).get("items", [])):
            label = f"{section_name}[{index}]"
            is_major = bool(item.get("major_event"))
            expanded = item.get("expanded")
            if expanded and not is_major:
                errors.append(f"{label} has expanded block but major_event is not true")
            if not is_major:
                continue
            if not expanded:
                errors.append(f"{label} major_event=true requires expanded block")
            if item.get("editorial_tier") != "core":
                errors.append(f"{label} major_event=true requires editorial_tier='core'")
            if not item.get("tracking_ref"):
                errors.append(f"{label} major_event=true requires tracking_ref")
    return errors


def validate_decision_radar(report: dict[str, Any], profile: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    counts = _daily_item_counts(report)
    known_decisions = {
        str(decision.get("name", ""))
        for decision in (profile or {}).get("decisions_in_flight", [])
        if decision.get("name")
    }
    radar = report.get("sections", {}).get("decision_radar", {})
    for group_index, group in enumerate(radar.get("decisions", [])):
        label = f"decision_radar.decisions[{group_index}]"
        name = group.get("decision_name", "")
        if known_decisions and name not in known_decisions:
            errors.append(f"{label} decision_name {name!r} not found in profile decisions_in_flight")
        for item_index, item in enumerate(group.get("items", [])):
            errors.extend(_validate_item_ref(f"{label}.items[{item_index}].ref", item.get("ref", ""), counts))
    return errors


def _join_text(values: list[Any]) -> str:
    return " ".join(str(value) for value in values if value)


def _has_hard_data_signal(item: dict[str, Any], fields: tuple[str, ...]) -> bool:
    text = _join_text([item.get(field, "") for field in fields]).lower()
    return any(keyword in text for keyword in HARD_DATA_KEYWORDS) or any(pattern.search(text) for pattern in HARD_DATA_PATTERNS)


def _explicit_hard_data_note(item: dict[str, Any]) -> str:
    return str(item.get("hard_data_note") or item.get("market_signal_note") or "").strip()


def _market_signal_refs(report: dict[str, Any]) -> set[str]:
    refs: set[str] = set()
    market_signals = report.get("sections", {}).get("market_signals", {})
    for item in market_signals.get("benchmark_watch", []):
        ref = item.get("ref")
        if ref:
            refs.add(ref)
    for item in market_signals.get("capability_gaps", []):
        ref = item.get("ref")
        if ref:
            refs.add(ref)
    for item in market_signals.get("adoption_signals", []):
        ref = item.get("ref")
        if ref:
            refs.add(ref)
    return refs


def _market_signal_entities(report: dict[str, Any]) -> set[str]:
    entities: set[str] = set()
    market_signals = report.get("sections", {}).get("market_signals", {})
    for bucket_name in ("benchmark_changes", "benchmark_watch", "pricing_changes"):
        for item in market_signals.get(bucket_name, []):
            for key in ("vendor", "model"):
                value = str(item.get(key, "")).strip().lower()
                if value:
                    entities.add(value)
    for item in market_signals.get("adoption_signals", []):
        for key in ("vendor", "product"):
            value = str(item.get(key, "")).strip().lower()
            if value:
                entities.add(value)
    return entities


def _matches_market_signals(report: dict[str, Any], ref: str, item: dict[str, Any], identity_fields: tuple[str, ...]) -> bool:
    if ref in _market_signal_refs(report):
        return True
    entities = _market_signal_entities(report)
    text = _join_text([item.get(field, "") for field in identity_fields]).lower()
    return any(entity in text for entity in entities if entity)


def _daily_hard_data_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    field_map = {
        "frontier_models": ("headline", "summary", "impact", "evidence_quote"),
        "coding_agents": ("headline", "summary", "impact", "evidence_quote"),
        "general_agents": ("headline", "summary", "heat_signal", "evidence_quote"),
    }
    identity_map = {
        "frontier_models": ("vendor", "headline", "summary"),
        "coding_agents": ("product", "headline", "summary"),
        "general_agents": ("product", "vendor", "headline", "summary"),
    }
    for section_name, fields in field_map.items():
        for index, item in enumerate(report.get("sections", {}).get(section_name, {}).get("items", [])):
            if not _has_hard_data_signal(item, fields):
                continue
            candidates.append(
                {
                    "section": section_name,
                    "index": index,
                    "ref": f"{section_name}[{index}]",
                    "headline": item.get("headline", ""),
                    "source_name": item.get("source_name", ""),
                    "identity_fields": identity_map[section_name],
                    "item": item,
                    "note": _explicit_hard_data_note(item),
                }
            )
    return candidates


def _weekly_hard_data_candidates(report: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    frontier = report.get("sections", {}).get("frontier_models", {}).get("vendor_groups", [])
    for index, item in enumerate(frontier):
        if _has_hard_data_signal(item, ("weekly_changes", "trend_judgment", "implication")):
            candidates.append(
                {
                    "section": "frontier_models",
                    "index": index,
                    "ref": f"frontier_models[{index}]",
                    "headline": item.get("vendor", ""),
                    "source_name": "weekly_frontier_models",
                    "identity_fields": ("vendor", "weekly_changes", "trend_judgment"),
                    "item": item,
                    "note": _explicit_hard_data_note(item),
                }
            )
    coding = report.get("sections", {}).get("coding_agents", {}).get("product_groups", [])
    for index, item in enumerate(coding):
        if _has_hard_data_signal(item, ("weekly_changes", "trend_judgment", "implication")):
            candidates.append(
                {
                    "section": "coding_agents",
                    "index": index,
                    "ref": f"coding_agents[{index}]",
                    "headline": item.get("product", ""),
                    "source_name": "weekly_coding_agents",
                    "identity_fields": ("product", "weekly_changes", "trend_judgment"),
                    "item": item,
                    "note": _explicit_hard_data_note(item),
                }
            )
    general_index = 0
    general = report.get("sections", {}).get("general_agents", {})
    for bucket_name in ("newcomers", "big_lab_moves"):
        for item in general.get(bucket_name, []):
            if _has_hard_data_signal(item, ("headline",)):
                candidates.append(
                    {
                        "section": "general_agents",
                        "index": general_index,
                        "ref": f"general_agents[{general_index}]",
                        "headline": item.get("headline", ""),
                        "source_name": bucket_name,
                        "identity_fields": ("product", "vendor", "headline"),
                        "item": item,
                        "note": _explicit_hard_data_note(item),
                    }
                )
            general_index += 1
    return candidates


def market_signal_consistency_findings(report: dict[str, Any], target_kind: str) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if target_kind == "daily":
        candidates = _daily_hard_data_candidates(report)
    else:
        candidates = _weekly_hard_data_candidates(report)

    for candidate in candidates:
        if _matches_market_signals(report, candidate["ref"], candidate["item"], candidate["identity_fields"]):
            continue
        note = candidate["note"]
        if note:
            findings.append(
                {
                    "category": "downgraded_evidence",
                    "severity": "medium",
                    "headline": candidate["headline"],
                    "section": candidate["section"],
                    "source_name": candidate["source_name"],
                    "source_attempt_refs": [],
                    "reason": f"正文出现 hard-data 信号，但已显式降级说明未入 market_signals：{note}",
                    "suggested_fix": "若后续补齐榜单/定价证据，可转写到 market_signals；否则保留降级说明。",
                }
            )
            continue
        findings.append(
            {
                "category": "hard_data_gap",
                "severity": "high",
                "headline": candidate["headline"],
                "section": candidate["section"],
                "source_name": candidate["source_name"],
                "source_attempt_refs": [],
                "reason": "正文已出现 benchmark/leaderboard/pricing 一类硬信号，但 market_signals 未给出对应条目或显式降级说明。",
                "suggested_fix": "补写 benchmark_watch / benchmark_changes / pricing_changes / capability_gaps，或在条目上加 hard_data_note 说明为何不入 hard-data。",
            }
        )
    return findings


def _daily_item_counts(report: dict[str, Any]) -> dict[str, int]:
    sections = report.get("sections", {})
    return {
        "frontier_models": len(sections.get("frontier_models", {}).get("items", [])),
        "coding_agents": len(sections.get("coding_agents", {}).get("items", [])),
        "general_agents": len(sections.get("general_agents", {}).get("items", [])),
    }


def _validate_item_ref(label: str, ref: str, counts: dict[str, int]) -> list[str]:
    match = ITEM_REF_PATTERN.match(ref or "")
    if not match:
        return [f"{label} has invalid itemRef {ref!r}"]
    section_name = match.group("section")
    item_index = int(match.group("index"))
    if item_index >= counts[section_name]:
        return [f"{label} points past {section_name}[{item_index}]"]
    return []


def validate_daily_market_signal_refs(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    counts = _daily_item_counts(report)
    market_signals = report.get("sections", {}).get("market_signals", {})

    for index, item in enumerate(market_signals.get("benchmark_watch", [])):
        ref = item.get("ref")
        if not ref:
            errors.append(f"benchmark_watch[{index}].ref missing")
            continue
        errors.extend(_validate_item_ref(f"benchmark_watch[{index}].ref", ref, counts))

    for index, item in enumerate(market_signals.get("capability_gaps", [])):
        ref = item.get("ref")
        text = _join_text([item.get("text", ""), item.get("evidence", "")])
        if ref:
            errors.extend(_validate_item_ref(f"capability_gaps[{index}].ref", ref, counts))
            continue
        if _has_hard_data_signal({"text": text}, ("text",)):
            errors.append(f"capability_gaps[{index}] has hard-data language but no ref")
    for index, item in enumerate(market_signals.get("adoption_signals", [])):
        ref = item.get("ref")
        if not ref:
            continue
        errors.extend(_validate_item_ref(f"adoption_signals[{index}].ref", ref, counts))
    return errors


def validate_market_signals_consistency(report: dict[str, Any], target_kind: str) -> list[str]:
    errors: list[str] = []
    for finding in market_signal_consistency_findings(report, target_kind):
        if finding["category"] != "hard_data_gap":
            continue
        errors.append(
            f"{finding['section']} headline {finding['headline']!r} has hard-data signal without market_signals coverage"
        )
    return errors


def validate_recall_probe_coverage(report: dict[str, Any], whitelist: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for finding in recall_probe_findings(report, whitelist):
        if finding.get("severity") != "high":
            continue
        source_name = finding.get("source_name") or RECALL_PROBE_SURFACE_NAME
        errors.append(f"{source_name}: {finding.get('reason', '')}")
    return errors


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _weekly_item_counts(report: dict[str, Any]) -> dict[str, int]:
    sections = report.get("sections", {})
    general = sections.get("general_agents", {})
    return {
        "frontier_models": len(sections.get("frontier_models", {}).get("vendor_groups", [])),
        "coding_agents": len(sections.get("coding_agents", {}).get("product_groups", [])),
        "general_agents": len(general.get("newcomers", [])) + len(general.get("big_lab_moves", [])),
    }


def _expected_rolling_week_dates(week_end: str) -> list[str]:
    end = datetime.fromisoformat(week_end).date()
    return [(end - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def validate_weekly_source_days(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    week_end = report.get("week_end")
    if not week_end:
        return ["weekly report missing week_end"]

    try:
        expected_days = _expected_rolling_week_dates(week_end)
    except ValueError as exc:
        return [f"weekly report has invalid week_end {week_end!r}: {exc}"]

    source_days = report.get("source_days", {})
    daily_reports_used = source_days.get("daily_reports_used", [])
    backfilled = source_days.get("backfilled", [])

    if len(daily_reports_used) != len(expected_days):
        errors.append(f"source_days.daily_reports_used must contain 7 dates ending {week_end}")
    if len(set(daily_reports_used)) != len(daily_reports_used):
        errors.append("source_days.daily_reports_used contains duplicate dates")
    if set(daily_reports_used) != set(expected_days):
        errors.append(f"source_days.daily_reports_used must be the 7 days ending {week_end}")
    if not set(backfilled).issubset(set(daily_reports_used)):
        errors.append("source_days.backfilled must be a subset of daily_reports_used")
    return errors


def _iter_weekly_item_refs(report: dict[str, Any]) -> list[tuple[str, str]]:
    refs: list[tuple[str, str]] = []
    market_signals = report.get("sections", {}).get("market_signals", {})
    for index, item in enumerate(market_signals.get("benchmark_watch", [])):
        ref = item.get("ref")
        if ref:
            refs.append((f"sections.market_signals.benchmark_watch[{index}].ref", ref))
    for index, item in enumerate(market_signals.get("capability_gaps", [])):
        ref = item.get("ref")
        if ref:
            refs.append((f"sections.market_signals.capability_gaps[{index}].ref", ref))
    for index, item in enumerate(market_signals.get("adoption_signals", [])):
        ref = item.get("ref")
        if ref:
            refs.append((f"sections.market_signals.adoption_signals[{index}].ref", ref))

    for obs_index, item in enumerate(report.get("sections", {}).get("pattern_observations", {}).get("items", [])):
        for ref_index, ref in enumerate(item.get("supporting_item_refs", [])):
            refs.append((f"sections.pattern_observations.items[{obs_index}].supporting_item_refs[{ref_index}]", ref))

    for exp_index, item in enumerate(report.get("sections", {}).get("experiments_this_week", {}).get("items", [])):
        for ref_index, ref in enumerate(item.get("related_item_refs", [])):
            refs.append((f"sections.experiments_this_week.items[{exp_index}].related_item_refs[{ref_index}]", ref))
    return refs


def validate_weekly_item_refs(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    counts = _weekly_item_counts(report)

    for label, ref in _iter_weekly_item_refs(report):
        match = ITEM_REF_PATTERN.match(ref or "")
        if not match:
            errors.append(f"{label} has invalid itemRef {ref!r}")
            continue
        section_name = match.group("section")
        item_index = int(match.group("index"))
        if item_index >= counts[section_name]:
            errors.append(f"{label} points past {section_name}[{item_index}]")
    return errors


def _load_weekly_daily_index(
    report: dict[str, Any],
    project_root: Path,
) -> tuple[dict[tuple[str, str, str], dict[str, Any]], list[str], set[str]]:
    errors: list[str] = []
    index: dict[tuple[str, str, str], dict[str, Any]] = {}
    source_days = report.get("source_days", {})
    ordered_days: list[str] = []
    for key in ("daily_reports_used", "backfilled"):
        for day in source_days.get(key, []):
            if day not in ordered_days:
                ordered_days.append(day)

    for day in ordered_days:
        report_path = project_root / "cache" / day / "report.json"
        if not report_path.exists():
            errors.append(f"source_days daily report missing: cache/{day}/report.json")
            continue
        try:
            daily_report = _read_json(report_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"failed to load cache/{day}/report.json: {exc}")
            continue
        if daily_report.get("type") != "daily":
            errors.append(f"cache/{day}/report.json is not a daily report")
            continue
        if daily_report.get("date") != day:
            errors.append(f"cache/{day}/report.json has mismatched date {daily_report.get('date')!r}")
            continue

        sections = daily_report.get("sections", {})
        for section_name in DAILY_REFERENCE_SECTIONS:
            for item in sections.get(section_name, {}).get("items", []):
                headline = item.get("headline")
                if headline:
                    index[(day, section_name, headline)] = item

    return index, errors, set(ordered_days)


def _iter_weekly_reference_lists(report: dict[str, Any]) -> list[tuple[str, list[dict[str, Any]]]]:
    refs: list[tuple[str, list[dict[str, Any]]]] = []
    frontier = report.get("sections", {}).get("frontier_models", {}).get("vendor_groups", [])
    coding = report.get("sections", {}).get("coding_agents", {}).get("product_groups", [])
    actions = report.get("sections", {}).get("action_items", {}).get("items", [])

    for index, group in enumerate(frontier):
        refs.append((f"sections.frontier_models.vendor_groups[{index}]", group.get("references", [])))
    for index, group in enumerate(coding):
        refs.append((f"sections.coding_agents.product_groups[{index}]", group.get("references", [])))
    for index, group in enumerate(actions):
        refs.append((f"sections.action_items.items[{index}]", group.get("references", [])))
    return refs


def validate_weekly_references(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    index, load_errors, declared_days = _load_weekly_daily_index(report, project_root)
    errors.extend(load_errors)

    comparable_fields = ("release_stage", "published_at_confidence", "authority_score", "evidence_quote")
    for label, refs in _iter_weekly_reference_lists(report):
        if not refs:
            errors.append(f"{label} missing references")
            continue
        for ref_index, ref in enumerate(refs):
            date = ref.get("date")
            section_name = ref.get("section")
            headline = ref.get("headline")
            if not date or not section_name or not headline:
                errors.append(f"{label}.references[{ref_index}] missing date/section/headline")
                continue
            if date not in declared_days:
                errors.append(f"{label}.references[{ref_index}] date {date!r} not listed in source_days")
                continue

            resolved = index.get((date, section_name, headline))
            if not resolved:
                errors.append(f"{label}.references[{ref_index}] cannot resolve {date} {section_name} {headline!r}")
                continue

            if resolved.get("editorial_tier") != ref.get("editorial_tier"):
                errors.append(
                    f"{label}.references[{ref_index}] editorial_tier {ref.get('editorial_tier')!r} "
                    f"does not match daily report {resolved.get('editorial_tier')!r}"
                )
            if ref.get("url") and resolved.get("source_url") and ref.get("url") != resolved.get("source_url"):
                errors.append(f"{label}.references[{ref_index}] url does not match daily report source_url")
            for field_name in comparable_fields:
                if field_name in ref and ref.get(field_name) != resolved.get(field_name):
                    errors.append(
                        f"{label}.references[{ref_index}] {field_name} {ref.get(field_name)!r} "
                        f"does not match daily report {resolved.get(field_name)!r}"
                    )
    return errors


def validate_practice_digest(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    items = report.get("sections", {}).get("practice_digest", {}).get("items", [])
    if not items:
        return errors

    declared_days = set(report.get("source_days", {}).get("daily_reports_used", []))
    for index, item in enumerate(items):
        label = f"practice_digest.items[{index}]"
        origin = item.get("origin", {})
        date = str(origin.get("date", ""))
        title = origin.get("title", "")
        if date not in declared_days:
            errors.append(f"{label} origin date {date!r} not listed in source_days")
            continue
        daily_path = project_root / "cache" / date / "report.json"
        if not daily_path.exists():
            errors.append(f"{label} origin daily report missing: cache/{date}/report.json")
            continue
        try:
            daily = _read_json(daily_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label} cannot load cache/{date}/report.json: {exc}")
            continue
        eco_titles = {
            eco.get("title", "")
            for eco in daily.get("sections", {}).get("agent_ecosystem", {}).get("items", [])
        }
        if title not in eco_titles:
            errors.append(f"{label} origin title {title!r} not found in {date} agent_ecosystem")
    return errors


def validate_weekly_artifacts(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_weekly_source_days(report))
    errors.extend(validate_weekly_item_refs(report))
    errors.extend(validate_weekly_references(report, project_root))
    errors.extend(validate_practice_digest(report, project_root))
    errors.extend(validate_market_signals_consistency(report, "weekly"))
    return errors


def validate_daily_artifacts(
    report: dict[str, Any],
    ledger: dict[str, Any],
    whitelist: dict[str, Any],
    project_root: Path | None = None,
    profile: dict[str, Any] | None = None,
) -> list[str]:
    errors: list[str] = []
    errors.extend(validate_candidate_ledger_schema(ledger))
    errors.extend(validate_fetch_status_integrity(report, whitelist))
    errors.extend(validate_source_attempt_refs(report, ledger))
    errors.extend(validate_candidate_ledger_semantics(ledger))
    errors.extend(validate_action_item_references(report))
    errors.extend(validate_candidate_ledger_alignment(report, ledger))
    errors.extend(validate_source_closure(report, ledger))
    errors.extend(validate_daily_market_signal_refs(report))
    errors.extend(validate_market_signals_consistency(report, "daily"))
    errors.extend(validate_recall_probe_coverage(report, whitelist))
    errors.extend(validate_major_event_consistency(report))
    errors.extend(validate_decision_radar(report, profile))
    if project_root is not None:
        errors.extend(validate_tracking_refs(report, project_root))
        errors.extend(
            validate_ecosystem_repeats(report, load_seen_repos(project_root), str(report.get("date", "")))
        )
    return errors


def _qa_summary(findings: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(finding["category"] for finding in findings)
    return {
        "total_findings": len(findings),
        "blocking_findings": sum(1 for finding in findings if finding.get("severity") == "high"),
        "categories": {name: counts.get(name, 0) for name in QA_CATEGORIES},
    }


def _dedupe_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for finding in findings:
        key = (
            finding.get("category", ""),
            finding.get("headline", ""),
            finding.get("section", ""),
            finding.get("source_name", ""),
            finding.get("reason", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def _make_finding(
    category: str,
    severity: str,
    reason: str,
    *,
    headline: str = "",
    section: str = "",
    source_name: str = "",
    source_attempt_refs: list[str] | None = None,
    suggested_fix: str = "",
) -> dict[str, Any]:
    return {
        "category": category,
        "severity": severity,
        "headline": headline,
        "section": section,
        "source_name": source_name,
        "source_attempt_refs": source_attempt_refs or [],
        "reason": reason,
        "suggested_fix": suggested_fix,
    }


def recall_probe_findings(report: dict[str, Any], whitelist: dict[str, Any]) -> list[dict[str, Any]]:
    probe_queries = whitelist.get("recall_probe_queries", [])
    if not probe_queries:
        return []

    source_details = report.get("fetch_status", {}).get("source_details", {})
    if RECALL_PROBE_SURFACE_NAME not in source_details:
        return []

    probe_detail = source_details.get(RECALL_PROBE_SURFACE_NAME, {})
    attempts = probe_detail.get("attempts", [])
    if not attempts:
        return [
            _make_finding(
                "missed_discovery",
                "high",
                f"recall_probe_queries 已配置，但 {RECALL_PROBE_SURFACE_NAME} 没有记录任何 attempt。",
                source_name=RECALL_PROBE_SURFACE_NAME,
                suggested_fix="运行 recall_probe_queries，并把搜索结果或空结果写入 fetch_status.source_details。",
            )
        ]

    attempted_targets = " ".join(str(attempt.get("target", "")) for attempt in attempts)
    date = str(report.get("date", ""))
    yesterday = ""
    if date:
        try:
            yesterday = (datetime.fromisoformat(date) - timedelta(days=1)).date().isoformat()
        except ValueError:
            yesterday = ""
    replacements = {
        "{date}": date,
        "{yesterday}": yesterday,
    }
    query_variants = set()
    for query in probe_queries:
        query_variants.add(query)
        for placeholder, value in replacements.items():
            if value:
                for variant in list(query_variants):
                    query_variants.add(variant.replace(placeholder, value))

    if "recall_probe_queries" not in attempted_targets and not any(query in attempted_targets for query in query_variants):
        return [
            _make_finding(
                "missed_discovery",
                "high",
                f"{RECALL_PROBE_SURFACE_NAME} 未指向 recall_probe_queries 或具体 probe query。",
                source_name=RECALL_PROBE_SURFACE_NAME,
                suggested_fix="把 recall_probe_queries 的执行摘要写入该 surface 的 attempts。",
            )
        ]
    return []


def build_daily_qa_diff(report: dict[str, Any], ledger: dict[str, Any], whitelist: dict[str, Any]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    source_details = report.get("fetch_status", {}).get("source_details", {})

    for name in missing_fetch_status_coverage(report, whitelist):
        findings.append(
            _make_finding(
                "missed_discovery",
                "high",
                "fetch_status.source_details 缺少该 discovery surface。",
                source_name=name,
                suggested_fix="补写该 surface 的 source_details 和 attempts，避免 finalize 前静默漏面。",
            )
        )
    for name, detail in source_details.items():
        for attempt in detail.get("attempts", []):
            if attempt.get("reason") == "pending discovery":
                findings.append(
                    _make_finding(
                        "missed_discovery",
                        "high",
                        "存在仍为 pending discovery 的抓取尝试。",
                        source_name=name,
                        suggested_fix="在 report.json 落盘前补齐该 attempt 的最终结果。",
                    )
                )
    findings.extend(recall_probe_findings(report, whitelist))

    for item in ledger.get("items", []):
        decision = item.get("decision")
        category = ""
        severity = "medium"
        if decision == "rejected_duplicate":
            category = "duplicate_rejected"
            severity = "low"
        elif decision == "rejected_weak_evidence":
            category = "weak_evidence_rejected"
        elif decision == "selected_unverified":
            category = "downgraded_evidence"
        if not category:
            continue
        findings.append(
            _make_finding(
                category,
                severity,
                str(item.get("decision_reason", "")).strip() or f"candidate ledger decision={decision}",
                headline=str(item.get("headline", "")),
                section=str(item.get("proposed_section", "")),
                source_attempt_refs=list(item.get("source_attempt_refs", [])),
                suggested_fix="若判断有误，优先调整证据闭环与 decision_reason，而不是直接改正文排序。",
            )
        )

    reference_errors = []
    reference_errors.extend(validate_candidate_ledger_schema(ledger))
    reference_errors.extend(validate_source_attempt_refs(report, ledger))
    reference_errors.extend(validate_candidate_ledger_semantics(ledger))
    reference_errors.extend(validate_action_item_references(report))
    reference_errors.extend(validate_candidate_ledger_alignment(report, ledger))
    reference_errors.extend(validate_daily_market_signal_refs(report))
    reference_errors.extend(validate_source_closure(report, ledger))
    for error in reference_errors:
        findings.append(
            _make_finding(
                "reference_integrity_gap",
                "high",
                error,
                suggested_fix="修复正文、candidate_ledger 与 action references 的闭环一致性。",
            )
        )

    findings.extend(market_signal_consistency_findings(report, "daily"))
    findings = _dedupe_findings(findings)
    return {
        "type": "qa_diff",
        "target_kind": "daily",
        "target_id": report.get("date", ""),
        "generated_at": report.get("generated_at", ""),
        "summary": _qa_summary(findings),
        "findings": findings,
    }


def build_weekly_qa_diff(report: dict[str, Any], project_root: Path) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    reference_errors = []
    reference_errors.extend(validate_weekly_source_days(report))
    reference_errors.extend(validate_weekly_item_refs(report))
    reference_errors.extend(validate_weekly_references(report, project_root))
    reference_errors.extend(validate_practice_digest(report, project_root))
    for error in reference_errors:
        findings.append(
            _make_finding(
                "reference_integrity_gap",
                "high",
                error,
                suggested_fix="修复 source_days、weekly item refs 或 daily backing reports 的引用闭环。",
            )
        )
    findings.extend(market_signal_consistency_findings(report, "weekly"))
    findings = _dedupe_findings(findings)
    return {
        "type": "qa_diff",
        "target_kind": "weekly",
        "target_id": report.get("week_end", ""),
        "generated_at": report.get("generated_at", ""),
        "summary": _qa_summary(findings),
        "findings": findings,
    }
