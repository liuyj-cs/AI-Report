"""PR #5 复审发现的边界：结构校验必须按类型判，不能靠 truthiness 与比例启发式。

两条的共同教训：**坏数据不能被"解释"成合法的负样本**——`due: null` 被 truthiness
读成"不用探"，`attempts: "corrupt"` 被强转成"探了 0 次没命中"，都是把损坏悄悄变成
了一个看起来正常的调度结论。
"""
import json
from datetime import date, timedelta

import pytest

from discovery import (
    compute_cadence,
    due_discovery_names,
    required_discovery_names,
)
from source_stats import load_source_stats, source_stats_path

DATE = "2026-07-28"
COLD = "Aider"


def _manifest(tmp_path, payload):
    cache_dir = tmp_path / "cache" / DATE
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _plan(whitelist, **overrides):
    plan = {
        name: {"cadence": "daily", "due": True, "last_probed": None}
        for name in required_discovery_names(whitelist)
    }
    plan.update(overrides)
    return plan


# --- P1-1: slot 必须按类型校验 ---------------------------------------------


@pytest.mark.parametrize("bad_due", [None, 0, 1, "false", "true", "", [], {}])
def test_non_boolean_due_rejects_whole_plan(tmp_path, sample_whitelist, bad_due):
    plan = _plan(sample_whitelist)
    plan[COLD] = {"cadence": "daily", "due": bad_due, "last_probed": None}
    _manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_null_due_majority_cannot_slip_past_ratio_guard(tmp_path, sample_whitelist):
    """复审的原始反例：19/74 due=true、其余 due=null，比例 0.257 刚好擦过 0.25 守卫。

    比例守卫是最后兜底，不是结构校验的替代品——类型不对就该整体回退。
    """
    names = required_discovery_names(sample_whitelist)
    plan = {
        name: {"cadence": "daily", "due": (True if i < 19 else None), "last_probed": None}
        for i, name in enumerate(names)
    }
    _manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_missing_manifest_date_rejects_plan(tmp_path, sample_whitelist):
    _manifest(tmp_path, {"cadence_plan": _plan(sample_whitelist)})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


@pytest.mark.parametrize("bad_cadence", ["hourly", "", None, 7, "DAILY"])
def test_invalid_cadence_enum_rejects_plan(tmp_path, sample_whitelist, bad_cadence):
    plan = _plan(sample_whitelist)
    plan[COLD] = {"cadence": bad_cadence, "due": True, "last_probed": None}
    _manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


@pytest.mark.parametrize("bad_probed", ["not-a-date", "2026-02-30", 20260727, [], {}])
def test_invalid_last_probed_rejects_plan(tmp_path, sample_whitelist, bad_probed):
    plan = _plan(sample_whitelist)
    plan[COLD] = {"cadence": "weekly", "due": False, "last_probed": bad_probed}
    _manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_wellformed_plan_still_accepted(tmp_path, sample_whitelist):
    plan = _plan(sample_whitelist, **{COLD: {"cadence": "weekly", "due": False, "last_probed": "2026-07-25"}})
    _manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    due = due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist)

    assert due is not None
    assert COLD not in due
    assert "OpenAI" in due


def test_last_probed_null_is_valid(tmp_path, sample_whitelist):
    _manifest(tmp_path, {"date": DATE, "cadence_plan": _plan(sample_whitelist)})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is not None


# --- P1-2: 坏 record 不得被解释成零命中探测 --------------------------------


def _seed(tmp_path, record, days_back=15):
    target = date.fromisoformat(DATE)
    days = {
        (target - timedelta(days=offset)).isoformat(): {COLD: record}
        for offset in range(1, days_back + 1)
    }
    # 拉开台账观察期，越过 14 天新源保护，让降频路径真正可达
    days[(target - timedelta(days=40)).isoformat()] = {COLD: record}
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "days": days}, ensure_ascii=False), encoding="utf-8")


@pytest.mark.parametrize(
    "record",
    [
        {"attempts": "corrupt", "hit": None},
        {"attempts": None, "hit": False},
        {"attempts": 1.5, "hit": False},
        {"attempts": True, "hit": False},
        {"attempts": -3, "hit": False},
        {"attempts": 1, "hit": "no"},
        {"attempts": 1, "hit": 0},
        {"attempts": 1},
        {"hit": False},
        {},
    ],
)
def test_corrupt_record_is_dropped_not_counted_as_miss(tmp_path, sample_whitelist, record):
    _seed(tmp_path, record)

    stats = load_source_stats(tmp_path)
    assert all(COLD not in entry for entry in stats["days"].values())

    plan = compute_cadence(sample_whitelist, stats, DATE)
    assert plan[COLD]["cadence"] == "daily"
    assert plan[COLD]["due"] is True


def test_valid_records_still_drive_downgrade(tmp_path, sample_whitelist):
    """加固不能把正常降频也一起挡掉。"""
    _seed(tmp_path, {"attempts": 2, "hit": False})

    plan = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)

    assert plan[COLD]["cadence"] == "weekly"


def test_zero_attempts_record_is_valid(tmp_path, sample_whitelist):
    """attempts=0 是合法值（面被跳过但记了一笔），不该当成损坏。"""
    _seed(tmp_path, {"attempts": 0, "hit": False})

    stats = load_source_stats(tmp_path)

    assert any(COLD in entry for entry in stats["days"].values())


def test_mixed_valid_and_corrupt_records_keep_the_valid_ones(tmp_path):
    target = date.fromisoformat(DATE)
    day = (target - timedelta(days=1)).isoformat()
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": "1.0", "days": {day: {"OpenAI": {"attempts": 3, "hit": True}, COLD: {"attempts": "x", "hit": None}}}}
        ),
        encoding="utf-8",
    )

    entry = load_source_stats(tmp_path)["days"][day]

    assert entry == {"OpenAI": {"attempts": 3, "hit": True}}
