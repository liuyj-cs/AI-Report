# P3: Experiment Audience + Weekly Practice Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Experiments carry an `audience` dimension (团队试点 team_pilot for the tech-director role / 个人工作流 personal_workflow for the engineer role), and the weekly report gains a `practice_digest` section (0-2 deep-read picks from the week's daily `agent_ecosystem` items, with an applicability verdict, deterministically traceable back to a daily ecosystem item).

**Architecture:** Same contract as P0/P1 — AI judges, scripts enforce. `audience` is a required enum on the shared experiment shape in BOTH daily and weekly schemas, rendered as a chip. `practice_digest` is a new required weekly section whose items must carry an `origin` {date, title} resolving to an `agent_ecosystem` item in that day's cached daily report (validated at weekly finalize, like `validate_weekly_references`). Weekly grows from 9 to 10 sections (practice_digest = 八, action_items → 九, next_week_signals → 十).

**Tech Stack:** Python 3.13, jsonschema, Jinja2, pytest.

**Baseline:** main @ 3e6f349 (P0+P1 merged; 156 tests green). Create branch `feat/p3-audience-practice-digest` first. Stage only the files named in each commit step. Append to every commit message the trailer line `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

## File Map

**Modify**
- `skills/ai-daily-report/schemas/daily_report.schema.json` — `$defs/experiment` gains required `audience`.
- `skills/ai-daily-report/schemas/weekly_report.schema.json` — same `audience` change; new `practice_digest` section + `$defs/practiceDigestItem`.
- `skills/ai-daily-report/templates/daily.html.j2` — audience chip in `experiments_block`.
- `skills/ai-daily-report/templates/weekly.html.j2` — audience chip; new section 八 实践精选; renumber 八→九, 九→十.
- `skills/ai-daily-report/scripts/editorial.py` — `validate_practice_digest`; wire into `validate_weekly_artifacts` + `build_weekly_qa_diff`.
- Fixtures: `tests/fixtures/sample_daily.json`, `tests/fixtures/sample_weekly.json` (audience on every experiment; weekly also gains practice_digest).
- `skills/ai-daily-report/SKILL.md`, `README.md` — workflow rules.
- Tests: `tests/test_render_html.py`, `tests/test_editorial.py`.

**Leave As-Is**
- `sample_daily_empty.json` (its experiments items array is empty — no audience needed).
- Daily-side validators (audience is schema-enforced; no cross-field rule).
- discovery/runner (weekly finalize already passes `project_root` to `validate_weekly_artifacts`).

---

### Task 1: `audience` field on experiments (daily + weekly, schema + render)

**Files:**
- Modify: `skills/ai-daily-report/schemas/daily_report.schema.json` (`$defs/experiment`)
- Modify: `skills/ai-daily-report/schemas/weekly_report.schema.json` (`$defs/experiment`)
- Modify: `tests/fixtures/sample_daily.json`, `tests/fixtures/sample_weekly.json`
- Modify: `templates/daily.html.j2`, `templates/weekly.html.j2`
- Test: `tests/test_render_html.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_render_html.py`:

```python
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
```

- [ ] **Step 2: Verify failure**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py -q -k "audience"`
Expected: 4 FAIL (first assertion in each schema test fails — fixture has no `audience` yet).

- [ ] **Step 3: Schemas**

In BOTH `schemas/daily_report.schema.json` and `schemas/weekly_report.schema.json`, inside `$defs/experiment`:
- add `"audience"` to the `required` array (after `"required_skills"`);
- add to `properties` (after `"required_skills"`):

```json
"audience": {"enum": ["team_pilot", "personal_workflow"]},
```

- [ ] **Step 4: Fixtures**

- `tests/fixtures/sample_daily.json`: add `"audience": "personal_workflow"` to the single item in `sections.experiments_this_week.items`.
- `tests/fixtures/sample_weekly.json`: add `"audience"` to EVERY item in `sections.experiments_this_week.items` — first item `"team_pilot"`, any further items alternate `"personal_workflow"` / `"team_pilot"`.

- [ ] **Step 5: Templates**

In `templates/daily.html.j2`, next to the existing `eco_type_labels`/`eco_cost_labels` set-statements, add:

```jinja
{% set audience_labels = {"team_pilot": "团队试点", "personal_workflow": "个人工作流"} %}
```

and in its `experiments_block` macro `meta-line` div, add after the 🧑 chip:

```jinja
      <span class="chip">👥 {{ audience_labels[e.audience] }}</span>
```

