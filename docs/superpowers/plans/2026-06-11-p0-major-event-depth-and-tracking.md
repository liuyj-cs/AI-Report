# P0: Major-Event Depth + Event Tracking + Weekly Enablement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give major releases (e.g. Claude Fable 5) same-day structured depth via an `expanded` block, keep covering them for 3-5 days via `cache/tracking/` event files exempt from cross-day dedup, and document the weekly-report cadence so it actually runs.

**Architecture:** All depth/tracking judgment stays with the AI editor (SKILL.md rules); repo scripts only add deterministic contracts — schema fields, finalize validators (`major_event` ⟺ `expanded` + `tracking_ref`, tracking refs must resolve to active files), manifest exposure of active tracking events, and cleanup safety. No new orchestration.

**Tech Stack:** Python 3.13, jsonschema, Jinja2, pytest (existing repo conventions).

**Working-tree note:** The repo has unrelated uncommitted changes (AI HOT source in `sources/whitelist.yaml` + `tests/test_discovery.py`). Never `git add -A`; stage only the files named in each task's commit step.

---

## File Map

**Create**
- `skills/ai-daily-report/schemas/event_tracking.schema.json` — contract for `cache/tracking/{slug}.json` files.
- `skills/ai-daily-report/scripts/tracking.py` — load/validate/filter/cleanup helpers for tracking files.
- `skills/ai-daily-report/tests/test_tracking.py` — unit tests for tracking module.

**Modify**
- `skills/ai-daily-report/schemas/daily_report.schema.json` — `$defs/expandedBlock`; optional `major_event` / `expanded` / `tracking_ref` on `modelItem` / `codingItem` / `generalItem`.
- `skills/ai-daily-report/schemas/candidate_ledger.schema.json` — optional `tracking_ref` on `candidateRecord`.
- `skills/ai-daily-report/scripts/editorial.py` — `validate_major_event_consistency`; wire tracking-ref validation into `validate_daily_artifacts`.
- `skills/ai-daily-report/scripts/archive.py` — exclude `cache/tracking/` from leaf-dir cleanup.
- `skills/ai-daily-report/scripts/discovery.py` — `build_discovery_manifest(..., active_tracking=None)`.
- `skills/ai-daily-report/scripts/report_runner.py` — init-daily surfaces active tracking; finalize-daily passes project root to validators and cleans expired tracking files.
- `skills/ai-daily-report/templates/daily.html.j2` — render expanded block + 重大事件/事件追踪 badges.
- `skills/ai-daily-report/SKILL.md` — major-event judgment, deep evidence expansion, tracking workflow, dedup exemption, weekly cadence.
- `README.md` — weekly trigger + tracking dir documentation.
- Tests: `tests/test_render_html.py`, `tests/test_editorial.py`, `tests/test_archive.py`, `tests/test_discovery.py`, `tests/test_report_runner.py`.

**Leave As-Is**
- `scripts/render_html.py`, `scripts/send_mail.py`, `scripts/evidence.py`, `templates/weekly.html.j2`, `schemas/weekly_report.schema.json` — weekly pipeline already works mechanically; enablement is cadence documentation, not code.

**Known pre-existing gap (do NOT fix in this plan):** `run_daily_finalize` never calls `cleanup_cache` (only the `archive.py` CLI path does), which is why `cache/` has >14-day-old dirs. Out of P0 scope; mention to the user at the end.

---

### Task 1: Daily Schema — `expandedBlock` + optional item fields

**Files:**
- Modify: `skills/ai-daily-report/schemas/daily_report.schema.json`
- Test: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: Write the failing schema tests**

Append to `skills/ai-daily-report/tests/test_render_html.py` (module already imports `json`, `Draft202012Validator`, `FIXTURES`, `SCHEMAS`):

```python
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
    item["expanded"]["what_shipped"] = "长" * 401
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py -q -k "expanded or tracking_ref"`
Expected: FAIL — `test_daily_schema_rejects_overlong_expanded_field` and `test_daily_schema_rejects_invalid_tracking_ref` fail because the schema currently allows arbitrary extra properties (no errors produced).

- [ ] **Step 3: Add `expandedBlock` def and item fields to the schema**

In `skills/ai-daily-report/schemas/daily_report.schema.json`, inside `"$defs"` (after `"generalItem"`, before `"itemRef"`), add:

