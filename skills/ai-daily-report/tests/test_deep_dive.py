import json
from copy import deepcopy

import pytest
from bs4 import BeautifulSoup

from deep_dive import deep_dive_path, selected_deep_dive_slugs, validate_deep_dives
from render_html import render


def _write_deep_dive(tmp_path, payload):
    path = deep_dive_path(tmp_path, payload["date"], payload["event_slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _selected_report(payload):
    return {
        "date": payload["date"], "deep_dive_refs": [payload["event_slug"]],
        "sections": {},
        "fetch_status": {"source_details": {"Eval": {"attempts": [
            {"target": ref["url"], "result": "success"} for ref in payload["references"]
        ]}}},
    }


def test_major_event_and_stale_files_do_not_select_delivery(tmp_path, sample_deep_dive):
    report = {"date": sample_deep_dive["date"], "sections": {"frontier_models": {"items": [
        {"major_event": True, "tracking_ref": sample_deep_dive["event_slug"]}
    ]}}}
    assert validate_deep_dives(report, tmp_path) == []
    path = _write_deep_dive(tmp_path, sample_deep_dive)
    path.write_text("unfinished draft")
    assert selected_deep_dive_slugs(report) == []
    assert validate_deep_dives(report, tmp_path) == []


def test_selected_research_works_without_major_event(tmp_path, research_deep_dive):
    _write_deep_dive(tmp_path, research_deep_dive)
    assert validate_deep_dives(_selected_report(research_deep_dive), tmp_path) == []


def test_selected_missing_file_is_not_silently_skipped(tmp_path, research_deep_dive):
    errors = validate_deep_dives(_selected_report(research_deep_dive), tmp_path)
    assert any("selects missing file" in error for error in errors)


@pytest.mark.parametrize("slugs", [["../elsewhere"], ["task-routing", "task-routing"], "task-routing", [None]])
def test_invalid_selection_is_rejected_before_file_access(tmp_path, slugs):
    assert validate_deep_dives({"deep_dive_refs": slugs}, tmp_path)


@pytest.mark.parametrize("field,value", [("event_slug", "different-topic"), ("date", "2026-06-14")])
def test_selected_identity_must_match(tmp_path, research_deep_dive, field, value):
    report = _selected_report(research_deep_dive)
    path = _write_deep_dive(tmp_path, research_deep_dive)
    payload = deepcopy(research_deep_dive)
    payload[field] = value
    path.write_text(json.dumps(payload))
    assert any(field in e for e in validate_deep_dives(report, tmp_path))


def test_legacy_can_render_but_cannot_enter_new_delivery(tmp_path, sample_deep_dive):
    path = _write_deep_dive(tmp_path, sample_deep_dive)
    assert render(path).exists()
    assert any("render-only" in e for e in validate_deep_dives(_selected_report(sample_deep_dive), tmp_path))


@pytest.mark.parametrize("result", ["error", "success_but_empty"])
def test_source_needs_successful_exact_url(tmp_path, research_deep_dive, result):
    _write_deep_dive(tmp_path, research_deep_dive)
    report = _selected_report(research_deep_dive)
    report["fetch_status"]["source_details"]["Eval"]["attempts"][0]["result"] = result
    assert any("exact-URL" in e for e in validate_deep_dives(report, tmp_path))


def test_reference_cannot_use_different_url(tmp_path, research_deep_dive):
    _write_deep_dive(tmp_path, research_deep_dive)
    report = _selected_report(research_deep_dive)
    report["fetch_status"]["source_details"]["Eval"]["attempts"][0]["target"] += "/other"
    assert any("exact-URL" in e for e in validate_deep_dives(report, tmp_path))


@pytest.mark.parametrize("change", ["duplicate", "unresolved", "future", "no_timezone", "empty_comparison"])
def test_broken_research_evidence_is_rejected(tmp_path, research_deep_dive, change):
    report = _selected_report(research_deep_dive)
    if change == "duplicate":
        research_deep_dive["references"].append(deepcopy(research_deep_dive["references"][0]))
    elif change == "unresolved":
        research_deep_dive["sections"]["scenarios"][0]["reference_ids"] = ["missing"]
    elif change == "future":
        research_deep_dive["references"][0]["observed_at"] = "2026-06-14T09:00:00+08:00"
    elif change == "no_timezone":
        research_deep_dive["references"][0]["observed_at"] = "2026-06-13T09:00:00"
    else:
        research_deep_dive["sections"]["comparisons"] = []
    _write_deep_dive(tmp_path, research_deep_dive)
    assert validate_deep_dives(report, tmp_path)


def test_research_render_keeps_comparisons_boundaries_and_sources(tmp_path, research_deep_dive):
    path = _write_deep_dive(tmp_path, research_deep_dive)
    soup = BeautifulSoup(render(path).read_text(), "html.parser")
    assert "A 73%，B 65%；长任务 A -2，B 0。" in soup.table.get_text()
    assert research_deep_dive["sections"]["comparisons"][0]["conditions"] in soup.table.get_text()
    assert "场景推断" in soup.get_text()
    assert "尚未解决的问题" in soup.get_text()
    assert not soup.find("script")
    assert "<script>unsafe</script>" in soup.get_text()
    assert soup.select('a[href="https://eval.example/task-routing"]')
    assert "对四个角色" not in soup.get_text()  # New research must not restore the retired role template.
