from methodology import (
    load_seen_methodology,
    record_methodology,
    validate_methodology_repeats,
)


def _report(slug: str, date: str = "2026-06-12") -> dict:
    return {
        "date": date,
        "sections": {
            "methodology_radar": {
                "title": "方法论雷达",
                "items": [
                    {
                        "slug": slug,
                        "title": "x",
                        "kind": "paradigm_shift",
                        "what_it_is": "y",
                        "why_trending": "z",
                        "how_team_can_use": "w",
                        "depth_link": "https://example.com",
                        "references": [{"source": "Example", "url": "https://example.com"}],
                    }
                ],
                "empty_message": "",
            }
        },
    }


def test_load_missing_file_returns_empty(tmp_path):
    assert load_seen_methodology(tmp_path) == {"version": "1.0", "methodologies": {}}


def test_record_then_repeat_within_cooldown_is_rejected(tmp_path):
    record_methodology(_report("spec-driven", "2026-06-12"), tmp_path, "2026-06-12")
    seen = load_seen_methodology(tmp_path)
    assert seen["methodologies"]["spec-driven"]["first_seen"] == "2026-06-12"
    errors = validate_methodology_repeats(_report("spec-driven", "2026-06-20"), load_seen_methodology(tmp_path), "2026-06-20")
    assert any("spec-driven" in e for e in errors)


def test_repeat_same_day_allowed_for_rerun(tmp_path):
    record_methodology(_report("spec-driven", "2026-06-12"), tmp_path, "2026-06-12")
    errors = validate_methodology_repeats(_report("spec-driven", "2026-06-12"), load_seen_methodology(tmp_path), "2026-06-12")
    assert errors == []


def test_repeat_after_cooldown_allowed(tmp_path):
    record_methodology(_report("spec-driven", "2026-06-12"), tmp_path, "2026-06-12")
    errors = validate_methodology_repeats(_report("spec-driven", "2026-08-01"), load_seen_methodology(tmp_path), "2026-08-01")
    assert errors == []


def test_record_updates_last_emitted_keeps_first_seen(tmp_path):
    record_methodology(_report("a-b", "2026-06-12"), tmp_path, "2026-06-12")
    record_methodology(_report("a-b", "2026-08-01"), tmp_path, "2026-08-01")
    seen = load_seen_methodology(tmp_path)
    assert seen["methodologies"]["a-b"]["first_seen"] == "2026-06-12"
    assert seen["methodologies"]["a-b"]["last_emitted"] == "2026-08-01"


def test_empty_section_records_nothing(tmp_path):
    report = {"date": "2026-06-12", "sections": {"methodology_radar": {"title": "方法论雷达", "items": [], "empty_message": "无"}}}
    assert record_methodology(report, tmp_path, "2026-06-12") == 0
    assert load_seen_methodology(tmp_path)["methodologies"] == {}
