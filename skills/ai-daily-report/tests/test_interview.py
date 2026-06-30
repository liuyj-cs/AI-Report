import json
from pathlib import Path

from interview import (
    interview_already_sent,
    iter_interview_files,
    load_interview_seen,
    record_interview_sent,
    validate_interviews,
)

SKILL_ROOT = Path(__file__).resolve().parent.parent
SAMPLE = json.loads((SKILL_ROOT / "tests" / "fixtures" / "sample_interview.json").read_text(encoding="utf-8"))


def _write_interview(project_root: Path, date: str, payload: dict) -> Path:
    cache_dir = project_root / "cache" / date
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"interview_{payload['slug']}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_iter_interview_files_globs_and_sorts(tmp_path):
    _write_interview(tmp_path, "2026-06-30", {**SAMPLE, "slug": "b-person", "person": "B"})
    _write_interview(tmp_path, "2026-06-30", {**SAMPLE, "slug": "a-person", "person": "A"})
    names = [p.name for p in iter_interview_files(tmp_path, "2026-06-30")]
    assert names == ["interview_a-person.json", "interview_b-person.json"]


def test_iter_interview_files_empty_when_no_dir(tmp_path):
    assert iter_interview_files(tmp_path, "2026-06-30") == []


def test_validate_interviews_passes_on_good_fixture(tmp_path):
    _write_interview(tmp_path, "2026-06-30", SAMPLE)
    assert validate_interviews("2026-06-30", tmp_path) == []


def test_validate_interviews_flags_date_mismatch(tmp_path):
    payload = {**SAMPLE, "date": "2026-06-29"}
    _write_interview(tmp_path, "2026-06-30", payload)
    errors = validate_interviews("2026-06-30", tmp_path)
    assert any("does not match report date" in e for e in errors)


def test_validate_interviews_flags_self_translated_without_full_translation(tmp_path):
    payload = {**SAMPLE, "mode": "self_translated_full"}
    payload.pop("full_translation", None)
    _write_interview(tmp_path, "2026-06-30", payload)
    errors = validate_interviews("2026-06-30", tmp_path)
    assert any("self_translated_full requires" in e for e in errors)


def test_validate_interviews_flags_linked_without_transcript_url(tmp_path):
    payload = {**SAMPLE, "mode": "linked_zh_transcript", "chinese_transcript": {"available": True}}
    payload.pop("full_translation", None)
    _write_interview(tmp_path, "2026-06-30", payload)
    errors = validate_interviews("2026-06-30", tmp_path)
    assert any("linked_zh_transcript requires" in e for e in errors)


def test_validate_interviews_flags_schema_error(tmp_path):
    payload = {**SAMPLE}
    payload.pop("lede")
    _write_interview(tmp_path, "2026-06-30", payload)
    errors = validate_interviews("2026-06-30", tmp_path)
    assert errors


def test_record_and_already_sent_roundtrip(tmp_path):
    assert load_interview_seen(tmp_path) == {"version": "1.0", "interviews": {}}
    assert interview_already_sent(tmp_path, "fiona-fung-claude-code") is False
    record_interview_sent(tmp_path, SAMPLE, "2026-06-30", "reports/interviews/2026-06-30-fiona-fung-claude-code.html")
    seen = load_interview_seen(tmp_path)
    assert seen["interviews"]["fiona-fung-claude-code"]["sent_date"] == "2026-06-30"
    assert seen["interviews"]["fiona-fung-claude-code"]["org"] == "Anthropic"
    assert interview_already_sent(tmp_path, "fiona-fung-claude-code") is True


def test_load_interview_seen_corrupt_returns_empty(tmp_path):
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / "interview_seen.json").write_text("{not json", encoding="utf-8")
    assert load_interview_seen(tmp_path) == {"version": "1.0", "interviews": {}}
