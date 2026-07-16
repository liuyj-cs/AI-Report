# Report Section Numbering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让日报与周报的顶层章节编号只由模板生成，schema 在发送前拒绝带编号的 JSON 标题，并修复 2026-07-13 至 2026-07-16 的本地产物。

**Architecture:** 保留现有 Jinja 模板的展示编号，在 daily/weekly JSON Schema 中新增同构的 `sectionTitle` 定义，并仅把顶层 `sections.*.title` 接到该定义。测试同时覆盖 schema 拒绝、目录/正文单层编号和嵌套标题不受影响；历史 payload 只做标题字段迁移，再调用仓库自带渲染与归档脚本，不经过发送链路。

**Tech Stack:** Python 3、pytest、jsonschema Draft 2020-12、Jinja2、BeautifulSoup、JSON、Markdown

---

## 文件边界

- Modify: `skills/ai-daily-report/tests/test_render_html.py`
  - 新增 daily/weekly 顶层章节标题契约测试，以及目录/正文精确标题测试。
- Modify: `skills/ai-daily-report/schemas/daily_report.schema.json`
  - 新增 `sectionTitle`，让日报十一节顶层标题引用它。
- Modify: `skills/ai-daily-report/schemas/weekly_report.schema.json`
  - 新增同构 `sectionTitle`，让周报十一节顶层标题引用它。
- Modify: `skills/ai-daily-report/SKILL.md`
  - 明确 JSON 标题不带编号，并把终端简版更新为连续十一节。
- Modify: `docs/superpowers/specs/2026-07-16-report-section-numbering-design.md`
  - 将受影响迁移范围从 2026-07-13/14 更新为当前真实的 2026-07-13..16。
- Modify, ignored runtime data:
  - `cache/2026-07-13/report.json`
  - `cache/2026-07-14/report.json`
  - `cache/2026-07-15/report.json`
  - `cache/2026-07-16/report.json`
- Regenerate, ignored runtime artifacts:
  - `cache/2026-07-13/report.html` through `cache/2026-07-16/report.html`
  - `reports/daily/2026-07-13.html` through `reports/daily/2026-07-16.html`

### Task 1: 建立干净基线

**Files:**
- Read: `skills/ai-daily-report/requirements.txt`
- Test: `skills/ai-daily-report/tests/`

- [ ] **Step 1: 确认当前 checkout 和依赖入口**

Run:

```bash
git status --short
git branch --show-current
python --version
python -m pytest --version
```

Expected: 工作区无未提交改动，分支为 `main`，Python 与 pytest 可运行。

- [ ] **Step 2: 运行完整基线测试**

Run:

```bash
python -m pytest skills/ai-daily-report/tests -q
```

Expected: 全部测试通过，0 failures。若失败，先判断是否为现存失败，不在失败基线上继续实现。

### Task 2: RED — 写顶层标题契约测试

**Files:**
- Modify: `skills/ai-daily-report/tests/test_render_html.py:20-40`
- Modify: `skills/ai-daily-report/tests/test_render_html.py:606-620`
- Test: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: 把新共享 schema 定义纳入一致性检查**

在 `SHARED_DEFS` 首项加入：

```python
SHARED_DEFS = [
    "sectionTitle",
    "itemRef",
    # existing shared definitions remain unchanged
]
```

- [ ] **Step 2: 新增 weekly schema loader 和编号化标题样例**

在 `_load_daily_schema()` 后加入：

```python
def _load_weekly_schema():
    return json.loads((SCHEMAS / "weekly_report.schema.json").read_text(encoding="utf-8"))


DAILY_NUMBERED_SECTION_TITLES = {
    "frontier_models": "一、模型动态",
    "coding_agents": "二、Coding Agent 专项",
    "general_agents": "三、通用 Agent 动态",
    "agent_ecosystem": "三a、Agent 生态与实践",
    "methodology_radar": "三b、方法论雷达",
    "market_signals": "四、硬数据信号",
    "pattern_observations": "五、跨条目模式",
    "experiments_this_week": "六、本期建议实验",
    "decision_radar": "六a、决策雷达",
    "action_items": "七、今日落地建议",
    "unverified": "八、观察区 / 待核实",
}


WEEKLY_NUMBERED_SECTION_TITLES = {
    "tldr": "一、本周核心结论",
    "frontier_models": "二、头部大模型：本周动态与趋势",
    "coding_agents": "三、Coding Agent 深度观察",
    "general_agents": "四、通用 Agent 格局变化",
    "market_signals": "五、硬数据信号",
    "pattern_observations": "六、跨条目模式",
    "experiments_this_week": "七、本周建议实验",
    "practice_digest": "八、本周实践精选",
    "methodology_radar": "九、方法论雷达",
    "action_items": "十、本周落地建议（体系化）",
    "next_week_signals": "十一、下周值得关注的信号",
}
```

