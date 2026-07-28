"""复验发现的加固：守门判据必须信 attempts 实迹，不信自报字段；重跑不塌基准。"""
import json
from datetime import date, timedelta

from discovery import compute_cadence, due_discovery_names, load_whitelist
from editorial import validate_recall_fallback_coverage

TARGET = "2026-07-27"
NAME = "DeepSeek"


def _report(attempts, final_layer_index):
    return {
        "fetch_status": {
            "succeeded": [NAME],
            "failed": [],
            "empty": [NAME],
            "source_details": {
                NAME: {"final_layer_index": final_layer_index, "attempts": attempts}
            },
        }
    }


def _fetch_attempts(indexes):
    return [
        {"layer_index": i, "layer_type": "webfetch", "target": "x", "result": "success_but_empty"}
        for i in indexes
    ]


def test_self_declared_final_index_cannot_bypass_chain_exhaustion():
    """只抓了 L0 却自报 final_layer_index=2 —— 判据必须按 attempts 实迹判 BLOCK。"""
    whitelist = load_whitelist()

    errors = validate_recall_fallback_coverage(_report(_fetch_attempts([0]), 2), whitelist)

    assert len(errors) == 1
    assert NAME in errors[0]


def test_empty_attempts_with_declared_index_is_fail_closed():
    whitelist = load_whitelist()

    assert len(validate_recall_fallback_coverage(_report([], 2), whitelist)) == 1


def test_stale_final_index_does_not_cause_false_block():
    """实际走完了 L0-L2，只是 final_layer_index 没更新 —— 不该误报。"""
    whitelist = load_whitelist()

    assert validate_recall_fallback_coverage(_report(_fetch_attempts([0, 1, 2]), 0), whitelist) == []


def test_same_day_reinit_does_not_shrink_due_baseline(sample_whitelist):
    """同日重跑 init-daily 后，due 不得因为"今天已探过"而塌掉。"""
    stats = {
        "version": "1.0",
        "days": {TARGET: {"OpenAI": {"attempts": 1, "hit": True}, "Aider": {"attempts": 1, "hit": False}}},
    }

    plan = compute_cadence(sample_whitelist, stats, TARGET)

    assert plan["OpenAI"]["due"] is True
    assert plan["Aider"]["due"] is True


# test_today_entry_still_counts_for_hit_ranking 已删除：它断言当天记录参与命中率
# 统计，而那个设计会让 init 与 finalize 重算结果不一致（重跑 finalize 自我否定），
# 语义上也是用今天探的结果决定今天该不该探。相反的断言见
# test_cadence_plan_authority.py::test_same_day_record_does_not_affect_ranking。


def test_narrow_due_list_falls_back_to_full_baseline(tmp_path):
    """due 塌到远少于豁免面数量 → plan 不可信，回退全量。"""
    cache_dir = tmp_path / "cache" / TARGET
    cache_dir.mkdir(parents=True)
    plan = {f"surface-{i}": {"cadence": "weekly", "due": False, "last_probed": None} for i in range(73)}
    plan["OpenAI"] = {"cadence": "daily", "due": True, "last_probed": None}
    plan["Anthropic"] = {"cadence": "daily", "due": True, "last_probed": None}
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"date": TARGET, "cadence_plan": plan}), encoding="utf-8"
    )

    assert due_discovery_names(tmp_path, TARGET) is None


def test_healthy_due_list_is_used(tmp_path):
    cache_dir = tmp_path / "cache" / TARGET
    cache_dir.mkdir(parents=True)
    plan = {f"surface-{i}": {"cadence": "daily", "due": True, "last_probed": None} for i in range(60)}
    plan["cold"] = {"cadence": "weekly", "due": False, "last_probed": "2026-07-24"}
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps({"date": TARGET, "cadence_plan": plan}), encoding="utf-8"
    )

    due = due_discovery_names(tmp_path, TARGET)

    assert due is not None
    assert "cold" not in due
    assert len(due) == 60


def test_sparse_rule_does_not_demote_after_pipeline_outage(sample_whitelist):
    """管线停摆造成的探测稀疏，不能被当成"按 weekly 节奏在探"。"""
    target = date.fromisoformat(TARGET)
    # 40 天前起连续探了 10 天，之后停摆至今
    days = {
        (target - timedelta(days=offset)).isoformat(): {"Aider": {"attempts": 1, "hit": False}}
        for offset in range(31, 41)
    }

    plan = compute_cadence(sample_whitelist, {"version": "1.0", "days": days}, TARGET)

    assert plan["Aider"]["cadence"] == "daily"
    assert plan["Aider"]["due"] is True
