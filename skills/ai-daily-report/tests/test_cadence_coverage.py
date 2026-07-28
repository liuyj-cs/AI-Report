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


def _plan_with_due(whitelist, due_names):
    """构造一份「只有这些面 due」的 cadence_plan，用于直接测试 integrity 的基准行为。

    这里不经过 trusted_cadence_plan，因此不受重算比对约束——被测的是 integrity 自身
    如何消费一份给定的 plan，plan 的可信性由 authority 测试单独把关。
    """
    from discovery import required_discovery_names

    return {
        name: {"cadence": "daily" if name in due_names else "weekly",
               "due": name in due_names,
               "last_probed": None if name in due_names else "2026-04-15"}
        for name in required_discovery_names(whitelist)
    }


def _drop_surface(report, name):
    payload = deepcopy(report)
    payload["fetch_status"]["source_details"].pop(name, None)
    payload["fetch_status"]["succeeded"] = [n for n in payload["fetch_status"]["succeeded"] if n != name]
    payload["fetch_status"]["empty"] = [n for n in payload["fetch_status"]["empty"] if n != name]
    return payload


# 「读取 manifest 的 due 名单」正向用例已移除：判据是重算比对，手工 plan 不再被接受；
# 正向断言见 test_cadence_plan_authority.py::test_authentic_plan_is_accepted。


def test_due_names_returns_none_when_manifest_missing(tmp_path, sample_whitelist):
    assert due_discovery_names(tmp_path, "2026-04-18", sample_whitelist) is None


def test_due_names_returns_none_for_legacy_manifest_without_cadence(tmp_path, sample_whitelist):
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"version": "1.0", "required_sources": []}), encoding="utf-8"
    )

    assert due_discovery_names(tmp_path, "2026-04-18", sample_whitelist) is None


def test_due_names_returns_none_for_corrupt_manifest(tmp_path, sample_whitelist):
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    (cache_dir / "discovery_manifest.json").write_text("{not json", encoding="utf-8")

    assert due_discovery_names(tmp_path, "2026-04-18", sample_whitelist) is None


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
    """非 due 面被 AI 唤醒后出现在 source_details：接受，不报错也不告警。

    唤醒本身合法——只要留下 wakeup_reason 说明依据（那是后来加的审计要求，
    见 test_no_downgrade_bypass.py::test_wakeup_audit_cannot_be_silently_skipped）。
    """
    whitelist = load_whitelist()
    report = _report(finalized_fetch_status, whitelist)
    from discovery import required_discovery_names

    all_names = required_discovery_names(whitelist)
    plan = _plan_with_due(whitelist, [n for n in all_names if n != LONGTAIL])
    report["fetch_status"]["source_details"][LONGTAIL]["attempts"][0]["wakeup_reason"] = "媒体信号指向该源当日有发布"

    errors = validate_fetch_status_integrity(report, whitelist, plan)

    assert errors == []


def test_integrity_reports_missing_due_surface(finalized_fetch_status):
    whitelist = load_whitelist()
    report = _drop_surface(_report(finalized_fetch_status, whitelist), LONGTAIL)

    errors = validate_fetch_status_integrity(report, whitelist, _plan_with_due(whitelist, ["OpenAI", LONGTAIL]))

    assert any(LONGTAIL in error for error in errors)


def test_integrity_skips_missing_non_due_surface(finalized_fetch_status):
    whitelist = load_whitelist()
    report = _drop_surface(_report(finalized_fetch_status, whitelist), LONGTAIL)

    errors = validate_fetch_status_integrity(report, whitelist, _plan_with_due(whitelist, ["OpenAI"]))

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

    # plan 必须是 compute_cadence 的真实产出——finalize 会重算比对
    from datetime import date, timedelta

    from discovery import compute_cadence
    from source_stats import load_source_stats, source_stats_path

    target = date.fromisoformat(DATE)
    days = {
        (target - timedelta(days=offset)).isoformat(): {LONGTAIL: {"attempts": 2, "hit": False}}
        for offset in range(1, 21)
    }
    days[(target - timedelta(days=40)).isoformat()] = {LONGTAIL: {"attempts": 2, "hit": False}}
    stats_path = source_stats_path(tmp_path)
    stats_path.parent.mkdir(parents=True, exist_ok=True)
    stats_path.write_text(json.dumps({"version": "1.0", "days": days}), encoding="utf-8")

    plan = compute_cadence(whitelist, load_source_stats(tmp_path), DATE)
    assert plan[LONGTAIL]["due"] is False
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"date": DATE, "cadence_plan": plan}), encoding="utf-8"
    )

    code, message = run_daily_finalize(tmp_path, DATE, dry_run=True, env_path=env_path)

    assert code == 0, message