- [ ] **Step 3: 新增 daily/weekly schema 拒绝测试**

```python
def _assert_numbered_section_titles_rejected(data, schema, numbered_titles):
    validator = Draft202012Validator(schema)
    for section_name, bad_title in numbered_titles.items():
        candidate = deepcopy(data)
        candidate["sections"][section_name]["title"] = bad_title
        errors = list(validator.iter_errors(candidate))
        assert any(
            list(error.path) == ["sections", section_name, "title"]
            for error in errors
        ), f"{section_name} should reject numbered title {bad_title!r}"


def test_daily_schema_rejects_numbered_top_level_section_titles():
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    _assert_numbered_section_titles_rejected(
        data,
        _load_daily_schema(),
        DAILY_NUMBERED_SECTION_TITLES,
    )


def test_weekly_schema_rejects_numbered_top_level_section_titles():
    data = json.loads((FIXTURES / "sample_weekly.json").read_text(encoding="utf-8"))
    _assert_numbered_section_titles_rejected(
        data,
        _load_weekly_schema(),
        WEEKLY_NUMBERED_SECTION_TITLES,
    )
```

- [ ] **Step 4: 新增边界测试，证明嵌套标题不受影响**

```python
def test_daily_schema_allows_numbered_nested_titles():
    data = json.loads((FIXTURES / "sample_daily.json").read_text(encoding="utf-8"))
    data["sections"]["coding_agents"]["deep_dive"]["title"] = "一、深度观察"
    data["sections"]["agent_ecosystem"]["items"][0]["title"] = "1. 多 Agent 编排"

    errors = list(Draft202012Validator(_load_daily_schema()).iter_errors(data))

    assert errors == []
```

- [ ] **Step 5: 新增渲染字符化测试，精确锁定单层编号**

```python
def test_render_daily_section_headings_have_one_numbering_layer(tmp_path):
    html = _render_daily(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    expected = [
        "一、头部大模型动态",
        "二、Coding Agent 专项",
        "三、通用 Agent 动态",
        "四、Agent 生态与实践",
        "五、方法论雷达",
        "六、硬数据信号",
        "七、跨条目模式",
        "八、本期建议实验",
        "九、决策雷达",
        "十、今日落地建议",
        "十一、待核实区",
    ]

    toc = [node.get_text(" ", strip=True) for node in soup.select("nav.toc a")]
    body = [node.get_text(" ", strip=True) for node in soup.select(".container > section > h2")]

    assert toc == expected
    assert body == expected


def test_render_weekly_section_headings_have_one_numbering_layer(tmp_path):
    html = _render_weekly(tmp_path)
    soup = BeautifulSoup(html, "html.parser")
    expected = [
        "一、本周核心结论",
        "二、头部大模型：本周动态与趋势",
        "三、Coding Agent 深度观察",
        "四、通用 Agent 格局变化",
        "五、硬数据信号",
        "六、跨条目模式",
        "七、本周建议实验",
        "八、本周实践精选",
        "九、方法论雷达",
        "十、本周落地建议（体系化）",
        "十一、下周值得关注的信号",
    ]

    body = [node.get_text(" ", strip=True) for node in soup.select(".container > section > h2")]

    assert body == expected
```

- [ ] **Step 6: 运行 RED 测试并确认失败原因正确**

Run:

```bash
python -m pytest \
  skills/ai-daily-report/tests/test_render_html.py::test_daily_schema_rejects_numbered_top_level_section_titles \
  skills/ai-daily-report/tests/test_render_html.py::test_weekly_schema_rejects_numbered_top_level_section_titles \
  skills/ai-daily-report/tests/test_render_html.py::test_daily_schema_allows_numbered_nested_titles \
  skills/ai-daily-report/tests/test_render_html.py::test_render_daily_section_headings_have_one_numbering_layer \
  skills/ai-daily-report/tests/test_render_html.py::test_render_weekly_section_headings_have_one_numbering_layer \
  -q
```

Expected: 两个 schema 拒绝测试 FAIL，失败信息为 `should reject numbered title`；嵌套标题和现有单层渲染测试 PASS。

### Task 3: GREEN — 实现顶层 `sectionTitle` schema

**Files:**
- Modify: `skills/ai-daily-report/schemas/daily_report.schema.json:185-205,419-575`
- Modify: `skills/ai-daily-report/schemas/weekly_report.schema.json:30-150,185-450`
- Test: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: 在两个 schema 的 `$defs` 首项加入完全相同的定义**

```json
"sectionTitle": {
  "type": "string",
  "minLength": 1,
  "pattern": "^(?=.*\\S)(?!\\s*(?:[一二三四五六七八九十百]+[A-Za-z]?、|[0-9]+[.、)])).+$"
},
```

