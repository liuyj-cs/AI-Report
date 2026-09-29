"""召回守门的判据必须信 attempts 实迹，不信自报的 final_layer_index。"""
from copy import deepcopy

import pytest

from discovery import compute_daily_window, load_whitelist
from daily_time import validate_daily_time_window
from editorial import validate_core_source_failures, validate_daily_artifacts, validate_recall_fallback_coverage

NAME = "DeepSeek"


def _report(attempts, final_layer_index):
    return {
        "fetch_status": {
            "succeeded": [NAME],
            "failed": [],
            "empty": [NAME],
            "source_details": {
                NAME: {"final_layer_index": final_layer_index, "attempts": attempts}
            },
        }
    }


def _fetch_attempts(indexes):
    return [
        {"layer_index": i, "layer_type": "webfetch", "target": "x", "result": "success_but_empty"}
        for i in indexes
    ]


def test_self_declared_final_index_cannot_bypass_chain_exhaustion():
    """只抓了 L0 却自报 final_layer_index=2 —— 判据必须按 attempts 实迹判 BLOCK。"""
    whitelist = load_whitelist()

    errors = validate_recall_fallback_coverage(_report(_fetch_attempts([0]), 2), whitelist)

    assert len(errors) == 1
    assert NAME in errors[0]


def test_empty_attempts_with_declared_index_is_fail_closed():
    whitelist = load_whitelist()

    assert len(validate_recall_fallback_coverage(_report([], 2), whitelist)) == 1


def test_stale_final_index_does_not_cause_false_block():
    """实际走完了 L0-L2，只是 final_layer_index 没更新 —— 不该误报。"""
    whitelist = load_whitelist()

    assert validate_recall_fallback_coverage(_report(_fetch_attempts([0, 1, 2]), 0), whitelist) == []


def _time_payloads():
    window = compute_daily_window("2026-09-29", "2026-09-29T10:00:00+08:00")
    manifest = {"date": "2026-09-29", "window": window}
    item = {"headline": "example", "published_at": "2026-09-28T12:00:00+08:00",
            "published_at_confidence": "exact", "confidence": "high"}
    report = {"version": "1.0", "date": manifest["date"], "window": deepcopy(window),
              "sections": {"general_agents": {"items": [item]}}}
    ledger = {"date": manifest["date"], "items": [{"headline": "example", "proposed_section": "general_agents",
              "decision": "selected_core", "published_at": item["published_at"], "date_basis": "release_metadata"}]}
    return report, ledger, manifest


@pytest.mark.parametrize("precision", ["exact", "approximate", "inferred"])
@pytest.mark.parametrize("value", ["2026-09-28T07:00:00+08:00", "2026-09-29T10:00:00+08:00", "2026-09-28T04:00:00Z"])
def test_publication_time_boundaries_and_precision_are_supported(precision, value):
    report, ledger, manifest = _time_payloads()
    item = report["sections"]["general_agents"]["items"][0]
    item.update(published_at=value, published_at_confidence=precision, confidence="medium")
    ledger["items"][0]["published_at"] = value
    assert validate_daily_time_window(report, ledger, manifest) == []


@pytest.mark.parametrize("section", ["frontier_models", "coding_agents", "general_agents", "policy_risk"])
@pytest.mark.parametrize("bad_time", ["1900-01-01T08:00:00+08:00", "2026-09-28T06:59:59+08:00",
                                     "2026-09-29T10:00:01+08:00", "2026-09-28T12:00:00", "", None])
def test_selected_news_times_are_checked_even_when_report_and_ledger_agree(section, bad_time):
    report, ledger, manifest = _time_payloads()
    report["sections"][section] = report["sections"].pop("general_agents")
    report["sections"][section]["items"][0]["published_at"] = bad_time
    ledger["items"][0].update(proposed_section=section, published_at=bad_time)
    errors = validate_daily_time_window(report, ledger, manifest)
    assert any(f"{section}[0].published_at" in error for error in errors)
    assert any("candidate_ledger.items[0].published_at" in error for error in errors)


