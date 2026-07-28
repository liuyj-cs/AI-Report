"""契约唯一性：不允许「省略某个参数就退回弱校验」的旁路。

五轮 review 的统一根因是**契约不唯一**：前四轮它由一堆逐字段规则隐式拼凑（拼凑必有
缝），第五轮它显式了、却还留着第二条不遵守它的入口。可选参数正是把契约强度交给调用点
的典型形式——只要它存在，"后续新增调用误用"就只是时间问题。

所以这些测试断言的不是某个具体反例被拒，而是**旁路本身不存在**：让签名强制契约，
而不是靠调用方自觉。
"""
import inspect
import json
from datetime import date, timedelta

import pytest

from discovery import (
    compute_cadence,
    due_discovery_names,
    trusted_cadence_plan,
    required_discovery_names,
)
from editorial import validate_fetch_status_integrity
from source_stats import load_source_stats, source_stats_path

DATE = "2026-07-28"
TARGET = date.fromisoformat(DATE)


def _ago(n):
    return (TARGET - timedelta(days=n)).isoformat()


def _seed(tmp_path, days=None):
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "days": days or {}}, ensure_ascii=False), encoding="utf-8")


def _write_plan(tmp_path, plan):
    cache_dir = tmp_path / "cache" / DATE
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"date": DATE, "cadence_plan": plan}, ensure_ascii=False), encoding="utf-8"
    )


# --- 签名层：不允许省略 --------------------------------------------------


@pytest.mark.parametrize(
    "func, param",
    [
        (trusted_cadence_plan, "whitelist"),
        (due_discovery_names, "whitelist"),
        (validate_fetch_status_integrity, "cadence_plan"),
    ],
)
def test_contract_carrying_params_have_no_default(func, param):
    """承载校验契约的参数不得有默认值——有默认值就等于给了一条弱校验旁路。"""
    sig = inspect.signature(func)
    assert param in sig.parameters, f"{func.__name__} 缺少 {param}"
    assert sig.parameters[param].default is inspect.Parameter.empty, (
        f"{func.__name__}({param}=...) 有默认值：省略它就会退回弱校验，"
        f"契约必须由签名强制，不能靠调用方自觉"
    )


@pytest.mark.parametrize("func", [trusted_cadence_plan, due_discovery_names])
def test_omitting_whitelist_is_a_type_error(tmp_path, func):
    with pytest.raises(TypeError):
        func(tmp_path, DATE)


def test_validate_integrity_requires_cadence_plan(sample_whitelist):
    with pytest.raises(TypeError):
        validate_fetch_status_integrity({"fetch_status": {}}, sample_whitelist)


# --- 行为层：round-4 反例在任何调用形态下都被拒 ---------------------------


def test_round4_bypass_rejected_in_every_call_shape(tmp_path, sample_whitelist):
    """同一份 19/74 的 plan：无论位置传参还是关键字传参，都必须回退全量。"""
    _seed(tmp_path)
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

    assert trusted_cadence_plan(tmp_path, DATE, sample_whitelist) is None
    assert due_discovery_names(tmp_path, DATE, sample_whitelist) is None
    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_authentic_plan_accepted_in_every_call_shape(tmp_path, sample_whitelist):
    _seed(tmp_path)
    plan = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)
    _write_plan(tmp_path, plan)

    assert trusted_cadence_plan(tmp_path, DATE, sample_whitelist) == plan
    assert due_discovery_names(tmp_path, DATE, sample_whitelist) is not None


# --- 唤醒审计不得因缺参数而静默失效 ---------------------------------------


def test_wakeup_audit_cannot_be_silently_skipped(tmp_path, sample_whitelist, finalized_fetch_status):
    """cadence_plan 曾是可选的：省略它，非 due 面的唤醒审计就静默失效。

    与 whitelist 那条同构——reviewer 未提出，但同一契约缺陷。
    """
    _seed(tmp_path, {_ago(o): {"Aider": {"attempts": 2, "hit": False}} for o in range(1, 21)}
          | {_ago(40): {"Aider": {"attempts": 2, "hit": False}}})
    plan = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)
    assert plan["Aider"]["due"] is False  # 前置：Aider 当日非 due

    fs = finalized_fetch_status(sample_whitelist)  # 含 Aider，但没有 wakeup_reason
    errors = validate_fetch_status_integrity({"fetch_status": fs}, sample_whitelist, plan)

    assert any("Aider" in e and "wakeup_reason" in e for e in errors)


def test_wakeup_audit_passes_with_reason(tmp_path, sample_whitelist, finalized_fetch_status):
    _seed(tmp_path, {_ago(o): {"Aider": {"attempts": 2, "hit": False}} for o in range(1, 21)}
          | {_ago(40): {"Aider": {"attempts": 2, "hit": False}}})
    plan = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)

    fs = finalized_fetch_status(sample_whitelist)
    fs["source_details"]["Aider"]["attempts"][0]["wakeup_reason"] = "媒体信号指向该源当日有发布"
    errors = validate_fetch_status_integrity({"fetch_status": fs}, sample_whitelist, plan)

    assert not any("Aider" in e for e in errors)


# --- 冗余参数消除：due 名单只有一个来源 -----------------------------------


def test_due_names_are_derived_not_passed_separately():
    """due_names 曾与 cadence_plan 并列为参数——同一事实两个来源，必然有不一致的一天。"""
    params = set(inspect.signature(validate_fetch_status_integrity).parameters)

    assert "due_names" not in params, "due 名单必须从 cadence_plan 推导，不得单独传入"