该规则拒绝 `一、`、`三a、`、`六A、`、`1.`、`1、`、`1)`，但允许 `一线模型`、`3D 模型` 以及嵌套对象自己的标题。

- [ ] **Step 2: 替换日报十一节顶层 title 定义**

将以下 section 的顶层 `"title": {"type": "string"}` 改为：

```json
"title": {"$ref": "#/$defs/sectionTitle"}
```

日报 section 列表：

```text
frontier_models (via itemSection)
coding_agents
general_agents (via generalSection)
agent_ecosystem
methodology_radar (via methodologyRadarSection)
market_signals (via marketSignalsSection)
pattern_observations (via patternObservationsSection)
experiments_this_week
decision_radar
action_items
unverified
```

不要修改 `deep_dive.title`、`ecosystemItem.title`、`experiment.title`、`methodologyRadarItem.title`。

- [ ] **Step 3: 替换周报十一节顶层 title 定义**

周报 section 列表：

```text
tldr
frontier_models
coding_agents
general_agents
market_signals (via marketSignalsSection)
pattern_observations
experiments_this_week
practice_digest
methodology_radar (via methodologyRadarSection)
action_items
next_week_signals
```

不要修改 vendor/product/item/experiment/methodology 等嵌套标题。

- [ ] **Step 4: 运行 GREEN 定向测试**

Run:

```bash
python -m pytest \
  skills/ai-daily-report/tests/test_render_html.py::test_daily_schema_rejects_numbered_top_level_section_titles \
  skills/ai-daily-report/tests/test_render_html.py::test_weekly_schema_rejects_numbered_top_level_section_titles \
  skills/ai-daily-report/tests/test_render_html.py::test_daily_schema_allows_numbered_nested_titles \
  skills/ai-daily-report/tests/test_render_html.py::test_render_daily_section_headings_have_one_numbering_layer \
  skills/ai-daily-report/tests/test_render_html.py::test_render_weekly_section_headings_have_one_numbering_layer \
  skills/ai-daily-report/tests/test_render_html.py::test_schema_shared_defs_are_byte_identical \
  -q
```

Expected: 6 passed。

### Task 4: 更新生成契约与设计范围

**Files:**
- Modify: `skills/ai-daily-report/SKILL.md:345-365`
- Modify: `skills/ai-daily-report/SKILL.md:390-430`
- Modify: `docs/superpowers/specs/2026-07-16-report-section-numbering-design.md`

- [ ] **Step 1: 在日报 JSON 产出要求中加入编号所有权**

在步骤 9 的结构化 JSON 约束中加入：

```markdown
- **章节标题契约**：`sections.*.title` 只写纯语义标题（如 `模型动态`、`方法论雷达`），不得写 `一、`、`三a、`、`6.` 等展示编号；日报/周报模板是章节编号的唯一真源，schema 会在渲染前拒绝带编号标题。
```

- [ ] **Step 2: 把日报终端简版改为连续十一节**

使用以下展示顺序替换旧 `三a / 三b / 六a / 七` 示例，并补回观察区：

```text
一、模型动态
二、Coding Agent 专项
三、通用 Agent 动态
四、Agent 生态与实践
五、方法论雷达
六、硬数据信号
七、跨条目模式
八、本期建议实验
九、决策雷达
十、今日落地建议
十一、观察区 / 待核实
```

- [ ] **Step 3: 更新设计文档中的迁移日期**

把所有“2026-07-13、2026-07-14”迁移描述改为“2026-07-13 至 2026-07-16”，并列出四个 payload。根因证据仍保留最初的 07-13/14，不把未检查的更早日期纳入迁移。

- [ ] **Step 4: 文档自检**

Run:

```bash
rg -n "三a、|三b、|六a、|2026-07-13.*2026-07-14" \
  skills/ai-daily-report/SKILL.md \
  docs/superpowers/specs/2026-07-16-report-section-numbering-design.md
```

Expected: `SKILL.md` 仅允许在“禁止示例”说明中出现旧编号；设计文档只在根因说明或禁止示例中出现，迁移范围已是 07-13..16。

### Task 5: 迁移四天 payload 并刷新本地产物

**Files:**
- Modify: `cache/2026-07-13/report.json`
- Modify: `cache/2026-07-14/report.json`
- Modify: `cache/2026-07-15/report.json`
- Modify: `cache/2026-07-16/report.json`
- Regenerate: corresponding cache/report HTML files and `reports/daily/*.html`

- [ ] **Step 1: 保存发送状态哈希作为不发信证据**

Run:

```bash
shasum cache/2026-07-13/send_state.json cache/2026-07-14/send_state.json cache/2026-07-15/send_state.json cache/2026-07-16/send_state.json
```