def test_equal_instants_with_different_timezone_spelling_align():
    report, ledger, manifest = _time_payloads()
    ledger["items"][0]["published_at"] = "2026-09-28T04:00:00Z"
    assert validate_daily_time_window(report, ledger, manifest) == []
    ledger["items"][0]["published_at"] = "2026-09-28T05:00:00Z"
    assert any("differs from selected" in error for error in validate_daily_time_window(report, ledger, manifest))


@pytest.mark.parametrize("value", ["2026-09-28", "2026-09-29"])
def test_date_only_preserves_uncertain_boundary_instead_of_inventing_midnight(value):
    report, ledger, manifest = _time_payloads()
    item = report["sections"]["general_agents"]["items"][0]
    item.update(published_at=value, published_at_confidence="approximate", confidence="medium")
    ledger["items"][0]["published_at"] = value
    before = deepcopy((report, ledger, manifest))
    errors = validate_daily_time_window(report, ledger, manifest)
    assert any("date-only overlaps a window boundary" in error for error in errors)
    assert (report, ledger, manifest) == before


@pytest.mark.parametrize("value", ["2026-09-27", "2026-09-30", "1900-01-01"])
def test_date_only_outside_window_is_rejected(value):
    report, ledger, manifest = _time_payloads()
    report["sections"]["general_agents"]["items"][0]["published_at"] = value
    assert any("outside locked" in error for error in validate_daily_time_window(report, ledger, manifest))


def test_inferred_date_cannot_be_promoted_by_report_confidence():
    report, ledger, manifest = _time_payloads()
    item = report["sections"]["general_agents"]["items"][0]
    item["published_at_confidence"] = "inferred"
    assert any("confidence <= medium" in error for error in validate_daily_time_window(report, ledger, manifest))
    item["published_at_confidence"] = "exact"
    ledger["items"][0]["date_basis"] = "inferred_from_search"
    errors = validate_daily_time_window(report, ledger, manifest)
    assert any("confidence <= medium" in error for error in errors)
    assert any("published_at_confidence=inferred" in error for error in errors)


def test_manifest_window_is_recomputed_instead_of_trusting_matching_tampering():
    report, ledger, manifest = _time_payloads()
    manifest["window"]["start"] = "1900-01-01T00:00:00+08:00"
    report["window"] = deepcopy(manifest["window"])
    errors = validate_daily_time_window(report, ledger, manifest)
    assert any("discovery_manifest.window does not match recomputed" in error for error in errors)
    assert any("report.window does not match recomputed" in error for error in errors)


@pytest.mark.parametrize("version", ["1.0", "1.1", "1.2"])
def test_all_report_versions_require_manifest_and_obey_dates(version):
    report, ledger, manifest = _time_payloads()
    report["version"] = version
    assert validate_daily_time_window(report, ledger, None)
    report["date"] = "2026-09-28"
    assert any("report.date" in error for error in validate_daily_time_window(report, ledger, manifest))


def test_legacy_manifest_timezone_alias_is_readable():
    report, ledger, manifest = _time_payloads()
    manifest["window"]["timezone"] = "UTC+08:00"
    report["window"]["timezone"] = "UTC+08:00"
    assert validate_daily_time_window(report, ledger, manifest) == []


@pytest.mark.parametrize("edge,value", [("start", "2026-09-30T07:00:00+08:00"),
                                       ("end", "2026-09-28T10:00:00+08:00"),
                                       ("end", "2026-09-29T10:00:00")])
def test_invalid_manifest_window_cannot_bypass_gate(edge, value):
    report, ledger, manifest = _time_payloads()
    manifest["window"][edge] = value
    assert validate_daily_time_window(report, ledger, manifest)


def test_daily_artifact_contract_cannot_omit_manifest():
    with pytest.raises(TypeError, match="manifest"):
        validate_daily_artifacts({}, {}, {}, project_root=None, profile=None)


