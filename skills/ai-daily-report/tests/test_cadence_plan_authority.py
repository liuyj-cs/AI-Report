"""cadence_plan 的信任判据：它是本流程自己算出来的，唯一完备的验证是重算比对。

前四轮 review 在同一个函数上找到 5 个绕过（缺 date / 未覆盖全部面 / 非布尔 due /
语义不可能 / 固定 cadence 策略被改写），每轮修法都是"再加一条校验规则"。这条路
收敛不了：逐字段校验是在用近似规则逼近「这个值是不是 compute_cadence 的输出」这个
等价判断，近似必然有缝。

改判据本身：**接受 ⟺ 等于 compute_cadence(whitelist, stats, date) 的输出**。
下面的测试按这个判据写——不再枚举"哪些坏值要拒绝"，而是断言"任何偏离都拒绝"。
"""
import json
from datetime import date, timedelta

import pytest

from discovery import (
    _exempt_daily_names,
    SLOW_TRACK_SURFACES,
    compute_cadence,
    due_discovery_names,
    required_discovery_names,
    trusted_cadence_plan,
)
from source_stats import source_stats_path

DATE = "2026-07-28"
TARGET = date.fromisoformat(DATE)


def _ago(days):
    return (TARGET - timedelta(days=days)).isoformat()


def _seed_stats(tmp_path, days=None):
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "days": days or {}}, ensure_ascii=False), encoding="utf-8")


def _write_plan(tmp_path, plan):
    cache_dir = tmp_path / "cache" / DATE
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"date": DATE, "cadence_plan": plan}, ensure_ascii=False), encoding="utf-8"
    )


def _authentic(tmp_path, whitelist):
    """本流程自己算出来的那份 plan。"""
    from source_stats import load_source_stats

    return compute_cadence(whitelist, load_source_stats(tmp_path), DATE)


# --- 完备判据：接受 ⟺ 等于重算结果 -----------------------------------------


def test_authentic_plan_is_accepted(tmp_path, sample_whitelist):
    _seed_stats(tmp_path)
    plan = _authentic(tmp_path, sample_whitelist)
    _write_plan(tmp_path, plan)

    assert trusted_cadence_plan(tmp_path, DATE, sample_whitelist) == plan


def test_authentic_plan_with_history_is_accepted(tmp_path, sample_whitelist):
    """有真实历史（含降频面）的 plan 同样被接受，加固不能挡住正常路径。"""
    days = {_ago(o): {"Aider": {"attempts": 2, "hit": False}} for o in range(1, 21)}
    days[_ago(40)] = {"Aider": {"attempts": 2, "hit": False}}
    _seed_stats(tmp_path, days)
    plan = _authentic(tmp_path, sample_whitelist)
    assert plan["Aider"]["cadence"] == "weekly"  # 前置：这份 plan 里确实有降频面
    _write_plan(tmp_path, plan)

    assert trusted_cadence_plan(tmp_path, DATE, sample_whitelist) == plan


def _mutations(plan, whitelist):
    """对真实 plan 的单点扰动，每一项都应当被拒绝。"""
    names = list(plan)
    exempt = next(n for n in names if n in _exempt_daily_names(whitelist))
    slow = SLOW_TRACK_SURFACES[0]
    out = {}

    # 本轮 review 的反例：恒 daily 豁免面被改成 weekly（每个字段单看都自洽）
    out["exempt_downgraded_to_weekly"] = {**plan, exempt: {"cadence": "weekly", "due": False, "last_probed": _ago(1)}}
    # 慢轨固定档被改写
    out["slow_track_forced_daily"] = {**plan, slow: {"cadence": "daily", "due": True, "last_probed": None}}
    # 前几轮的反例，判据换了之后应当同样被覆盖
    out["non_boolean_due"] = {**plan, names[0]: {**plan[names[0]], "due": None}}
    out["daily_not_due"] = {**plan, names[0]: {"cadence": "daily", "due": False, "last_probed": None}}
    out["fabricated_last_probed"] = {**plan, names[0]: {"cadence": "daily", "due": True, "last_probed": _ago(3)}}
    out["future_last_probed"] = {**plan, names[0]: {"cadence": "daily", "due": True, "last_probed": _ago(-2)}}
    out["invalid_cadence"] = {**plan, names[0]: {**plan[names[0]], "cadence": "hourly"}}
    out["dropped_surface"] = {k: v for k, v in plan.items() if k != names[0]}
    out["extra_surface"] = {**plan, "ghost-surface": {"cadence": "daily", "due": True, "last_probed": None}}
    out["slot_not_a_dict"] = {**plan, names[0]: "not-a-slot"}
    return out


