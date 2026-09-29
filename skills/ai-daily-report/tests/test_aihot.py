"""Synthetic HTTP responses exercise discovery coverage without network or delivery."""
from copy import deepcopy
import json
from urllib.parse import urlencode

import pytest

from aihot import recompute_aihot_coverage, summarize_aihot_pages, validate_aihot_discovery
from evidence import save_response


WINDOW = {"start": "2026-09-28T07:00:00+08:00", "end": "2026-09-29T10:00:00+08:00"}
COLLECTED = "2026-09-29T10:01:00+08:00"
URL = "https://aihot.virxact.com/api/v1/items?mode=all&window=7d&by=published&limit=2"


def item(identity, published):
    return {"id": identity, "title": f"Synthetic item {identity}", "publishedAt": published,
            "discoveredAt": "2026-09-29T00:00:00Z", "selected": False,
            "source": {"name": "Synthetic source"},
            "links": {"aihot": f"https://aihot.news/a/{identity}", "original": "https://example.com/"}}


def page(items, *, more=False, cursor=None, request_cursor=None):
    return {"request_url": URL + ("&" + urlencode({"cursor": request_cursor}) if request_cursor else ""),
            "requested_at": "2026-09-29T10:00:30+08:00", "status_code": 200,
            "content_type": "application/json; charset=utf-8", "collected_at": COLLECTED,
            "body": {"schemaVersion": 1,
                     "query": {"mode": "all", "window": "7d", "by": "published", "category": None,
                               "q": None, "ordering": "publishedAtDesc"},
                     "items": items, "page": {"count": len(items), "hasMore": more, "nextCursor": cursor}}}


def first_page():
    return page([item("new", "2026-09-29T00:00:00Z"), item("older", "2026-09-28T01:00:00Z")],
                more=True, cursor="opaque+/cursor=")


def test_successful_first_page_is_partial_even_if_selected_items_exist():
    record = first_page()
    record["body"]["items"][0]["selected"] = True
    summary = summarize_aihot_pages([record], window=WINDOW)
    assert summary["status"] == "partial"
    assert summary["next_cursor"] == "opaque+/cursor="
    assert summary["in_window_count"] == 2


def test_cursor_chain_is_followed_and_complete_empty_is_narrow():
    records = [first_page(), page([], request_cursor="opaque+/cursor=")]
    summary = summarize_aihot_pages(records, window=WINDOW)
    assert summary["status"] == "complete"
    assert summary["stop_reason"] == "exhausted"
    assert summary["pages_fetched"] == 2
    assert summarize_aihot_pages([page([])], window=WINDOW)["in_window_count"] == 0


def test_strict_window_crossing_completes_without_falsifying_has_more():
    record = page([item("boundary", WINDOW["start"]), item("before", "2026-09-28T06:59:59+08:00")],
                  more=True, cursor="continue")
    summary = summarize_aihot_pages([record], window=WINDOW)
    assert summary["status"] == "complete"
    assert summary["stop_reason"] == "target_window_passed"
    assert summary["next_cursor"] == "continue"
    assert summary["in_window_count"] == 1
    record["body"]["items"][1]["publishedAt"] = WINDOW["start"]
    assert summarize_aihot_pages([record], window=WINDOW)["status"] == "partial"


def test_null_publication_uses_discovery_only_as_inferred_time():
    record = page([item("unknown-date", None)])
    summary = summarize_aihot_pages([record], window=WINDOW)
    assert summary["status"] == "complete"
    assert summary["inferred_time_count"] == 1
    assert record["body"]["items"][0]["publishedAt"] is None


@pytest.mark.parametrize("timestamp", ["1900-01-01T00:00:00Z", "2100-01-01T00:00:00Z"])
def test_impossible_api_item_time_cannot_prove_empty_window(timestamp):
    summary = summarize_aihot_pages([page([item("bad-time", timestamp)])], window=WINDOW)
    assert summary["status"] == "error"


def test_extra_older_page_failure_does_not_erase_observed_target_boundary():
    covered = page([item("a", WINDOW["start"]), item("b", "2026-09-28T06:59:59+08:00")],
                   more=True, cursor="older")
    extra = page([], request_cursor="older")
    extra.update(status_code=503)
    summary = summarize_aihot_pages([covered, extra], window=WINDOW)
    assert summary["status"] == "complete"
    assert summary["stop_reason"] == "target_window_passed"


@pytest.mark.parametrize("field", ["title", "source", "links"])
def test_truncated_item_structure_cannot_complete_discovery(field):
    record = page([item("truncated", "2026-09-29T00:00:00Z")])
    del record["body"]["items"][0][field]
    assert summarize_aihot_pages([record], window=WINDOW)["status"] == "error"


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(status_code=400, content_type="application/problem+json",
                       body={"type": "about:blank", "title": "Bad Request", "status": 400, "code": "invalid_request"}),
    lambda r: r.update(status_code=400, body={"items": [], "page": None}),
    lambda r: r.update(status_code=304, body=None),
    lambda r: r.update(status_code=True),
    lambda r: r["body"].pop("items"),
    lambda r: r["body"].update(page=None),
    lambda r: r["body"].update(schemaVersion=True),
    lambda r: r["body"]["page"].update(count=True),
    lambda r: r["body"]["page"].update(count=7),
    lambda r: r["body"]["page"].update(hasMore=True, nextCursor=None),
    lambda r: r["body"]["query"].update(by="timeline"),
    lambda r: r.update(request_url=URL + "&category=coding"),
    lambda r: r.update(request_url=URL + "&mode=all"),
    lambda r: r.update(request_url=URL.replace("aihot.virxact.com", "example.com")),
    lambda r: r.update(collected_at="2026-10-10T10:01:00+08:00"),
    lambda r: r.update(collected_at="2026-09-29T09:59:00+08:00"),
])
def test_invalid_or_error_responses_never_become_empty_success(mutation):
    record = page([])
    mutation(record)
    summary = summarize_aihot_pages([record], window=WINDOW)
    assert summary["status"] == "error"
    assert summary["pages_fetched"] == 0


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(request_url=URL + "&cursor=wrong"),
    lambda r: r["body"]["page"].update(nextCursor="opaque+/cursor="),
    lambda r: r["body"]["items"][0].update(id="new"),
    lambda r: r["body"]["items"][0].update(publishedAt="2026-09-29T01:00:00Z"),
    lambda r: r.update(status_code=400, content_type="application/problem+json", body={"code": "invalid_cursor"}),
])
def test_bad_continuation_retains_partial_counts_and_does_not_claim_completion(mutation):
    second = page([item("a", "2026-09-28T00:30:00Z"), item("b", "2026-09-28T00:00:00Z")],
                  more=True, cursor="next", request_cursor="opaque+/cursor=")
    mutation(second)
    summary = summarize_aihot_pages([first_page(), second], window=WINDOW)
    assert summary["status"] == "partial"
    assert summary["items_seen"] == 2
    assert summary["pages_fetched"] == 1