def _core_fixture():
    sources = [{"name": f"core-{index}", "category": "us_labs", "fetch_chain": [
        {"type": "webfetch", "surface_kind": "feed"}, {"type": "websearch_scoped"}]} for index in range(8)]
    whitelist = {"sources": sources, "core_sources": [s["name"] for s in sources]}
    details = {s["name"]: {"attempts": [{"layer_index": 0, "layer_type": "webfetch",
        "target": "https://example.test", "result": "success"}]} for s in sources}
    report = {"fetch_status": {"succeeded": list(details), "failed": [], "empty": [], "source_details": details}}
    return report, whitelist


def _fail_core(report, name):
    status = report["fetch_status"]
    status["succeeded"].remove(name)
    status["failed"].append({"name": name, "reason": "offline test", "attempts": 2})
    status["source_details"][name]["attempts"] = [
        {"layer_index": index, "layer_type": kind, "target": "offline test", "result": "error"}
        for index, kind in enumerate(["webfetch", "websearch_scoped"])]


def test_three_failed_core_chains_allowed_but_four_blocks():
    report, whitelist = _core_fixture()
    for name in whitelist["core_sources"][:3]:
        _fail_core(report, name)
    assert validate_core_source_failures(report, whitelist) == []
    _fail_core(report, whitelist["core_sources"][3])
    assert any("failures=4 >=4" in error for error in validate_core_source_failures(report, whitelist))


def test_failure_threshold_recomputed_when_failed_summary_is_omitted():
    report, whitelist = _core_fixture()
    for name in whitelist["core_sources"][:4]:
        _fail_core(report, name)
    report["fetch_status"]["failed"] = []
    errors = validate_core_source_failures(report, whitelist)
    assert any("failures=4 >=4" in error for error in errors)
    assert any("status arrays disagree" in error for error in errors)


def test_fallback_success_and_later_supplemental_error_are_not_failures():
    report, whitelist = _core_fixture()
    status = report["fetch_status"]
    for name in whitelist["core_sources"]:
        _fail_core(report, name)
        attempts = status["source_details"][name]["attempts"]
        attempts.extend([{**attempts[-1], "result": "success"}, deepcopy(attempts[-1])])
    status["failed"] = []
    status["succeeded"] = list(whitelist["core_sources"])
    assert validate_core_source_failures(report, whitelist) == []


def test_incomplete_core_chain_never_counts_as_completed_failure():
    report, whitelist = _core_fixture()
    _fail_core(report, "core-0")
    detail = report["fetch_status"]["source_details"]["core-0"]
    detail["attempts"].pop()
    detail["final_layer_index"] = 1
    errors = validate_core_source_failures(report, whitelist)
    assert any("incomplete fetch_chain" in error for error in errors)
    assert not any("failures=" in error for error in errors)


def test_status_arrays_cannot_override_core_attempts():
    report, whitelist = _core_fixture()
    report["fetch_status"]["failed"] = [{"name": "core-0"}]
    report["fetch_status"]["empty"] = ["core-1"]
    errors = validate_core_source_failures(report, whitelist)
    assert any("succeeded and failed contradict" in error for error in errors)
    assert any("empty status disagrees" in error for error in errors)


def test_feed_empty_counts_as_success_but_static_empty_needs_fallback():
    report, whitelist = _core_fixture()
    status = report["fetch_status"]
    status["source_details"]["core-0"]["attempts"][0]["result"] = "success_but_empty"
    status["empty"] = ["core-0"]
    assert validate_core_source_failures(report, whitelist) == []
    whitelist["sources"][0]["fetch_chain"][0]["surface_kind"] = "static"
    assert any("incomplete" in error for error in validate_core_source_failures(report, whitelist))
    status["source_details"]["core-0"]["attempts"].append(
        {"layer_index": 1, "layer_type": "websearch_scoped", "target": "query", "result": "success_but_empty"})
    assert validate_core_source_failures(report, whitelist) == []