@pytest.mark.parametrize(
    "label",
    [
        "exempt_downgraded_to_weekly",
        "slow_track_forced_daily",
        "non_boolean_due",
        "daily_not_due",
        "fabricated_last_probed",
        "future_last_probed",
        "invalid_cadence",
        "dropped_surface",
        "extra_surface",
        "slot_not_a_dict",
    ],
)
def test_any_deviation_from_recomputed_plan_is_rejected(tmp_path, sample_whitelist, label):
    _seed_stats(tmp_path)
    authentic = _authentic(tmp_path, sample_whitelist)
    _write_plan(tmp_path, _mutations(authentic, sample_whitelist)[label])

    assert trusted_cadence_plan(tmp_path, DATE, sample_whitelist) is None


def test_round4_policy_bypass_counterexample(tmp_path, sample_whitelist):
    """本轮 review 的完整反例：19 个 daily/due=true、55 个 weekly/due=false+昨日。

    每个 slot 对「按 cadence 和 last_probed 重推 due」都自洽，比例也刚过 0.25——
    逐字段校验拦不住，重算比对拦得住。
    """
    _seed_stats(tmp_path)
    names = required_discovery_names(sample_whitelist)
    plan = {
        name: (
            {"cadence": "daily", "due": True, "last_probed": None}
            if i < 19
            else {"cadence": "weekly", "due": False, "last_probed": _ago(1)}
        )
        for i, name in enumerate(names)
    }
    _write_plan(tmp_path, plan)

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_single_core_surface_downgrade_is_rejected(tmp_path, sample_whitelist):
    _seed_stats(tmp_path)
    plan = {**_authentic(tmp_path, sample_whitelist)}
    plan["OpenAI"] = {"cadence": "weekly", "due": False, "last_probed": _ago(1)}
    _write_plan(tmp_path, plan)

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_whitelist_change_after_init_invalidates_plan(tmp_path, sample_whitelist):
    """init 之后 whitelist 增源：重算结果不同 → plan 失效，回退全量。"""
    _seed_stats(tmp_path)
    _write_plan(tmp_path, _authentic(tmp_path, sample_whitelist))
    grown = {
        **sample_whitelist,
        "english_media": sample_whitelist["english_media"]
        + [
            {
                "name": "Brand New Source",
                "category": "english_media",
                "authority_tier": 2,
                "fetch_chain": [{"type": "webfetch", "url": "https://example.com/", "surface_kind": "static"}],
            }
        ],
    }

    assert trusted_cadence_plan(tmp_path, DATE, grown) is None


# --- 幂等：重算必须与 init 时一致 -------------------------------------------


def test_recompute_is_stable_after_same_day_finalize(tmp_path, sample_whitelist):
    """finalize 会写入当天记录；重算时它不得改变分档，否则重跑 finalize 会自我否定。"""
    days = {_ago(o): {"Aider": {"attempts": 2, "hit": False}} for o in range(1, 21)}
    days[_ago(40)] = {"Aider": {"attempts": 2, "hit": False}}
    _seed_stats(tmp_path, days)
    plan_at_init = _authentic(tmp_path, sample_whitelist)
    _write_plan(tmp_path, plan_at_init)

    # 模拟 finalize 写入当天记录后再次校验（重跑 finalize 的场景）
    days[DATE] = {"Aider": {"attempts": 3, "hit": True}}
    _seed_stats(tmp_path, days)

    assert trusted_cadence_plan(tmp_path, DATE, sample_whitelist) == plan_at_init


def test_same_day_record_does_not_affect_ranking(tmp_path, sample_whitelist):
    """当天的采集结果不能影响"今天该不该探"——那是因果倒置。"""
    from source_stats import load_source_stats

    days = {_ago(o): {"Aider": {"attempts": 2, "hit": False}} for o in range(1, 21)}
    days[_ago(40)] = {"Aider": {"attempts": 2, "hit": False}}
    _seed_stats(tmp_path, days)
    before = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)["Aider"]

    days[DATE] = {"Aider": {"attempts": 3, "hit": True}}
    _seed_stats(tmp_path, days)
    after = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)["Aider"]

    assert before == after


# 原「不传 whitelist 时走弱判据」的用例已删除：它把一条不安全的兼容行为固化成了契约。
# 那条兼容分支是为一个不存在的约束做的妥协——仓内两个生产调用都传了 whitelist，而这个
# PR 尚未合并，根本没有"既有调用方"。whitelist 现为必需参数，省略即 TypeError，
# 断言见 test_no_downgrade_bypass.py。