```json
"expandedBlock": {
  "type": "object",
  "required": ["what_shipped", "open_questions"],
  "properties": {
    "what_shipped": {"type": "string", "minLength": 50, "maxLength": 400},
    "benchmarks": {"type": "string", "maxLength": 400},
    "pricing_availability": {"type": "string", "maxLength": 300},
    "comparison": {"type": "string", "maxLength": 300},
    "third_party_reaction": {"type": "string", "maxLength": 300},
    "open_questions": {
      "type": "array",
      "minItems": 1,
      "maxItems": 5,
      "items": {"type": "string", "minLength": 1, "maxLength": 120}
    }
  }
},
```

Then add these three properties to **each** of `modelItem`, `codingItem`, `generalItem` `properties` (after `"via_broad_search"`):

```json
"major_event": {"type": "boolean"},
"expanded": {"$ref": "#/$defs/expandedBlock"},
"tracking_ref": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py -q`
Expected: PASS (all, including pre-existing render tests)

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/schemas/daily_report.schema.json skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: add major_event expanded block to daily schema"
```

### Task 2: Render expanded block + badges in daily template

**Files:**
- Modify: `skills/ai-daily-report/templates/daily.html.j2`
- Test: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: Write the failing render test**

Append to `skills/ai-daily-report/tests/test_render_html.py` (reuses `_major_event_item` from Task 1):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py::test_render_daily_major_event_expanded_block -q`
Expected: FAIL — no `.badge-major` / `.major-expanded` elements rendered.

- [ ] **Step 3: Add CSS, badge markup, and expanded macro to the template**

In `skills/ai-daily-report/templates/daily.html.j2`:

(a) Add CSS inside `<style>` right before the final dark-mode `@media` block (after the `.badge-horizon` rule, around line 126):

```css
  .badge-major { background: #ffebe9; color: #cf222e; font-weight: 600; }
  .badge-tracking { background: #fbefff; color: #8250df; }
  .major-expanded { border: 2px solid var(--accent); background: var(--accent-soft); border-radius: 8px; padding: 14px; margin: 12px 0; font-size: 15px; }
  .major-expanded .row { margin: 6px 0; }
  .major-expanded .row .label { font-weight: 600; }
  .major-expanded ul.open-questions { margin: 4px 0 0; padding-left: 22px; }
```

and inside the existing dark-mode `@media (prefers-color-scheme: dark)` block at the end of the stylesheet (the one containing `.badge-rec-patch`), add:

```css
    .badge-major          { background: #4a0e0e; color: #ff7b72; }
    .badge-tracking       { background: #2d1b3e; color: #d2a8ff; }
```

(b) Extend the `item_meta` macro (lines 139-144) by adding two lines before `{%- endmacro %}`:

```jinja
  {% if item.major_event %}<span class="badge badge-major">重大事件</span>{% endif %}
  {% if item.tracking_ref %}<span class="badge badge-tracking">事件追踪</span>{% endif %}
```

(c) Add a new macro right after the `item_meta` macro:

```jinja
{% macro expanded_block(item) -%}
{% if item.expanded %}
<div class="major-expanded">
  <div class="row"><span class="label">发布要点：</span>{{ item.expanded.what_shipped }}</div>
  {% if item.expanded.benchmarks %}<div class="row"><span class="label">官方基准：</span>{{ item.expanded.benchmarks }}</div>{% endif %}
  {% if item.expanded.pricing_availability %}<div class="row"><span class="label">定价与可用性：</span>{{ item.expanded.pricing_availability }}</div>{% endif %}
  {% if item.expanded.comparison %}<div class="row"><span class="label">对比现役：</span>{{ item.expanded.comparison }}</div>{% endif %}
  {% if item.expanded.third_party_reaction %}<div class="row"><span class="label">第三方反应：</span>{{ item.expanded.third_party_reaction }}</div>{% endif %}
  <div class="row"><span class="label">待验证：</span></div>
  <ul class="open-questions">{% for q in item.expanded.open_questions %}<li>{{ q }}</li>{% endfor %}</ul>
</div>
{% endif %}
{%- endmacro %}
```

(d) Call the macro in all three item sections, adding `{{ expanded_block(item) }}` on a new line immediately after the `<div class="source">...</div>` line inside each `<article class="card">`:
- frontier section (`id="frontier_models-{{ loop.index0 }}"` article)
- coding section (`id="coding_agents-{{ loop.index0 }}"` article)
- general section (`id="general_agents-{{ loop.index0 }}"` article)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_render_html.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/templates/daily.html.j2 skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: render major event expanded block and tracking badges"
```

### Task 3: Editorial validator — major_event consistency

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Write the failing validator tests**

Append to `skills/ai-daily-report/tests/test_editorial.py` (the module already imports `json` and editorial functions via conftest `sys.path`; add `validate_major_event_consistency` to its imports from `editorial`):

```python
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
```

If `test_editorial.py` does not already import `validate_daily_artifacts`, add it to the same `from editorial import ...` statement as `validate_major_event_consistency`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_editorial.py -q -k "major_event"`
Expected: FAIL with `ImportError: cannot import name 'validate_major_event_consistency'`

