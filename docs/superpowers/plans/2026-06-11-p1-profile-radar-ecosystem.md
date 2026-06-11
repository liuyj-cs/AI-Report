# P1: Reader Profile + Decision Radar + Agent Ecosystem Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the daily report decision-aware (a `profile.yaml` of the reader's four roles drives a per-decision `decision_radar` section) and give the practice line a home (a new `agent_ecosystem` section for trending repos / skills / practice cases / tool releases with snapshot discipline and a 30-day repeat cooldown).

**Architecture:** Same contract as P0 — the AI editor makes all judgments per SKILL.md; repo scripts add deterministic surface: profile exposure in the discovery manifest, two new required report sections (schema + render), ref/name validators at finalize, and a `cache/seen_repos.json` cooldown ledger maintained by the runner. Daily report grows from 8 to 10 sections (decision_radar before action_items; agent_ecosystem after general_agents).

**Tech Stack:** Python 3.13, PyYAML, jsonschema, Jinja2, pytest.

**Baseline:** main @ 14b0751 (P0 merged; 133 tests green). Create branch `feat/p1-profile-radar-ecosystem` first. Stage only the files named in each commit step.

---

## File Map

**Create**
- `skills/ai-daily-report/sources/profile.yaml` — reader roles, decisions in flight, practice focus.
- `skills/ai-daily-report/scripts/ecosystem.py` — seen-repos cooldown ledger helpers + ecosystem validators.
- `skills/ai-daily-report/tests/test_ecosystem.py` — unit tests for ecosystem module.

**Modify**
- `skills/ai-daily-report/scripts/discovery.py` — `load_profile`, `ECOSYSTEM_DISCOVERY_NAME` surface, manifest gains `reader_profile` + `ecosystem_search_queries`.
- `skills/ai-daily-report/scripts/report_runner.py` — init passes profile to manifest; finalize passes profile to validators and records ecosystem repos after success.
- `skills/ai-daily-report/scripts/editorial.py` — `validate_decision_radar`; wire radar + ecosystem validators into `validate_daily_artifacts`.
- `skills/ai-daily-report/schemas/daily_report.schema.json` — `decision_radar` + `agent_ecosystem` required sections with `$defs`.
- `skills/ai-daily-report/templates/daily.html.j2` — render both sections; TOC renumbered 一–十.
- `skills/ai-daily-report/sources/whitelist.yaml` — ecosystem + workplace sources/queries.
- `skills/ai-daily-report/SKILL.md`, `README.md` — workflow rules + docs.
- Fixtures `tests/fixtures/sample_daily.json`, `tests/fixtures/sample_daily_empty.json` — add the two new sections.
- Tests: `test_discovery.py`, `test_report_runner.py`, `test_editorial.py`, `test_render_html.py`.

**Leave As-Is**
- Weekly schema/template/validators (weekly aggregation of radar/ecosystem is第三批 scope). Weekly readers only consume the three body sections of dailies, so 10-section dailies are backward compatible for weekly runs.
- `scripts/tracking.py`, `scripts/evidence.py`, `scripts/archive.py` (seen_repos.json is a FILE under cache/, and `_iter_cache_leaf_dirs` only iterates dirs — already safe).

---

### Task 1: profile.yaml + manifest exposure

**Files:**
- Create: `skills/ai-daily-report/sources/profile.yaml`
- Modify: `skills/ai-daily-report/scripts/discovery.py` (add `load_profile`; `build_discovery_manifest` gains `reader_profile=None`)
- Modify: `skills/ai-daily-report/scripts/report_runner.py` (`run_daily_init` loads + passes profile)
- Test: `skills/ai-daily-report/tests/test_discovery.py`, `skills/ai-daily-report/tests/test_report_runner.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_discovery.py`:

```python
def test_load_profile_returns_roles_and_decisions():
    from discovery import load_profile

    profile = load_profile()
    role_ids = [role["id"] for role in profile["roles"]]
    assert "coding_agent_selection" in role_ids
    assert "workplace_ai_enablement" in role_ids
    assert "ai_coding_adoption_lead" in role_ids
    assert "agent_power_user" in role_ids
    decision_names = [d["name"] for d in profile["decisions_in_flight"]]
    assert "coding-agent-2026H2" in decision_names
    assert "workplace-ai" in decision_names
    assert profile["practice_focus"]


def test_build_discovery_manifest_includes_reader_profile(sample_whitelist):
    from discovery import build_discovery_manifest, compute_daily_window, load_profile

    window = compute_daily_window("2026-06-12", "2026-06-12T07:10:00+08:00")
    manifest = build_discovery_manifest("2026-06-12", window, sample_whitelist)
    assert manifest["reader_profile"] == {}

    profile = load_profile()
    manifest = build_discovery_manifest(
        "2026-06-12", window, sample_whitelist, reader_profile=profile
    )
    assert manifest["reader_profile"]["roles"]
```

Append to `tests/test_report_runner.py`:

```python
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
```

