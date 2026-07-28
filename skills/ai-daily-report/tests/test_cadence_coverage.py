import json
from copy import deepcopy

from discovery import (
    due_discovery_names,
    load_whitelist,
    missing_fetch_status_coverage,
)
from editorial import validate_fetch_status_integrity

LONGTAIL = "Aider"


def _report(finalized_fetch_status, whitelist):
    return {"date": "2026-04-18", "fetch_status": finalized_fetch_status(whitelist)}


def _drop_surface(report, name):
    payload = deepcopy(report)
    payload["fetch_status"]["source_details"].pop(name, None)
    payload["fetch_status"]["succeeded"] = [n for n in payload["fetch_status"]["succeeded"] if n != name]
    payload["fetch_status"]["empty"] = [n for n in payload["fetch_status"]["empty"] if n != name]
    return payload


def test_due_names_reads_manifest_cadence_plan(tmp_path):
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps(
            {
                "date": "2026-04-18",
                "cadence_plan": {
                    "OpenAI": {"cadence": "daily", "due": True, "last_probed": None},
                    LONGTAIL: {"cadence": "weekly", "due": False, "last_probed": "2026-04-17"},
                },
            }
        ),
        encoding="utf-8",
    )

    assert due_discovery_names(tmp_path, "2026-04-18") == ["OpenAI"]


def test_due_names_returns_none_when_manifest_missing(tmp_path):
    assert due_discovery_names(tmp_path, "2026-04-18") is None


def test_due_names_returns_none_for_legacy_manifest_without_cadence(tmp_path):
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"version": "1.0", "required_sources": []}), encoding="utf-8"
    )

    assert due_discovery_names(tmp_path, "2026-04-18") is None


def test_due_names_returns_none_for_corrupt_manifest(tmp_path):
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovery_manifest.json").write_text("{not json", encoding="utf-8")

    assert due_discovery_names(tmp_path, "2026-04-18") is None


def test_missing_coverage_defaults_to_full_whitelist(finalized_fetch_status):
    whitelist = load_whitelist()
    report = _drop_surface(_report(finalized_fetch_status, whitelist), LONGTAIL)

    assert LONGTAIL in missing_fetch_status_coverage(report, whitelist)


def test_missing_coverage_ignores_absent_non_due_surface(finalized_fetch_status):
    whitelist = load_whitelist()
    report = _drop_surface(_report(finalized_fetch_status, whitelist), LONGTAIL)
    due = [name for name in missing_fetch_status_coverage(report, whitelist)]
    assert LONGTAIL in due  # 前置：默认基准下确实缺席

    missing = missing_fetch_status_coverage(report, whitelist, due_names=["OpenAI"])

    assert LONGTAIL not in missing


def test_missing_coverage_still_reports_absent_due_surface(finalized_fetch_status):
    whitelist = load_whitelist()
    report = _drop_surface(_report(finalized_fetch_status, whitelist), LONGTAIL)

    missing = missing_fetch_status_coverage(report, whitelist, due_names=["OpenAI", LONGTAIL])

    assert LONGTAIL in missing


def test_awakened_non_due_surface_is_accepted(finalized_fetch_status):
    """非 due 面被 AI 唤醒后出现在 source_details：接受，不报错也不告警。"""
    whitelist = load_whitelist()
    report = _report(finalized_fetch_status, whitelist)

    errors = validate_fetch_status_integrity(report, whitelist, due_names=["OpenAI"])

    assert errors == []


def test_integrity_reports_missing_due_surface(finalized_fetch_status):
    whitelist = load_whitelist()
    report = _drop_surface(_report(finalized_fetch_status, whitelist), LONGTAIL)

    errors = validate_fetch_status_integrity(report, whitelist, due_names=["OpenAI", LONGTAIL])

    assert any(LONGTAIL in error for error in errors)


def test_integrity_skips_missing_non_due_surface(finalized_fetch_status):
    whitelist = load_whitelist()
    report = _drop_surface(_report(finalized_fetch_status, whitelist), LONGTAIL)

    errors = validate_fetch_status_integrity(report, whitelist, due_names=["OpenAI"])

    assert not any(LONGTAIL in error for error in errors)


def test_finalize_accepts_report_missing_non_due_surface(
    tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
):
    """端到端：manifest 把某面标 due=false，日报里没有它，finalize 不报错。"""
    from test_cadence_runner import DATE, _prepare_finalize_cache, _write_env
    from report_runner import run_daily_finalize

    env_path = _write_env(tmp_path)
    cache_dir, report = _prepare_finalize_cache(
        tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
    )
    whitelist = load_whitelist()
    stripped = _drop_surface(report, LONGTAIL)
    (cache_dir / "report.json").write_text(json.dumps(stripped, ensure_ascii=False), encoding="utf-8")

    plan = {
        name: {"cadence": "daily", "due": name != LONGTAIL, "last_probed": None}
        for name in stripped["fetch_status"]["source_details"]
    }
    plan[LONGTAIL] = {"cadence": "weekly", "due": False, "last_probed": None}
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"date": DATE, "cadence_plan": plan}), encoding="utf-8"
    )

    code, message = run_daily_finalize(tmp_path, DATE, dry_run=True, env_path=env_path)

    assert code == 0, message
