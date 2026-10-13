"""Versioned structural contracts. Semantic classification remains an AI decision."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from evidence import validate_evidence_reviews

from report_contract import (decision_sections, product_sections, has_editorial_contract,
                             uses_agent_taxonomy, expected_ledger_version)
ACTION_TYPES = {
    "none": set(), "monitor": {"monitor"}, "experiment": {"monitor", "experiment"},
    "full_action": {"patch", "experiment", "adopt", "migrate", "monitor", "hire"},
}
SELECTED = {"selected_core", "selected_watch", "selected_unverified"}


def validate_batch_version(report: dict[str, Any], manifest: dict[str, Any] | None) -> list[str]:
    expected = manifest.get("expected_report_version") if manifest else None
    if expected and report.get("version") != expected:
        return [f"batch version requires {expected}, got {report.get('version')}"]
    new = has_editorial_contract(report)
    if new and not expected:
        return ["new report requires an initialized version-locked manifest"]
    return []


def validate_report_schema(report: dict[str, Any]) -> list[str]:
    kind = report.get("type")
    if kind not in {"daily", "weekly"}:
        return ["report type must be daily or weekly"]
    path = Path(__file__).resolve().parent.parent / "schemas" / f"{kind}_report.schema.json"
    validator = Draft202012Validator(json.loads(path.read_text(encoding="utf-8")))
    return [f"report schema {'.'.join(map(str, error.path))}: {error.message}"
            for error in validator.iter_errors(report)]


def validate_candidate_contract(report: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    if not has_editorial_contract(report):
        return []
    errors = []
    if ledger.get("version") != expected_ledger_version(report):
        errors.append(f"classification: daily {report.get('version')} requires candidate ledger {expected_ledger_version(report)}")
    if ledger.get("date") != report.get("date"):
        errors.append("classification: report and ledger dates must match")
    selected = {}
    ids = set()
    attempts = report.get("fetch_status", {}).get("source_details", {})
    for candidate in ledger.get("items", []):
        key = (candidate.get("proposed_section"), candidate.get("headline"))
        label = f"classification: {key}"
        cid = candidate.get("candidate_id")
        if cid in ids:
            errors.append(f"{label} duplicate candidate_id")
        ids.add(cid)
        if key[0] in {"general_agents", "vertical_agents"} and candidate.get("subject_kind") not in {"product", "capability", "platform"}:
            errors.append(f"{label} Agent section requires a product/capability/platform subject")
        if candidate.get("decision") in SELECTED:
            if key in selected:
                errors.append(f"{label} duplicate selected candidate")
            selected[key] = candidate
            expected_tier = candidate["decision"].removeprefix("selected_")
            if candidate.get("editorial_tier") != expected_tier:
                errors.append(f"{label} selected decision and editorial tier disagree")
            if (key[0] == "unverified") != (expected_tier == "unverified"):
                errors.append(f"{label} unverified decision must use unverified section")
            if expected_tier != "unverified" and not any(c.get("direct_attempt_refs") for c in candidate.get("claim_support", [])):
                errors.append(f"claim_support: {key} selected news needs direct support for at least one key claim")
        used = set(candidate.get("source_attempt_refs", []))
        for claim in candidate.get("claim_support", []):
            direct = set(claim.get("direct_attempt_refs", []))
            background = set(claim.get("background_attempt_refs", []))
            if not (direct | background) <= used or direct & background:
                errors.append(f"claim_support: {key} references must be disjoint subsets of source_attempt_refs")
            if not direct and not claim.get("unresolved_questions"):
                errors.append(f"claim_support: {key} lacks direct evidence and an explicit unresolved question")
            for ref in direct:
                match = re.fullmatch(r"(.+)\.attempts\[(\d+)\]", ref)
                values = attempts.get(match[1], {}).get("attempts", []) if match else []
                attempt = values[int(match[2])] if match and int(match[2]) < len(values) else {}
                if attempt.get("result") != "success" or attempt.get("review", {}).get("status") != "complete":
                    errors.append(f"claim_support: {key} direct evidence must be successfully retrieved and reviewed: {ref}")
    actual = {}
    dedup_keys = set()
    for section in (*decision_sections(report), "unverified"):
        for item in report.get("sections", {}).get(section, {}).get("items", []):
            key = (section, item.get("headline"))
            if key in actual:
                errors.append(f"classification: duplicate report item {key}")
            actual[key] = item
            dedup = item.get("dedup_key")
            if dedup and dedup in dedup_keys:
                errors.append(f"classification: duplicate event dedup_key {dedup}")
            if dedup:
                dedup_keys.add(dedup)
    for key in selected.keys() ^ actual.keys():
        errors.append(f"classification: selected ledger/report mismatch {key}")
    for key in selected.keys() & actual.keys():
        tier = selected[key].get("editorial_tier")
        if key[0] != "unverified" and actual[key].get("editorial_tier") != tier:
            errors.append(f"classification: ledger/report tier mismatch {key}")
    if uses_agent_taxonomy(report):
        for key in selected.keys() & actual.keys():
            if key[0] in {"general_agents", "vertical_agents"}:
                for field in ("task_domain", "capability_layer"):
                    if selected[key].get(field) != actual[key].get(field):
                        errors.append(f"classification: ledger/report {field} mismatch {key}")
    for action in report.get("sections", {}).get("action_items", {}).get("items", []):
        for ref in action.get("references", []):
            item = actual.get((ref.get("section"), ref.get("headline")), {})
            if ref.get("date") != report.get("date") or ref.get("url") != item.get("source_url"):
                errors.append("action_eligibility: reference date/url must match the actual daily item")
    errors.extend(validate_action_eligibility(report, selected))
    return errors


def validate_action_eligibility(report: dict[str, Any], selected: dict[tuple, dict]) -> list[str]:
    errors = []
    for i, action in enumerate(report.get("sections", {}).get("action_items", {}).get("items", [])):
        for ref in action.get("references", []):
            key = (ref.get("section"), ref.get("headline"))
            candidate = selected.get(key, {})
            if action.get("recommendation_type") not in ACTION_TYPES.get(candidate.get("action_eligibility"), set()):
                errors.append(f"action_eligibility: action_items[{i}] exceeds eligibility of {key}")
            if candidate.get("editorial_tier") != ref.get("editorial_tier"):
                errors.append(f"action_eligibility: action_items[{i}] reference tier mismatch {key}")
    return errors


def validate_decision_refs(report: dict[str, Any]) -> list[str]:
    new = has_editorial_contract(report)
    if not new:
        return []
    sections = report.get("sections", {})
    errors = []
    for field, refs_field, allowed in [
        ("pattern_observations", "supporting_item_refs", decision_sections(report)),
        ("experiments_this_week", "related_item_refs", product_sections(report)[1:]),
    ]:
        for i, item in enumerate(sections.get(field, {}).get("items", [])):
            refs = item.get(refs_field, [])
            if len(refs) != len(set(refs)):
                errors.append(f"{field}[{i}] duplicate references are not independent evidence")
            if field == "experiments_this_week" and not refs:
                errors.append(f"{field}[{i}] requires product references")
            for ref in refs:
                match = re.fullmatch(r"(\w+)\[(\d+)\]", ref)
                if not match or match[1] not in allowed:
                    errors.append(f"{field}[{i}] invalid reference {ref}")
                    continue
                key = "items"
                if report.get("type") == "weekly":
                    key = {"frontier_models": "vendor_groups", "coding_agents": "product_groups"}.get(match[1], "items")
                if int(match[2]) >= len(sections.get(match[1], {}).get(key, [])):
                    errors.append(f"{field}[{i}] unresolved reference {ref}")
    return errors


def validate_agent_daily(report: dict[str, Any], ledger: dict[str, Any], project_root: Path | None) -> list[str]:
    if not has_editorial_contract(report):
        return []
    from editorial import validate_candidate_ledger_schema
    schema_errors = validate_report_schema(report) + validate_candidate_ledger_schema(ledger)
    if schema_errors:
        return schema_errors
    cache_dir = project_root / "cache" / report["date"] if project_root is not None else None
    return (validate_candidate_contract(report, ledger)
            + validate_decision_refs(report) + validate_evidence_reviews(report, cache_dir))


def validate_agent_weekly(report: dict[str, Any], project_root: Path) -> list[str]:
    if not has_editorial_contract(report):
        return []
    errors = validate_report_schema(report)
    if errors:
        return errors
    errors.extend(validate_decision_refs(report))
    for section in (*product_sections(report)[1:], "policy_risk"):
        if section == "coding_agents":
            continue
        for item in report.get("sections", {}).get(section, {}).get("items", []):
            for ref in item.get("references", []):
                if ref.get("section") != section and not ref.get("origin_classification_note", "").strip():
                    errors.append(f"classification: {section} cross-section reference requires origin_classification_note")
    # Legacy evidence can be re-reviewed in an isolated bundle without rewriting
    # the delivered daily. The weekly reference still resolves against the original.
    from editorial import validate_candidate_ledger_semantics, validate_source_attempt_refs
    for i, action in enumerate(report.get("sections", {}).get("action_items", {}).get("items", [])):
        for ref in action.get("references", []):
            day = ref.get("date", "")
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
                errors.append(f"action_eligibility: weekly action {i} invalid date")
                continue
            evidence_root = project_root
            try:
                daily = json.loads((project_root / "cache" / day / "report.json").read_text(encoding="utf-8"))
                if not has_editorial_contract(daily):
                    evidence_root = project_root / "cache" / "weekly" / report["week_end"] / "evidence_reviews"
                cache = evidence_root / "cache" / day
                reviewed = json.loads((cache / "report.json").read_text(encoding="utf-8"))
                ledger = json.loads((cache / "candidate_ledger.json").read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"action_eligibility: weekly action {i} evidence re-review unavailable: {exc}")
                continue
            if not has_editorial_contract(reviewed) or reviewed.get("date") != day or ledger.get("version") != expected_ledger_version(reviewed) or ledger.get("date") != day:
                errors.append(f"action_eligibility: weekly action {i} requires dated version-matched daily / ledger evidence")
                continue
            evidence_errors = validate_agent_daily(reviewed, ledger, evidence_root)
            errors.extend(evidence_errors)
            if evidence_errors:
                continue
            errors.extend(validate_candidate_ledger_semantics(ledger))
            errors.extend(validate_source_attempt_refs(reviewed, ledger))
            matches = [(section, item) for section in decision_sections(reviewed)
                       for item in reviewed.get("sections", {}).get(section, {}).get("items", [])
                       if item.get("headline") == ref.get("headline") and item.get("source_url") == ref.get("url")]
            if len(matches) != 1:
                errors.append(f"action_eligibility: weekly action {i} cannot uniquely match re-reviewed original evidence")
                continue
            section, item = matches[0]
            if item.get("editorial_tier") != ref.get("editorial_tier"):
                errors.append(f"action_eligibility: weekly action {i} cannot upgrade original evidence tier")
            selected = {(c.get("proposed_section"), c.get("headline")): c for c in ledger.get("items", []) if c.get("decision") in SELECTED}
            single = {"sections": {"action_items": {"items": [{**action, "references": [{**ref, "section": section}]}]}}}
            errors.extend(validate_action_eligibility(single, selected))
    return errors


def validate_agent_discovery(report: dict[str, Any], manifest: dict[str, Any] | None) -> list[str]:
    """Check configured cross-domain searches were attempted, not whether news exists."""
    if not uses_agent_taxonomy(report):
        return []
    if manifest is None:
        return ["agent discovery requires the locked manifest"]
    from datetime import date, timedelta
    try:
        day = date.fromisoformat(manifest["date"])
    except (KeyError, TypeError, ValueError):
        return ["agent discovery manifest date is invalid"]
    groups = {"General Agent Search Queries": manifest.get("general_agent_search_queries", [])}
    for source in manifest.get("required_sources", []):
        if source.get("name") == "Vertical Agent Search Queries":
            groups[source["name"]] = [q for layer in source.get("fetch_chain", []) for q in layer.get("queries", [])]
    if not groups.get("General Agent Search Queries") or not groups.get("Vertical Agent Search Queries"):
        return ["agent discovery manifest must include general and vertical search queries"]
    errors = []
    details = report.get("fetch_status", {}).get("source_details", {})
    for name, queries in groups.items():
        attempted = {a.get("target") for a in details.get(name, {}).get("attempts", [])
                     if a.get("layer_type") in {"websearch_scoped", "websearch_broad"}
                     and a.get("result") in {"success", "success_but_empty", "empty", "error"}
                     and a.get("reason") != "pending discovery"}
        for query in queries:
            target = query.replace("{yesterday}", (day - timedelta(days=1)).isoformat()).replace("{date}", day.isoformat())
            if target not in attempted:
                errors.append(f"agent discovery: {name} missing query attempt: {target}")
    return errors