- [ ] **Step 3: Implement the validator and wire it in**

In `skills/ai-daily-report/scripts/editorial.py`, add after `validate_candidate_ledger_semantics` (around line 249):

```python
def validate_major_event_consistency(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section_name in DAILY_REFERENCE_SECTIONS:
        for index, item in enumerate(report.get("sections", {}).get(section_name, {}).get("items", [])):
            label = f"{section_name}[{index}]"
            is_major = bool(item.get("major_event"))
            expanded = item.get("expanded")
            if expanded and not is_major:
                errors.append(f"{label} has expanded block but major_event is not true")
            if not is_major:
                continue
            if not expanded:
                errors.append(f"{label} major_event=true requires expanded block")
            if item.get("editorial_tier") != "core":
                errors.append(f"{label} major_event=true requires editorial_tier='core'")
            if not item.get("tracking_ref"):
                errors.append(f"{label} major_event=true requires tracking_ref")
    return errors
```

In `validate_daily_artifacts` (line 694), add before `return errors`:

```python
    errors.extend(validate_major_event_consistency(report))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_editorial.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: validate major_event expanded/tracking consistency"
```

### Task 4: Tracking module — schema + load/active/cleanup helpers

**Files:**
- Create: `skills/ai-daily-report/schemas/event_tracking.schema.json`
- Create: `skills/ai-daily-report/scripts/tracking.py`
- Create: `skills/ai-daily-report/tests/test_tracking.py`

- [ ] **Step 1: Write the failing tracking tests**

Create `skills/ai-daily-report/tests/test_tracking.py`:

```python
import json
from pathlib import Path

from tracking import (
    active_tracking_events,
    cleanup_expired_tracking,
    load_tracking_events,
    validate_tracking_refs,
)


def _write_tracking(project_root: Path, slug: str, opened: str, expires: str) -> Path:
    payload = {
        "version": "1.0",
        "type": "event_tracking",
        "event_slug": slug,
        "title": "Claude Fable 5 / Mythos 5 发布",
        "opened_date": opened,
        "expires_on": expires,
        "origin": {"date": opened, "section": "frontier_models", "headline": "Claude Fable 5 / Mythos 5 发布"},
        "watch_items": ["第三方 benchmark 何时收录"],
        "updates": [],
    }
    directory = project_root / "cache" / "tracking"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{slug}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_load_tracking_events_accepts_valid_file(tmp_path):
    _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-14")
    events, errors = load_tracking_events(tmp_path)
    assert errors == []
    assert [event["event_slug"] for event in events] == ["claude-fable-5"]


def test_load_tracking_events_rejects_window_over_five_days(tmp_path):
    _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-20")
    events, errors = load_tracking_events(tmp_path)
    assert events == []
    assert any("0-5 days" in error for error in errors)


def test_load_tracking_events_rejects_slug_filename_mismatch(tmp_path):
    path = _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-14")
    path.rename(path.with_name("other-name.json"))
    events, errors = load_tracking_events(tmp_path)
    assert events == []
    assert any("does not match filename" in error for error in errors)


def test_active_tracking_events_filters_by_date(tmp_path):
    _write_tracking(tmp_path, "claude-fable-5", "2026-06-10", "2026-06-14")
    _write_tracking(tmp_path, "old-event", "2026-06-01", "2026-06-05")
    active = active_tracking_events(tmp_path, "2026-06-11")
    assert [event["event_slug"] for event in active] == ["claude-fable-5"]


def test_validate_tracking_refs_flags_unknown_slug(tmp_path, sample_daily_report):
    _write_tracking(tmp_path, "claude-fable-5", "2026-04-09", "2026-04-12")
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["frontier_models"]["items"][0]["tracking_ref"] = "missing-event"
    errors = validate_tracking_refs(report, tmp_path)
    assert any("missing-event" in error for error in errors)


def test_validate_tracking_refs_accepts_active_slug(tmp_path, sample_daily_report):
    # sample_daily.json 的 date 是 2026-04-10，落在追踪窗口内
    _write_tracking(tmp_path, "claude-fable-5", "2026-04-09", "2026-04-12")
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["frontier_models"]["items"][0]["tracking_ref"] = "claude-fable-5"
    assert validate_tracking_refs(report, tmp_path) == []


def test_cleanup_expired_tracking_removes_old_files(tmp_path):
    _write_tracking(tmp_path, "old-event", "2026-05-20", "2026-05-24")
    _write_tracking(tmp_path, "fresh-event", "2026-06-08", "2026-06-12")
    removed = cleanup_expired_tracking(tmp_path, "2026-06-11", grace_days=7)
    assert removed == 1
    assert not (tmp_path / "cache" / "tracking" / "old-event.json").exists()
    assert (tmp_path / "cache" / "tracking" / "fresh-event.json").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_tracking.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'tracking'`