- [ ] **Step 2: Verify failure**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_discovery.py -q -k "profile" skills/ai-daily-report/tests/test_report_runner.py::test_init_daily_manifest_includes_reader_profile`
Expected: ImportError (`load_profile`) / KeyError (`reader_profile`).

- [ ] **Step 3: Create `sources/profile.yaml`**

```yaml
# 读者画像：AI 编辑做相关性与决策影响判断的输入。
# roles 是长期角色；decisions_in_flight 是在途决策（radar 按它分组）；
# practice_focus 锚定 agent_ecosystem 的相关性判断。过期决策应删除或归档。

roles:
  - id: coding_agent_selection
    description: 公司 coding agent 方案选型负责人
  - id: workplace_ai_enablement
    description: 公司非技术人员 AI Agent 方案负责人
  - id: ai_coding_adoption_lead
    description: 技术总监，负责团队 AI coding 推进与最佳实践沉淀
  - id: agent_power_user
    description: 开发工程师，深度使用 Claude Code / Codex

decisions_in_flight:
  - name: coding-agent-2026H2
    description: 公司 coding agent 选型
    candidates: [Claude Code, Codex, Cursor, GitHub Copilot]
    criteria: [企业管控/SSO/审计, 定价与席位, 模型路由灵活性, CN 可用性]
  - name: workplace-ai
    description: 非技术员工 AI agent 方案
    candidates: [Microsoft 365 Copilot, ChatGPT Enterprise, 飞书/钉钉 AI]
    criteria: [非技术上手成本, 数据合规, 部署形态]

practice_focus:
  - 团队级 agent 工作流（code review / 测试 / CI 集成 / 多 agent 编排）
  - Claude Code / Codex 的 skills、插件、MCP 生态
  - AI coding 推广度量与治理（采纳率、效率度量、权限管控）
