import json
from pathlib import Path

from ecosystem import load_seen_repos, record_ecosystem_repos, validate_ecosystem_repeats


def _report_with_repo(slug: str, date: str = "2026-06-12") -> dict:
    return {
        "date": date,
        "sections": {
            "agent_ecosystem": {
                "title": "Agent 生态与实践",
                "items": [
                    {
                        "item_type": "trending_repo",
                        "title": "x",
                        "summary": "y",
                        "source_name": "GitHub Trending",
                        "source_url": f"https://github.com/{slug}",
                        "relevance": "团队级 agent 工作流",
                        "heat_note": "快照",
                        "repo_slug": slug,
                    }
                ],
                "empty_message": "",
            }
        },
    }


def test_load_seen_repos_missing_file_returns_empty(tmp_path):
    assert load_seen_repos(tmp_path) == {"version": "1.0", "repos": {}}


def test_record_then_repeat_within_cooldown_is_rejected(tmp_path):
    report = _report_with_repo("example/claude-flow", "2026-06-12")
    record_ecosystem_repos(report, tmp_path, "2026-06-12")

    seen = load_seen_repos(tmp_path)
    assert seen["repos"]["example/claude-flow"]["first_seen"] == "2026-06-12"

    repeat = _report_with_repo("example/claude-flow", "2026-06-20")
    errors = validate_ecosystem_repeats(repeat, load_seen_repos(tmp_path), "2026-06-20")
    assert any("example/claude-flow" in error for error in errors)


def test_repeat_same_day_is_allowed_for_rerun(tmp_path):
    report = _report_with_repo("example/claude-flow", "2026-06-12")
    record_ecosystem_repos(report, tmp_path, "2026-06-12")
    errors = validate_ecosystem_repeats(report, load_seen_repos(tmp_path), "2026-06-12")
    assert errors == []


def test_repeat_after_cooldown_is_allowed(tmp_path):
    report = _report_with_repo("example/claude-flow", "2026-06-12")
    record_ecosystem_repos(report, tmp_path, "2026-06-12")
    later = _report_with_repo("example/claude-flow", "2026-08-01")
    errors = validate_ecosystem_repeats(later, load_seen_repos(tmp_path), "2026-08-01")
    assert errors == []


def test_record_updates_last_listed_keeps_first_seen(tmp_path):
    record_ecosystem_repos(_report_with_repo("a/b", "2026-06-12"), tmp_path, "2026-06-12")
    record_ecosystem_repos(_report_with_repo("a/b", "2026-08-01"), tmp_path, "2026-08-01")
    seen = load_seen_repos(tmp_path)
    assert seen["repos"]["a/b"]["first_seen"] == "2026-06-12"
    assert seen["repos"]["a/b"]["last_listed"] == "2026-08-01"


def test_non_repo_items_are_ignored(tmp_path):
    report = _report_with_repo("a/b", "2026-06-12")
    report["sections"]["agent_ecosystem"]["items"][0]["item_type"] = "practice_case"
    record_ecosystem_repos(report, tmp_path, "2026-06-12")
    assert load_seen_repos(tmp_path)["repos"] == {}
    assert validate_ecosystem_repeats(report, load_seen_repos(tmp_path), "2026-06-12") == []
