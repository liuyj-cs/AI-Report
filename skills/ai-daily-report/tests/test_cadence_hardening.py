"""终审发现的边界加固：未来日期、非法日期、weekly 档振荡、due 基准 fail-open。"""
import json
from datetime import date, timedelta

import pytest

from discovery import compute_cadence, due_discovery_names

TARGET = "2026-07-27"
LONGTAIL = "Aider"


def _stats(days):
    return {"version": "1.0", "days": days}


def _days_back(name, count, *, hit_on=(), start_offset=1, step=1):
    target = date.fromisoformat(TARGET)
    days = {}
    for offset in range(start_offset, start_offset + count * step, step):
        days[(target - timedelta(days=offset)).isoformat()] = {
            name: {"attempts": 2, "hit": offset in hit_on}
        }
    return days


def test_future_dated_ledger_entry_never_suppresses_due(sample_whitelist):
    """未来日期（--date 笔误 / 时钟偏移）不得让全部面变成 not-due。"""
    future = (date.fromisoformat(TARGET) + timedelta(days=65)).isoformat()
    stats = _stats({future: {"OpenAI": {"attempts": 1, "hit": False}}})

    plan = compute_cadence(sample_whitelist, stats, TARGET)

    assert plan["OpenAI"]["due"] is True
    assert plan["OpenAI"]["last_probed"] is None


def test_future_entries_do_not_count_as_probes(sample_whitelist):
    days = _days_back(LONGTAIL, 20)
    future = (date.fromisoformat(TARGET) + timedelta(days=3)).isoformat()
    days[future] = {LONGTAIL: {"attempts": 1, "hit": True}}

    plan = compute_cadence(sample_whitelist, _stats(days), TARGET)

    # 未来那条"命中"不得把长尾面救回 daily
    assert plan[LONGTAIL]["cadence"] == "weekly"


# 「空 due 名单回退」用例已删除：同属比例守卫，已由重算比对覆盖。


def test_invalid_target_date_raises_clear_error(sample_whitelist):
    with pytest.raises(ValueError, match="target_date"):
        compute_cadence(sample_whitelist, _stats({}), "2026-02-30")


def test_weekly_cadence_does_not_oscillate_back_to_daily(sample_whitelist):
    """降到 weekly 后实探日自然跌破 10，档位必须稳住，否则省不下抓取量。"""
    # 已观察 60 天、近 30 天按 weekly 节奏只探了 5 次、全部零命中
    days = _days_back(LONGTAIL, 5, start_offset=7, step=7)
    days[(date.fromisoformat(TARGET) - timedelta(days=60)).isoformat()] = {
        LONGTAIL: {"attempts": 1, "hit": False}
    }

    plan = compute_cadence(sample_whitelist, _stats(days), TARGET)

    assert plan[LONGTAIL]["cadence"] == "weekly"


def test_long_observed_surface_with_one_hit_still_downgrades_to_two_days(sample_whitelist):
    """稳态判据放宽只对零命中面生效，有命中的仍走 every_2_days，不被误降 weekly。"""
    days = _days_back(LONGTAIL, 5, hit_on=(14,), start_offset=7, step=7)
    days[(date.fromisoformat(TARGET) - timedelta(days=60)).isoformat()] = {
        LONGTAIL: {"attempts": 1, "hit": False}
    }

    plan = compute_cadence(sample_whitelist, _stats(days), TARGET)

    assert plan[LONGTAIL]["cadence"] == "every_2_days"


def test_short_history_surface_is_not_downgraded_by_relaxed_rule(sample_whitelist):
    """放宽判据不得绕过 14 天新源保护。"""
    days = _days_back(LONGTAIL, 4, start_offset=1, step=3)

    plan = compute_cadence(sample_whitelist, _stats(days), TARGET)

    assert plan[LONGTAIL]["cadence"] == "daily"
