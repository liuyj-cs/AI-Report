import json
from copy import deepcopy
from datetime import date, timedelta

from discovery import RECALL_PROBE_SURFACE_NAME, load_whitelist
from report_runner import main, run_daily_finalize, run_daily_init
from source_stats import load_source_stats, source_stats_path

DATE = "2026-04-18"
LONGTAIL = "Aider"


def _write_env(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )
    return env_path


def _prepare_finalize_cache(tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    """落一份能通过 finalize 校验的当日缓存（沿用 test_report_runner 的最小骨架）。"""
    cache_dir = tmp_path / "cache" / DATE
    cache_dir.mkdir(parents=True, exist_ok=True)
    whitelist = load_whitelist()

    report = deepcopy(sample_daily_report)
    report["date"] = DATE
    report["generated_at"] = f"{DATE}T07:30:00+08:00"
    report["window"] = {
        "start": "2026-04-17T07:00:00+08:00",
        "end": f"{DATE}T07:30:00+08:00",
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
            "published_at": f"{DATE}T05:20:00+08:00",
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
                    "date": DATE,
                    "headline": "Agents SDK 原生接入沙箱执行",
                    "url": "https://openai.com/index/the-next-evolution-of-the-agents-sdk/",
                    "section": "general_agents",
                    "editorial_tier": "core",
                }
            ],
        }
    ]

    ledger = deepcopy(sample_candidate_ledger)
    ledger["date"] = DATE
    ledger["generated_at"] = f"{DATE}T07:30:00+08:00"
    ledger["items"][0]["proposed_section"] = "general_agents"
    ledger["items"][0]["headline"] = "Agents SDK 原生接入沙箱执行"
    ledger["items"][0]["published_at"] = f"{DATE}T05:20:00+08:00"
    ledger["items"][0]["source_attempt_refs"] = ["OpenAI.attempts[0]"]
    ledger["items"] = ledger["items"][:1]

    (cache_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (cache_dir / "candidate_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (cache_dir / "run.log").write_text(f"{DATE}T07:30:00+08:00 START daily\n", encoding="utf-8")
    return cache_dir, report


def _seed_stats(tmp_path, name, count, *, hit_on=(), start_offset=1):
    target = date.fromisoformat(DATE)
    days = {}
    for offset in range(start_offset, start_offset + count):
        day = (target - timedelta(days=offset)).isoformat()
        days[day] = {name: {"attempts": 2, "hit": offset in hit_on}}
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "days": days}, ensure_ascii=False), encoding="utf-8")


def test_init_daily_writes_cadence_into_manifest(tmp_path):
    env_path = _write_env(tmp_path)
    _seed_stats(tmp_path, LONGTAIL, 20)

    code, _ = run_daily_init(tmp_path, DATE, f"{DATE}T07:30:00+08:00", env_path)
    assert code == 0

    manifest = json.loads((tmp_path / "cache" / DATE / "discovery_manifest.json").read_text(encoding="utf-8"))
    by_name = {source["name"]: source for source in manifest["required_sources"]}
    assert by_name[LONGTAIL]["cadence"] == "weekly"
    assert by_name[LONGTAIL]["due"] is False
    assert by_name[LONGTAIL]["last_probed"] == (date.fromisoformat(DATE) - timedelta(days=1)).isoformat()
    assert by_name["OpenAI"]["cadence"] == "daily"
    assert by_name["OpenAI"]["due"] is True


def test_init_daily_writes_cadence_summary_and_run_log(tmp_path):
    env_path = _write_env(tmp_path)
    _seed_stats(tmp_path, LONGTAIL, 20)

    run_daily_init(tmp_path, DATE, f"{DATE}T07:30:00+08:00", env_path)

    manifest = json.loads((tmp_path / "cache" / DATE / "discovery_manifest.json").read_text(encoding="utf-8"))
    summary = manifest["cadence_summary"]
    assert summary["skipped"] == 1
    assert summary["due"] + summary["skipped"] == len(manifest["cadence_plan"])
    run_log = (tmp_path / "cache" / DATE / "run.log").read_text(encoding="utf-8")
    assert f"CADENCE due={summary['due']} skipped={summary['skipped']}" in run_log


def test_manifest_cadence_plan_covers_aggregate_surfaces(tmp_path):
    env_path = _write_env(tmp_path)

    run_daily_init(tmp_path, DATE, f"{DATE}T07:30:00+08:00", env_path)

    manifest = json.loads((tmp_path / "cache" / DATE / "discovery_manifest.json").read_text(encoding="utf-8"))
    assert manifest["cadence_plan"][RECALL_PROBE_SURFACE_NAME]["cadence"] == "daily"
    assert manifest["cadence_plan"][RECALL_PROBE_SURFACE_NAME]["due"] is True


def test_finalize_records_source_stats(
    tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
):
    env_path = _write_env(tmp_path)
    _prepare_finalize_cache(tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status)

    code, _ = run_daily_finalize(tmp_path, DATE, dry_run=True, env_path=env_path)
    assert code == 0

    stats = load_source_stats(tmp_path)
    assert DATE in stats["days"]
    assert stats["days"][DATE]["OpenAI"]["attempts"] >= 1
    run_log = (tmp_path / "cache" / DATE / "run.log").read_text(encoding="utf-8")
    assert "SOURCE_STATS recorded=" in run_log


def test_finalize_dry_run_still_records_source_stats(
    tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status
):
    """dry-run 统计的是采集事实，与投递结果无关——与 seen-ledger 语义有意不同。"""
    env_path = _write_env(tmp_path)
    _prepare_finalize_cache(tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status)

    run_daily_finalize(tmp_path, DATE, dry_run=True, env_path=env_path)

    assert DATE in load_source_stats(tmp_path)["days"]


def test_source_stats_subcommand_prints_summary_and_due_preview(tmp_path, capsys):
    _seed_stats(tmp_path, LONGTAIL, 20)

    exit_code = main(["--project-root", str(tmp_path), "source-stats", "--date", DATE])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["date"] == DATE
    assert payload["summary"][LONGTAIL] == {"probed_days": 20, "hit_days": 0, "cadence": "weekly", "due": False}
    assert payload["due_count"] + payload["skipped_count"] == len(payload["cadence_plan"])


def test_source_stats_subcommand_on_empty_ledger(tmp_path, capsys):
    exit_code = main(["--project-root", str(tmp_path), "source-stats", "--date", DATE])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"] == {}
    assert payload["skipped_count"] == 0