Expected: 记录四个文件的原始哈希；若某日没有文件，明确记录 `missing`，不创建发送状态。

- [ ] **Step 2: 只清理十一节顶层 title**

四份 JSON 均改为以下纯标题映射：

```json
{
  "frontier_models": "模型动态",
  "coding_agents": "Coding Agent 专项",
  "general_agents": "通用 Agent 动态",
  "agent_ecosystem": "Agent 生态与实践",
  "methodology_radar": "方法论雷达",
  "market_signals": "硬数据信号",
  "pattern_observations": "跨条目模式",
  "experiments_this_week": "本期建议实验",
  "decision_radar": "决策雷达",
  "action_items": "今日落地建议",
  "unverified": "观察区 / 待核实"
}
```

不修改任何 items、references、fetch_status、send_state 或 run.log。

- [ ] **Step 3: 使用 bundled renderer 重渲染 cache HTML**

Run:

```bash
python skills/ai-daily-report/scripts/render_html.py cache/2026-07-13/report.json
python skills/ai-daily-report/scripts/render_html.py cache/2026-07-14/report.json
python skills/ai-daily-report/scripts/render_html.py cache/2026-07-15/report.json
python skills/ai-daily-report/scripts/render_html.py cache/2026-07-16/report.json
```

Expected: 四条命令均退出 0，并分别输出对应 `cache/<date>/report.html` 路径。

- [ ] **Step 4: 使用 bundled archiver 更新本地归档**

Run:

```bash
python skills/ai-daily-report/scripts/archive.py cache/2026-07-13/report.html --type daily --date 2026-07-13
python skills/ai-daily-report/scripts/archive.py cache/2026-07-14/report.html --type daily --date 2026-07-14
python skills/ai-daily-report/scripts/archive.py cache/2026-07-15/report.html --type daily --date 2026-07-15
python skills/ai-daily-report/scripts/archive.py cache/2026-07-16/report.html --type daily --date 2026-07-16
```

Expected: 四条命令均退出 0，输出对应 `reports/daily/<date>.html`。不要运行 `finalize-daily` 或 `send_mail.py`。

- [ ] **Step 5: 对比发送状态哈希**

重新运行 Step 1 的 `shasum` 命令。

Expected: 四个现存 `send_state.json` 哈希与迁移前完全一致。

### Task 6: 完整验证与提交

**Files:**
- Test: all files above
- Inspect: `cache/2026-07-13..16/report.html`
- Inspect: `reports/daily/2026-07-13..16.html`

- [ ] **Step 1: 验证 JSON 顶层标题已纯化**

Run:

```bash
for file in cache/2026-07-{13,14,15,16}/report.json; do
  jq -r '.sections | to_entries[] | "\(.key)\t\(.value.title)"' "$file"
done
```

Expected: 十一节均为纯语义标题，无 `一、`、`三a、`、`六a、` 等前缀。

- [ ] **Step 2: 验证 cache 与归档 HTML 无重复编号**

Run:

```bash
rg -n "一、一、|二、二、|三、三、|四、三a、|五、三b、|六、四、|七、五、|八、六、|九、六a、|十、七、|十一、八、" \
  cache/2026-07-{13,14,15,16}/report.html \
  reports/daily/2026-07-{13,14,15,16}.html
```

Expected: 无输出，退出码 1（未找到匹配）。

- [ ] **Step 3: 运行渲染测试文件**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_render_html.py -q
```

Expected: 全部通过，0 failures。

- [ ] **Step 4: 运行完整测试集**

Run:

```bash
python -m pytest skills/ai-daily-report/tests -q
```

Expected: 全部通过，0 failures。

- [ ] **Step 5: 检查代码与文档差异**

Run:

```bash
git diff --check
git status --short
git diff -- skills/ai-daily-report/tests/test_render_html.py skills/ai-daily-report/schemas/daily_report.schema.json skills/ai-daily-report/schemas/weekly_report.schema.json skills/ai-daily-report/SKILL.md docs/superpowers/specs/2026-07-16-report-section-numbering-design.md
```

Expected: `git diff --check` 无输出；差异只涉及本计划列出的 tracked files。cache/report artifacts 因 gitignore 不出现在 tracked diff。

- [ ] **Step 6: 提交实现**

Run:

```bash
git add \
  skills/ai-daily-report/tests/test_render_html.py \
  skills/ai-daily-report/schemas/daily_report.schema.json \
  skills/ai-daily-report/schemas/weekly_report.schema.json \
  skills/ai-daily-report/SKILL.md \
  docs/superpowers/specs/2026-07-16-report-section-numbering-design.md
git commit -m "fix: enforce single-source report section numbering"
```

Expected: 提交成功；提交不包含 cache、reports 或发送状态文件。