In `templates/weekly.html.j2`, add the same `{% set audience_labels = ... %}` line immediately before the `experiments_block` macro definition, and the same chip line in its `meta-line` div.

- [ ] **Step 6: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 160 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/ai-daily-report/schemas/daily_report.schema.json skills/ai-daily-report/schemas/weekly_report.schema.json skills/ai-daily-report/tests/fixtures/sample_daily.json skills/ai-daily-report/tests/fixtures/sample_weekly.json skills/ai-daily-report/templates/daily.html.j2 skills/ai-daily-report/templates/weekly.html.j2 skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: add audience dimension to experiments"
```

### Task 2: `practice_digest` weekly section (schema + fixture + render + renumber)

**Files:**
- Modify: `skills/ai-daily-report/schemas/weekly_report.schema.json`
- Modify: `tests/fixtures/sample_weekly.json`
- Modify: `templates/weekly.html.j2`
- Test: `tests/test_render_html.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_render_html.py`:

```python
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
```

- [ ] **Step 2: Verify failure**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py -q -k "practice_digest"` → 2 FAIL.

- [ ] **Step 3: Weekly schema**

(a) `sections.required`: insert `"practice_digest"` after `"experiments_this_week"`.

(b) `sections.properties`, after `experiments_this_week`:

```json
"practice_digest": {
  "type": "object",
  "required": ["title", "items", "empty_message"],
  "properties": {
    "title": {"type": "string"},
    "items": {
      "type": "array",
      "maxItems": 2,
      "items": {"$ref": "#/$defs/practiceDigestItem"}
    },
    "empty_message": {"type": "string"}
  }
},
```

(c) `$defs`, after `experimentsSection`:

```json
"practiceDigestItem": {
  "type": "object",
  "required": ["title", "source_name", "source_url", "summary", "applicability", "applicability_note", "origin"],
  "properties": {
    "title": {"type": "string", "minLength": 1, "maxLength": 60},
    "source_name": {"type": "string"},
    "source_url": {"type": "string"},
    "summary": {"type": "string", "minLength": 120, "maxLength": 600},
    "applicability": {"enum": ["adopt_now", "wait_mature", "reference_only"]},
    "applicability_note": {"type": "string", "minLength": 1, "maxLength": 120},
    "origin": {
      "type": "object",
      "required": ["date", "title"],
      "properties": {
        "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "title": {"type": "string", "minLength": 1}
      }
    }
  }
},
```

- [ ] **Step 4: Fixture**

`tests/fixtures/sample_weekly.json` — check its `source_days.daily_reports_used` for a real date D it contains (use the first listed date), then add to `sections` after `experiments_this_week`:

```json
"practice_digest": {
  "title": "本周实践精选",
  "items": [
    {
      "title": "claude-flow：多 agent 编排框架",
      "source_name": "GitHub",
      "source_url": "https://github.com/example/claude-flow",
      "summary": "claude-flow 用声明式 pipeline 把多个 Claude Code 实例编排成评审-实现-验证流水线，内置回滚步骤与每步产物校验。作者给出了在 12 人团队落地六周的数据：PR 平均评审时长下降约三成，回滚率持平。配置面较薄，依赖自维护的编排服务，权限模型还在迭代中，适合先在单一仓库试点验证收益再决定推广范围。",
      "applicability": "adopt_now",
      "applicability_note": "适合先在单一仓库做 2-3 人试点，验证评审时长指标后再扩大。",
      "origin": {"date": "<D>", "title": "claude-flow：多 agent 编排框架"}
    }
  ],
  "empty_message": "本周无值得深读的实践内容"
},
```

Replace `<D>` with the actual first date from the fixture's `daily_reports_used`. The summary above is 158 chars — within 120-600.

- [ ] **Step 5: Weekly template**

In `templates/weekly.html.j2`:

(a) CSS — find the `<style>` block and add near the `.experiment-card` rules:

```css
  .digest-card { border: 1px solid var(--border); border-left: 4px solid #0969da; background: var(--card); padding: 14px; border-radius: 0 8px 8px 0; margin-bottom: 12px; }
  .digest-card .title { font-weight: 600; font-size: 17px; margin-bottom: 6px; }
  .digest-card .summary { font-size: 15px; margin: 8px 0; }
  .digest-card .verdict { font-size: 14px; color: var(--muted); }
  .badge-apt-adopt_now      { background: #dafbe1; color: #1a7f37; }
  .badge-apt-wait_mature    { background: #fff8c5; color: #9a6700; }
  .badge-apt-reference_only { background: #eaeef2; color: #57606a; }
```