- [ ] **Step 3: Create the tracking schema**

Create `skills/ai-daily-report/schemas/event_tracking.schema.json`:

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "AIReportEventTracking",
  "type": "object",
  "required": ["version", "type", "event_slug", "title", "opened_date", "expires_on", "origin", "watch_items"],
  "properties": {
    "version": {"const": "1.0"},
    "type": {"const": "event_tracking"},
    "event_slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$"},
    "title": {"type": "string", "minLength": 1, "maxLength": 80},
    "opened_date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "expires_on": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
    "origin": {
      "type": "object",
      "required": ["date", "section", "headline"],
      "properties": {
        "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
        "section": {"enum": ["frontier_models", "coding_agents", "general_agents"]},
        "headline": {"type": "string", "minLength": 1}
      }
    },
    "watch_items": {
      "type": "array",
      "minItems": 1,
      "maxItems": 6,
      "items": {"type": "string", "minLength": 1, "maxLength": 120}
    },
    "updates": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["date", "headline"],
        "properties": {
          "date": {"type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$"},
          "headline": {"type": "string", "minLength": 1},
          "ref": {"type": "string"}
        }
      }
    }
  }
}
```

- [ ] **Step 4: Create the tracking module**

Create `skills/ai-daily-report/scripts/tracking.py`:

```python
#!/usr/bin/env python3
"""Deterministic helpers for major-event tracking files under cache/tracking/."""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SKILL_ROOT = Path(__file__).resolve().parent.parent
TRACKING_SCHEMA_PATH = SKILL_ROOT / "schemas" / "event_tracking.schema.json"
MAX_TRACKING_DAYS = 5


def tracking_dir(project_root: Path) -> Path:
    return project_root / "cache" / "tracking"


def load_tracking_events(project_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    events: list[dict[str, Any]] = []
    errors: list[str] = []
    directory = tracking_dir(project_root)
    if not directory.exists():
        return events, errors

    schema = json.loads(TRACKING_SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"cache/tracking/{path.name}: cannot load ({exc})")
            continue
        schema_errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.path))
        if schema_errors:
            errors.append(f"cache/tracking/{path.name}: {schema_errors[0].message}")
            continue
        if payload["event_slug"] != path.stem:
            errors.append(f"cache/tracking/{path.name}: event_slug {payload['event_slug']!r} does not match filename")
            continue
        opened = date.fromisoformat(payload["opened_date"])
        expires = date.fromisoformat(payload["expires_on"])
        if expires < opened or (expires - opened).days > MAX_TRACKING_DAYS:
            errors.append(f"cache/tracking/{path.name}: tracking window must be 0-{MAX_TRACKING_DAYS} days")
            continue
        events.append(payload)
    return events, errors


def active_tracking_events(project_root: Path, target_date: str) -> list[dict[str, Any]]:
    events, _ = load_tracking_events(project_root)
    target = date.fromisoformat(target_date)
    return [
        event
        for event in events
        if date.fromisoformat(event["opened_date"]) <= target <= date.fromisoformat(event["expires_on"])
    ]


def validate_tracking_refs(report: dict[str, Any], project_root: Path) -> list[str]:
    errors: list[str] = []
    events, load_errors = load_tracking_events(project_root)
    errors.extend(load_errors)
    target_date = str(report.get("date", ""))
    try:
        target = date.fromisoformat(target_date)
    except ValueError:
        errors.append(f"report date {target_date!r} is not a valid date")
        return errors

    active = {
        event["event_slug"]
        for event in events
        if date.fromisoformat(event["opened_date"]) <= target <= date.fromisoformat(event["expires_on"])
    }
    for section_name in ("frontier_models", "coding_agents", "general_agents"):
        for index, item in enumerate(report.get("sections", {}).get(section_name, {}).get("items", [])):
            slug = item.get("tracking_ref")
            if slug and slug not in active:
                errors.append(f"{section_name}[{index}] tracking_ref {slug!r} has no active tracking file")
    return errors