```

- [ ] **Step 4: Implement loader + manifest key**

In `scripts/discovery.py`, after `WHITELIST_PATH` add:

```python
PROFILE_PATH = Path(__file__).resolve().parent.parent / "sources" / "profile.yaml"
```

After `load_whitelist` add:

```python
def load_profile(path: Path | None = None) -> dict[str, Any]:
    target = path or PROFILE_PATH
    if not target.exists():
        return {}
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}
```

Change `build_discovery_manifest` signature to:

```python
def build_discovery_manifest(
    target_date: str,
    window: dict[str, str],
    whitelist: dict[str, Any],
    active_tracking: list[dict[str, Any]] | None = None,
    reader_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
```

and add to the returned dict after `"active_tracking": active_tracking or [],`:

```python
        "reader_profile": reader_profile or {},
```

In `scripts/report_runner.py` `run_daily_init`: extend the discovery import with `load_profile` (it already imports `build_discovery_manifest, compute_daily_window, load_whitelist, ...` from discovery), and change the manifest call to:

```python
    manifest = build_discovery_manifest(
        target_date, window, whitelist, active_tracking=active, reader_profile=load_profile()
    )
```

- [ ] **Step 5: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 136 passed.

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/sources/profile.yaml skills/ai-daily-report/scripts/discovery.py skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/tests/test_discovery.py skills/ai-daily-report/tests/test_report_runner.py
git commit -m "feat: add reader profile and expose it in discovery manifest"
```

### Task 2: decision_radar schema section + fixtures + render

**Files:**
- Modify: `skills/ai-daily-report/schemas/daily_report.schema.json`
- Modify: `skills/ai-daily-report/tests/fixtures/sample_daily.json`, `tests/fixtures/sample_daily_empty.json`
- Modify: `skills/ai-daily-report/templates/daily.html.j2`
- Test: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_render_html.py`:

```python
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
```

- [ ] **Step 2: Verify failure**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py -q -k "decision_radar"` → 3 FAIL.

- [ ] **Step 3: Schema**

In `schemas/daily_report.schema.json`:

(a) `sections.required`: insert `"decision_radar"` after `"experiments_this_week"`.

(b) `sections.properties`: add after `experiments_this_week`:

```json
"decision_radar": {
  "type": "object",
  "required": ["title", "decisions", "empty_message"],
  "properties": {
    "title": {"type": "string"},
    "decisions": {
      "type": "array",
      "items": {"$ref": "#/$defs/decisionRadarGroup"}
    },
    "empty_message": {"type": "string"}
  }
},
```

(c) `$defs`: add after `expandedBlock`:

```json
"decisionRadarGroup": {
  "type": "object",
  "required": ["decision_name", "items"],
  "properties": {
    "decision_name": {"type": "string", "minLength": 1, "maxLength": 60},
    "items": {
      "type": "array",
      "minItems": 1,
      "maxItems": 4,
      "items": {
        "type": "object",
        "required": ["ref", "impact"],
        "properties": {
          "ref": {"$ref": "#/$defs/itemRef"},
          "impact": {"type": "string", "minLength": 1, "maxLength": 120}
        }
      }
    }
  }
},
```

- [ ] **Step 4: Fixtures**

In `tests/fixtures/sample_daily.json`, add to `sections` (after `experiments_this_week`):

```json
"decision_radar": {
  "title": "决策雷达",
  "decisions": [
    {
      "decision_name": "coding-agent-2026H2",
      "items": [
        {"ref": "coding_agents[0]", "impact": "Composer 2.0 内测开放，对比评估窗口提前，建议纳入本轮选型测试。"}
      ]
    }
  ],
  "empty_message": "今日无影响在途决策的信息"
},
```

(Check the fixture's `coding_agents.items[0]` exists — it does, 2 items.)

In `tests/fixtures/sample_daily_empty.json`, add to `sections` in the same position:

```json
"decision_radar": {
  "title": "决策雷达",
  "decisions": [],
  "empty_message": "今日无影响在途决策的信息"
},
```

- [ ] **Step 5: Template**

In `templates/daily.html.j2`:

(a) CSS, after the `.major-expanded ul.open-questions` rule:

```css
  .radar-group { border: 1px solid var(--border); border-left: 4px solid #1a7f37; background: var(--card); padding: 14px; border-radius: 0 8px 8px 0; margin-bottom: 12px; }
  .radar-group .decision-name { font-weight: 600; font-size: 16px; margin-bottom: 6px; }
  .radar-item { padding: 4px 0; font-size: 15px; }
  .radar-item .refs { font-size: 13px; color: var(--muted); }
```

(b) New section between the experiments `</section>` and the action `<section id="action">`:

```jinja
  <section id="radar">
    <h2>八、{{ report.sections.decision_radar.title }}</h2>
    {% if report.sections.decision_radar.decisions %}
      {% for group in report.sections.decision_radar.decisions %}
      <div class="radar-group">
        <div class="decision-name">{{ group.decision_name }}</div>
        {% for r in group["items"] %}
        <div class="radar-item">{{ r.impact }} <span class="refs">{{ ref_link(r.ref) }}</span></div>
        {% endfor %}
      </div>
      {% endfor %}
    {% else %}
      <p class="unverified">{{ report.sections.decision_radar.empty_message }}</p>
    {% endif %}
  </section>
```

(c) TOC: insert `<li><a href="#radar">八、{{ report.sections.decision_radar.title }}</a></li>` before the action entry, and renumber action → 九、, unverified → 十、 in BOTH the TOC and the `<h2>` headings of those two sections. (agent_ecosystem will become 四 in Task 4; for now sections 1-7 keep their numbers, radar=八, action=九, unverified=十.)

Wait — to avoid renumbering twice, do the FULL final numbering now: frontier 一, coding 二, general 三, market **五**, patterns **六**, experiments **七**, radar **八**, action **九**, unverified **十** — leaving 四 vacant for agent_ecosystem (Task 4 inserts it). The TOC and h2 headings for market/patterns/experiments change from 四/五/六 to 五/六/七 in this task.

- [ ] **Step 6: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 139 passed (render suite + all others; fixtures now satisfy the new required section).

- [ ] **Step 7: Commit**

```bash
git add skills/ai-daily-report/schemas/daily_report.schema.json skills/ai-daily-report/tests/fixtures/sample_daily.json skills/ai-daily-report/tests/fixtures/sample_daily_empty.json skills/ai-daily-report/templates/daily.html.j2 skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: add decision radar section to daily report"
```

### Task 3: decision_radar validator + finalize wiring

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Modify: `skills/ai-daily-report/scripts/report_runner.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_editorial.py` (add `validate_decision_radar` to the editorial imports):

```python
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
```

- [ ] **Step 2: Verify failure**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_editorial.py -q -k "decision_radar"` → ImportError.

- [ ] **Step 3: Implement**

In `scripts/editorial.py`, add after `validate_major_event_consistency`:

```python
def validate_decision_radar(report: dict[str, Any], profile: dict[str, Any] | None = None) -> list[str]:
    errors: list[str] = []
    counts = _daily_item_counts(report)
    known_decisions = {
        str(decision.get("name", ""))
        for decision in (profile or {}).get("decisions_in_flight", [])
        if decision.get("name")
    }
    radar = report.get("sections", {}).get("decision_radar", {})
    for group_index, group in enumerate(radar.get("decisions", [])):
        label = f"decision_radar.decisions[{group_index}]"
        name = group.get("decision_name", "")
        if known_decisions and name not in known_decisions:
            errors.append(f"{label} decision_name {name!r} not found in profile decisions_in_flight")
        for item_index, item in enumerate(group.get("items", [])):
            errors.extend(_validate_item_ref(f"{label}.items[{item_index}].ref", item.get("ref", ""), counts))
    return errors
```

In `validate_daily_artifacts`, change signature to add `profile: dict[str, Any] | None = None` (after `project_root`), and before `return errors` add:

```python
    errors.extend(validate_decision_radar(report, profile))
```

In `scripts/report_runner.py` `run_daily_finalize`: extend the discovery import with `load_profile`, and change the validation call to:

```python
    errors = validate_daily_artifacts(report, ledger, whitelist, project_root, profile=load_profile())
```

- [ ] **Step 4: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 144 passed.

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: validate decision radar refs and decision names"
```

### Task 4: agent_ecosystem schema section + fixtures + render

**Files:**
- Modify: `skills/ai-daily-report/schemas/daily_report.schema.json`
- Modify: `tests/fixtures/sample_daily.json`, `tests/fixtures/sample_daily_empty.json`
- Modify: `skills/ai-daily-report/templates/daily.html.j2`
- Test: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_render_html.py`:

```python
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
```

- [ ] **Step 2: Verify failure**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py -q -k "ecosystem"` → 3 FAIL.

- [ ] **Step 3: Schema**

In `schemas/daily_report.schema.json`:

(a) `sections.required`: insert `"agent_ecosystem"` after `"general_agents"`.

(b) `sections.properties` after `general_agents`:

```json
"agent_ecosystem": {
  "type": "object",
  "required": ["title", "items", "empty_message"],
  "properties": {
    "title": {"type": "string"},
    "items": {
      "type": "array",
      "maxItems": 4,
      "items": {"$ref": "#/$defs/ecosystemItem"}
    },
    "empty_message": {"type": "string"}
  }
},
```

(c) `$defs` after `decisionRadarGroup`:

```json
"ecosystemItem": {
  "type": "object",
  "required": ["item_type", "title", "summary", "source_name", "source_url", "relevance"],
  "properties": {
    "item_type": {"enum": ["trending_repo", "skill_plugin", "practice_case", "tool_release"]},
    "title": {"type": "string", "minLength": 1, "maxLength": 60},
    "summary": {"type": "string", "minLength": 1, "maxLength": 120},
    "source_name": {"type": "string"},
    "source_url": {"type": "string"},
    "relevance": {"type": "string", "minLength": 1, "maxLength": 80},
    "heat_note": {"type": "string", "maxLength": 80},
    "onboarding_cost": {"enum": ["ready_to_use", "needs_config", "needs_build"]},
    "repo_slug": {"type": "string", "maxLength": 100}
  },
  "allOf": [
    {
      "if": {"properties": {"item_type": {"const": "trending_repo"}}, "required": ["item_type"]},
      "then": {"required": ["heat_note", "repo_slug"]}
    },
    {
      "if": {"properties": {"item_type": {"const": "skill_plugin"}}, "required": ["item_type"]},
      "then": {"required": ["onboarding_cost"]}
    }
  ]
},
```

- [ ] **Step 4: Fixtures**

`tests/fixtures/sample_daily.json` — add to `sections` after `general_agents`:

```json
"agent_ecosystem": {
  "title": "Agent 生态与实践",
  "items": [
    {
      "item_type": "trending_repo",
      "title": "claude-flow：多 agent 编排框架",
      "summary": "用声明式 pipeline 编排多个 Claude Code 实例，内置评审与回滚步骤。",
      "source_name": "GitHub Trending",
      "source_url": "https://github.com/example/claude-flow",
      "relevance": "团队级 agent 工作流",
      "heat_note": "快照 2026-04-10：8.2k stars，本周 +1.9k",
      "repo_slug": "example/claude-flow"
    }
  ],
  "empty_message": "今日无值得收录的生态信号"
},
```

`tests/fixtures/sample_daily_empty.json` — same position:

```json
"agent_ecosystem": {
  "title": "Agent 生态与实践",
  "items": [],
  "empty_message": "今日无值得收录的生态信号"
},
```

- [ ] **Step 5: Template**

In `templates/daily.html.j2`:

(a) CSS after the `.radar-item .refs` rule:

```css
  .badge-eco-trending_repo { background: #fff8c5; color: #9a6700; }
  .badge-eco-skill_plugin  { background: #dafbe1; color: #1a7f37; }
  .badge-eco-practice_case { background: #ddf4ff; color: #0969da; }
  .badge-eco-tool_release  { background: #fbefff; color: #8250df; }
  .eco-meta { color: var(--muted); font-size: 14px; margin-top: 4px; }
```

(b) Jinja dict for type labels — add near the top macros:

```jinja
{% set eco_type_labels = {"trending_repo": "热门仓库", "skill_plugin": "技能/插件", "practice_case": "实践案例", "tool_release": "工具发布"} %}
{% set eco_cost_labels = {"ready_to_use": "即装即用", "needs_config": "需配置", "needs_build": "需自建"} %}
```

(c) New section after the general `</section>` (before market):

```jinja
  <section id="ecosystem">
    <h2>四、{{ report.sections.agent_ecosystem.title }}</h2>
    {% for item in report.sections.agent_ecosystem["items"] %}
    <article class="card" id="agent_ecosystem-{{ loop.index0 }}">
      <div>
        <span class="badge badge-eco-{{ item.item_type }}">{{ eco_type_labels[item.item_type] }}</span>
        {% if item.onboarding_cost %}<span class="badge badge-tier">{{ eco_cost_labels[item.onboarding_cost] }}</span>{% endif %}
      </div>
      <div class="headline">{{ item.title }}</div>
      <div class="summary">{{ item.summary }}</div>
      {% if item.heat_note %}<div class="heat">{{ item.heat_note }}</div>{% endif %}
      <div class="eco-meta">适用：{{ item.relevance }}</div>
      <div class="source">{{ item.source_name }} · <a href="{{ item.source_url }}">查看原文</a></div>
    </article>
    {% else %}
    <p class="unverified">{{ report.sections.agent_ecosystem.empty_message }}</p>
    {% endfor %}
  </section>
```

(d) TOC: insert `<li><a href="#ecosystem">四、{{ report.sections.agent_ecosystem.title }}</a></li>` after the general entry. (Numbers 五–十 were already assigned in Task 2; nothing else renumbers.)

- [ ] **Step 6: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 147 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/ai-daily-report/schemas/daily_report.schema.json skills/ai-daily-report/tests/fixtures/sample_daily.json skills/ai-daily-report/tests/fixtures/sample_daily_empty.json skills/ai-daily-report/templates/daily.html.j2 skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: add agent ecosystem section to daily report"
```

### Task 5: ecosystem module — seen-repos cooldown + validators + finalize wiring

**Files:**
- Create: `skills/ai-daily-report/scripts/ecosystem.py`
- Create: `skills/ai-daily-report/tests/test_ecosystem.py`
- Modify: `skills/ai-daily-report/scripts/editorial.py`, `scripts/report_runner.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Failing tests — new file `tests/test_ecosystem.py`:**

```python
import json
from pathlib import Path

from ecosystem import load_seen_repos, record_ecosystem_repos, validate_ecosystem_repeats


def _report_with_repo(slug: str, date: str = "2026-06-12") -> dict:
    return {
        "date": date,
        "sections": {
            "agent_ecosystem": {
                "title": "Agent 生态与实践",
                "items": [
                    {
                        "item_type": "trending_repo",
                        "title": "x",
                        "summary": "y",
                        "source_name": "GitHub Trending",
                        "source_url": f"https://github.com/{slug}",
                        "relevance": "团队级 agent 工作流",
                        "heat_note": "快照",
                        "repo_slug": slug,
                    }
                ],
                "empty_message": "",
            }
        },
    }


def test_load_seen_repos_missing_file_returns_empty(tmp_path):
    assert load_seen_repos(tmp_path) == {"version": "1.0", "repos": {}}


def test_record_then_repeat_within_cooldown_is_rejected(tmp_path):
    report = _report_with_repo("example/claude-flow", "2026-06-12")
    record_ecosystem_repos(report, tmp_path, "2026-06-12")

    seen = load_seen_repos(tmp_path)
    assert seen["repos"]["example/claude-flow"]["first_seen"] == "2026-06-12"

    repeat = _report_with_repo("example/claude-flow", "2026-06-20")
    errors = validate_ecosystem_repeats(repeat, load_seen_repos(tmp_path), "2026-06-20")
    assert any("example/claude-flow" in error for error in errors)


def test_repeat_same_day_is_allowed_for_rerun(tmp_path):
    report = _report_with_repo("example/claude-flow", "2026-06-12")
    record_ecosystem_repos(report, tmp_path, "2026-06-12")
    errors = validate_ecosystem_repeats(report, load_seen_repos(tmp_path), "2026-06-12")
    assert errors == []


def test_repeat_after_cooldown_is_allowed(tmp_path):
    report = _report_with_repo("example/claude-flow", "2026-06-12")
    record_ecosystem_repos(report, tmp_path, "2026-06-12")
    later = _report_with_repo("example/claude-flow", "2026-08-01")
    errors = validate_ecosystem_repeats(later, load_seen_repos(tmp_path), "2026-08-01")
    assert errors == []


def test_record_updates_last_listed_keeps_first_seen(tmp_path):
    record_ecosystem_repos(_report_with_repo("a/b", "2026-06-12"), tmp_path, "2026-06-12")
    record_ecosystem_repos(_report_with_repo("a/b", "2026-08-01"), tmp_path, "2026-08-01")
    seen = load_seen_repos(tmp_path)
    assert seen["repos"]["a/b"]["first_seen"] == "2026-06-12"
    assert seen["repos"]["a/b"]["last_listed"] == "2026-08-01"


def test_non_repo_items_are_ignored(tmp_path):
    report = _report_with_repo("a/b", "2026-06-12")
    report["sections"]["agent_ecosystem"]["items"][0]["item_type"] = "practice_case"
    record_ecosystem_repos(report, tmp_path, "2026-06-12")
    assert load_seen_repos(tmp_path)["repos"] == {}
    assert validate_ecosystem_repeats(report, load_seen_repos(tmp_path), "2026-06-12") == []
```

- [ ] **Step 2: Verify failure** — `ModuleNotFoundError: No module named 'ecosystem'`.

- [ ] **Step 3: Create `scripts/ecosystem.py`:**

```python
#!/usr/bin/env python3
"""Deterministic helpers for the agent_ecosystem section: seen-repos cooldown ledger."""
from __future__ import annotations

from datetime import date
import json
from pathlib import Path
from typing import Any

ECOSYSTEM_COOLDOWN_DAYS = 30


def _seen_repos_path(project_root: Path) -> Path:
    return project_root / "cache" / "seen_repos.json"


def load_seen_repos(project_root: Path) -> dict[str, Any]:
    path = _seen_repos_path(project_root)
    if not path.exists():
        return {"version": "1.0", "repos": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "1.0", "repos": {}}
    if not isinstance(payload.get("repos"), dict):
        return {"version": "1.0", "repos": {}}
    return payload


def _trending_repo_slugs(report: dict[str, Any]) -> list[str]:
    items = report.get("sections", {}).get("agent_ecosystem", {}).get("items", [])
    return [
        str(item.get("repo_slug", ""))
        for item in items
        if item.get("item_type") == "trending_repo" and item.get("repo_slug")
    ]


def validate_ecosystem_repeats(
    report: dict[str, Any],
    seen: dict[str, Any],
    today: str,
    cooldown_days: int = ECOSYSTEM_COOLDOWN_DAYS,
) -> list[str]:
    errors: list[str] = []
    try:
        target = date.fromisoformat(today)
    except ValueError:
        return [f"ecosystem validation date {today!r} is not a valid date"]
    repos = seen.get("repos", {})
    for slug in _trending_repo_slugs(report):
        record = repos.get(slug)
        if not record:
            continue
        try:
            last_listed = date.fromisoformat(str(record.get("last_listed", "")))
        except ValueError:
            continue
        delta = (target - last_listed).days
        if 0 < delta <= cooldown_days:
            errors.append(
                f"agent_ecosystem repo {slug!r} already listed on {record.get('last_listed')} (cooldown {cooldown_days}d)"
            )
    return errors


def record_ecosystem_repos(report: dict[str, Any], project_root: Path, today: str) -> int:
    slugs = _trending_repo_slugs(report)
    if not slugs:
        return 0
    seen = load_seen_repos(project_root)
    for slug in slugs:
        record = seen["repos"].setdefault(slug, {"first_seen": today})
        record["last_listed"] = today
    path = _seen_repos_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, ensure_ascii=False, indent=2), encoding="utf-8")
    return len(slugs)
```

- [ ] **Step 4: Wire into editorial + runner**

`scripts/editorial.py`: add import `from ecosystem import load_seen_repos, validate_ecosystem_repeats`; in `validate_daily_artifacts`, inside the existing `if project_root is not None:` block, add:

```python
        errors.extend(
            validate_ecosystem_repeats(report, load_seen_repos(project_root), str(report.get("date", "")))
        )
```

`scripts/report_runner.py`: add `from ecosystem import record_ecosystem_repos`; in `run_daily_finalize`, immediately after the tracking-cleanup block, add:

```python
    recorded = record_ecosystem_repos(report, project_root, target_date)
    if recorded:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} ECOSYSTEM seen_repos+={recorded}")
```

Append integration test to `tests/test_editorial.py`:

```python
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
```

(The fixture report date is 2026-04-10, 9 days after last_listed → inside the 30-day cooldown.)

- [ ] **Step 5: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 154 passed.

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/scripts/ecosystem.py skills/ai-daily-report/tests/test_ecosystem.py skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: enforce ecosystem repo cooldown via seen-repos ledger"
```

### Task 6: whitelist sources + ecosystem discovery surface

**Files:**
- Modify: `skills/ai-daily-report/sources/whitelist.yaml`
- Modify: `skills/ai-daily-report/scripts/discovery.py`
- Test: `skills/ai-daily-report/tests/test_discovery.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_discovery.py`:

```python
def test_whitelist_contains_practice_and_workplace_sources(sample_whitelist):
    eco_names = [item["name"] for item in sample_whitelist["agent_ecosystem_sources"]]
    assert "Anthropic Engineering" in eco_names
    assert "LangChain Blog" in eco_names
    assert "Latent Space" in eco_names
    watch_names = [item["name"] for item in sample_whitelist["general_agent_watchlist"]]
    assert "Google Workspace Updates" in watch_names
    assert any("钉钉" in q or "飞书" in q for q in sample_whitelist["general_agent_search_queries"])
    assert sample_whitelist["ecosystem_search_queries"]


def test_discovery_manifest_includes_ecosystem_surface(sample_whitelist):
    from discovery import ECOSYSTEM_DISCOVERY_NAME, build_discovery_manifest, compute_daily_window, initial_fetch_status, required_discovery_names

    assert ECOSYSTEM_DISCOVERY_NAME in required_discovery_names(sample_whitelist)
    assert ECOSYSTEM_DISCOVERY_NAME in initial_fetch_status(sample_whitelist)["source_details"]
    window = compute_daily_window("2026-06-12", "2026-06-12T07:10:00+08:00")
    manifest = build_discovery_manifest("2026-06-12", window, sample_whitelist)
    assert manifest["ecosystem_search_queries"] == sample_whitelist["ecosystem_search_queries"]
    assert ECOSYSTEM_DISCOVERY_NAME in manifest["required_discovery_surfaces"]
```

- [ ] **Step 2: Verify failure** — KeyError / ImportError.

- [ ] **Step 3: whitelist.yaml additions**

Add a new top-level category after `general_agent_watchlist` ends (before `english_media`):

```yaml
agent_ecosystem_sources:
  - name: Anthropic Engineering
    category: agent_ecosystem_sources
    weight: high
    authority_tier: 1
    fetch_chain:
      - type: webfetch
        url: https://www.anthropic.com/engineering
      - type: websearch_scoped
        queries:
          - "site:anthropic.com/engineering {date}"
      - type: websearch_broad
        queries:
          - "Anthropic engineering blog agents {date}"

  - name: LangChain Blog
    category: agent_ecosystem_sources
    weight: medium
    authority_tier: 2
    fetch_chain:
      - type: webfetch
        url: https://blog.langchain.dev/
      - type: websearch_scoped
        queries:
          - "site:blog.langchain.dev agent {date}"

  - name: Latent Space
    category: agent_ecosystem_sources
    weight: medium
    authority_tier: 3
    fetch_chain:
      - type: webfetch
        url: https://www.latent.space/
      - type: websearch_scoped
        queries:
          - "Latent Space AI engineering {date}"
```

Add to `general_agent_watchlist` (after `Microsoft 365 Copilot Adoption`):

```yaml
  - name: Google Workspace Updates
    category: general_agent_watchlist
    weight: medium
    authority_tier: 1
    fetch_chain:
      - type: webfetch
        url: https://workspaceupdates.googleblog.com/
      - type: websearch_scoped
        queries:
          - "Google Workspace Gemini update site:workspaceupdates.googleblog.com {date}"
      - type: websearch_broad
        queries:
          - "Google Workspace Gemini AI update {date}"
```

Append to `general_agent_search_queries`:

```yaml
  - "ChatGPT Enterprise Teams update {date}"
  - "Claude for Work enterprise update {date}"
  - "飞书 智能伙伴 AI 更新 {date}"
  - "钉钉 AI 助理 更新 {date}"
  - "Salesforce Agentforce update {date}"
```

Add new top-level list after `recall_probe_queries`:

```yaml
ecosystem_search_queries:
  - "github trending claude code skill {date}"
  - "github trending MCP server {date}"
  - "awesome-claude-code new entries {date}"
  - "claude code plugin marketplace new {date}"
  - "\"how we use\" coding agent site:news.ycombinator.com {date}"
  - "AI coding agent team workflow case study {date}"
```

- [ ] **Step 4: discovery.py surface**

Add constant after `RECALL_PROBE_SURFACE_NAME`:

```python
ECOSYSTEM_DISCOVERY_NAME = "Agent Ecosystem Discovery"
```

In `required_discovery_names`, add `ECOSYSTEM_DISCOVERY_NAME` to the `names.extend([...])` list (after `RECALL_PROBE_SURFACE_NAME`).

In `initial_fetch_status`, add (mirroring the recall-probe entry):

```python
    source_details[ECOSYSTEM_DISCOVERY_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "websearch_broad",
        "via_broad_search": True,
        "confidence_policy": "force_medium_plus_flag",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "websearch_broad",
                "target": "ecosystem_search_queries",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
```

In `build_discovery_manifest`'s returned dict: add `"ecosystem_search_queries": whitelist.get("ecosystem_search_queries", []),` after the `recall_probe_queries` line, and add `ECOSYSTEM_DISCOVERY_NAME` to `required_discovery_surfaces` (after `RECALL_PROBE_SURFACE_NAME`).

- [ ] **Step 5: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 156 passed. NOTE: `missing_fetch_status_coverage`-based tests use `initial_fetch_status`/fixtures — if any existing test asserts an exact surface count or list, update it to include the new surface (report any such change in your commit message body).

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/sources/whitelist.yaml skills/ai-daily-report/scripts/discovery.py skills/ai-daily-report/tests/test_discovery.py
git commit -m "feat: add ecosystem and workplace discovery sources"
```

### Task 7: SKILL.md + README + full verification

**Files:**
- Modify: `skills/ai-daily-report/SKILL.md`, `README.md`

- [ ] **Step 1: SKILL.md edits**

(a) 运行前检查 step 1, change to also read profile: after the line about reading `sources/whitelist.yaml`, add:

```markdown
1b. **读取 sources/profile.yaml**：读者画像（四个角色、在途决策、实践关注点）。它是编辑判断的输入：相关性、决策雷达分组、生态板块取舍都要回答"这条信息服务哪个角色/哪个在途决策"。
```

(b) New step after step 3b (重大事件深度与事件追踪), numbered 3c:

```markdown
3c. **生成 Agent 生态与实践（agent_ecosystem）**

   - 每天 0-4 条，来源：GitHub Trending（已有 surface）、`ecosystem_search_queries`、`agent_ecosystem_sources`（Anthropic Engineering / LangChain Blog / Latent Space 等）、HN 实践讨论
   - 四种 `item_type`：
     - `trending_repo`：热门 agent 仓库。必须带 `repo_slug` 与 `heat_note`（star 数 + 快照时间，沿用 community_snapshot 纪律，不写"今日登顶"）。受 `cache/seen_repos.json` 30 天冷却约束：同一仓库 30 天内不重复收录（finalize 强制）；同日重跑不受限
     - `skill_plugin`：可直接使用的 skills / 插件 / MCP server。必须带 `onboarding_cost`（ready_to_use / needs_config / needs_build）
     - `practice_case`：工程实践 / 团队落地复盘。日报只写 1-2 句导读 + 链接，深读进周报
     - `tool_release`：值得关注的工具发布
   - **准入窗口与新闻线不同**：放宽为"7 天内首次达到阈值 / 首次被收录"，但 `relevance` 必须锚定 profile.yaml 的 `practice_focus` 或某个角色——不泛收一切 AI 热门
   - 生态条目不进入 `action_items` 依据，可作为 `experiments_this_week` 的素材
   - 空则 `items: []` + `empty_message`，不凑数
```

(c) New step after step 7 (生成本期实验), numbered 7a:

```markdown
7a. **生成决策雷达（decision_radar）**

   - 对 `profile.yaml > decisions_in_flight` 的每个在途决策，检查当日 `core/watch` 正文条目是否影响该决策（候选变化、定价、企业功能、benchmark、可用性等）
   - 有影响 → 该决策建一个 group：`decision_name` 必须与 profile 中的 `name` 一致（finalize 校验），每条 `{ref, impact}`，`ref` 指向正文条目，`impact` 一句话说清"对这个决策意味着什么"（≤120 字）
   - 每个决策最多 4 条；无影响的决策不建 group；全空则 `decisions: []` + `empty_message: "今日无影响在途决策的信息"`
   - 雷达是 action_items 的输入参考：step 8 写建议前先看雷达
   - `unverified` 条目不得进入雷达
```

(d) Step 9 产出结构化 JSON: change `**八个 \`sections\`**` to `**十个 \`sections\`**` and the section list to `frontier_models / coding_agents / general_agents / agent_ecosystem / market_signals / pattern_observations / experiments_this_week / decision_radar / action_items / unverified`.

(e) 终端输出 (step 13 模板): after 「三、通用 Agent 动态」 block add:

```
      三a、Agent 生态与实践
        · {item 1 title}（{item_type 中文标签}）
        ...（最多 2 条）
```

and after 「六、本期建议实验」 block add:

```
      六a、决策雷达
        {每个有内容的决策一行：decision_name: N 条影响；空则显示 empty_message}
```

(f) 产出字段约束 table — add rows:

```markdown
| `decision_radar` impact | ≤ 120 字，每决策 ≤ 4 条 |
| `agent_ecosystem` items | 0-4 条/天；trending_repo 30 天冷却；relevance ≤ 80 字 |
```

(g) 归类规则 section — add:

```markdown
- **agent_ecosystem**：生态与实践信号（热门仓库、skills/插件、实践案例、工具发布）。不是新闻，准入窗口放宽到 7 天首见；不作为 action_items 依据。
- **decision_radar**：编辑结论层，只引用当日 core/watch 正文条目，按 profile.yaml 在途决策分组。
```

- [ ] **Step 2: README edits**

In 目录 section add:

```markdown
- `skills/ai-daily-report/sources/profile.yaml`：读者画像（角色、在途决策、实践关注点）
- `cache/seen_repos.json`：生态板块已收录仓库台账（30 天冷却，运行时生成）
```

- [ ] **Step 3: Full verification**

1. `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → all pass (~156).
2. Render smoke test on the updated fixture:

```bash
cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python skills/ai-daily-report/scripts/render_html.py skills/ai-daily-report/tests/fixtures/sample_daily.json --output /tmp/p1-smoke.html && grep -c "决策雷达\|Agent 生态" /tmp/p1-smoke.html
```

Expected: exit 0, grep count ≥ 2.

- [ ] **Step 4: Commit**

```bash
git add skills/ai-daily-report/SKILL.md README.md
git commit -m "feat: document decision radar and ecosystem workflow"
```

---

## Spec Coverage Check

- Profile-driven relevance (P1a): Tasks 1, 3, 7(a/c).
- decision_radar section end-to-end (schema/render/validate/docs): Tasks 2, 3, 7.
- agent_ecosystem section end-to-end: Tasks 4, 5, 7.
- Snapshot discipline + 30-day cooldown: Tasks 4 (heat_note required), 5 (ledger), 7 (rules).
- Practice/workplace sources: Task 6.
- Weekly intentionally untouched (第三批).

## Placeholder Scan
No TODO/TBD; all code steps include code; commands include expected outcomes. Task 6 Step 5 includes a contingency note for surface-count assertions — that is an instruction, not a placeholder.

## Type Consistency Check
- `load_profile()` → dict; manifest key `reader_profile` — Tasks 1, 3, 7 consistent.
- `validate_decision_radar(report, profile=None)`; `validate_daily_artifacts(report, ledger, whitelist, project_root=None, profile=None)` — Task 3 signature used by runner call.
- `ecosystem.py` exports `load_seen_repos` / `validate_ecosystem_repeats` / `record_ecosystem_repos` — Tasks 5 wiring matches.
- `ECOSYSTEM_DISCOVERY_NAME` — Task 6 constant used in all three discovery touch points.
- itemRef `$defs` reused by radar refs (3 body sections only) — radar cannot reference ecosystem items by design.