def test_failed_request_is_retained_and_retry_must_use_same_cursor():
    failed = page([], request_cursor="opaque+/cursor=")
    failed.update(status_code=503, content_type="application/problem+json", body={"code": "temporarily_unavailable"})
    records = [first_page(), failed, page([], request_cursor="opaque+/cursor=")]
    summary = summarize_aihot_pages(records, window=WINDOW)
    assert summary["status"] == "complete"
    assert summary["pages_fetched"] == 2
    records[-1]["request_url"] = URL  # Restarting from page 1 cannot fill a missing continuation.
    assert summarize_aihot_pages(records, window=WINDOW)["status"] == "partial"


def stored_report(tmp_path, records):
    attempts = []
    for index, original in enumerate(records):
        record = deepcopy(original)
        collected = record.pop("collected_at")
        artifact = save_response(tmp_path, json.dumps(record), collected_at=collected,
                                 batch_id="test", query_ids=[f"page-{index}"], limitations=[])
        attempts.append({"layer_index": 0, "layer_type": "webfetch", "target": record["request_url"],
                         "result": "success", "evidence_artifact": artifact})
    detail = {"attempts": attempts, "final_layer_index": 0, "final_layer_type": "webfetch"}
    detail["aihot_coverage"] = recompute_aihot_coverage(detail, window=WINDOW, cache_dir=tmp_path)
    report = {"fetch_status": {"source_details": {"AI HOT": detail}, "succeeded": ["AI HOT"], "empty": []}}
    manifest = {"window": WINDOW, "required_sources": [{"name": "AI HOT", "fetch_chain": [{"url": URL}]}]}
    return report, manifest, detail


def test_saved_evidence_is_recomputed_not_self_reported(tmp_path):
    report, manifest, detail = stored_report(tmp_path, [page([])])
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path) == []
    detail["aihot_coverage"]["in_window_count"] = 99
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)
    artifact = detail["attempts"][0]["evidence_artifact"]
    (tmp_path / artifact["path"]).write_text("{}", encoding="utf-8")
    assert recompute_aihot_coverage(detail, window=WINDOW, cache_dir=tmp_path)["status"] == "error"


def test_partial_is_an_explicit_gap_even_when_search_fallback_succeeds(tmp_path):
    report, manifest, detail = stored_report(tmp_path, [first_page()])
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)
    detail["attempts"][0].update(result="error", reason="API discovery partial; further pages unavailable")
    detail["attempts"].append({"layer_index": 1, "layer_type": "websearch_scoped", "result": "success"})
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path) == []
    report["fetch_status"]["empty"] = ["AI HOT"]
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)


def test_historical_manifest_does_not_acquire_new_contract(tmp_path):
    report, manifest, detail = stored_report(tmp_path, [page([])])
    manifest["required_sources"][0]["fetch_chain"][0]["url"] = "https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=50"
    del detail["aihot_coverage"]
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path) == []


def test_missing_manifest_and_malformed_new_url_do_not_bypass_validation(tmp_path):
    report, manifest, _ = stored_report(tmp_path, [page([])])
    assert validate_aihot_discovery(report, manifest=None, cache_dir=tmp_path)
    manifest["required_sources"][0]["fetch_chain"][0]["url"] = URL.replace("by=published", "by=timeline")
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)


def test_malformed_locked_window_returns_validation_error_instead_of_crashing(tmp_path):
    report, manifest, _ = stored_report(tmp_path, [page([])])
    del manifest["window"]
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)


@pytest.mark.parametrize("sources", [None, [], {}, [{"name": "AI HOT"}, {"name": "AI HOT"}]])
def test_removed_or_duplicated_locked_aihot_source_does_not_bypass_validation(tmp_path, sources):
    report, manifest, _ = stored_report(tmp_path, [page([])])
    manifest["required_sources"] = sources
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)


def test_complete_api_coverage_cannot_claim_failed_source(tmp_path):
    report, manifest, detail = stored_report(tmp_path, [page([])])
    report["fetch_status"]["failed"] = [{"name": "AI HOT", "reason": "failed", "attempts": 1}]
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)
    report["fetch_status"]["failed"] = []
    detail["attempts"][0]["result"] = "error"
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)


def test_nonempty_page_cannot_be_reported_as_empty(tmp_path):
    report, manifest, _ = stored_report(tmp_path, [page([item("item", "2026-09-29T00:00:00Z")])])
    report["fetch_status"]["empty"] = ["AI HOT"]
    assert validate_aihot_discovery(report, manifest=manifest, cache_dir=tmp_path)
