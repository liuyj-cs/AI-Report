import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
FIXTURES = SKILL_ROOT / "tests" / "fixtures"
SCRIPT = SKILL_ROOT / "scripts" / "render_html.py"
SCHEMAS = SKILL_ROOT / "schemas"

SHARED_DEFS = [
    "itemRef",
    "benchmarkChange",
    "benchmarkWatch",
    "pricingChange",
    "adoptionSignal",
    "capabilityGap",
    "marketSignalsSection",
    "patternObservation",
    "patternObservationsSection",
    "experiment",
    "experimentsSection",
    "actionItem",
    "reference",
]


def run_render(json_path: Path, output_path: Path | None = None) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT), str(json_path)]
    if output_path is not None:
        cmd += ["--output", str(output_path)]
    return subprocess.run(cmd, capture_output=True, text=True)


def test_render_daily_basic(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"

    result = run_render(fixture, output)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert output.exists(), "output HTML should be written"

    html = output.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # 标题包含日期
    assert "AI 日报" in soup.get_text()
    assert "2026-04-10" in soup.get_text()

    # 八个章节标题都在
    text = soup.get_text()
    assert "头部大模型动态" in text
    assert "Coding Agent 专项" in text
    assert "通用 Agent 动态" in text
    assert "硬数据信号" in text
    assert "跨条目模式" in text
    assert "本期建议实验" in text
    assert "今日落地建议" in text
    assert "待核实区" in text


def test_render_daily_has_items_and_card_structure(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    run_render(fixture, output)

    html = output.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    # 头部大模型：应该看到具体条目
    assert "Anthropic" in text
    assert "Claude Opus 4.6" in text
    assert "DeepSeek" in text
    assert "V4" in text

    # Coding Agent
    assert "Claude Code" in text
    assert "Plan Mode" in text
    # 深度观察正文
    assert "Plan Mode 的深度观察" in text

    # 通用 Agent
    assert "openclaw" in text

    # 落地建议
    assert "P1" in text
    assert "P2" in text
    assert "本周让 2-3 个核心工程师试用" in text

    # 待核实区
    assert "字节即将发布通用 agent" in text

    # 抓取状态（footer 折叠）
    assert "MiniMax" in text
    assert "timeout" in text

    # 视口和 HTML 语言
    assert soup.find("meta", attrs={"name": "viewport"}) is not None
    assert soup.find("html").get("lang") == "zh-CN"


def test_render_daily_empty_shows_empty_message(tmp_path):
    fixture = FIXTURES / "sample_daily_empty.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    html = output.read_text(encoding="utf-8")
    text = BeautifulSoup(html, "html.parser").get_text()

    # action_items 为空时显示 empty_message
    assert "今日无明显行动项" in text


def test_render_daily_invalid_json_fails_schema(tmp_path):
    bad = {"version": "1.0", "type": "daily"}  # 缺失必填字段
    bad_path = tmp_path / "bad.json"
    bad_path.write_text(json.dumps(bad), encoding="utf-8")
    output = tmp_path / "report.html"
    result = run_render(bad_path, output)

    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_daily_with_release_stage_badges(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    run_render(fixture, output)

    html = output.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    # GA / BETA 徽章应被渲染
    assert soup.select(".badge-stage-ga"), "expect at least one GA stage badge"
    assert soup.select(".badge-stage-beta"), "expect at least one BETA stage badge"
    text = soup.get_text()
    assert "GA" in text
    assert "BETA" in text

    # via_broad_search 标记
    assert soup.select(".badge-broad"), "expect broad search badge for Cursor item"


def test_render_daily_with_evidence_quote(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    run_render(fixture, output)

    html = output.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")

    quotes = soup.select("blockquote.evidence")
    assert quotes, "expect blockquote.evidence on items with evidence_quote"
    assert "Claude Opus 4.6 sets a new bar" in quotes[0].get_text()


def test_render_daily_fetch_status_source_details(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    run_render(fixture, output)

    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "降级路径" in text
    assert "OpenAI" in text and "websearch_scoped" in text
    assert "广义搜索" in text  # Cursor via_broad_search
    assert "首轮无窗口内条目" in text
    assert "经补证 / 其他 surface 命中" in text


def test_render_daily_missing_required_new_field_fails_schema(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    data = json.loads(fixture.read_text(encoding="utf-8"))
    # 移除 release_stage 触发 schema 校验失败
    data["sections"]["frontier_models"]["items"][0].pop("release_stage")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "out.html"
    result = run_render(bad, output)

    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_weekly_reference_badges(tmp_path):
    fixture = FIXTURES / "sample_weekly.json"
    output = tmp_path / "report.html"
    run_render(fixture, output)

    html = output.read_text(encoding="utf-8")
    # reference 行应渲染 release_stage 徽章，但不再把 authority_score 视觉化成星级
    assert "badge-stage-ga" in html
    assert "authority-stars" not in html


def test_render_weekly_full(tmp_path):
    fixture = FIXTURES / "sample_weekly.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    html = output.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    # 标题和窗口标识
    assert "AI 周报" in text
    assert "2026-04-12" in text
    assert "2026-04-06" in text

    # 九个章节标题
    assert "本周核心结论" in text
    assert "头部大模型：本周动态与趋势" in text
    assert "Coding Agent 深度观察" in text
    assert "通用 Agent 格局变化" in text
    assert "硬数据信号" in text
    assert "跨条目模式" in text
    assert "本周建议实验" in text
    assert "本周落地建议" in text
    assert "下周值得关注的信号" in text

    # TL;DR bullets
    assert "Claude Opus 4.6 与 DeepSeek V4 同周释放" in text

    # vendor group 三段式
    assert "Anthropic" in text
    assert "模型+工具双轮驱动" in text

    # 落地建议 P0
    assert "P0" in text
    assert "约 1 人周" in text

    # Next week signals
    assert "Google I/O" in text

    # 视口
    assert soup.find("meta", attrs={"name": "viewport"}) is not None


# ---------- Phase 2 新增测试 ----------


def _render_daily(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return output.read_text(encoding="utf-8")


def _render_weekly(tmp_path):
    fixture = FIXTURES / "sample_weekly.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    return output.read_text(encoding="utf-8")


def _render_with_mutated(tmp_path, mutate):
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    mutate(data)
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "out.html"
    return run_render(bad, output)


def test_render_daily_with_market_signals(tmp_path):
    html = _render_daily(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    assert soup.select(".market-signals"), "expect .market-signals block"
    assert "Arena Elo" in text
    assert "1412" in text and "1438" in text
    assert "评分 / 榜单观察" in text
    assert "新一轮官方 benchmark 快照" in text
    assert "-31.5%" in text
    assert soup.select(".delta-up"), "expect at least one .delta-up"
    assert soup.select(".delta-down"), "expect at least one .delta-down"


def test_daily_schema_requires_adoption_signals_bucket():
    schema = json.loads((SCHEMAS / "daily_report.schema.json").read_text(encoding="utf-8"))
    required = schema["$defs"]["marketSignalsSection"]["required"]
    assert "adoption_signals" in required
    assert schema["$defs"]["marketSignalsSection"]["properties"]["adoption_signals"]["items"]["$ref"] == "#/$defs/adoptionSignal"


def test_weekly_schema_requires_adoption_signals_bucket():
    schema = json.loads((SCHEMAS / "weekly_report.schema.json").read_text(encoding="utf-8"))
    required = schema["$defs"]["marketSignalsSection"]["required"]
    assert "adoption_signals" in required
    assert schema["$defs"]["marketSignalsSection"]["properties"]["adoption_signals"]["items"]["$ref"] == "#/$defs/adoptionSignal"


def test_render_daily_adoption_signals(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "采用率 / 商业化信号" in text
    assert "Microsoft 365 Copilot" in text
    assert "20M paid seats" in text


def test_render_weekly_adoption_signals(tmp_path):
    fixture = FIXTURES / "sample_weekly.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "采用率 / 商业化信号" in text
    assert "Microsoft 365 Copilot" in text


def test_render_daily_market_signals_empty_shows_message(tmp_path):
    fixture = FIXTURES / "sample_daily_empty.json"
    output = tmp_path / "report.html"
    run_render(fixture, output)

    html = output.read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    assert "今日无显著硬数据变化" in text
    assert not soup.select(".signal-row"), "empty fixture should have zero .signal-row"


def test_render_daily_pattern_observations(tmp_path):
    html = _render_daily(tmp_path)
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select(".pattern-card")
    assert cards, "expect at least one .pattern-card"
    assert "推理能力开始向开源外溢" in cards[0].get_text()

    refs = cards[0].select(".refs a")
    assert len(refs) >= 2, "pattern card should reference ≥2 items"
    for a in refs:
        assert a.get("href", "").startswith("#"), "ref link should be anchor"


def test_render_daily_pattern_observations_empty(tmp_path):
    fixture = FIXTURES / "sample_daily_empty.json"
    output = tmp_path / "report.html"
    run_render(fixture, output)

    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "今日无显著跨条目模式" in text


def test_render_daily_experiment_block(tmp_path):
    html = _render_daily(tmp_path)
    soup = BeautifulSoup(html, "html.parser")

    cards = soup.select(".experiment-card")
    assert cards, "expect .experiment-card"
    text = cards[0].get_text()
    assert "假设：" in text
    steps = cards[0].select("ol.steps li")
    assert len(steps) >= 2, "experiment should have ≥2 steps"
    assert "4" in text and "8" in text and "小时" in text


def test_render_daily_action_items_have_person_days_and_type(tmp_path):
    html = _render_daily(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    assert soup.select(".badge-rec-experiment"), "expect experiment recommendation badge"
    assert soup.select(".badge-rec-adopt"), "expect adopt recommendation badge"
    assert soup.select(".badge-rec-monitor"), "expect monitor recommendation badge"
    assert "人日" in text
    assert soup.select(".badge-horizon"), "expect time_horizon badge"


def test_render_daily_editorial_tiers_are_visible(tmp_path):
    html = _render_daily(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text()

    assert soup.select(".badge-tier-core"), "expect core editorial badge"
    assert soup.select(".badge-tier-watch"), "expect watch editorial badge"
    assert "核心发布" in text
    assert "重要观察" in text


def test_render_daily_action_items_diversity_rule_is_soft(tmp_path):
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    items = data["sections"]["action_items"]["items"]
    types = {it["recommendation_type"] for it in items}
    assert len(items) >= 3
    assert len(types) >= 3, f"fixture should cover ≥3 distinct recommendation_types, got {types}"


def test_render_daily_anchor_ids_exist(tmp_path):
    html = _render_daily(tmp_path)
    assert 'id="frontier_models-0"' in html
    assert 'id="coding_agents-0"' in html
    assert 'id="general_agents-0"' in html


def test_render_daily_missing_market_signals_fails_schema(tmp_path):
    def mutate(data):
        data["sections"].pop("market_signals")

    result = _render_with_mutated(tmp_path, mutate)
    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_daily_action_item_missing_recommendation_type_fails_schema(tmp_path):
    def mutate(data):
        data["sections"]["action_items"]["items"][0].pop("recommendation_type")

    result = _render_with_mutated(tmp_path, mutate)
    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_daily_missing_editorial_tier_fails_schema(tmp_path):
    def mutate(data):
        data["sections"]["frontier_models"]["items"][0].pop("editorial_tier")

    result = _render_with_mutated(tmp_path, mutate)
    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_daily_action_reference_missing_section_fails_schema(tmp_path):
    def mutate(data):
        data["sections"]["action_items"]["items"][0]["references"][0].pop("section")

    result = _render_with_mutated(tmp_path, mutate)
    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_daily_action_reference_missing_editorial_tier_fails_schema(tmp_path):
    def mutate(data):
        data["sections"]["action_items"]["items"][0]["references"][0].pop("editorial_tier")

    result = _render_with_mutated(tmp_path, mutate)
    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_daily_effort_person_days_range_valid(tmp_path):
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    for item in data["sections"]["action_items"]["items"]:
        epd = item["effort_person_days"]
        assert epd["max"] >= epd["min"], f"max < min in {item['recommendation']}"


def test_render_daily_itemref_pattern_valid(tmp_path):
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    section_lengths = {
        "frontier_models": len(data["sections"]["frontier_models"]["items"]),
        "coding_agents": len(data["sections"]["coding_agents"]["items"]),
        "general_agents": len(data["sections"]["general_agents"]["items"]),
    }
    pattern = re.compile(r"^(frontier_models|coding_agents|general_agents)\[(\d+)\]$")

    refs = []
    for p in data["sections"]["pattern_observations"]["items"]:
        refs.extend(p["supporting_item_refs"])
    for g in data["sections"]["market_signals"]["capability_gaps"]:
        if "ref" in g:
            refs.append(g["ref"])
    for e in data["sections"]["experiments_this_week"]["items"]:
        refs.extend(e.get("related_item_refs", []))

    assert refs, "fixture should contain at least one itemRef to validate"
    for ref in refs:
        m = pattern.match(ref)
        assert m, f"bad ref shape: {ref}"
        section, idx = m.group(1), int(m.group(2))
        assert idx < section_lengths[section], f"{ref} index out of range"


def test_render_weekly_pattern_observations_required_nonempty(tmp_path):
    data = json.loads((FIXTURES / "sample_weekly.json").read_text(encoding="utf-8"))
    data["sections"]["pattern_observations"]["items"] = []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "out.html"
    result = run_render(bad, output)

    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_weekly_experiments_required_nonempty(tmp_path):
    data = json.loads((FIXTURES / "sample_weekly.json").read_text(encoding="utf-8"))
    data["sections"]["experiments_this_week"]["items"] = []
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(data), encoding="utf-8")
    output = tmp_path / "out.html"
    result = run_render(bad, output)

    assert result.returncode == 1
    assert "schema validation" in result.stderr.lower()


def test_render_weekly_action_items_match_daily_schema_shape(tmp_path):
    daily = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    weekly = json.loads((FIXTURES / "sample_weekly.json").read_text(encoding="utf-8"))

    daily_keys = set(daily["sections"]["action_items"]["items"][0].keys())
    weekly_keys = set(weekly["sections"]["action_items"]["items"][0].keys())

    required = {
        "recommendation",
        "rationale",
        "recommendation_type",
        "effort_person_days",
        "time_horizon",
        "team_size_applicability",
        "priority",
    }
    assert required.issubset(daily_keys)
    assert required.issubset(weekly_keys)


def test_schema_shared_defs_are_byte_identical():
    daily = json.loads((SCHEMAS / "daily_report.schema.json").read_text(encoding="utf-8"))
    weekly = json.loads((SCHEMAS / "weekly_report.schema.json").read_text(encoding="utf-8"))

    for name in SHARED_DEFS:
        assert name in daily["$defs"], f"daily missing $def {name}"
        assert name in weekly["$defs"], f"weekly missing $def {name}"
        assert daily["$defs"][name] == weekly["$defs"][name], f"$def drift: {name}"


def test_render_weekly_market_signals_block_renders(tmp_path):
    html = _render_weekly(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select(".market-signals"), "weekly should render .market-signals"
    assert "Arena Elo" in soup.get_text()
    assert "评分 / 榜单观察" in soup.get_text()


def test_render_weekly_experiment_block_renders(tmp_path):
    html = _render_weekly(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    assert soup.select(".experiment-card"), "weekly should render .experiment-card"


def test_candidate_ledger_fixture_matches_schema():
    schema = json.loads((SCHEMAS / "candidate_ledger.schema.json").read_text(encoding="utf-8"))
    data = json.loads((FIXTURES / "sample_candidate_ledger.json").read_text(encoding="utf-8"))

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    assert not errors, [f"{'/'.join(str(p) for p in err.path)}: {err.message}" for err in errors]


def test_candidate_ledger_invalid_decision_fails_schema():
    schema = json.loads((SCHEMAS / "candidate_ledger.schema.json").read_text(encoding="utf-8"))
    data = json.loads((FIXTURES / "sample_candidate_ledger.json").read_text(encoding="utf-8"))
    data["items"][0]["decision"] = "selected_priority_score"

    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    assert errors


def test_candidate_ledger_requires_audit_fields():
    schema = json.loads((SCHEMAS / "candidate_ledger.schema.json").read_text(encoding="utf-8"))
    data = json.loads((FIXTURES / "sample_candidate_ledger.json").read_text(encoding="utf-8"))
    data["items"][0].pop("date_basis", None)

    errors = list(Draft202012Validator(schema).iter_errors(data))

    assert any("date_basis" in error.message for error in errors)


def test_candidate_ledger_rejects_page_update_as_core_date_basis():
    schema = json.loads((SCHEMAS / "candidate_ledger.schema.json").read_text(encoding="utf-8"))
    data = json.loads((FIXTURES / "sample_candidate_ledger.json").read_text(encoding="utf-8"))
    data["items"][0]["date_basis"] = "page_updated_at"
    data["items"][0]["decision"] = "selected_core"

    errors = list(Draft202012Validator(schema).iter_errors(data))

    assert any("page_updated_at" in error.message for error in errors)


# ---------- Task 1: major_event expanded block schema tests ----------


def _load_daily_schema():
    return json.loads((SCHEMAS / "daily_report.schema.json").read_text(encoding="utf-8"))


def _major_event_item(base_item):
    item = dict(base_item)
    item["major_event"] = True
    item["tracking_ref"] = "claude-fable-5"
    item["expanded"] = {
        "what_shipped": "Anthropic 发布 Claude Fable 5 与 Mythos 5，首次把 Mythos 级模型开放到通用用户侧，并同步更新模型卡与定价页。",
        "benchmarks": "官方模型卡给出 SWE-bench Verified 与 Terminal-Bench 对比数字。",
        "pricing_availability": "API 与 Claude Code 当天可用，定价沿用 Opus 档位。",
        "open_questions": ["第三方 benchmark（LMArena / AA）何时收录", "长任务实测是否优于 Opus 4.8"],
    }
    return item


def test_daily_schema_accepts_major_event_expanded_block():
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    data["sections"]["frontier_models"]["items"][0] = _major_event_item(
        data["sections"]["frontier_models"]["items"][0]
    )
    validator = Draft202012Validator(_load_daily_schema())
    assert list(validator.iter_errors(data)) == []


def test_daily_schema_rejects_overlong_expanded_field():
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    item = _major_event_item(data["sections"]["frontier_models"]["items"][0])
    item["expanded"]["what_shipped"] = "长" * 601
    data["sections"]["frontier_models"]["items"][0] = item
    validator = Draft202012Validator(_load_daily_schema())
    assert any(
        "what_shipped" in "/".join(str(p) for p in e.path)
        for e in validator.iter_errors(data)
    )


def test_daily_schema_rejects_invalid_tracking_ref():
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    data["sections"]["frontier_models"]["items"][0]["tracking_ref"] = "Claude Fable!"
    validator = Draft202012Validator(_load_daily_schema())
    assert any(
        "tracking_ref" in "/".join(str(p) for p in e.path)
        for e in validator.iter_errors(data)
    )


def test_render_daily_major_event_expanded_block(tmp_path):
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    data["sections"]["frontier_models"]["items"][0] = _major_event_item(
        data["sections"]["frontier_models"]["items"][0]
    )
    src = tmp_path / "report.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "report.html"
    result = run_render(src, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    soup = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser")
    text = soup.get_text()
    assert soup.select(".badge-major"), "expect major event badge"
    assert soup.select(".badge-tracking"), "expect tracking badge"
    assert soup.select(".major-expanded"), "expect expanded block container"
    assert "发布要点" in text
    assert "待验证" in text
    assert "第三方 benchmark（LMArena / AA）何时收录" in text


def test_render_daily_expanded_decision_and_quickstart(tmp_path):
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    item = _major_event_item(data["sections"]["frontier_models"]["items"][0])
    item["expanded"]["decision_relevance"] = "对正在评估的 coding agent 选型，这一代模型显著改变 Claude 档位的性价比判断，建议本周内重排候选。"
    item["expanded"]["quick_start"] = "Claude Code 中 /model 切换 claude-fable-5 即可试用；API 侧把模型号换成 claude-fable-5，无需改请求结构。"
    data["sections"]["frontier_models"]["items"][0] = item
    src = tmp_path / "report.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "report.html"
    result = run_render(src, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "对选型意味着什么" in text
    assert "快速上手" in text
    assert "coding agent 选型" in text
    assert "claude-fable-5" in text


# ---------- Task 2: decision_radar ----------


def test_daily_schema_requires_decision_radar_section():
    schema = _load_daily_schema()
    assert "decision_radar" in schema["properties"]["sections"]["required"]


def test_render_daily_decision_radar(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    soup = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser")
    text = soup.get_text()
    assert "决策雷达" in text
    assert "coding-agent-2026H2" in text
    assert soup.select(".radar-group"), "expect radar group container"


def test_render_daily_decision_radar_empty_shows_message(tmp_path):
    fixture = FIXTURES / "sample_daily_empty.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "今日无影响在途决策的信息" in text


# ---------- Task 4: agent_ecosystem ----------


def test_daily_schema_requires_agent_ecosystem_section():
    schema = _load_daily_schema()
    assert "agent_ecosystem" in schema["properties"]["sections"]["required"]


def test_daily_schema_trending_repo_requires_heat_note():
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    item = data["sections"]["agent_ecosystem"]["items"][0]
    assert item["item_type"] == "trending_repo"
    item.pop("heat_note")
    validator = Draft202012Validator(_load_daily_schema())
    assert any(
        "heat_note" in e.message for e in validator.iter_errors(data)
    )


def test_render_daily_agent_ecosystem(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    soup = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser")
    text = soup.get_text()
    assert "Agent 生态与实践" in text
    assert soup.select(".badge-eco-trending_repo"), "expect ecosystem type badge"
    assert "适用：" in text
    assert "claude-flow" in text


def test_daily_schema_requires_experiment_audience():
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    item = data["sections"]["experiments_this_week"]["items"][0]
    assert item["audience"] in {"team_pilot", "personal_workflow"}
    item.pop("audience")
    validator = Draft202012Validator(_load_daily_schema())
    assert any("audience" in e.message for e in validator.iter_errors(data))


def test_weekly_schema_requires_experiment_audience():
    schema = json.loads((SCHEMAS / "weekly_report.schema.json").read_text(encoding="utf-8"))
    data = json.loads((FIXTURES / "sample_weekly.json").read_text(encoding="utf-8"))
    item = data["sections"]["experiments_this_week"]["items"][0]
    assert item["audience"] in {"team_pilot", "personal_workflow"}
    item.pop("audience")
    validator = Draft202012Validator(schema)
    assert any("audience" in e.message for e in validator.iter_errors(data))


def test_render_daily_experiment_audience_chip(tmp_path):
    fixture = FIXTURES / "sample_daily.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "团队试点" in text or "个人工作流" in text


def test_render_weekly_experiment_audience_chip(tmp_path):
    fixture = FIXTURES / "sample_weekly.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "团队试点" in text or "个人工作流" in text


def test_weekly_schema_requires_practice_digest_section():
    schema = json.loads((SCHEMAS / "weekly_report.schema.json").read_text(encoding="utf-8"))
    assert "practice_digest" in schema["properties"]["sections"]["required"]


def test_render_weekly_practice_digest(tmp_path):
    fixture = FIXTURES / "sample_weekly.json"
    output = tmp_path / "report.html"
    result = run_render(fixture, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    soup = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser")
    text = soup.get_text()
    assert "本周实践精选" in text
    assert soup.select(".digest-card"), "expect practice digest card"
    assert "适合现在引入" in text
    assert "九、" in text and "十、" in text


# ---------- deep dive ----------


def test_render_deep_dive_basic(tmp_path, sample_deep_dive):
    src = tmp_path / "deep_dive_claude-fable-5.json"
    src.write_text(json.dumps(sample_deep_dive, ensure_ascii=False), encoding="utf-8")
    output = tmp_path / "deep_dive_claude-fable-5.html"
    result = run_render(src, output)
    assert result.returncode == 0, f"stderr: {result.stderr}"

    text = BeautifulSoup(output.read_text(encoding="utf-8"), "html.parser").get_text()
    assert "AI 深度" in text
    assert "背景与时间线" in text
    assert "对四个角色意味着什么" in text
    assert "选型负责人" in text
    assert "快速上手" in text
    assert "待验证问题" in text


def test_render_deep_dive_default_output_next_to_json(tmp_path, sample_deep_dive):
    src = tmp_path / "deep_dive_claude-fable-5.json"
    src.write_text(json.dumps(sample_deep_dive, ensure_ascii=False), encoding="utf-8")
    result = run_render(src)
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert (tmp_path / "deep_dive_claude-fable-5.html").exists()


def test_render_deep_dive_missing_section_fails_schema(tmp_path, sample_deep_dive):
    data = deepcopy(sample_deep_dive)
    del data["sections"]["quick_start"]
    src = tmp_path / "deep_dive_claude-fable-5.json"
    src.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    result = run_render(src, tmp_path / "out.html")
    assert result.returncode == 1
    assert "quick_start" in result.stderr
