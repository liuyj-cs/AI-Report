from copy import deepcopy
import json
from pathlib import Path

from discovery import initial_fetch_status, load_whitelist
from editorial import (
    build_daily_qa_diff,
    build_weekly_qa_diff,
    eligible_action_refs,
    validate_candidate_ledger_schema,
    validate_daily_artifacts,
    validate_decision_radar,
    validate_major_event_consistency,
    validate_practice_digest,
    validate_weekly_artifacts,
    validate_weekly_source_days,
)


def _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist):
    report = deepcopy(sample_daily_report)
    report["date"] = "2026-04-27"
    report["window"] = {
        "start": "2026-04-26T07:00:00+08:00",
        "end": "2026-04-27T22:28:30+08:00",
        "timezone": "Asia/Shanghai",
    }
    report["generated_at"] = "2026-04-27T22:28:30+08:00"
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["frontier_models"]["items"] = []
    report["sections"]["coding_agents"]["items"] = []
    report["sections"]["coding_agents"]["deep_dive"] = {
        "title": "今日无 coding agent fixture 条目",
        "body": "本 helper 构造最小回归 fixture，未设置 coding agent 正文条目，因此不保留样例报告的深挖引用。",
        "related_item_indexes": [],
    }
    report["sections"]["general_agents"]["items"] = []
    report["sections"]["unverified"]["items"] = []
    report["sections"]["action_items"]["items"] = []
    report["sections"]["market_signals"]["benchmark_changes"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = []
    report["sections"]["market_signals"]["pricing_changes"] = []
    report["sections"]["market_signals"]["adoption_signals"] = []
    report["sections"]["market_signals"]["capability_gaps"] = []
    report["sections"]["pattern_observations"]["items"] = []
    report["sections"]["pattern_observations"]["empty_message"] = "今日无显著跨条目模式"
    report["sections"]["experiments_this_week"]["items"] = []
    report["sections"]["experiments_this_week"]["empty_message"] = "今日无适合 1 日内验证的实验"
    report["sections"]["decision_radar"]["decisions"] = []
    return report


def test_unverified_candidates_never_drive_action_items():
    refs = [
        {"headline": "Official release", "editorial_tier": "core", "decision": "selected_core"},
        {"headline": "Rumor", "editorial_tier": "unverified", "decision": "selected_unverified"},
    ]

    selected = eligible_action_refs(refs)

    assert [item["headline"] for item in selected] == ["Official release"]


def test_validate_daily_artifacts_passes_with_complete_coverage(sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["frontier_models"]["items"] = []
    report["sections"]["coding_agents"]["items"] = []
    report["sections"]["decision_radar"]["decisions"] = []
    report["sections"]["coding_agents"]["deep_dive"] = {
        "title": "今日无 coding agent 新动作",
        "body": "今日无 coding agent 新动作，保持跟踪即可。为满足 schema，本段仅作为空窗说明，不驱动建议。",
        "related_item_indexes": [],
    }
    report["sections"]["general_agents"]["items"] = [
        {
            "product": "OpenAI Agents SDK",
            "vendor": "OpenAI",
            "headline": "Agents SDK 原生接入沙箱执行",
            "summary": "让 agent 可检查文件、跑命令与改代码。",
            "heat_signal": "执行层基础设施更新",
            "source_name": "OpenAI",
            "source_url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
            "published_at": "2026-04-10T05:20:00+08:00",
            "confidence": "high",
            "release_stage": "ga",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "core",
        }
    ]
    report["sections"]["unverified"]["items"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = []
    report["sections"]["market_signals"]["capability_gaps"] = []
    report["sections"]["action_items"]["items"] = [
        {
            "recommendation": "评估 Agents SDK 执行层",
            "rationale": "官方已把文件、命令、代码编辑纳入 SDK 执行面。",
            "recommendation_type": "adopt",
            "effort_person_days": {"min": 1, "max": 2},
            "time_horizon": "this_week",
            "team_size_applicability": ["small_lt_10"],
            "priority": "P1",
            "references": [
                {
                    "date": "2026-04-10",
                    "headline": "Agents SDK 原生接入沙箱执行",
                    "url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
                    "section": "general_agents",
                    "editorial_tier": "core",
                }
            ],
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][0]["proposed_section"] = "general_agents"
    ledger["items"][0]["headline"] = "Agents SDK 原生接入沙箱执行"
    ledger["items"][0]["source_attempt_refs"] = ["OpenAI.attempts[0]"]
    ledger["items"] = ledger["items"][:1]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []


def test_validate_daily_artifacts_rejects_missing_action_item_references(sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["action_items"]["items"][0]["references"] = []

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("missing references" in error for error in errors)


def test_validate_daily_artifacts_rejects_pending_discovery_attempts(sample_daily_report, sample_candidate_ledger):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = initial_fetch_status(whitelist)
    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)
    assert any("pending discovery" in error for error in errors)


def test_validate_daily_artifacts_rejects_invalid_source_attempt_refs(sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["frontier_models"]["items"] = []
    report["sections"]["coding_agents"]["items"] = []
    report["sections"]["coding_agents"]["deep_dive"] = {
        "title": "今日无 coding agent 新动作",
        "body": "今日无 coding agent 新动作，保持跟踪即可。为满足 schema，本段仅作为空窗说明，不驱动建议。",
        "related_item_indexes": [],
    }
    report["sections"]["general_agents"]["items"] = [
        {
            "product": "OpenAI Agents SDK",
            "vendor": "OpenAI",
            "headline": "Agents SDK 原生接入沙箱执行",
            "summary": "让 agent 可检查文件、跑命令与改代码。",
            "heat_signal": "执行层基础设施更新",
            "source_name": "OpenAI",
            "source_url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
            "published_at": "2026-04-10T05:20:00+08:00",
            "confidence": "high",
            "release_stage": "ga",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "core",
        }
    ]
    report["sections"]["unverified"]["items"] = []
    report["sections"]["action_items"]["items"] = [
        {
            "recommendation": "评估 Agents SDK 执行层",
            "rationale": "官方已把文件、命令、代码编辑纳入 SDK 执行面。",
            "recommendation_type": "adopt",
            "effort_person_days": {"min": 1, "max": 2},
            "time_horizon": "this_week",
            "team_size_applicability": ["small_lt_10"],
            "priority": "P1",
            "references": [
                {
                    "date": "2026-04-10",
                    "headline": "Agents SDK 原生接入沙箱执行",
                    "url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
                    "section": "general_agents",
                    "editorial_tier": "core",
                }
            ],
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][0]["proposed_section"] = "general_agents"
    ledger["items"][0]["headline"] = "Agents SDK 原生接入沙箱执行"
    ledger["items"][0]["source_attempt_refs"] = ["OpenAI.attempts[9]"]
    ledger["items"] = ledger["items"][:1]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any("source_attempt_ref" in error for error in errors)


def test_validate_daily_artifacts_rejects_missing_market_signal_coverage(sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["benchmark_changes"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = []
    report["sections"]["market_signals"]["pricing_changes"] = []
    report["sections"]["market_signals"]["capability_gaps"] = []
    report["sections"]["frontier_models"]["items"][1]["headline"] = "DeepSeek V4 榜单评分逼近 o1"
    report["sections"]["frontier_models"]["items"][1]["summary"] = "新 benchmark 显示其在 MATH-500 与 AIME 上继续逼近 o1。"

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("hard-data signal without market_signals coverage" in error for error in errors)


def test_build_daily_qa_diff_marks_downgraded_hard_data_when_note_present(sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["benchmark_changes"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = []
    report["sections"]["market_signals"]["pricing_changes"] = []
    report["sections"]["market_signals"]["capability_gaps"] = []
    report["sections"]["frontier_models"]["items"][1]["headline"] = "DeepSeek V4 榜单评分逼近 o1"
    report["sections"]["frontier_models"]["items"][1]["summary"] = "新 benchmark 显示其在 MATH-500 与 AIME 上继续逼近 o1。"
    report["sections"]["frontier_models"]["items"][1]["hard_data_note"] = "本条先留在正文观察，等稳定前一日基线后再写入 benchmark_watch。"

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)
    qa_diff = build_daily_qa_diff(report, sample_candidate_ledger, whitelist)

    assert not any("hard-data signal without market_signals coverage" in error for error in errors)
    assert any(finding["category"] == "downgraded_evidence" for finding in qa_diff["findings"])
    assert qa_diff["summary"]["categories"]["hard_data_gap"] == 0


def test_build_daily_qa_diff_reports_missing_recall_probe_surface(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    from discovery import RECALL_PROBE_SURFACE_NAME

    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["fetch_status"]["source_details"].pop(RECALL_PROBE_SURFACE_NAME)

    qa_diff = build_daily_qa_diff(report, sample_candidate_ledger, whitelist)

    assert qa_diff["summary"]["categories"]["missed_discovery"] >= 1
    recall_missing_findings = [
        finding
        for finding in qa_diff["findings"]
        if finding["category"] == "missed_discovery"
        and finding["severity"] == "high"
        and finding["source_name"] == RECALL_PROBE_SURFACE_NAME
    ]
    assert len(recall_missing_findings) == 1
    assert "缺少该 discovery surface" in recall_missing_findings[0]["reason"]


def test_build_daily_qa_diff_accepts_rendered_recall_probe_target(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    from discovery import RECALL_PROBE_SURFACE_NAME

    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["date"] = "2026-04-30"
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["fetch_status"]["source_details"][RECALL_PROBE_SURFACE_NAME]["attempts"] = [
        {
            "layer_index": 0,
            "layer_type": "websearch_broad",
            "target": "Cursor SDK @cursor/sdk public beta 2026-04-30",
            "result": "success_but_empty",
            "note": "rendered recall probe query returned no new candidate",
        }
    ]

    qa_diff = build_daily_qa_diff(report, sample_candidate_ledger, whitelist)

    assert not any("未指向 recall_probe_queries" in finding["reason"] for finding in qa_diff["findings"])


def test_build_daily_qa_diff_rejects_recall_probe_attempt_without_probe_target(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    from discovery import RECALL_PROBE_SURFACE_NAME

    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["fetch_status"]["source_details"][RECALL_PROBE_SURFACE_NAME]["attempts"] = [
        {
            "layer_index": 0,
            "layer_type": "websearch_broad",
            "target": "generic AI news",
            "result": "success_but_empty",
            "note": "generic sweep did not execute configured recall probes",
        }
    ]

    qa_diff = build_daily_qa_diff(report, sample_candidate_ledger, whitelist)

    assert qa_diff["summary"]["categories"]["missed_discovery"] >= 1
    assert any("未指向 recall_probe_queries" in finding["reason"] for finding in qa_diff["findings"])


def test_validate_daily_artifacts_rejects_recall_probe_attempt_without_probe_target(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    from discovery import RECALL_PROBE_SURFACE_NAME

    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["fetch_status"]["source_details"][RECALL_PROBE_SURFACE_NAME]["attempts"] = [
        {
            "layer_index": 0,
            "layer_type": "websearch_broad",
            "target": "generic AI news",
            "result": "success_but_empty",
            "note": "generic sweep did not execute configured recall probes",
        }
    ]

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("未指向 recall_probe_queries" in error for error in errors)


def test_build_daily_qa_diff_classifies_duplicate_and_weak_evidence(sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"].append(
        {
            "candidate_id": "duplicate-item",
            "headline": "重复事件",
            "proposed_section": "coding_agents",
            "published_at": "2026-04-10T06:00:00+08:00",
            "source_attempt_refs": ["Anthropic Claude Code.attempts[0]"],
            "verification_state": "official_confirmed",
            "editorial_tier": "watch",
            "decision": "rejected_duplicate",
            "decision_reason": "昨天已写过，今天无新增状态。",
            "novelty_vs_yesterday": "duplicate",
        }
    )
    ledger["items"].append(
        {
            "candidate_id": "weak-evidence-item",
            "headline": "证据过弱事件",
            "proposed_section": "general_agents",
            "published_at": "2026-04-10T06:10:00+08:00",
            "source_attempt_refs": ["OpenAI.attempts[0]"],
            "verification_state": "single_media_only",
            "editorial_tier": "watch",
            "decision": "rejected_weak_evidence",
            "decision_reason": "只有单源媒体转述，没有一跳官方补证。",
            "novelty_vs_yesterday": "new",
        }
    )

    qa_diff = build_daily_qa_diff(report, ledger, whitelist)

    assert qa_diff["summary"]["categories"]["duplicate_rejected"] == 1
    assert qa_diff["summary"]["categories"]["weak_evidence_rejected"] == 1


def test_validate_daily_artifacts_rejects_page_updated_at_for_selected_candidate(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][0]["decision"] = "selected_watch"
    ledger["items"][0]["date_basis"] = "page_updated_at"
    ledger["items"][0]["why_today"] = "页面 updated_at 落在窗口内，但条目小节日期没有落在窗口内。"

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any("page_updated_at cannot support selected_watch" in error for error in errors)


def test_validate_daily_artifacts_rejects_unverified_action_eligibility(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][1]["decision"] = "selected_unverified"
    ledger["items"][1]["action_eligibility"] = "monitor"

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any("selected_unverified must have action_eligibility='none'" in error for error in errors)


def test_validate_daily_artifacts_rejects_media_only_action_eligibility(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][0]["decision"] = "selected_watch"
    ledger["items"][0]["editorial_tier"] = "watch"
    ledger["items"][0]["evidence_path"] = "media_only"
    ledger["items"][0]["action_eligibility"] = "monitor"

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any("evidence_path='media_only' cannot have action_eligibility='monitor'" in error for error in errors)


def test_validate_daily_artifacts_rejects_one_hop_full_action(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][0]["decision"] = "selected_watch"
    ledger["items"][0]["editorial_tier"] = "watch"
    ledger["items"][0]["evidence_path"] = "media_plus_official_one_hop"
    ledger["items"][0]["action_eligibility"] = "full_action"

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any(
        "evidence_path='media_plus_official_one_hop' cannot have action_eligibility='full_action'" in error
        for error in errors
    )


def test_build_daily_qa_diff_reports_ledger_semantic_errors(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][0]["decision"] = "selected_core"
    ledger["items"][0]["evidence_path"] = "media_only"

    qa_diff = build_daily_qa_diff(report, ledger, whitelist)

    assert qa_diff["summary"]["categories"]["reference_integrity_gap"] >= 1
    assert any("selected_core requires evidence_path='primary'" in finding["reason"] for finding in qa_diff["findings"])


def test_validate_daily_artifacts_allows_rejected_candidate_raw_action_metadata(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"][0]["decision"] = "rejected_weak_evidence"
    ledger["items"][0]["evidence_path"] = "media_only"
    ledger["items"][0]["action_eligibility"] = "full_action"

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert not any("cannot have action_eligibility='full_action'" in error for error in errors)


def test_validate_daily_artifacts_rejects_capability_gap_without_ref(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["benchmark_changes"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = []
    report["sections"]["market_signals"]["pricing_changes"] = []
    report["sections"]["market_signals"]["capability_gaps"] = [
        {
            "text": "LMArena 前四全部为 Claude，Anthropic 形成结构性领先。",
            "evidence": "LMArena leaderboard snapshot",
        }
    ]

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("capability_gaps[0] has hard-data language but no ref" in error for error in errors)


def test_validate_daily_artifacts_rejects_capability_gap_without_ref_when_other_bucket_exists(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["benchmark_changes"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = [
        {
            "vendor": "OpenAI",
            "model": "GPT-5",
            "source": "LMArena",
            "signal": "当天榜单快照已有独立 ref。",
            "observed_at": "2026-04-18T07:00:00+08:00",
            "ref": "frontier_models[0]",
        }
    ]
    report["sections"]["market_signals"]["pricing_changes"] = []
    report["sections"]["market_signals"]["capability_gaps"] = [
        {
            "text": "Claude 在 leaderboard score 上仍保持优势。",
            "evidence": "LMArena leaderboard snapshot",
        }
    ]

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("capability_gaps[0] has hard-data language but no ref" in error for error in errors)


def test_validate_daily_artifacts_rejects_market_signal_ref_out_of_range(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["benchmark_watch"][0]["ref"] = "frontier_models[99]"

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("benchmark_watch[0].ref points past frontier_models[99]" in error for error in errors)


def test_validate_daily_artifacts_rejects_benchmark_watch_missing_ref(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["benchmark_watch"][0].pop("ref", None)

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("benchmark_watch[0].ref missing" in error for error in errors)


def test_2026_04_27_openai_microsoft_partnership_can_be_selected(
    sample_daily_report,
    finalized_fetch_status,
    sample_candidate_ledger,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["sections"]["frontier_models"]["items"] = [
        {
            "vendor": "OpenAI / Microsoft",
            "vendor_region": "US",
            "headline": "微软-OpenAI 合作进入下一阶段",
            "summary": "OpenAI 可跨云分发产品，微软仍保留 IP 授权。",
            "impact": "多云采购与模型分发格局松动。",
            "source_name": "OpenAI Blog",
            "source_url": "https://openai.com/index/next-phase-of-microsoft-partnership/",
            "published_at": "2026-04-27",
            "confidence": "high",
            "release_stage": "announced",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "core",
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "openai-microsoft-next-phase-2026-04-27",
            "headline": "微软-OpenAI 合作进入下一阶段",
            "proposed_section": "frontier_models",
            "published_at": "2026-04-27",
            "source_attempt_refs": ["OpenAI.attempts[0]"],
            "verification_state": "official_confirmed",
            "editorial_tier": "core",
            "decision": "selected_core",
            "decision_reason": "OpenAI 官方页面日期落在窗口内，属于公司级分发与基础设施变化。",
            "novelty_vs_yesterday": "new",
            "event_type": "partnership",
            "date_basis": "official_event_date",
            "evidence_path": "primary",
            "why_today": "OpenAI 官方页面日期为 2026-04-27。",
            "action_eligibility": "full_action",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []


def test_2026_04_27_help_center_page_update_cannot_select_window_out_item(
    sample_daily_report,
    finalized_fetch_status,
    sample_candidate_ledger,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "chatgpt-business-japan-data-residency",
            "headline": "ChatGPT Business 日本数据本地化",
            "proposed_section": "frontier_models",
            "published_at": "2026-04-22",
            "source_attempt_refs": ["OpenAI.attempts[0]"],
            "verification_state": "help_center_section_date_window_outside",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "页面 updated_at 在窗口内，但 Help Center 小节日期是 2026-04-22。",
            "novelty_vs_yesterday": "not_new",
            "event_type": "enterprise_update",
            "date_basis": "page_updated_at",
            "evidence_path": "primary",
            "why_today": "仅页面 updated_at 落在窗口内。",
            "action_eligibility": "monitor",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any("page_updated_at cannot support selected_watch" in error for error in errors)


def test_2026_04_27_dirac_benchmark_without_delta_needs_watch_ref(
    sample_daily_report,
    finalized_fetch_status,
    sample_candidate_ledger,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["sections"]["coding_agents"]["items"] = [
        {
            "product": "Dirac",
            "product_tier": "secondary",
            "headline": "Dirac Terminal-Bench-2 观察",
            "summary": "社区讨论显示 Dirac 跑出 65.2% 的 benchmark 分数。",
            "impact": "小模型与成本优化路径值得复测。",
            "source_name": "GitHub / Hugging Face",
            "source_url": "https://github.com/dirac-run/dirac",
            "published_at": "2026-04-27",
            "confidence": "medium",
            "release_stage": "announced",
            "published_at_confidence": "approximate",
            "authority_score": 3,
            "editorial_tier": "watch",
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "dirac-terminal-bench-2-2026-04-27",
            "headline": "Dirac Terminal-Bench-2 观察",
            "proposed_section": "coding_agents",
            "published_at": "2026-04-27",
            "source_attempt_refs": ["Hacker News front page.attempts[0]"],
            "verification_state": "community_snapshot_with_repo",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "分数值得观察，但缺少当天 leaderboard delta，不写成今日登顶。",
            "novelty_vs_yesterday": "new",
            "event_type": "benchmark",
            "date_basis": "community_snapshot_time",
            "evidence_path": "community_snapshot",
            "why_today": "社区快照观察时间落在日报窗口内。",
            "action_eligibility": "none",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any("hard-data signal without market_signals coverage" in error for error in errors)

    report["sections"]["market_signals"]["benchmark_watch"] = [
        {
            "vendor": "Dirac",
            "model": "Dirac + gemini-3-flash-preview",
            "source": "Terminal-Bench-2",
            "signal": "社区快照显示 65.2% 分数，但缺少可验证前后基线。",
            "observed_at": "2026-04-27T22:00:00+08:00",
            "ref": "coding_agents[0]",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []


def test_validate_daily_artifacts_accepts_adoption_signal_with_ref(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["sections"]["general_agents"]["items"] = [
        {
            "product": "Microsoft 365 Copilot",
            "vendor": "Microsoft",
            "headline": "M365 Copilot 付费席位破 2000 万",
            "summary": "财报电话会披露 M365 Copilot 付费席位破 2000 万。",
            "heat_signal": "FY26 Q3 earnings call",
            "source_name": "Microsoft earnings call transcript",
            "source_url": "https://m.investing.com/news/transcripts/earnings-call-transcript-microsoft-q3-2026-results-exceed-expectations-stock-dips-93CH-4647426?ampMode=1",
            "published_at": "2026-04-29T22:00:00+08:00",
            "confidence": "medium",
            "release_stage": "announced",
            "published_at_confidence": "exact",
            "authority_score": 4,
            "editorial_tier": "watch",
        }
    ]
    report["sections"]["market_signals"]["adoption_signals"] = [
        {
            "vendor": "Microsoft",
            "product": "Microsoft 365 Copilot",
            "metric": "paid_seats",
            "value": "20M paid seats",
            "source": "Microsoft earnings call transcript",
            "observed_at": "2026-04-29T22:00:00+08:00",
            "note": "采用率信号，不等同于新产品发布",
            "ref": "general_agents[0]",
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "m365-copilot-20m-paid-seats-2026-04-29",
            "headline": "M365 Copilot 付费席位破 2000 万",
            "proposed_section": "general_agents",
            "published_at": "2026-04-29T22:00:00+08:00",
            "source_attempt_refs": ["Microsoft 365 Copilot Adoption.attempts[1]"],
            "verification_state": "earnings_call_transcript_confirmed",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "财报电话会转录给出明确席位和活跃度口径，属于企业采用率信号。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "adoption_signal",
            "date_basis": "article_published_at",
            "evidence_path": "media_plus_official_one_hop",
            "why_today": "FY26 Q3 电话会与转录发布时间落在 2026-04-29 日报窗口内。",
            "action_eligibility": "monitor",
        }
    ]
    report["fetch_status"]["source_details"]["Microsoft 365 Copilot Adoption"]["attempts"].append(
        {
            "layer_index": 1,
            "layer_type": "websearch_scoped",
            "target": "Microsoft 365 Copilot paid seats site:microsoft.com 2026-04-29",
            "result": "success",
            "note": "earnings call transcript confirmed adoption signal",
        }
    )

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []


def test_validate_daily_artifacts_rejects_adoption_language_without_market_signal(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["sections"]["general_agents"]["items"] = [
        {
            "product": "Microsoft 365 Copilot",
            "vendor": "Microsoft",
            "headline": "M365 Copilot 付费席位破 2000 万",
            "summary": "财报披露 paid seats 破 2000 万，weekly engagement 已接近 Outlook。",
            "heat_signal": "AI ARR and paid seats",
            "source_name": "Microsoft earnings call transcript",
            "source_url": "https://m.investing.com/news/transcripts/earnings-call-transcript-microsoft-q3-2026-results-exceed-expectations-stock-dips-93CH-4647426?ampMode=1",
            "published_at": "2026-04-29T22:00:00+08:00",
            "confidence": "medium",
            "release_stage": "announced",
            "published_at_confidence": "exact",
            "authority_score": 4,
            "editorial_tier": "watch",
        }
    ]
    report["sections"]["market_signals"]["adoption_signals"] = []
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "m365-copilot-20m-paid-seats-2026-04-29",
            "headline": "M365 Copilot 付费席位破 2000 万",
            "proposed_section": "general_agents",
            "published_at": "2026-04-29T22:00:00+08:00",
            "source_attempt_refs": ["Microsoft 365 Copilot Adoption.attempts[1]"],
            "verification_state": "earnings_call_transcript_confirmed",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "财报电话会转录给出明确席位和活跃度口径，属于企业采用率信号。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "adoption_signal",
            "date_basis": "article_published_at",
            "evidence_path": "media_plus_official_one_hop",
            "why_today": "FY26 Q3 电话会与转录发布时间落在 2026-04-29 日报窗口内。",
            "action_eligibility": "monitor",
        }
    ]
    report["fetch_status"]["source_details"]["Microsoft 365 Copilot Adoption"]["attempts"].append(
        {
            "layer_index": 1,
            "layer_type": "websearch_scoped",
            "target": "Microsoft 365 Copilot paid seats site:microsoft.com 2026-04-29",
            "result": "success",
            "note": "earnings call transcript confirmed adoption signal",
        }
    )

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert any("hard-data signal without market_signals coverage" in error for error in errors)
    assert not any("source_attempt_ref" in error for error in errors)
    assert not any("missing from candidate ledger" in error for error in errors)


def test_validate_daily_artifacts_allows_usage_command_without_market_signal(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["sections"]["coding_agents"]["items"] = [
        {
            "product": "GitHub Copilot CLI",
            "product_tier": "primary",
            "headline": "Copilot CLI 新增 /usage 命令",
            "summary": "新增 /usage 命令用于查看本地会话用量说明。",
            "impact": "便于开发者查看命令行会话状态。",
            "source_name": "GitHub Copilot changelog",
            "source_url": "https://github.blog/changelog/",
            "published_at": "2026-04-29T22:00:00+08:00",
            "confidence": "high",
            "release_stage": "ga",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "watch",
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "github-copilot-cli-usage-command-2026-04-29",
            "headline": "Copilot CLI 新增 /usage 命令",
            "proposed_section": "coding_agents",
            "published_at": "2026-04-29T22:00:00+08:00",
            "source_attempt_refs": ["GitHub Copilot.attempts[0]"],
            "verification_state": "official_changelog_confirmed",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "官方 changelog 更新了 CLI 辅助命令，属于产品体验变化。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "coding_release",
            "date_basis": "official_event_date",
            "evidence_path": "primary",
            "why_today": "GitHub changelog 发布时间落在 2026-04-29 日报窗口内。",
            "action_eligibility": "monitor",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []


def test_validate_daily_artifacts_allows_openai_arrives_without_market_signal(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["sections"]["general_agents"]["items"] = [
        {
            "product": "OpenAI enterprise workflow",
            "vendor": "OpenAI",
            "headline": "OpenAI arrives in workflow console",
            "summary": "OpenAI arranged a safer rollout path for admins.",
            "heat_signal": "admin workflow update",
            "source_name": "OpenAI Blog",
            "source_url": "https://openai.com/index/workflow-console/",
            "published_at": "2026-04-29T22:00:00+08:00",
            "confidence": "high",
            "release_stage": "ga",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "watch",
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "openai-workflow-console-2026-04-29",
            "headline": "OpenAI arrives in workflow console",
            "proposed_section": "general_agents",
            "published_at": "2026-04-29T22:00:00+08:00",
            "source_attempt_refs": ["OpenAI.attempts[0]"],
            "verification_state": "official_confirmed",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "官方更新说明企业工作流控制台能力，未披露采用率或收入指标。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "enterprise_update",
            "date_basis": "official_event_date",
            "evidence_path": "primary",
            "why_today": "OpenAI 官方发布时间落在 2026-04-29 日报窗口内。",
            "action_eligibility": "monitor",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []


def test_validate_daily_artifacts_allows_commercialization_path_without_market_signal(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["sections"]["general_agents"]["items"] = [
        {
            "product": "OpenAI enterprise workflow",
            "vendor": "OpenAI",
            "headline": "OpenAI 企业工作流商业化路径更清晰",
            "summary": "官方更新让企业管理员的商业化路径更清晰，但没有披露具体量化指标。",
            "heat_signal": "enterprise workflow update",
            "source_name": "OpenAI Blog",
            "source_url": "https://openai.com/index/workflow-console/",
            "published_at": "2026-04-29T22:00:00+08:00",
            "confidence": "high",
            "release_stage": "ga",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "watch",
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "openai-enterprise-workflow-commercialization-2026-04-29",
            "headline": "OpenAI 企业工作流商业化路径更清晰",
            "proposed_section": "general_agents",
            "published_at": "2026-04-29T22:00:00+08:00",
            "source_attempt_refs": ["OpenAI.attempts[0]"],
            "verification_state": "official_confirmed",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "官方更新说明企业工作流能力，未披露采用率或收入指标。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "enterprise_update",
            "date_basis": "official_event_date",
            "evidence_path": "primary",
            "why_today": "OpenAI 官方发布时间落在 2026-04-29 日报窗口内。",
            "action_eligibility": "monitor",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []


def test_validate_daily_artifacts_rejects_adoption_signal_ref_out_of_range(
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    whitelist = load_whitelist()
    report = deepcopy(sample_daily_report)
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["adoption_signals"][0]["ref"] = "general_agents[99]"

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("adoption_signals[0].ref points past general_agents[99]" in error for error in errors)


def _write_weekly_source_days(tmp_path: Path, weekly_report: dict, sample_daily_report: dict) -> None:
    for day in weekly_report["source_days"]["daily_reports_used"]:
        cache_dir = tmp_path / "cache" / day
        cache_dir.mkdir(parents=True, exist_ok=True)
        report = deepcopy(sample_daily_report)
        report["date"] = day
        report["generated_at"] = f"{day}T07:30:00+08:00"
        report["window"] = {
            "start": f"{day}T00:00:00+08:00",
            "end": f"{day}T23:59:59+08:00",
            "timezone": "Asia/Shanghai",
        }
        (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def test_validate_weekly_artifacts_passes_with_backing_daily_reports(tmp_path, normalized_weekly_report, sample_daily_report):
    _write_weekly_source_days(tmp_path, normalized_weekly_report, sample_daily_report)

    errors = validate_weekly_artifacts(normalized_weekly_report, tmp_path)

    assert errors == []


def test_validate_weekly_artifacts_rejects_missing_daily_report(tmp_path, normalized_weekly_report, sample_daily_report):
    _write_weekly_source_days(tmp_path, normalized_weekly_report, sample_daily_report)
    missing_day = normalized_weekly_report["source_days"]["daily_reports_used"][-1]
    (tmp_path / "cache" / missing_day / "report.json").unlink()

    errors = validate_weekly_artifacts(normalized_weekly_report, tmp_path)

    assert any(f"cache/{missing_day}/report.json" in error for error in errors)


def test_validate_weekly_artifacts_rejects_unresolvable_reference(tmp_path, normalized_weekly_report, sample_daily_report):
    _write_weekly_source_days(tmp_path, normalized_weekly_report, sample_daily_report)
    weekly = deepcopy(normalized_weekly_report)
    weekly["sections"]["action_items"]["items"][0]["references"][0]["headline"] = "不存在的日报条目"

    errors = validate_weekly_artifacts(weekly, tmp_path)

    assert any("cannot resolve" in error for error in errors)


def test_validate_weekly_artifacts_rejects_out_of_range_item_ref(tmp_path, normalized_weekly_report, sample_daily_report):
    _write_weekly_source_days(tmp_path, normalized_weekly_report, sample_daily_report)
    weekly = deepcopy(normalized_weekly_report)
    weekly["sections"]["experiments_this_week"]["items"][0]["related_item_refs"] = ["coding_agents[9]"]

    errors = validate_weekly_artifacts(weekly, tmp_path)

    assert any("points past coding_agents[9]" in error for error in errors)


def test_validate_weekly_artifacts_rejects_adoption_signal_ref_out_of_range(
    tmp_path,
    normalized_weekly_report,
    sample_daily_report,
):
    _write_weekly_source_days(tmp_path, normalized_weekly_report, sample_daily_report)
    weekly = deepcopy(normalized_weekly_report)
    weekly["sections"]["market_signals"]["adoption_signals"][0]["ref"] = "general_agents[99]"

    errors = validate_weekly_artifacts(weekly, tmp_path)

    assert any("sections.market_signals.adoption_signals[0].ref points past general_agents[99]" in error for error in errors)


def test_validate_weekly_artifacts_rejects_incomplete_source_days(tmp_path, normalized_weekly_report, sample_daily_report):
    _write_weekly_source_days(tmp_path, normalized_weekly_report, sample_daily_report)
    weekly = deepcopy(normalized_weekly_report)
    weekly["source_days"]["daily_reports_used"] = weekly["source_days"]["daily_reports_used"][:6]

    errors = validate_weekly_artifacts(weekly, tmp_path)

    assert any("must contain 7 dates" in error for error in errors)
    assert any("must be the 7 days ending" in error for error in errors)


def test_validate_weekly_source_days_rolling_window_crosses_month():
    report = {
        "week_end": "2026-05-03",
        "source_days": {
            "daily_reports_used": [
                "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
                "2026-05-01", "2026-05-02", "2026-05-03",
            ],
            "backfilled": [],
        },
    }
    assert validate_weekly_source_days(report) == []


def test_validate_weekly_source_days_requires_week_end():
    report = {"source_days": {"daily_reports_used": [], "backfilled": []}}
    assert validate_weekly_source_days(report) == ["weekly report missing week_end"]


def test_build_weekly_qa_diff_reports_reference_gaps(tmp_path, normalized_weekly_report, sample_daily_report):
    _write_weekly_source_days(tmp_path, normalized_weekly_report, sample_daily_report)
    weekly = deepcopy(normalized_weekly_report)
    weekly["source_days"]["daily_reports_used"] = weekly["source_days"]["daily_reports_used"][:6]

    qa_diff = build_weekly_qa_diff(weekly, tmp_path)

    assert qa_diff["summary"]["categories"]["reference_integrity_gap"] >= 1


def test_2026_04_30_recall_regression_accepts_cursor_zed_deepseek_and_m365(
    sample_daily_report,
    finalized_fetch_status,
    sample_candidate_ledger,
):
    whitelist = load_whitelist()
    report = _minimal_report_with_fetch_status(sample_daily_report, finalized_fetch_status, whitelist)
    report["date"] = "2026-04-30"
    report["generated_at"] = "2026-04-30T10:58:00+08:00"
    report["window"] = {
        "start": "2026-04-29T07:00:00+08:00",
        "end": "2026-04-30T10:58:00+08:00",
        "timezone": "Asia/Shanghai",
    }
    report["sections"]["frontier_models"]["items"] = [
        {
            "vendor": "DeepSeek",
            "vendor_region": "CN",
            "headline": "DeepSeek 视觉 beta 灰度",
            "summary": "媒体确认 DeepSeek chat 端新增图像识别 beta。",
            "impact": "中文多模态预算需要纳入观察。",
            "source_name": "South China Morning Post",
            "source_url": "https://www.scmp.com/tech/tech-trends/article/3351892/whale-can-now-see-deepseek-adds-ai-vision-major-move",
            "published_at": "2026-04-29T12:00:00+08:00",
            "confidence": "medium",
            "release_stage": "beta",
            "published_at_confidence": "exact",
            "authority_score": 4,
            "editorial_tier": "watch",
            "via_broad_search": True,
        }
    ]
    report["sections"]["coding_agents"]["items"] = [
        {
            "product": "Cursor",
            "product_tier": "secondary",
            "headline": "Cursor TypeScript SDK 公测",
            "summary": "@cursor/sdk 开放公测，可程序化调度 agent runtime。",
            "impact": "CI 与产品内 agent 接入门槛下降。",
            "source_name": "Cursor Blog",
            "source_url": "https://cursor.com/blog/typescript-sdk",
            "published_at": "2026-04-29T22:00:00+08:00",
            "confidence": "high",
            "release_stage": "beta",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "core",
        }
    ]
    report["sections"]["coding_agents"]["deep_dive"] = {
        "title": "IDE agent 正在平台化",
        "body": "Cursor SDK 把编辑器内 agent runtime 暴露给 TypeScript 调用，Zed 1.0 同时把协作和 agent protocol 放进编辑器主线。两条信号合在一起，说明 IDE 厂商正在把过去只能在桌面内使用的 agent 能力包装成可复用平台。技术负责人需要用小型 CI demo 验证 token 成本、权限边界、可重放性和失败恢复，而不是只看编辑器交互体验。",
        "related_item_indexes": [0],
    }
    report["sections"]["general_agents"]["items"] = [
        {
            "product": "Zed 1.0",
            "vendor": "Zed Industries",
            "headline": "Zed 1.0 GA 发布",
            "summary": "AI-native 编辑器正式发版，强调 multiple agents 与协作。",
            "heat_signal": "HN front page",
            "source_name": "Zed Blog",
            "source_url": "https://zed.dev/blog/zed-1-0",
            "published_at": "2026-04-29T20:00:00+08:00",
            "confidence": "high",
            "release_stage": "ga",
            "published_at_confidence": "exact",
            "authority_score": 5,
            "editorial_tier": "watch",
        },
        {
            "product": "Microsoft 365 Copilot",
            "vendor": "Microsoft",
            "headline": "M365 Copilot 付费席位破 2000 万",
            "summary": "财报电话会披露 paid seats 破 2000 万，weekly engagement 接近 Outlook。",
            "heat_signal": "FY26 Q3 earnings call",
            "source_name": "Microsoft earnings call transcript",
            "source_url": "https://m.investing.com/news/transcripts/earnings-call-transcript-microsoft-q3-2026-results-exceed-expectations-stock-dips-93CH-4647426?ampMode=1",
            "published_at": "2026-04-29T22:00:00+08:00",
            "confidence": "medium",
            "release_stage": "announced",
            "published_at_confidence": "exact",
            "authority_score": 4,
            "editorial_tier": "watch",
        },
    ]
    report["sections"]["market_signals"]["adoption_signals"] = [
        {
            "vendor": "Microsoft",
            "product": "Microsoft 365 Copilot",
            "metric": "paid_seats",
            "value": "20M paid seats",
            "source": "Microsoft earnings call transcript",
            "observed_at": "2026-04-29T22:00:00+08:00",
            "note": "采用率信号，不等同于新产品发布",
            "ref": "general_agents[1]",
        }
    ]
    report["sections"]["market_signals"]["capability_gaps"] = [
        {
            "text": "DeepSeek 视觉 beta 尚未进入主流综合榜单，应先观察中文多模态价格和准确率。",
            "ref": "frontier_models[0]",
        }
    ]
    report["sections"]["pattern_observations"]["items"] = [
        {
            "theme": "IDE 与模型厂商同时争夺 agent 平台入口",
            "supporting_item_refs": ["coding_agents[0]", "general_agents[0]"],
            "interpretation_for_tech_lead": "Cursor SDK 和 Zed 1.0 说明 IDE 入口正在平台化。团队应验证 SDK 成本、权限边界和失败恢复，而不是只比较编辑器交互体验。",
        }
    ]
    report["sections"]["experiments_this_week"]["items"] = [
        {
            "title": "Cursor SDK 最小 CI demo",
            "hypothesis": "用 @cursor/sdk 接入一条最小 CI 用例能在一天内验证成本和可控性。",
            "steps": [
                "选一个少于 200 行改动的回归任务",
                "用 @cursor/sdk 跑 cloud 与 local 各一次",
                "记录 token、耗时、失败恢复和人工接管点",
            ],
            "time_budget_hours": {"min": 3, "max": 6},
            "expected_output": "一页 Cursor SDK 与 Claude Code CI 场景对照",
            "required_skills": ["TypeScript", "CI/CD"],
            "related_item_refs": ["coding_agents[0]"],
        }
    ]

    ledger = deepcopy(sample_candidate_ledger)
    ledger["items"] = [
        {
            "candidate_id": "deepseek-vision-beta-2026-04-29",
            "headline": "DeepSeek 视觉 beta 灰度",
            "proposed_section": "frontier_models",
            "published_at": "2026-04-29T12:00:00+08:00",
            "source_attempt_refs": ["DeepSeek.attempts[2]", "High-Recall Product/Adoption Probes.attempts[0]"],
            "verification_state": "media_plus_product_surface",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "媒体给出明确日期，且能回到 DeepSeek 产品面；证据不足以 high confidence。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "model_release",
            "date_basis": "article_published_at",
            "evidence_path": "media_plus_official_one_hop",
            "why_today": "报道时间落在 2026-04-29 北京时间窗口内。",
            "action_eligibility": "monitor",
        },
        {
            "candidate_id": "cursor-typescript-sdk-public-beta-2026-04-29",
            "headline": "Cursor TypeScript SDK 公测",
            "proposed_section": "coding_agents",
            "published_at": "2026-04-29T22:00:00+08:00",
            "source_attempt_refs": ["Cursor.attempts[0]", "High-Recall Product/Adoption Probes.attempts[0]"],
            "verification_state": "official_confirmed",
            "editorial_tier": "core",
            "decision": "selected_core",
            "decision_reason": "Cursor 官方博客发布 SDK 公测，直接影响 coding-agent 接入方式。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "coding_release",
            "date_basis": "official_event_date",
            "evidence_path": "primary",
            "why_today": "Cursor Blog 发布日期落在日报窗口内。",
            "action_eligibility": "experiment",
        },
        {
            "candidate_id": "zed-1-0-ga-2026-04-29",
            "headline": "Zed 1.0 GA 发布",
            "proposed_section": "general_agents",
            "published_at": "2026-04-29T20:00:00+08:00",
            "source_attempt_refs": ["Zed.attempts[0]", "High-Recall Product/Adoption Probes.attempts[0]"],
            "verification_state": "official_confirmed",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "Zed 官方博客发布 1.0，AI-native editor 与 agent protocol 具备平台化观察价值。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "enterprise_update",
            "date_basis": "official_event_date",
            "evidence_path": "primary",
            "why_today": "官方博客日期落在日报窗口内。",
            "action_eligibility": "experiment",
        },
        {
            "candidate_id": "m365-copilot-20m-paid-seats-2026-04-29",
            "headline": "M365 Copilot 付费席位破 2000 万",
            "proposed_section": "general_agents",
            "published_at": "2026-04-29T22:00:00+08:00",
            "source_attempt_refs": ["Microsoft 365 Copilot Adoption.attempts[1]", "High-Recall Product/Adoption Probes.attempts[0]"],
            "verification_state": "earnings_call_transcript_confirmed",
            "editorial_tier": "watch",
            "decision": "selected_watch",
            "decision_reason": "财报电话会转录给出明确 paid seats 与 engagement 口径。",
            "novelty_vs_yesterday": "new_in_today_window",
            "event_type": "adoption_signal",
            "date_basis": "article_published_at",
            "evidence_path": "media_plus_official_one_hop",
            "why_today": "财报电话会与转录发布时间落在窗口内。",
            "action_eligibility": "monitor",
        },
    ]
    source_details = report["fetch_status"]["source_details"]
    source_details["Cursor"]["attempts"] = [
        {
            "layer_index": 0,
            "layer_type": "webfetch",
            "target": "https://cursor.com/blog",
            "result": "success",
            "note": "Cursor SDK public beta found",
        }
    ]
    source_details["DeepSeek"]["attempts"].append(
        {
            "layer_index": 1,
            "layer_type": "websearch_scoped",
            "target": "DeepSeek vision site:deepseek.com 2026-04-29",
            "result": "partial",
            "note": "official product surface was weak; broad search needed for dated evidence",
        }
    )
    source_details["DeepSeek"]["attempts"].append(
        {
            "layer_index": 2,
            "layer_type": "websearch_broad",
            "target": "DeepSeek vision multimodal 2026-04-29",
            "result": "success",
            "note": "media plus product surface confirmed",
        }
    )
    source_details["Zed"]["attempts"] = [
        {
            "layer_index": 0,
            "layer_type": "webfetch",
            "target": "https://zed.dev/blog",
            "result": "success",
            "note": "Zed 1.0 found",
        }
    ]
    source_details["Microsoft 365 Copilot Adoption"]["attempts"].append(
        {
            "layer_index": 1,
            "layer_type": "websearch_scoped",
            "target": "Microsoft 365 Copilot paid seats earnings call 2026-04-29",
            "result": "success",
            "note": "earnings call transcript found",
        }
    )
    source_details["High-Recall Product/Adoption Probes"]["attempts"] = [
        {
            "layer_index": 0,
            "layer_type": "websearch_broad",
            "target": "recall_probe_queries",
            "result": "success",
            "note": "Cursor SDK, Zed 1.0, DeepSeek vision, and Microsoft Copilot adoption probes executed",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)
    qa_diff = build_daily_qa_diff(report, ledger, whitelist)

    assert errors == []
    assert qa_diff["summary"]["blocking_findings"] == 0


def _daily_report_with_major_item(sample_daily_report, **overrides):
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    item = report["sections"]["frontier_models"]["items"][0]
    item.update(
        {
            "major_event": True,
            "editorial_tier": "core",
            "tracking_ref": "claude-fable-5",
            "expanded": {
                "what_shipped": "Anthropic 发布 Claude Fable 5 与 Mythos 5，首次把 Mythos 级模型开放到通用用户侧，并同步更新模型卡与定价页。",
                "open_questions": ["第三方 benchmark 何时收录"],
            },
        }
    )
    item.update(overrides)
    return report


def test_major_event_with_expanded_core_and_tracking_passes(sample_daily_report):
    report = _daily_report_with_major_item(sample_daily_report)
    assert validate_major_event_consistency(report) == []


def test_expanded_without_major_event_flag_fails(sample_daily_report):
    report = _daily_report_with_major_item(sample_daily_report, major_event=False)
    errors = validate_major_event_consistency(report)
    assert any("expanded block but major_event" in error for error in errors)


def test_major_event_requires_expanded_core_tier_and_tracking(sample_daily_report):
    report = _daily_report_with_major_item(
        sample_daily_report, expanded=None, editorial_tier="watch", tracking_ref=None
    )
    errors = validate_major_event_consistency(report)
    assert any("requires expanded block" in error for error in errors)
    assert any("editorial_tier='core'" in error for error in errors)
    assert any("requires tracking_ref" in error for error in errors)


def test_validate_daily_artifacts_flags_major_event_gap(
    sample_daily_report, sample_candidate_ledger, sample_whitelist
):
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["frontier_models"]["items"][0]["major_event"] = True
    errors = validate_daily_artifacts(report, sample_candidate_ledger, sample_whitelist)
    assert any("major_event=true requires expanded block" in error for error in errors)


def test_validate_daily_artifacts_checks_tracking_refs_when_root_given(
    tmp_path, sample_daily_report, sample_candidate_ledger, sample_whitelist
):
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["frontier_models"]["items"][0]["tracking_ref"] = "missing-event"
    errors = validate_daily_artifacts(
        report, sample_candidate_ledger, sample_whitelist, project_root=tmp_path
    )
    assert any("missing-event" in error for error in errors)


def test_candidate_ledger_accepts_optional_tracking_ref(sample_candidate_ledger):
    ledger = json.loads(json.dumps(sample_candidate_ledger, ensure_ascii=False))
    ledger["items"][0]["tracking_ref"] = "claude-fable-5"
    assert validate_candidate_ledger_schema(ledger) == []

    ledger["items"][0]["tracking_ref"] = "Claude Fable!"
    errors = validate_candidate_ledger_schema(ledger)
    assert any("tracking_ref" in error for error in errors)


def _radar_report(sample_daily_report, decision_name="coding-agent-2026H2", ref="frontier_models[0]"):
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["decision_radar"] = {
        "title": "决策雷达",
        "decisions": [
            {"decision_name": decision_name, "items": [{"ref": ref, "impact": "影响选型评估节奏。"}]}
        ],
        "empty_message": "今日无影响在途决策的信息",
    }
    return report


_PROFILE = {
    "decisions_in_flight": [
        {"name": "coding-agent-2026H2"},
        {"name": "workplace-ai"},
    ]
}


def test_decision_radar_valid_ref_and_name_passes(sample_daily_report):
    report = _radar_report(sample_daily_report)
    assert validate_decision_radar(report, _PROFILE) == []


def test_decision_radar_rejects_dangling_ref(sample_daily_report):
    report = _radar_report(sample_daily_report, ref="general_agents[9]")
    errors = validate_decision_radar(report, _PROFILE)
    assert any("general_agents[9]" in error for error in errors)


def test_decision_radar_rejects_unknown_decision_name(sample_daily_report):
    report = _radar_report(sample_daily_report, decision_name="not-a-decision")
    errors = validate_decision_radar(report, _PROFILE)
    assert any("not-a-decision" in error for error in errors)


def test_decision_radar_skips_name_check_without_profile(sample_daily_report):
    report = _radar_report(sample_daily_report, decision_name="not-a-decision")
    assert validate_decision_radar(report, None) == []


def test_validate_daily_artifacts_includes_decision_radar(
    sample_daily_report, sample_candidate_ledger, sample_whitelist
):
    report = _radar_report(sample_daily_report, ref="frontier_models[99]")
    errors = validate_daily_artifacts(report, sample_candidate_ledger, sample_whitelist)
    assert any("frontier_models[99]" in error for error in errors)


def test_validate_daily_artifacts_flags_ecosystem_repeat(
    tmp_path, sample_daily_report, sample_candidate_ledger, sample_whitelist
):
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    seen_path = tmp_path / "cache" / "seen_repos.json"
    seen_path.parent.mkdir(parents=True)
    seen_path.write_text(
        json.dumps({"version": "1.0", "repos": {"example/claude-flow": {"first_seen": "2026-04-01", "last_listed": "2026-04-01"}}}),
        encoding="utf-8",
    )
    errors = validate_daily_artifacts(
        report, sample_candidate_ledger, sample_whitelist, project_root=tmp_path
    )
    assert any("example/claude-flow" in error for error in errors)


def _weekly_with_digest(date: str, origin_title: str) -> dict:
    return {
        "source_days": {"daily_reports_used": [date], "backfilled": []},
        "sections": {
            "practice_digest": {
                "title": "本周实践精选",
                "items": [
                    {
                        "title": "claude-flow 深读",
                        "source_name": "GitHub",
                        "source_url": "https://github.com/example/claude-flow",
                        "summary": "占位摘要",
                        "applicability": "adopt_now",
                        "applicability_note": "先小范围试点。",
                        "origin": {"date": date, "title": origin_title},
                    }
                ],
                "empty_message": "",
            }
        },
    }


def _write_daily_with_ecosystem(project_root, date: str, eco_title: str) -> None:
    daily = {
        "type": "daily",
        "date": date,
        "sections": {
            "agent_ecosystem": {
                "title": "Agent 生态与实践",
                "items": [
                    {
                        "item_type": "practice_case",
                        "title": eco_title,
                        "summary": "x",
                        "source_name": "GitHub",
                        "source_url": "https://github.com/example/claude-flow",
                        "relevance": "团队级 agent 工作流",
                    }
                ],
                "empty_message": "",
            }
        },
    }
    cache_dir = project_root / "cache" / date
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "report.json").write_text(json.dumps(daily, ensure_ascii=False), encoding="utf-8")


def test_practice_digest_resolving_origin_passes(tmp_path):
    _write_daily_with_ecosystem(tmp_path, "2026-06-08", "claude-flow：多 agent 编排框架")
    report = _weekly_with_digest("2026-06-08", "claude-flow：多 agent 编排框架")
    assert validate_practice_digest(report, tmp_path) == []


def test_practice_digest_rejects_unknown_origin_title(tmp_path):
    _write_daily_with_ecosystem(tmp_path, "2026-06-08", "其他条目")
    report = _weekly_with_digest("2026-06-08", "claude-flow：多 agent 编排框架")
    errors = validate_practice_digest(report, tmp_path)
    assert any("not found in 2026-06-08 agent_ecosystem" in error for error in errors)


def test_practice_digest_rejects_date_outside_source_days(tmp_path):
    _write_daily_with_ecosystem(tmp_path, "2026-06-08", "claude-flow：多 agent 编排框架")
    report = _weekly_with_digest("2026-06-08", "claude-flow：多 agent 编排框架")
    report["sections"]["practice_digest"]["items"][0]["origin"]["date"] = "2026-06-01"
    errors = validate_practice_digest(report, tmp_path)
    assert any("not listed in source_days" in error for error in errors)


def test_practice_digest_rejects_missing_daily_report(tmp_path):
    report = _weekly_with_digest("2026-06-08", "claude-flow：多 agent 编排框架")
    errors = validate_practice_digest(report, tmp_path)
    assert any("cache/2026-06-08/report.json" in error for error in errors)


def test_validate_weekly_artifacts_includes_practice_digest(tmp_path, normalized_weekly_report):
    report = json.loads(json.dumps(normalized_weekly_report, ensure_ascii=False))
    report["sections"]["practice_digest"] = _weekly_with_digest("2026-06-01", "不存在的条目")["sections"]["practice_digest"]
    report["sections"]["practice_digest"]["items"][0]["origin"]["date"] = "1999-01-01"
    errors = validate_weekly_artifacts(report, tmp_path)
    assert any("not listed in source_days" in error for error in errors)
