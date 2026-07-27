from datetime import date, timedelta

import pytest

from discovery import (
    LEADER_INTERVIEW_DISCOVERY_NAME,
    METHODOLOGY_DISCOVERY_NAME,
    RECALL_PROBE_SURFACE_NAME,
    compute_cadence,
)

TARGET = "2026-07-27"
# 非豁免的具名源：不在 core_sources、tier != 1、category != hard_data
LONGTAIL = "Aider"
CORE = "OpenAI"
TIER1 = "智谱 GLM"
HARD_DATA = "LMArena Leaderboard"


def _stats(entries: dict[str, dict[str, dict]]) -> dict:
    return {"version": "1.0", "days": entries}


def _days_back(name, count, *, hit_on=(), start_offset=1):
    """连续 count 天（从 target 往回）都探过该面，hit_on 里的偏移量记命中。"""
    target = date.fromisoformat(TARGET)
    days = {}
    for offset in range(start_offset, start_offset + count):
        day = (target - timedelta(days=offset)).isoformat()
        days[day] = {name: {"attempts": 2, "hit": offset in hit_on}}
    return days


def test_empty_ledger_keeps_every_surface_daily(sample_whitelist):
    result = compute_cadence(sample_whitelist, _stats({}), TARGET)

    assert result[LONGTAIL]["cadence"] == "daily"
    assert result[LONGTAIL]["due"] is True
    assert result[LONGTAIL]["last_probed"] is None


def test_frequent_hits_stay_daily(sample_whitelist):
    stats = _stats(_days_back(LONGTAIL, 20, hit_on=(2, 5, 9)))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[LONGTAIL]["cadence"] == "daily"
    assert result[LONGTAIL]["due"] is True


def test_sparse_hits_drop_to_every_two_days(sample_whitelist):
    stats = _stats(_days_back(LONGTAIL, 20, hit_on=(4, 11)))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[LONGTAIL]["cadence"] == "every_2_days"


def test_zero_hits_with_enough_probes_drop_to_weekly(sample_whitelist):
    stats = _stats(_days_back(LONGTAIL, 20))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[LONGTAIL]["cadence"] == "weekly"
    # 昨天刚探过 → 未到 7 天间隔
    assert result[LONGTAIL]["due"] is False
    assert result[LONGTAIL]["last_probed"] == (date.fromisoformat(TARGET) - timedelta(days=1)).isoformat()


def test_new_source_never_downgraded_before_14_days(sample_whitelist):
    # 零命中、探测 12 天：探测次数够但台账首见不足 14 天 → 仍 daily
    stats = _stats(_days_back(LONGTAIL, 12))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[LONGTAIL]["cadence"] == "daily"


def test_zero_hits_but_too_few_probes_stays_daily(sample_whitelist):
    # 首见 20 天前，但只实探了 8 天（< 10）→ 不够判长尾
    target = date.fromisoformat(TARGET)
    days = {}
    for offset in list(range(1, 8)) + [20]:
        day = (target - timedelta(days=offset)).isoformat()
        days[day] = {LONGTAIL: {"attempts": 1, "hit": False}}
    result = compute_cadence(sample_whitelist, _stats(days), TARGET)

    assert result[LONGTAIL]["cadence"] == "daily"


@pytest.mark.parametrize("name", [CORE, TIER1, HARD_DATA])
def test_exempt_sources_stay_daily_despite_zero_hits(sample_whitelist, name):
    stats = _stats(_days_back(name, 30))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[name]["cadence"] == "daily"
    assert result[name]["due"] is True


def test_cadence_pin_forces_daily(sample_whitelist):
    pinned = {
        **sample_whitelist,
        "coding_agents_secondary": [
            {**source, "cadence": "daily"} if source["name"] == LONGTAIL else source
            for source in sample_whitelist["coding_agents_secondary"]
        ],
    }
    stats = _stats(_days_back(LONGTAIL, 30))
    result = compute_cadence(pinned, stats, TARGET)

    assert result[LONGTAIL]["cadence"] == "daily"


def test_aggregate_probe_surfaces_stay_daily(sample_whitelist):
    stats = _stats(_days_back(RECALL_PROBE_SURFACE_NAME, 30))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[RECALL_PROBE_SURFACE_NAME]["cadence"] == "daily"


@pytest.mark.parametrize(
    "name", [LEADER_INTERVIEW_DISCOVERY_NAME, METHODOLOGY_DISCOVERY_NAME]
)
def test_slow_track_surfaces_fixed_every_two_days(sample_whitelist, name):
    # 慢信号轨道固定隔日，不参与命中率浮动：命中再多也不回 daily
    stats = _stats(_days_back(name, 30, hit_on=tuple(range(1, 31))))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[name]["cadence"] == "every_2_days"


def test_due_uses_interval_since_last_probe(sample_whitelist):
    target = date.fromisoformat(TARGET)
    # 慢轨面上次探测在 2 天前 → 到期
    stats = _stats(
        {
            (target - timedelta(days=2)).isoformat(): {
                LEADER_INTERVIEW_DISCOVERY_NAME: {"attempts": 1, "hit": False}
            }
        }
    )
    result = compute_cadence(sample_whitelist, stats, TARGET)
    assert result[LEADER_INTERVIEW_DISCOVERY_NAME]["due"] is True

    # 上次探测在 1 天前 → 未到期
    stats = _stats(
        {
            (target - timedelta(days=1)).isoformat(): {
                LEADER_INTERVIEW_DISCOVERY_NAME: {"attempts": 1, "hit": False}
            }
        }
    )
    result = compute_cadence(sample_whitelist, stats, TARGET)
    assert result[LEADER_INTERVIEW_DISCOVERY_NAME]["due"] is False


def test_weekly_surface_becomes_due_after_seven_days(sample_whitelist):
    stats = _stats(_days_back(LONGTAIL, 20, start_offset=7))
    result = compute_cadence(sample_whitelist, stats, TARGET)

    assert result[LONGTAIL]["cadence"] == "weekly"
    assert result[LONGTAIL]["due"] is True


def test_covers_every_required_discovery_name(sample_whitelist):
    from discovery import required_discovery_names

    result = compute_cadence(sample_whitelist, _stats({}), TARGET)

    assert set(result) == set(required_discovery_names(sample_whitelist))


def test_hits_outside_30_day_window_do_not_rescue(sample_whitelist):
    # 窗口内 20 天零命中，命中全部落在 30 天之外 → 仍判长尾降为 weekly
    days = _days_back(LONGTAIL, 20)
    days.update(_days_back(LONGTAIL, 2, hit_on=(35, 40), start_offset=35))
    result = compute_cadence(sample_whitelist, _stats(days), TARGET)

    assert result[LONGTAIL]["cadence"] == "weekly"
