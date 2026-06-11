import json
from pathlib import Path

from tracking import (
    active_tracking_events,
    cleanup_expired_tracking,
    load_tracking_events,
    validate_tracking_refs,
)


def _write_tracking(project_root: Path, slug: str, opened: str, expires: str) -> Path:
    payload = {
        "version": "1.0",
        "type": "event_tracking",
        "event_slug": slug,
        "title": "Claude Fable 5 / Mythos 5 发布",
        "opened_date": opened,
        "expires_on": expires,
        "origin": {"date": opened, "section": "frontier_models", "headline": "Claude Fable 5 / Mythos 5 发布"},
        "watch_items": ["第三方 benchmark 何时收录"],
        "updates": [],
    }
    directory = project_root / "cache" / "tracking"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_tracking_events_accepts_valid_file(tmp_path):
    _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-14")
    events, errors = load_tracking_events(tmp_path)
    assert errors == []
    assert [event["event_slug"] for event in events] == ["claude-fable-5"]


def test_load_tracking_events_rejects_window_over_five_days(tmp_path):
    _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-20")
    events, errors = load_tracking_events(tmp_path)
    assert events == []
    assert any("0-5 days" in error for error in errors)


def test_load_tracking_events_rejects_slug_filename_mismatch(tmp_path):
    path = _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-14")
    path.rename(path.with_name("other-name.json"))
    events, errors = load_tracking_events(tmp_path)
    assert events == []
    assert any("does not match filename" in error for error in errors)


def test_active_tracking_events_filters_by_date(tmp_path):
    _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-14")
    _write_tracking(tmp_path, "old-event", "2026-06-01", "2026-06-05")
    active = active_tracking_events(tmp_path, "2026-06-11")
    assert [event["event_slug"] for event in active] == ["claude-fable-5"]


def test_validate_tracking_refs_flags_unknown_slug(tmp_path, sample_daily_report):
    _write_tracking(tmp_path, "claude-fable-5", "2026-04-09", "2026-04-12")
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["frontier_models"]["items"][0]["tracking_ref"] = "missing-event"
    errors = validate_tracking_refs(report, tmp_path)
    assert any("missing-event" in error for error in errors)


def test_validate_tracking_refs_accepts_active_slug(tmp_path, sample_daily_report):
    # sample_daily.json 的 date 是 2026-04-10，落在追踪窗口内
    _write_tracking(tmp_path, "claude-fable-5", "2026-04-09", "2026-04-12")
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["frontier_models"]["items"][0]["tracking_ref"] = "claude-fable-5"
    assert validate_tracking_refs(report, tmp_path) == []


def test_cleanup_expired_tracking_removes_old_files(tmp_path):
    _write_tracking(tmp_path, "old-event", "2026-05-20", "2026-05-24")
    _write_tracking(tmp_path, "fresh-event", "2026-06-08", "2026-06-12")
    removed = cleanup_expired_tracking(tmp_path, "2026-06-11", grace_days=7)
    assert removed == 1
    assert not (tmp_path / "cache" / "tracking" / "old-event.json").exists()
    assert (tmp_path / "cache" / "tracking" / "fresh-event.json").exists()


def test_load_tracking_events_collects_impossible_date_instead_of_crashing(tmp_path):
    _write_tracking(tmp_path, "claude-fable-5", "2026-02-30", "2026-03-02")
    events, errors = load_tracking_events(tmp_path)
    assert events == []
    assert any("invalid date" in error for error in errors)


def test_load_tracking_events_collects_malformed_json(tmp_path):
    directory = tmp_path / "cache" / "tracking"
    directory.mkdir(parents=True)
    (directory / "broken-event.json").write_text("{not json", encoding="utf-8")
    events, errors = load_tracking_events(tmp_path)
    assert events == []
    assert any("cannot load" in error for error in errors)


def test_load_tracking_events_window_boundaries(tmp_path):
    _write_tracking(tmp_path, "five-day-event", "2026-06-10", "2026-06-15")
    _write_tracking(tmp_path, "six-day-event", "2026-06-10", "2026-06-16")
    events, errors = load_tracking_events(tmp_path)
    assert [event["event_slug"] for event in events] == ["five-day-event"]
    assert any("six-day-event.json" in error and "0-5 days" in error for error in errors)
