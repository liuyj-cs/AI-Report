"""PR #5 复审 round 3：类型合法 ≠ 语义可能；记了一笔 ≠ 真探过。

两条的共同形态是**"看起来合法"的数据被当成了事实**：一个 `daily/due=false` 的 slot
在类型上无懈可击，却与 compute_cadence 的语义直接矛盾；一条 `attempts=0` 的审计记录
形状完好，却不代表这个面真被探过。校验必须落到"这个值可能吗"，不是"这个值像不像"。
"""
import json
from datetime import date, timedelta

import pytest

from discovery import (
    compute_cadence,
    due_discovery_names,
    required_discovery_names,
)
from report_runner import run_source_stats
from source_stats import load_source_stats, source_stats_path

DATE = "2026-07-28"
TARGET = date.fromisoformat(DATE)
COLD = "Aider"


def _manifest(tmp_path, plan):
    cache_dir = tmp_path / "cache" / DATE
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"date": DATE, "cadence_plan": plan}, ensure_ascii=False), encoding="utf-8"
    )


def _plan(whitelist, **overrides):
    plan = {
        name: {"cadence": "daily", "due": True, "last_probed": None}
        for name in required_discovery_names(whitelist)
    }
    plan.update(overrides)
    return plan


def _ago(days):
    return (TARGET - timedelta(days=days)).isoformat()


# --- P1-1: slot 必须语义自洽 -----------------------------------------------


def test_impossible_daily_not_due_rejects_plan(tmp_path, sample_whitelist):
    """复审反例：74 个 slot 类型全合法，19 个 due=true、55 个 daily/due=false。

    daily 面永远是 due 的（间隔 1 天，last_probed 最晚只能是昨天），所以
    `daily + due=false` 在语义上不可能——它只能来自伪造或损坏。
    """
    names = required_discovery_names(sample_whitelist)
    plan = {name: {"cadence": "daily", "due": i < 19, "last_probed": None} for i, name in enumerate(names)}
    _manifest(tmp_path, plan)

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_null_last_probed_must_be_due(tmp_path, sample_whitelist):
    """从没探过的面一定到期。"""
    plan = _plan(sample_whitelist, **{COLD: {"cadence": "weekly", "due": False, "last_probed": None}})
    _manifest(tmp_path, plan)

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_due_must_match_interval_since_last_probe(tmp_path, sample_whitelist):
    # weekly 面昨天刚探过 → 差 1 天 < 7，不可能 due
    plan = _plan(sample_whitelist, **{COLD: {"cadence": "weekly", "due": True, "last_probed": _ago(1)}})
    _manifest(tmp_path, plan)
    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None

    # every_2_days 面 5 天没探 → 差 5 >= 2，不可能不 due
    plan = _plan(sample_whitelist, **{COLD: {"cadence": "every_2_days", "due": False, "last_probed": _ago(5)}})
    _manifest(tmp_path, plan)
    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


# 「语义自洽的手工 slot 应被接受」一组用例已移除：判据改为重算比对后，手工构造的
# plan 不再是可接受的充分条件。正向断言由 test_cadence_plan_authority.py 的
# test_authentic_plan_is_accepted / _with_history 承担（更强：真实产物必须通过）。


def test_real_manifest_from_init_is_accepted(tmp_path, sample_whitelist):
    """最强的回归：init-daily 真实产出的 plan 必须通过自己的校验。"""
    from discovery import build_discovery_manifest, compute_daily_window, write_discovery_manifest

    plan = compute_cadence(sample_whitelist, {"version": "1.0", "days": {}}, DATE)
    window = compute_daily_window(DATE, f"{DATE}T08:00:00+08:00")
    manifest = build_discovery_manifest(DATE, window, sample_whitelist, cadence_plan=plan)
    cache_dir = tmp_path / "cache" / DATE
    cache_dir.mkdir(parents=True)
    write_discovery_manifest(cache_dir, manifest)

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is not None


# --- P1-2: 跳过不是实探 -----------------------------------------------------


def _seed(tmp_path, record, days_back=15):
    days = {_ago(offset): {COLD: record} for offset in range(1, days_back + 1)}
    days[_ago(40)] = {COLD: record}
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "days": days}, ensure_ascii=False), encoding="utf-8")


def test_zero_attempt_records_do_not_count_as_probes(tmp_path, sample_whitelist):
    """连续 16 天"记了一笔但没探" ≠ 16 个实探日，不得据此降频。"""
    _seed(tmp_path, {"attempts": 0, "hit": False})

    plan = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)

    assert plan[COLD]["cadence"] == "daily"
    assert plan[COLD]["due"] is True


def test_zero_attempt_records_do_not_become_last_probed(tmp_path, sample_whitelist):
    _seed(tmp_path, {"attempts": 0, "hit": False})

    assert compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)[COLD]["last_probed"] is None


def test_zero_attempt_records_are_still_kept_as_audit_trail(tmp_path):
    """跳过记录本身仍是合法审计留痕，只是不参与调度统计。"""
    _seed(tmp_path, {"attempts": 0, "hit": False})

    assert any(COLD in entry for entry in load_source_stats(tmp_path)["days"].values())


def test_source_stats_summary_excludes_zero_attempt_days(tmp_path, capsys):
    _seed(tmp_path, {"attempts": 0, "hit": False})

    assert run_source_stats(tmp_path, DATE)[0] == 0
    payload = json.loads(run_source_stats(tmp_path, DATE)[1])

    assert payload["summary"].get(COLD, {"probed_days": 0})["probed_days"] == 0


def test_mixed_real_and_skipped_days_count_only_real(tmp_path, sample_whitelist):
    days = {_ago(offset): {COLD: {"attempts": 0, "hit": False}} for offset in range(1, 16)}
    days.update({_ago(offset): {COLD: {"attempts": 2, "hit": False}} for offset in range(16, 27)})
    days[_ago(40)] = {COLD: {"attempts": 2, "hit": False}}
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "days": days}, ensure_ascii=False), encoding="utf-8")

    plan = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)

    # 11 个真实实探日（>=10）且零命中 → 正常降 weekly；last_probed 取最近的真实探测
    assert plan[COLD]["cadence"] == "weekly"
    assert plan[COLD]["last_probed"] == _ago(16)


def test_real_probes_still_drive_downgrade(tmp_path, sample_whitelist):
    _seed(tmp_path, {"attempts": 1, "hit": False})

    assert compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)[COLD]["cadence"] == "weekly"