(b) Label dict near `audience_labels`:

```jinja
{% set applicability_labels = {"adopt_now": "适合现在引入", "wait_mature": "等工具成熟", "reference_only": "仅参考思路"} %}
```

(c) New section between the experiments section (`七、`) and the action section, and renumber the two sections after it (action_items 八→九, next_week_signals 九→十):

```jinja
  <section>
    <h2>八、{{ report.sections.practice_digest.title }}</h2>
    {% for d in report.sections.practice_digest["items"] %}
    <div class="digest-card">
      <div><span class="badge badge-apt-{{ d.applicability }}">{{ applicability_labels[d.applicability] }}</span></div>
      <div class="title">{{ d.title }}</div>
      <div class="summary">{{ d.summary }}</div>
      <div class="verdict">判断：{{ d.applicability_note }}</div>
      <div class="verdict">来源：<a href="{{ d.source_url }}">{{ d.source_name }}</a> · 首报 {{ d.origin.date }} 日报生态板块</div>
    </div>
    {% else %}
    <p>{{ report.sections.practice_digest.empty_message }}</p>
    {% endfor %}
  </section>
```

- [ ] **Step 6: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 162 passed.

- [ ] **Step 7: Commit**

```bash
git add skills/ai-daily-report/schemas/weekly_report.schema.json skills/ai-daily-report/tests/fixtures/sample_weekly.json skills/ai-daily-report/templates/weekly.html.j2 skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: add weekly practice digest section"
```

### Task 3: `validate_practice_digest` + weekly finalize wiring

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Failing tests**

Append to `tests/test_editorial.py` (add `validate_practice_digest` to the editorial imports):

```python
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
```

(`validate_weekly_artifacts` may already be imported; add if missing.)

- [ ] **Step 2: Verify failure** — ImportError on `validate_practice_digest`.

- [ ] **Step 3: Implement**

In `scripts/editorial.py`, add after `validate_weekly_references`:

```python
def validate_practice_digest(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    items = report.get("sections", {}).get("practice_digest", {}).get("items", [])
    if not items:
        return errors

    declared_days = set(report.get("source_days", {}).get("daily_reports_used", []))
    for index, item in enumerate(items):
        label = f"practice_digest.items[{index}]"
        origin = item.get("origin", {})
        date = str(origin.get("date", ""))
        title = origin.get("title", "")
        if date not in declared_days:
            errors.append(f"{label} origin date {date!r} not listed in source_days")
            continue
        daily_path = project_root / "cache" / date / "report.json"
        if not daily_path.exists():
            errors.append(f"{label} origin daily report missing: cache/{date}/report.json")
            continue
        try:
            daily = _read_json(daily_path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{label} cannot load cache/{date}/report.json: {exc}")
            continue
        eco_titles = {
            eco.get("title", "")
            for eco in daily.get("sections", {}).get("agent_ecosystem", {}).get("items", [])
        }
        if title not in eco_titles:
            errors.append(f"{label} origin title {title!r} not found in {date} agent_ecosystem")
    return errors
```

Wire into `validate_weekly_artifacts` (add before the market-signals line):

```python
    errors.extend(validate_practice_digest(report, project_root))
```

And in `build_weekly_qa_diff`, add to the `reference_errors` collection:

```python
    reference_errors.extend(validate_practice_digest(report, project_root))
```

- [ ] **Step 4: Verify**

`cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → expect 167 passed. NOTE: existing weekly tests that call `validate_weekly_artifacts` with fixture data may now also exercise the digest validator — the weekly fixture's digest origin must resolve against cache files those tests create; if an existing test creates daily cache files for the fixture's source_days, ensure the digest origin date matches one of those days OR the existing tests fail with the new digest errors. If that happens, the correct fix is to make the fixture's digest origin date one whose daily report the existing test harness writes WITH an agent_ecosystem item of the same title — check `test_editorial.py`'s existing weekly harness helpers and extend the daily payloads they write with an `agent_ecosystem` section containing the fixture digest title. Report exactly what you changed.

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: validate practice digest origins against daily ecosystem"
```

### Task 4: SKILL.md + README + full verification

**Files:**
- Modify: `skills/ai-daily-report/SKILL.md`, `README.md`

- [ ] **Step 1: SKILL.md edits** (verify each anchor with grep before editing; NEEDS_CONTEXT if missing)

