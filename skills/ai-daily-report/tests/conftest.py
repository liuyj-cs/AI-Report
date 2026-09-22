import sys
from pathlib import Path

import json
import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


@pytest.fixture
def sample_whitelist():
    import yaml

    path = SKILL_ROOT / "sources" / "whitelist.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_daily_report():
    path = SKILL_ROOT / "tests" / "fixtures" / "sample_daily.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_candidate_ledger():
    path = SKILL_ROOT / "tests" / "fixtures" / "sample_candidate_ledger.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_weekly_report():
    path = SKILL_ROOT / "tests" / "fixtures" / "sample_weekly.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def normalized_weekly_report(sample_weekly_report):
    payload = json.loads(json.dumps(sample_weekly_report, ensure_ascii=False))
    payload["sections"]["frontier_models"]["vendor_groups"][1]["references"][0]["editorial_tier"] = "watch"
    payload["sections"]["action_items"]["items"][1]["references"][0]["editorial_tier"] = "watch"
    payload["sections"]["action_items"]["items"][2]["references"][0]["headline"] = "Composer 2.0 内测开放"
    return payload


@pytest.fixture
def sample_deep_dive():
    return {
        "version": "1.0",
        "type": "deep_dive",
        "date": "2026-06-13",
        "event_slug": "claude-fable-5",
        "title": "Claude Fable 5 / Mythos 5 发布",
        "generated_at": "2026-06-13T10:00:00+08:00",
        "sections": {
            "background": "Anthropic 于 2026-06-10 发布 Claude 5 家族首个模型 Fable 5，与受信网络版 Mythos 5 同源。此前 Claude 4.x 家族以 Opus 4.8 为旗舰，本次是 Mythos 级能力首次开放到通用用户侧，发布当天即在 API 与 Claude Code 可用。",
            "what_shipped_detail": "Fable 5 与 Mythos 5 共享同一底层模型，Fable 5 面向通用市场并带有针对双用途能力的额外安全措施，Mythos 5 仅向获批组织开放。官方同步更新了模型卡、定价页与开发者文档，模型号 claude-fable-5，Claude Code 与 API 当天可用，定价沿用 Opus 档位。官方公告强调长任务执行与 agent 编排能力的提升，并给出与 Opus 4.8 的对比基准。",
            "benchmarks_pricing": "官方模型卡给出 SWE-bench Verified 与 Terminal-Bench 对比数字，定价沿用 Opus 档位，API 与 Claude Code 当天可用，未单列新配额档。",
            "ecosystem_reaction": "发布当天第三方榜单（LMArena / Artificial Analysis）尚未收录，社区讨论集中在 Mythos 准入条件与 Fable/Mythos 的能力差异，暂无可引用的独立评测数据。",
            "role_implications": [
                {"role": "选型负责人", "implication": "Claude 档位的性价比判断需要重估，建议把 Fable 5 纳入当前评估矩阵再做结论。"},
                {"role": "workplace AI", "implication": "通用侧能力上限提高，值得在现有工作流里对比一轮回答质量与长任务表现。"},
                {"role": "技术总监", "implication": "Mythos 级模型开放通用侧是供应商梯队变化信号，关注后续竞品应对节奏。"},
                {"role": "深度使用工程师", "implication": "Claude Code 中可直接切换 claude-fable-5，优先验证长任务与多文件重构场景。"},
            ],
            "quick_start": "Claude Code 内用 /model 切换到 claude-fable-5 即可试用；API 侧把模型号换成 claude-fable-5，无需改请求结构，注意先在非生产环境验证工具调用行为。",
            "open_questions": [
                "第三方 benchmark（LMArena / AA）何时收录",
                "长任务实测是否稳定优于 Opus 4.8",
            ],
        },
        "references": [
            {"source": "Anthropic", "url": "https://www.anthropic.com/news/claude-fable-5-mythos-5"}
        ],
    }


@pytest.fixture
def research_deep_dive():
    """Synthetic research evidence; never used as a published report."""
    return {
        "version": "1.1", "type": "deep_dive", "date": "2026-06-13",
        "event_slug": "task-routing", "title": "测试样例：任务路由选择",
        "generated_at": "2026-06-13T10:00:00+08:00",
        "decision_question": "样例中的 A 是否适合替代 B？",
        "incremental_value": "区分工具任务与长任务的取舍，补充失败项。",
        "sections": {
            "verdict": "只考虑工具任务；长任务维持原方案。",
            "comparisons": [{"dimension": "工具任务", "finding": "A 73%，B 65%；长任务 A -2，B 0。",
                "conditions": "同一框架和预算，样本量未披露。", "interpretation": "工具任务有优势，不能外推长任务。", "reference_ids": ["eval"]}],
            "scenarios": [{"task": "工具辅助检索", "recommendation": "conditional", "reason": "需先验证业务文档；<script>unsafe</script>",
                "evidence_boundary": "inferred", "reference_ids": ["eval"]}],
            "costs_and_constraints": {"analysis": "缺少完整任务费用，不据单价判断节省。", "reference_ids": ["eval"]},
            "remaining_unknowns": [{"question": "业务召回是否保持？", "kind": "business_validation", "checked": "已查看样例评测表。", "decision_impact": "未验证前不迁移默认路由。"}],
            "next_action": "固定业务样本对照，召回下降则维持现状。",
        },
        "references": [{"id": "eval", "source": "Synthetic evaluator", "url": "https://eval.example/task-routing",
            "evidence_type": "independent", "observed_at": "2026-06-13T09:00:00+08:00"}],
    }


@pytest.fixture
def finalized_fetch_status():
    from discovery import initial_fetch_status, iter_named_sources

    def _build(whitelist):
        payload = initial_fetch_status(whitelist)
        high_recall = {
            source["name"]
            for source in iter_named_sources(whitelist)
            if source.get("category") in ("cn_labs", "hard_data")
        }
        for name, detail in payload["source_details"].items():
            attempts = []
            for attempt in detail.get("attempts", []):
                attempts.append(
                    {
                        **attempt,
                        "result": "success_but_empty",
                        "note": "discovery completed without candidate in fixture",
                    }
                )
                attempts[-1].pop("reason", None)
            if name in high_recall:
                attempts.append(
                    {
                        "layer_index": len(attempts),
                        "layer_type": "websearch_scoped",
                        "target": f"{name} fallback search",
                        "result": "success_but_empty",
                        "note": "search fallback ran empty in fixture",
                    }
                )
            detail["attempts"] = attempts
        payload["succeeded"] = sorted(payload["source_details"].keys())
        payload["failed"] = []
        payload["empty"] = sorted(payload["source_details"].keys())
        return payload

    return _build
