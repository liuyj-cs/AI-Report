import json
from copy import deepcopy
from pathlib import Path

from discovery import load_whitelist
from report_runner import main, run_daily_finalize, run_daily_init


def test_run_daily_init_fails_fast_when_email_env_missing(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("GMAIL_USER=\nGMAIL_APP_PASSWORD=\nREPORT_RECIPIENTS=\n", encoding="utf-8")

    code, message = run_daily_init(
        project_root=tmp_path,
        target_date="2026-04-18",
        now_iso="2026-04-18T07:30:00+08:00",
        env_path=env_path,
    )

    assert code == 1
    assert "GMAIL_USER / GMAIL_APP_PASSWORD / REPORT_RECIPIENTS" in message


def test_run_daily_init_succeeds_with_email_env_only(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )

    code, message = run_daily_init(
        project_root=tmp_path,
        target_date="2026-04-18",
        now_iso="2026-04-18T07:30:00+08:00",
        env_path=env_path,
    )

    assert code == 0
    assert message.endswith("cache/2026-04-18/discovery_manifest.json")
    run_log = tmp_path / "cache" / "2026-04-18" / "run.log"
    assert run_log.exists()
    assert "DISCOVERY manifest=discovery_manifest.json ready" in run_log.read_text(encoding="utf-8")
    assert not (tmp_path / "cache" / "2026-04-18" / "discovery_result.json").exists()
    assert not (tmp_path / "cache" / "2026-04-18" / "raw_candidates.json").exists()


def test_init_daily_writes_discovery_manifest_and_run_log(tmp_path, capsys):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "init-daily",
            "--date",
            "2026-04-18",
            "--now",
            "2026-04-18T07:30:00+08:00",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 0
    assert (tmp_path / "cache" / "2026-04-18" / "discovery_manifest.json").exists()
    assert (tmp_path / "cache" / "2026-04-18" / "run.log").exists()
    captured = capsys.readouterr()
    assert captured.out.strip().endswith("cache/2026-04-18/discovery_manifest.json")
    assert "DISCOVERY manifest=discovery_manifest.json ready" in (tmp_path / "cache" / "2026-04-18" / "run.log").read_text(encoding="utf-8")


def test_finalize_daily_dry_run_writes_html_and_archive(tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    whitelist = load_whitelist()

    report = deepcopy(sample_daily_report)
    report["date"] = "2026-04-18"
    report["generated_at"] = "2026-04-18T07:30:00+08:00"
    report["window"] = {
        "start": "2026-04-17T07:00:00+08:00",
        "end": "2026-04-18T07:30:00+08:00",
        "timezone": "Asia/Shanghai",
    }
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["frontier_models"]["items"] = []
    report["sections"]["coding_agents"]["items"] = []
    report["sections"]["decision_radar"]["decisions"] = []
    report["sections"]["coding_agents"]["deep_dive"] = {
        "title": "今日无 coding agent 新动作",
        "body": "今日无 coding agent 新动作，保持跟踪即可。这段文字专门用于满足 deep_dive 的最小长度约束，同时明确说明当天没有值得单独展开的 coding agent 事件，因此本段不驱动新增建议，只作为编辑层的空窗注记与趋势延续说明。",
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
            "published_at": "2026-04-18T05:20:00+08:00",
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
                    "date": "2026-04-18",
                    "headline": "Agents SDK 原生接入沙箱执行",
                    "url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
                    "section": "general_agents",
                    "editorial_tier": "core",
                }
            ],
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["date"] = "2026-04-18"
    ledger["generated_at"] = "2026-04-18T07:30:00+08:00"
    ledger["items"][0]["proposed_section"] = "general_agents"
    ledger["items"][0]["headline"] = "Agents SDK 原生接入沙箱执行"
    ledger["items"][0]["published_at"] = "2026-04-18T05:20:00+08:00"
    ledger["items"][0]["source_attempt_refs"] = ["OpenAI.attempts[0]"]
    ledger["items"] = ledger["items"][:1]

    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "candidate_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_dir / "run.log").write_text("2026-04-18T07:30:00+08:00 START daily\n", encoding="utf-8")

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "finalize-daily",
            "--date",
            "2026-04-18",
            "--dry-run",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 0
    assert (cache_dir / "qa_diff.json").exists()
    assert (cache_dir / "report.html").exists()
    assert (tmp_path / "reports" / "daily" / "2026-04-18.html").exists()


def test_finalize_daily_failure_still_writes_qa_diff(tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    whitelist = load_whitelist()

    report = deepcopy(sample_daily_report)
    report["date"] = "2026-04-18"
    report["generated_at"] = "2026-04-18T07:30:00+08:00"
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["market_signals"]["benchmark_changes"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = []
    report["sections"]["market_signals"]["pricing_changes"] = []
    report["sections"]["market_signals"]["capability_gaps"] = []
    report["sections"]["frontier_models"]["items"][1]["headline"] = "DeepSeek V4 榜单评分逼近 o1"
    report["sections"]["frontier_models"]["items"][1]["summary"] = "新 benchmark 显示其在 MATH-500 与 AIME 上继续逼近 o1。"
    ledger = deepcopy(sample_candidate_ledger)

    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "candidate_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_dir / "run.log").write_text("2026-04-18T07:30:00+08:00 START daily\n", encoding="utf-8")

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "finalize-daily",
            "--date",
            "2026-04-18",
            "--dry-run",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 1
    assert (cache_dir / "qa_diff.json").exists()
    assert not (cache_dir / "report.html").exists()
    assert not (tmp_path / "reports" / "daily" / "2026-04-18.html").exists()


def test_finalize_daily_rejects_candidate_ledger_missing_audit_field(
    tmp_path,
    sample_daily_report,
    sample_candidate_ledger,
    finalized_fetch_status,
):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    whitelist = load_whitelist()

    report = deepcopy(sample_daily_report)
    report["date"] = "2026-04-18"
    report["generated_at"] = "2026-04-18T07:30:00+08:00"
    report["window"] = {
        "start": "2026-04-17T07:00:00+08:00",
        "end": "2026-04-18T07:30:00+08:00",
        "timezone": "Asia/Shanghai",
    }
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["frontier_models"]["items"] = []
    report["sections"]["coding_agents"]["items"] = []
    report["sections"]["decision_radar"]["decisions"] = []
    report["sections"]["coding_agents"]["deep_dive"] = {
        "title": "今日无 coding agent 新动作",
        "body": "今日无 coding agent 新动作，保持跟踪即可。这段文字专门用于满足 deep_dive 的最小长度约束，同时明确说明当天没有值得单独展开的 coding agent 事件，因此本段不驱动新增建议，只作为编辑层的空窗注记与趋势延续说明。",
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
            "published_at": "2026-04-18T05:20:00+08:00",
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
                    "date": "2026-04-18",
                    "headline": "Agents SDK 原生接入沙箱执行",
                    "url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
                    "section": "general_agents",
                    "editorial_tier": "core",
                }
            ],
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["date"] = "2026-04-18"
    ledger["generated_at"] = "2026-04-18T07:30:00+08:00"
    ledger["items"][0]["proposed_section"] = "general_agents"
    ledger["items"][0]["headline"] = "Agents SDK 原生接入沙箱执行"
    ledger["items"][0]["published_at"] = "2026-04-18T05:20:00+08:00"
    ledger["items"][0]["source_attempt_refs"] = ["OpenAI.attempts[0]"]
    ledger["items"][0].pop("date_basis")
    ledger["items"] = ledger["items"][:1]

    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "candidate_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_dir / "run.log").write_text("2026-04-18T07:30:00+08:00 START daily\n", encoding="utf-8")

    exit_code, message = run_daily_finalize(tmp_path, "2026-04-18", True, env_path)

    assert exit_code == 1
    assert "date_basis" in message
    assert (cache_dir / "qa_diff.json").exists()
    qa_diff = json.loads((cache_dir / "qa_diff.json").read_text(encoding="utf-8"))
    assert any("date_basis" in finding["reason"] for finding in qa_diff["findings"])
    assert not (cache_dir / "report.html").exists()


def test_init_weekly_writes_rolling_input_days(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "init-weekly",
            "--end-date",
            "2026-05-03",
            "--now",
            "2026-05-03T08:00:00+08:00",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 0
    payload = json.loads(
        (tmp_path / "cache" / "weekly" / "2026-05-03" / "input_days.json").read_text(encoding="utf-8")
    )
    assert payload["week_end"] == "2026-05-03"
    assert payload["source_days"] == [
        "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
        "2026-05-01", "2026-05-02", "2026-05-03",
    ]


def test_init_weekly_rejects_invalid_end_date(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "init-weekly",
            "--end-date",
            "2026-W20",
            "--now",
            "2026-05-03T08:00:00+08:00",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 1


def _write_weekly_daily_reports(tmp_path, weekly_report, sample_daily_report):
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


def test_finalize_weekly_dry_run_writes_html_and_archive(tmp_path, normalized_weekly_report, sample_daily_report):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    _write_weekly_daily_reports(tmp_path, normalized_weekly_report, sample_daily_report)
    cache_dir = tmp_path / "cache" / "weekly" / "2026-04-12"
    cache_dir.mkdir(parents=True)
    report = deepcopy(normalized_weekly_report)
    report["generated_at"] = "2026-04-12T08:00:00+08:00"
    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "run.log").write_text("2026-04-12T08:00:00+08:00 START weekly\n", encoding="utf-8")

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "finalize-weekly",
            "--end-date",
            "2026-04-12",
            "--dry-run",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 0
    assert (cache_dir / "qa_diff.json").exists()
    assert (cache_dir / "report.html").exists()
    assert (tmp_path / "reports" / "weekly" / "2026-04-12.html").exists()


def test_finalize_weekly_rejects_missing_source_day_report(tmp_path, normalized_weekly_report):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache" / "weekly" / "2026-04-12"
    cache_dir.mkdir(parents=True)
    report = deepcopy(normalized_weekly_report)
    report["generated_at"] = "2026-04-12T08:00:00+08:00"
    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "run.log").write_text("2026-04-12T08:00:00+08:00 START weekly\n", encoding="utf-8")

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "finalize-weekly",
            "--end-date",
            "2026-04-12",
            "--dry-run",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 1
    assert (cache_dir / "qa_diff.json").exists()


def test_finalize_weekly_rejects_week_end_mismatch(tmp_path, normalized_weekly_report, sample_daily_report):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    _write_weekly_daily_reports(tmp_path, normalized_weekly_report, sample_daily_report)
    cache_dir = tmp_path / "cache" / "weekly" / "2026-04-13"
    cache_dir.mkdir(parents=True)
    report = deepcopy(normalized_weekly_report)
    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "run.log").write_text("2026-04-12T08:00:00+08:00 START weekly\n", encoding="utf-8")

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "finalize-weekly",
            "--end-date",
            "2026-04-13",
            "--dry-run",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 1


def _build_passing_finalize_setup(tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    """Return (cache_dir, env_path) with a fully valid finalize fixture written to tmp_path."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    cache_dir = tmp_path / "cache" / "2026-04-18"
    cache_dir.mkdir(parents=True)
    whitelist = load_whitelist()

    report = deepcopy(sample_daily_report)
    report["date"] = "2026-04-18"
    report["generated_at"] = "2026-04-18T07:30:00+08:00"
    report["window"] = {
        "start": "2026-04-17T07:00:00+08:00",
        "end": "2026-04-18T07:30:00+08:00",
        "timezone": "Asia/Shanghai",
    }
    report["fetch_status"] = finalized_fetch_status(whitelist)
    report["sections"]["frontier_models"]["items"] = []
    report["sections"]["coding_agents"]["items"] = []
    report["sections"]["decision_radar"]["decisions"] = []
    report["sections"]["coding_agents"]["deep_dive"] = {
        "title": "今日无 coding agent 新动作",
        "body": "今日无 coding agent 新动作，保持跟踪即可。这段文字专门用于满足 deep_dive 的最小长度约束，同时明确说明当天没有值得单独展开的 coding agent 事件，因此本段不驱动新增建议，只作为编辑层的空窗注记与趋势延续说明。",
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
            "published_at": "2026-04-18T05:20:00+08:00",
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
                    "date": "2026-04-18",
                    "headline": "Agents SDK 原生接入沙箱执行",
                    "url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
                    "section": "general_agents",
                    "editorial_tier": "core",
                }
            ],
        }
    ]
    ledger = deepcopy(sample_candidate_ledger)
    ledger["date"] = "2026-04-18"
    ledger["generated_at"] = "2026-04-18T07:30:00+08:00"
    ledger["items"][0]["proposed_section"] = "general_agents"
    ledger["items"][0]["headline"] = "Agents SDK 原生接入沙箱执行"
    ledger["items"][0]["published_at"] = "2026-04-18T05:20:00+08:00"
    ledger["items"][0]["source_attempt_refs"] = ["OpenAI.attempts[0]"]
    ledger["items"] = ledger["items"][:1]

    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "candidate_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_dir / "run.log").write_text("2026-04-18T07:30:00+08:00 START daily\n", encoding="utf-8")
    return cache_dir, env_path


def test_finalize_daily_rejects_inactive_tracking_ref(
    tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
):
    """project_root passthrough: a tracking_ref with no active file must cause exit code 1."""
    cache_dir, env_path = _build_passing_finalize_setup(
        tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
    )

    # Inject an unknown tracking_ref into general_agents[0]
    report_path = cache_dir / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["sections"]["general_agents"]["items"][0]["tracking_ref"] = "missing-event"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    exit_code, message = run_daily_finalize(tmp_path, "2026-04-18", True, env_path)

    assert exit_code == 1
    assert "missing-event" in message


def test_finalize_daily_cleans_expired_tracking(
    tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
):
    """Post-archive cleanup: expired tracking files are removed and run.log records the count."""
    cache_dir, env_path = _build_passing_finalize_setup(
        tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
    )

    # Write a schema-valid tracking file whose expires_on is well past the 7-day grace window.
    # target_date = 2026-04-18; cutoff = 2026-04-11; use opened=D-60, expires=D-56 (window=4 days ≤ 5).
    tracking_dir = tmp_path / "cache" / "tracking"
    tracking_dir.mkdir(parents=True)
    stale_payload = {
        "version": "1.0",
        "type": "event_tracking",
        "event_slug": "stale-event",
        "title": "Stale event",
        "opened_date": "2026-02-17",
        "expires_on": "2026-02-21",
        "origin": {
            "date": "2026-02-17",
            "section": "frontier_models",
            "headline": "Stale",
        },
        "watch_items": ["x"],
        "updates": [],
    }
    stale_path = tracking_dir / "stale-event.json"
    stale_path.write_text(json.dumps(stale_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    exit_code = main(
        [
            "--project-root",
            str(tmp_path),
            "finalize-daily",
            "--date",
            "2026-04-18",
            "--dry-run",
            "--env",
            str(env_path),
        ]
    )

    assert exit_code == 0
    assert not stale_path.exists()
    run_log = (cache_dir / "run.log").read_text(encoding="utf-8")
    assert "TRACKING cleanup removed=1" in run_log


def test_init_daily_manifest_lists_active_tracking(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    tracking_dir = tmp_path / "cache" / "tracking"
    tracking_dir.mkdir(parents=True)
    payload = {
        "version": "1.0",
        "type": "event_tracking",
        "event_slug": "claude-fable-5",
        "title": "Claude Fable 5 / Mythos 5 发布",
        "opened_date": "2026-06-10",
        "expires_on": "2026-06-14",
        "origin": {"date": "2026-06-10", "section": "frontier_models", "headline": "Claude Fable 5 / Mythos 5 发布"},
        "watch_items": ["第三方 benchmark 何时收录"],
        "updates": [],
    }
    (tracking_dir / "claude-fable-5.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    code, message = run_daily_init(tmp_path, "2026-06-11", "2026-06-11T07:10:00+08:00", env_path)

    assert code == 0, message
    manifest = json.loads(
        (tmp_path / "cache" / "2026-06-11" / "discovery_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["active_tracking"] == [
        {
            "event_slug": "claude-fable-5",
            "title": "Claude Fable 5 / Mythos 5 发布",
            "expires_on": "2026-06-14",
            "watch_items": ["第三方 benchmark 何时收录"],
        }
    ]


def test_init_daily_manifest_includes_reader_profile(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )

    code, message = run_daily_init(tmp_path, "2026-06-12", "2026-06-12T07:10:00+08:00", env_path)

    assert code == 0, message
    manifest = json.loads(
        (tmp_path / "cache" / "2026-06-12" / "discovery_manifest.json").read_text(encoding="utf-8")
    )
    decision_names = [d["name"] for d in manifest["reader_profile"]["decisions_in_flight"]]
    assert "coding-agent-2026H2" in decision_names