(a) Daily step 7 (生成本期实验) — add to its field list line a new bullet after the existing 字段 bullet:

```markdown
   - 每条实验必须标 `audience`：`team_pilot`（设计为 2-3 人小范围团队试点，expected_output 必须是可向上汇报的度量结果）或 `personal_workflow`（个人当天/当周可试的新用法）。按当日素材选最合适的受众，不强行轮换
```

(b) Weekly step 3c (生成本周实验) — add bullet:

```markdown
   - 每条实验必须标 `audience`（team_pilot / personal_workflow）。若本周日报素材足够，1-3 条实验应覆盖两种受众各至少一次；素材不足时不强凑，但要在 hypothesis 里说明为何只面向单一受众
```

(c) New weekly step after 3c, numbered 3d:

```markdown
3d. **生成本周实践精选（practice_digest）**

   - 从本周 7 份日报的 `agent_ecosystem` 条目（优先 `practice_case`，也可选特别值得深读的 `skill_plugin` / `trending_repo`）中挑 0-2 篇做深读
   - 每篇：`summary`（200-400 字深读摘要：它解决什么问题、怎么做的、有什么数据或代价）+ `applicability`（adopt_now 适合现在引入 / wait_mature 等工具成熟 / reference_only 仅参考思路）+ `applicability_note`（一句话判断依据）
   - 每篇必须带 `origin: {date, title}`，date 在本周 `source_days` 内，title 与该日日报 `agent_ecosystem` 条目的 title 完全一致（finalize 校验，校验不过会阻塞发送）
   - 当周日报生态板块没有值得深读的内容 → `items: []` + `empty_message`，不硬凑
```

(d) Weekly step 5 (产出周报 JSON): change `**九章节**：\`tldr / frontier_models / coding_agents / general_agents / market_signals / pattern_observations / experiments_this_week / action_items / next_week_signals\`` to `**十章节**：\`tldr / frontier_models / coding_agents / general_agents / market_signals / pattern_observations / experiments_this_week / practice_digest / action_items / next_week_signals\``.

(e) 产出字段约束 table — add rows:

```markdown
| `experiments_this_week.items[].audience` | team_pilot / personal_workflow；周报尽量两种各 ≥1 |
| `practice_digest.items[].summary` | 200-400 字（schema 兜底 120-600） |
| `practice_digest.items[]` | 0-2 篇/周；origin 必须回指本周某日日报 agent_ecosystem 条目 |
```

- [ ] **Step 2: README** — in the 目录 section, no change needed unless desired; skip.

- [ ] **Step 3: Full verification**

1. `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q` → all pass (~167).
2. Render smoke both report types:

```bash
cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python skills/ai-daily-report/scripts/render_html.py skills/ai-daily-report/tests/fixtures/sample_weekly.json --output /tmp/p3-weekly.html && grep -c "本周实践精选\|团队试点\|个人工作流" /tmp/p3-weekly.html && .venv/bin/python skills/ai-daily-report/scripts/render_html.py skills/ai-daily-report/tests/fixtures/sample_daily.json --output /tmp/p3-daily.html && grep -c "团队试点\|个人工作流" /tmp/p3-daily.html
```

Expected: both render exit 0, both grep counts ≥ 1.

- [ ] **Step 4: Commit**

```bash
git add skills/ai-daily-report/SKILL.md
git commit -m "feat: document experiment audience and practice digest workflow"
```

(Include README.md in the git add only if it was actually edited.)

---

## Spec Coverage Check
- P1c audience (daily + weekly, schema/render/docs): Tasks 1, 4(a/b/e).
- P1d practice_digest (schema/fixture/render/renumber/validator/docs): Tasks 2, 3, 4(c/d/e).
- Weekly 9→10 sections renumber: Task 2 Step 5(c) + Task 4(d).

## Placeholder Scan
No TODO/TBD. Task 2 Step 4 has one deliberate substitution token `<D>` with explicit instructions to replace it with the fixture's first daily_reports_used date. Task 3 Step 4 contains a contingency instruction for fixture/harness alignment — instruction, not placeholder.

## Type Consistency Check
- `audience` enum identical in both schemas; `audience_labels` dict identical in both templates.
- `validate_practice_digest(report, project_root)` — signature matches `validate_weekly_artifacts(report, project_root)` call pattern; wired in both validate_weekly_artifacts and build_weekly_qa_diff.
- `practiceDigestItem.origin.title` matched against daily `agent_ecosystem.items[].title` (the P1 `ecosystemItem` uses `title`, not `headline` — consistent).
