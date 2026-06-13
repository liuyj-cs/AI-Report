import json
from copy import deepcopy

from deep_dive import deep_dive_path, major_event_slugs, validate_deep_dives


def _report_with_major_event(slug="claude-fable-5"):
    return {
        "date": "2026-06-13",
        "sections": {
            "frontier_models": {
                "items": [
                    {
                        "headline": "Claude Fable 5 / Mythos 5 发布",
                        "major_event": True,
                        "tracking_ref": slug,
                    }
                ]
            },
            "coding_agents": {"items": []},
            "general_agents": {"items": []},
        },
    }


def _write_deep_dive(tmp_path, payload):
    path = deep_dive_path(tmp_path, payload["date"], payload["event_slug"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_major_event_slugs_lists_major_items_only():
    report = _report_with_major_event()
    report["sections"]["coding_agents"]["items"].append({"headline": "普通条目"})
    assert major_event_slugs(report) == [("frontier_models[0]", "claude-fable-5")]


def test_validate_deep_dives_missing_file(tmp_path):
    errors = validate_deep_dives(_report_with_major_event(), tmp_path)
    assert errors == [
        "frontier_models[0] major_event requires deep dive file cache/2026-06-13/deep_dive_claude-fable-5.json"
    ]


def test_validate_deep_dives_passes_with_valid_file(tmp_path, sample_deep_dive):
    _write_deep_dive(tmp_path, sample_deep_dive)
    assert validate_deep_dives(_report_with_major_event(), tmp_path) == []


def test_validate_deep_dives_rejects_slug_mismatch(tmp_path, sample_deep_dive):
    payload = deepcopy(sample_deep_dive)
    payload["event_slug"] = "wrong-slug"
    path = deep_dive_path(tmp_path, "2026-06-13", "claude-fable-5")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    errors = validate_deep_dives(_report_with_major_event(), tmp_path)
    assert any("event_slug" in error for error in errors)


def test_validate_deep_dives_rejects_schema_violation(tmp_path, sample_deep_dive):
    payload = deepcopy(sample_deep_dive)
    del payload["sections"]["quick_start"]
    _write_deep_dive(tmp_path, payload)

    errors = validate_deep_dives(_report_with_major_event(), tmp_path)
    assert any("quick_start" in error for error in errors)


def test_validate_deep_dives_no_major_events_is_noop(tmp_path):
    report = {"date": "2026-06-13", "sections": {"frontier_models": {"items": []}, "coding_agents": {"items": []}, "general_agents": {"items": []}}}
    assert validate_deep_dives(report, tmp_path) == []