def cleanup_expired_tracking(project_root: Path, today: str, grace_days: int = 7) -> int:
    directory = tracking_dir(project_root)
    if not directory.exists():
        return 0
    cutoff = date.fromisoformat(today) - timedelta(days=grace_days)
    removed = 0
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            expires = date.fromisoformat(payload["expires_on"])
        except (OSError, json.JSONDecodeError, KeyError, ValueError):
            continue
        if expires < cutoff:
            path.unlink()
            removed += 1
    return removed
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_tracking.py -q`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/schemas/event_tracking.schema.json skills/ai-daily-report/scripts/tracking.py skills/ai-daily-report/tests/test_tracking.py
git commit -m "feat: add event tracking schema and helpers"
```

### Task 5: Wire tracking validation into finalize + runner

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py:694` (`validate_daily_artifacts`)
- Modify: `skills/ai-daily-report/scripts/report_runner.py:110-150` (`run_daily_finalize`)
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Write the failing integration test**

Append to `skills/ai-daily-report/tests/test_editorial.py`:

```python
def test_validate_daily_artifacts_checks_tracking_refs_when_root_given(
    tmp_path, sample_daily_report, sample_candidate_ledger, sample_whitelist
):
    report = json.loads(json.dumps(sample_daily_report, ensure_ascii=False))
    report["sections"]["frontier_models"]["items"][0]["tracking_ref"] = "missing-event"
    errors = validate_daily_artifacts(
        report, sample_candidate_ledger, sample_whitelist, project_root=tmp_path
    )
    assert any("missing-event" in error for error in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_checks_tracking_refs_when_root_given -q`
Expected: FAIL with `TypeError: validate_daily_artifacts() got an unexpected keyword argument 'project_root'`

- [ ] **Step 3: Extend `validate_daily_artifacts` and the runner**

In `skills/ai-daily-report/scripts/editorial.py`:

(a) Add import near the existing `from discovery import ...` line:

```python
from tracking import validate_tracking_refs
```

(b) Change the `validate_daily_artifacts` signature and body:

```python
def validate_daily_artifacts(
    report: dict[str, Any],
    ledger: dict[str, Any],
    whitelist: dict[str, Any],
    project_root: Path | None = None,
) -> list[str]:
```

and after the `validate_major_event_consistency` line (added in Task 3), before `return errors`:

```python
    if project_root is not None:
        errors.extend(validate_tracking_refs(report, project_root))
```

In `skills/ai-daily-report/scripts/report_runner.py`:

(a) Add import next to the other local imports:

```python
from tracking import cleanup_expired_tracking
```

(b) In `run_daily_finalize`, change the validation call (line 130) to:

```python
    errors = validate_daily_artifacts(report, ledger, whitelist, project_root)
```

(c) Still in `run_daily_finalize`, immediately after the `ARCHIVE` run-log line (line 137), add:

```python
    removed_tracking = cleanup_expired_tracking(project_root, target_date)
    if removed_tracking:
        append_run_log(run_log, f"{report.get('generated_at', datetime.now().isoformat())} TRACKING cleanup removed={removed_tracking}")
```

- [ ] **Step 4: Run the affected suites**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_editorial.py skills/ai-daily-report/tests/test_report_runner.py -q`
Expected: PASS (existing runner tests keep passing because the new parameter defaults to `None` for other callers and tracking refs are absent from fixtures)

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: enforce active tracking refs at daily finalize"
```

### Task 6: Protect `cache/tracking/` from cache cleanup

**Files:**
- Modify: `skills/ai-daily-report/scripts/archive.py:24-35` (`_iter_cache_leaf_dirs`)
- Test: `skills/ai-daily-report/tests/test_archive.py`

- [ ] **Step 1: Write the failing test**

Append to `skills/ai-daily-report/tests/test_archive.py` (add `import os` and `import time` to the imports if not present; the module already imports `cleanup_cache` or import it the same way existing tests do):

```python
def test_cleanup_cache_preserves_tracking_dir(tmp_path):
    cache = tmp_path / "cache"
    old_daily = cache / "2026-01-01"
    tracking = cache / "tracking"
    old_daily.mkdir(parents=True)
    tracking.mkdir(parents=True)
    (tracking / "claude-fable-5.json").write_text("{}", encoding="utf-8")
    old_time = time.time() - 90 * 86400
    os.utime(old_daily, (old_time, old_time))
    os.utime(tracking, (old_time, old_time))

    removed = cleanup_cache(tmp_path)

    assert removed == 1
    assert not old_daily.exists()
    assert tracking.exists()
    assert (tracking / "claude-fable-5.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_archive.py::test_cleanup_cache_preserves_tracking_dir -q`
Expected: FAIL — `tracking` dir is treated as a stale leaf and deleted (`removed == 2`).

- [ ] **Step 3: Exclude the tracking dir**

In `skills/ai-daily-report/scripts/archive.py`, inside `_iter_cache_leaf_dirs`, add right after the `if not child.is_dir():` guard:

```python
        if child.name == "tracking":
            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_archive.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/archive.py skills/ai-daily-report/tests/test_archive.py
git commit -m "fix: exclude cache/tracking from stale cache cleanup"
```

### Task 7: Surface active tracking events in the discovery manifest

**Files:**
- Modify: `skills/ai-daily-report/scripts/discovery.py` (`build_discovery_manifest`, around line 289)
- Modify: `skills/ai-daily-report/scripts/report_runner.py:42-65` (`run_daily_init`)
- Test: `skills/ai-daily-report/tests/test_discovery.py`
- Test: `skills/ai-daily-report/tests/test_report_runner.py`

- [ ] **Step 1: Write the failing tests**

Append to `skills/ai-daily-report/tests/test_discovery.py`:

```python
def test_build_discovery_manifest_includes_active_tracking(sample_whitelist):
    from discovery import build_discovery_manifest, compute_daily_window

    window = compute_daily_window("2026-06-11", "2026-06-11T07:10:00+08:00")
    manifest = build_discovery_manifest("2026-06-11", window, sample_whitelist)
    assert manifest["active_tracking"] == []

    tracked = [
        {
            "event_slug": "claude-fable-5",
            "title": "Claude Fable 5 发布",
            "expires_on": "2026-06-14",
            "watch_items": ["第三方 benchmark 何时收录"],
        }
    ]
    manifest = build_discovery_manifest("2026-06-11", window, sample_whitelist, active_tracking=tracked)
    assert manifest["active_tracking"] == tracked
```

Append to `skills/ai-daily-report/tests/test_report_runner.py` (add `import json` if missing; `run_daily_init` is imported the same way the existing init tests do):

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_discovery.py::test_build_discovery_manifest_includes_active_tracking skills/ai-daily-report/tests/test_report_runner.py::test_init_daily_manifest_lists_active_tracking -q`
Expected: FAIL — `KeyError: 'active_tracking'`

- [ ] **Step 3: Implement manifest + init wiring**

In `skills/ai-daily-report/scripts/discovery.py`, change the `build_discovery_manifest` signature to:

```python
def build_discovery_manifest(
    target_date: str,
    window: dict[str, str],
    whitelist: dict[str, Any],
    active_tracking: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
```

and add to the returned dict (after `"window": window,`):

```python
        "active_tracking": active_tracking or [],
```

In `skills/ai-daily-report/scripts/report_runner.py`:

(a) Extend the tracking import from Task 5:

```python
from tracking import active_tracking_events, cleanup_expired_tracking
```

(b) In `run_daily_init`, replace the `manifest = build_discovery_manifest(...)` line with:

```python
    active = [
        {
            "event_slug": event["event_slug"],
            "title": event["title"],
            "expires_on": event["expires_on"],
            "watch_items": event.get("watch_items", []),
        }
        for event in active_tracking_events(project_root, target_date)
    ]
    manifest = build_discovery_manifest(target_date, window, whitelist, active_tracking=active)
```

and after the `DISCOVERY manifest=... ready` run-log line add:

```python
    append_run_log(run_log, f"{now_iso} TRACKING active={len(active)}")
```

- [ ] **Step 4: Run the affected suites**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_discovery.py skills/ai-daily-report/tests/test_report_runner.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/discovery.py skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/tests/test_discovery.py skills/ai-daily-report/tests/test_report_runner.py
git commit -m "feat: surface active tracking events in discovery manifest"
```

### Task 8: Ledger field, SKILL.md workflow rules, README, full verification

**Files:**
- Modify: `skills/ai-daily-report/schemas/candidate_ledger.schema.json`
- Modify: `skills/ai-daily-report/SKILL.md`
- Modify: `README.md`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Write the failing ledger test**

Append to `skills/ai-daily-report/tests/test_editorial.py` (import `validate_candidate_ledger_schema` from `editorial` if not already imported):

```python
def test_candidate_ledger_accepts_optional_tracking_ref(sample_candidate_ledger):
    ledger = json.loads(json.dumps(sample_candidate_ledger, ensure_ascii=False))
    ledger["items"][0]["tracking_ref"] = "claude-fable-5"
    assert validate_candidate_ledger_schema(ledger) == []

    ledger["items"][0]["tracking_ref"] = "Claude Fable!"
    errors = validate_candidate_ledger_schema(ledger)
    assert any("tracking_ref" in error for error in errors)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_candidate_ledger_accepts_optional_tracking_ref -q`
Expected: FAIL — the second assertion fails because `tracking_ref` is unconstrained today.

- [ ] **Step 3: Add the ledger property**

In `skills/ai-daily-report/schemas/candidate_ledger.schema.json`, add to `candidateRecord.properties` (after `"action_eligibility"`; do NOT add it to `required`):

```json
"tracking_ref": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$"}
```

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_candidate_ledger_accepts_optional_tracking_ref -q`
Expected: PASS

- [ ] **Step 4: Update SKILL.md**

Make these edits in `skills/ai-daily-report/SKILL.md`:

(a) In step 3 **编辑原则** bullet list (after the bullet 「严禁因为"某厂商默认更重要"…」), add:

```markdown
     - **重大事件判定（major_event）**：当一条 `selected_core` 候选满足「会改变读者的选型决策、或值得当天安排评估」（典型：新一代前沿模型发布、头部 coding agent 重大版本或定价变化、影响选型的重大产品发布）时，标记 `major_event: true`。这是编辑结论，不是分数阈值；每天 0-2 条，宁缺毋滥。
```

(b) After step **3a. 当前状态校验** 一节末尾，新增一节：

```markdown
3b. **重大事件深度与事件追踪（major_event）**

   - **判定**：见编辑原则。`major_event: true` 只能标在 `editorial_tier: core` 的条目上。
   - **当天深度补证（2-3 跳）**：对重大事件，证据扩展从常规 1 跳放宽到 2-3 跳，目标面优先：model card / system card / 官方 benchmark 页 / pricing 页 / developer docs / 可用区与配额说明。每次尝试照常写入 `fetch_status.source_details`。
   - **撰写 `expanded` 块**（schema `$defs/expandedBlock`，挂在条目上）：
     - `what_shipped`（50-400 字，必填）：发布要点
     - `benchmarks`（≤400 字，可选）：官方 benchmark 摘录，只写官方给出的数字
     - `pricing_availability`（≤300 字，可选）：定价、配额、可用区
     - `comparison`（≤300 字，可选）：与现役模型/版本对比
     - `third_party_reaction`（≤300 字，可选）：已抓到证据的第三方反应，禁止臆测
     - `open_questions`（1-5 条，必填）：待验证问题清单，将转入事件追踪
   - **开追踪档案**：写 `cache/tracking/{event_slug}.json`（schema `schemas/event_tracking.schema.json`）。`event_slug` 用小写连字符（如 `claude-fable-5`），`expires_on` 距 `opened_date` 不超过 5 天，`watch_items` 直接继承 `open_questions`。条目同时写 `tracking_ref: {event_slug}`；finalize 会校验 `major_event` 条目必须有 expanded + tracking_ref，且 tracking_ref 能解析到活跃档案。
   - **追踪期内的后续日报**：`discovery_manifest.json` 的 `active_tracking` 会列出活跃追踪事件。对每个活跃事件至少执行一轮定向搜索（第三方评测 / 实测反馈 / 价格与配额变化）。命中的增量条目：
     - 豁免 3-1 跨日去重（见该节例外 2），headline 必须体现增量（如「Fable 5 第三方评测首批出炉」）
     - 条目带 `tracking_ref`，并把 `{date, headline, ref}` 追加进追踪档案的 `updates[]`
     - 没有增量就不写条目，不为追踪而凑数
   - **关闭**：`expires_on` 过后档案自动失效；finalize 会清理过期超过 7 天的档案。追踪档案的 `updates[]` 是周报回顾该事件的现成素材。
```

(c) In step **3-1 跨日去重**, after the existing 「唯一例外」 bullet, add (and change 「唯一例外」 to 「例外 1」):

```markdown
   - **例外 2（事件追踪）**：当日条目带 `tracking_ref` 且对应 `cache/tracking/{slug}.json` 处于活跃期 → 不因与昨日/前日同一实体而丢弃，但 headline 与 summary 必须只写增量信息，不复述发布日内容
```

(d) In the **产出字段约束** table, add rows:

```markdown
| `expanded.what_shipped` | 50-400 字（仅 major_event 条目） |
| `expanded.open_questions` | 1-5 条，每条 ≤ 120 字 |
| `major_event` 条目 | 仅 core；每日 0-2 条；必须同时有 `expanded` 与 `tracking_ref` |
```

(e) In the **周报工作流** header block (right under 「**采集窗口**」 line), add:

```markdown
**运行节奏**：每周一上午运行上一 ISO 周的周报（例如周一为 2026-06-15 时，iso_week = 2026-W24）。`cache/tracking/` 中本周活跃过的追踪档案（含 `updates[]`）是周报回顾重大事件的现成素材，读入后随日报 JSON 一起聚合。
```

- [ ] **Step 5: Update README**

In `README.md`:

(a) In the 快速开始 step 4 example list, add one line:

```markdown
   - `生成上周的 AI 周报`（建议每周一上午跑，聚合上一 ISO 周 7 天日报）
```

(b) In the 目录 section, add one line:

```markdown
- `cache/tracking/`：重大事件追踪档案（3-5 天有效期，驱动跨日追踪报道，运行时生成）
```

- [ ] **Step 6: Full verification**

Run: `cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python -m pytest skills/ai-daily-report/tests -q`
Expected: ALL PASS

Then render a real report end-to-end as a smoke test (expanded block injected into a copy of the latest cached report):

```bash
cd /Users/liuyingjie/Documents/CodexTool/AIReport && .venv/bin/python - <<'EOF'
import json, pathlib, subprocess, sys, tempfile
src = json.loads(pathlib.Path("cache/2026-06-10/report.json").read_text())
item = src["sections"]["frontier_models"]["items"][0]
item.update({
    "major_event": True,
    "tracking_ref": "claude-fable-5",
    "expanded": {
        "what_shipped": "Anthropic 发布 Claude Fable 5 与 Mythos 5，首次把 Mythos 级模型开放到通用用户侧，并同步更新模型卡与定价页。",
        "open_questions": ["第三方 benchmark 何时收录"],
    },
})
with tempfile.TemporaryDirectory() as tmp:
    p = pathlib.Path(tmp) / "report.json"
    p.write_text(json.dumps(src, ensure_ascii=False))
    out = subprocess.run([sys.executable, "skills/ai-daily-report/scripts/render_html.py", str(p)], capture_output=True, text=True)
    print(out.stdout or out.stderr)
    assert out.returncode == 0
    html = (pathlib.Path(tmp) / "report.html").read_text()
    assert "重大事件" in html and "发布要点" in html
print("smoke OK")
EOF
```

Expected: `smoke OK`

- [ ] **Step 7: Commit**

```bash
git add skills/ai-daily-report/schemas/candidate_ledger.schema.json skills/ai-daily-report/SKILL.md README.md skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: document major event tracking workflow and weekly cadence"
```

---

## Spec Coverage Check

- major_event expanded block (schema + render + deterministic gating): Tasks 1, 2, 3.
- Event tracking files + dedup exemption + finalize closure: Tasks 4, 5, 8(d SKILL.md rules).
- Tracking survives cache cleanup / expires cleanly: Tasks 5 (finalize cleanup), 6 (archive exclusion).
- Follow-up discovery on T+1..T+n (manifest exposure): Task 7.
- Weekly enablement (cadence + tracking as weekly input): Task 8 (SKILL.md + README).
- Audit trail (ledger `tracking_ref`): Task 8.

## Placeholder Scan

- No TODO/TBD markers; every code step shows complete code; every test step has exact command + expected outcome.

## Type Consistency Check

- `validate_major_event_consistency(report)` defined Task 3, wired Task 3, referenced Task 8 docs — consistent.
- `validate_daily_artifacts(report, ledger, whitelist, project_root=None)` — Task 5 signature matches Task 5 runner call and Task 3/5 tests.
- `tracking.py` exports `load_tracking_events` / `active_tracking_events` / `validate_tracking_refs` / `cleanup_expired_tracking` — used consistently in Tasks 5, 7 and tests.
- `tracking_ref` pattern `^[a-z0-9][a-z0-9-]{2,63}$` identical in daily schema (Task 1), tracking schema (Task 4), ledger schema (Task 8).
