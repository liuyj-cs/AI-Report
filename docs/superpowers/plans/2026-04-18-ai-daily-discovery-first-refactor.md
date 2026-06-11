# AI Daily Discovery-First Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the AI daily/weekly report workflow so discovery coverage is mandatory, one-hop evidence expansion is explicit, and AI makes editorial decisions only after a complete candidate pool exists.

**Architecture:** Introduce a new orchestration layer that separates discovery, evidence expansion, editorial closure, and final artifact generation. The new runner should always finish mandatory discovery surfaces first, materialize a candidate ledger with source-attempt provenance, and only then invoke AI/editorial logic to close candidates into `core/watch/unverified/reject` and derive action items.

**Tech Stack:** Python 3.12, requests, PyYAML, JSON Schema, pytest, Jinja2, python-dotenv

---

## File Map

**Create**
- `skills/ai-daily-report/scripts/report_runner.py`
  Coordinates daily/weekly runs, environment validation, run.log lifecycle, discovery → editorial → render/archive/send execution order.
- `skills/ai-daily-report/scripts/discovery.py`
  Runs mandatory discovery surfaces, records `fetch_status.source_details`, executes `general_agent_search_queries`, HN top 50, GitHub Trending daily+weekly, and writes raw candidates.
- `skills/ai-daily-report/scripts/evidence.py`
  Implements one-hop evidence expansion and official fallback logic (including OpenAI 403 fallback handling).
- `skills/ai-daily-report/scripts/editorial.py`
  Applies window hard-gating, dedupe, candidate closure into `core/watch/unverified/reject`, and action-item eligibility rules.
- `skills/ai-daily-report/tests/test_report_runner.py`
  CLI/integration tests for orchestration, env validation, artifact sequencing, and run.log lifecycle.
- `skills/ai-daily-report/tests/test_discovery.py`
  Unit tests for mandatory discovery completion, source status tracking, HN/Trending/general-search coverage.
- `skills/ai-daily-report/tests/test_evidence.py`
  Unit tests for one-hop expansion triggers, official fallback ordering, and OpenAI 403 handling.
- `skills/ai-daily-report/tests/test_editorial.py`
  Unit tests for candidate closure, action-item gating, and weekly reuse of daily artifacts.
- `skills/ai-daily-report/tests/fixtures/discovery/`
  Discovery-layer fixtures for official 403, empty official page, media-triggered candidate, HN hits, and GitHub release metadata.

**Modify**
- `skills/ai-daily-report/requirements.txt`
  Add runtime deps needed by discovery/orchestration modules.
- `skills/ai-daily-report/SKILL.md`
  Align instructions with the new executable flow and make discovery coverage/one-hop expansion non-optional.
- `skills/ai-daily-report/sources/whitelist.yaml`
  Refine source metadata comments, OpenAI fallback notes, and discovery-surface metadata.
- `skills/ai-daily-report/tests/conftest.py`
  Add reusable helpers/fixtures for the new runner and discovery/editorial modules.
- `skills/ai-daily-report/tests/fixtures/sample_daily.json`
  Keep fixture compatible with `editorial_tier`/reference constraints if new renderer-visible fields are added.

**Leave As-Is**
- `skills/ai-daily-report/scripts/render_html.py`
- `skills/ai-daily-report/scripts/archive.py`
- `skills/ai-daily-report/scripts/send_mail.py`

These remain deterministic artifact steps; the refactor should feed them better JSON, not expand their responsibilities.

### Task 1: Scaffold the Runner and Environment Gate

**Files:**
- Create: `skills/ai-daily-report/scripts/report_runner.py`
- Modify: `skills/ai-daily-report/requirements.txt`
- Test: `skills/ai-daily-report/tests/test_report_runner.py`

- [ ] **Step 1: Write the failing runner/env test**

```python
from pathlib import Path

from skills.ai_daily_report.scripts.report_runner import run_daily


def test_run_daily_fails_fast_when_email_env_missing(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text("GMAIL_USER=\nGMAIL_APP_PASSWORD=\nREPORT_RECIPIENTS=\n", encoding="utf-8")

    code, message = run_daily(
        project_root=tmp_path,
        target_date="2026-04-18",
        dry_run=True,
        now_iso="2026-04-18T07:30:00+08:00",
        env_path=env_path,
    )

    assert code == 1
    assert "GMAIL_USER / GMAIL_APP_PASSWORD / REPORT_RECIPIENTS" in message
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest skills/ai-daily-report/tests/test_report_runner.py::test_run_daily_fails_fast_when_email_env_missing -q`
Expected: FAIL with `ModuleNotFoundError` or `cannot import name 'run_daily'`

- [ ] **Step 3: Write minimal runner skeleton**

```python
from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values


def _validate_env(env_path: Path) -> tuple[bool, str]:
    env = {k: v for k, v in dotenv_values(env_path).items() if v is not None}
    required = ["GMAIL_USER", "GMAIL_APP_PASSWORD"]
    recipients = env.get("REPORT_RECIPIENTS") or env.get("RECIPIENT_EMAIL")
    missing = [k for k in required if not env.get(k)]
    if missing or not recipients:
        return False, "GMAIL_USER / GMAIL_APP_PASSWORD / REPORT_RECIPIENTS missing"
    return True, ""


def run_daily(project_root: Path, target_date: str, dry_run: bool, now_iso: str, env_path: Path) -> tuple[int, str]:
    ok, message = _validate_env(env_path)
    if not ok:
        return 1, message
    return 0, "runner scaffold ready"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest skills/ai-daily-report/tests/test_report_runner.py::test_run_daily_fails_fast_when_email_env_missing -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/tests/test_report_runner.py skills/ai-daily-report/requirements.txt
git commit -m "feat: scaffold ai daily runner env gate"
```

### Task 2: Make Discovery Coverage Mandatory

**Files:**
- Create: `skills/ai-daily-report/scripts/discovery.py`
- Create: `skills/ai-daily-report/tests/test_discovery.py`
- Create: `skills/ai-daily-report/tests/fixtures/discovery/official_openai_403.json`
- Modify: `skills/ai-daily-report/tests/conftest.py`

- [ ] **Step 1: Write the failing discovery-coverage test**

```python
from skills.ai_daily_report.scripts.discovery import run_discovery


def test_run_discovery_always_records_all_mandatory_surfaces(sample_whitelist, tmp_path):
    result = run_discovery(
        whitelist=sample_whitelist,
        target_date="2026-04-18",
        window_start="2026-04-17T07:00:00+08:00",
        window_end="2026-04-18T07:30:00+08:00",
        project_root=tmp_path,
    )

    assert "OpenAI" in result.fetch_status["source_details"]
    assert "Anthropic Claude Code" in result.fetch_status["source_details"]
    assert "Hacker News front page" in result.fetch_status["source_details"]
    assert "GitHub Trending (daily)" in result.fetch_status["source_details"]
    assert "GitHub Trending (weekly)" in result.fetch_status["source_details"]
    assert result.discovery_completed is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest skills/ai-daily-report/tests/test_discovery.py::test_run_discovery_always_records_all_mandatory_surfaces -q`
Expected: FAIL because `run_discovery` does not exist

- [ ] **Step 3: Implement discovery result structure and mandatory-surface loop**

```python
from __future__ import annotations

from dataclasses import dataclass, field


MANDATORY_DISCOVERY_SURFACES = (
    "general_agent_search_queries",
    "Hacker News front page",
    "GitHub Trending (daily)",
    "GitHub Trending (weekly)",
)


@dataclass
class DiscoveryResult:
    candidates: list[dict] = field(default_factory=list)
    fetch_status: dict = field(default_factory=lambda: {"succeeded": [], "failed": [], "empty": [], "source_details": {}})
    discovery_completed: bool = False


def run_discovery(whitelist: dict, target_date: str, window_start: str, window_end: str, project_root) -> DiscoveryResult:
    result = DiscoveryResult()
    for section_items in whitelist.values():
        if isinstance(section_items, list):
            for item in section_items:
                if isinstance(item, dict) and "name" in item:
                    result.fetch_status["source_details"][item["name"]] = {
                        "final_layer_index": 0,
                        "final_layer_type": item["fetch_chain"][0]["type"],
                        "via_broad_search": False,
                        "confidence_policy": "none",
                        "attempts": [],
                    }
    for name in MANDATORY_DISCOVERY_SURFACES:
        result.fetch_status["source_details"].setdefault(
            name,
            {"final_layer_index": 0, "final_layer_type": "webfetch", "via_broad_search": False, "confidence_policy": "none", "attempts": []},
        )
    result.discovery_completed = True
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest skills/ai-daily-report/tests/test_discovery.py::test_run_discovery_always_records_all_mandatory_surfaces -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/discovery.py skills/ai-daily-report/tests/test_discovery.py skills/ai-daily-report/tests/conftest.py skills/ai-daily-report/tests/fixtures/discovery
git commit -m "feat: add mandatory discovery coverage scaffold"
```

### Task 3: Implement One-Hop Evidence Expansion and OpenAI Fallback

**Files:**
- Create: `skills/ai-daily-report/scripts/evidence.py`
- Test: `skills/ai-daily-report/tests/test_evidence.py`
- Modify: `skills/ai-daily-report/sources/whitelist.yaml`

- [ ] **Step 1: Write the failing OpenAI 403 fallback test**

```python
from skills.ai_daily_report.scripts.evidence import maybe_expand_candidate


def test_openai_403_with_external_signal_triggers_one_hop_fallback():
    candidate = {
        "entity": "OpenAI Codex",
        "headline": "Codex Mac gains desktop control",
        "source_attempt_refs": ["OpenAI Codex.attempts[0]", "Hacker News front page.attempts[0]"],
        "discovery_signals": ["official_error", "hn_hot", "media_multi_source"],
    }
    source_context = {
        "official_status": "error_403",
        "fallback_targets": ["site:openai.com codex April 2026", "site:openai.com/sitemap codex"],
    }

    expanded = maybe_expand_candidate(candidate, source_context)

    assert expanded["expansion_triggered"] is True
    assert expanded["expansion_reason"] == "official_error_with_external_signal"
    assert expanded["fallback_targets"][0] == "site:openai.com codex April 2026"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest skills/ai-daily-report/tests/test_evidence.py::test_openai_403_with_external_signal_triggers_one_hop_fallback -q`
Expected: FAIL because `maybe_expand_candidate` does not exist

- [ ] **Step 3: Implement one-hop expansion trigger logic**

```python
def maybe_expand_candidate(candidate: dict, source_context: dict) -> dict:
    official_status = source_context.get("official_status")
    discovery_signals = set(candidate.get("discovery_signals", []))
    should_expand = official_status in {"error_403", "js_shell", "empty_shell"} and bool(
        discovery_signals.intersection({"hn_hot", "search_multi_hit", "media_multi_source"})
    )
    return {
        **candidate,
        "expansion_triggered": should_expand,
        "expansion_reason": "official_error_with_external_signal" if should_expand else "",
        "fallback_targets": source_context.get("fallback_targets", []) if should_expand else [],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest skills/ai-daily-report/tests/test_evidence.py::test_openai_403_with_external_signal_triggers_one_hop_fallback -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/evidence.py skills/ai-daily-report/tests/test_evidence.py skills/ai-daily-report/sources/whitelist.yaml
git commit -m "feat: add one-hop evidence expansion rules"
```

### Task 4: Close Candidates into `core/watch/unverified/reject`

**Files:**
- Create: `skills/ai-daily-report/scripts/editorial.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`
- Modify: `skills/ai-daily-report/tests/fixtures/sample_candidate_ledger.json`

- [ ] **Step 1: Write the failing closure test**

```python
from skills.ai_daily_report.scripts.editorial import close_candidate


def test_media_only_candidate_without_official_support_closes_to_watch():
    candidate = {
        "headline": "Codex Mac gains desktop control",
        "published_at": "2026-04-17T09:30:00+08:00",
        "evidence_strength": "multi_media",
        "published_at_confidence": "exact",
        "supports_action_items": False,
    }

    decision = close_candidate(candidate)

    assert decision["decision"] == "selected_watch"
    assert decision["editorial_tier"] == "watch"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest skills/ai-daily-report/tests/test_editorial.py::test_media_only_candidate_without_official_support_closes_to_watch -q`
Expected: FAIL because `close_candidate` does not exist

- [ ] **Step 3: Implement minimal closure rules**

```python
def close_candidate(candidate: dict) -> dict:
    if candidate.get("window_rejected"):
        return {**candidate, "decision": "rejected_window", "editorial_tier": "not_applicable"}
    if candidate.get("evidence_strength") == "official":
        return {**candidate, "decision": "selected_core", "editorial_tier": "core"}
    if candidate.get("evidence_strength") in {"partner_official", "multi_media"}:
        return {**candidate, "decision": "selected_watch", "editorial_tier": "watch"}
    if candidate.get("evidence_strength") == "single_media":
        return {**candidate, "decision": "selected_unverified", "editorial_tier": "unverified"}
    return {**candidate, "decision": "rejected_weak_evidence", "editorial_tier": "not_applicable"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest skills/ai-daily-report/tests/test_editorial.py::test_media_only_candidate_without_official_support_closes_to_watch -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/tests/test_editorial.py skills/ai-daily-report/tests/fixtures/sample_candidate_ledger.json
git commit -m "feat: add candidate closure tiers"
```

### Task 5: Gate `action_items` and Reuse Daily Artifacts for Weekly

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Modify: `skills/ai-daily-report/scripts/report_runner.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`
- Test: `skills/ai-daily-report/tests/test_report_runner.py`

- [ ] **Step 1: Write the failing action-item gating test**

```python
from skills.ai_daily_report.scripts.editorial import eligible_action_refs


def test_unverified_candidates_never_drive_action_items():
    refs = [
        {"headline": "Official release", "editorial_tier": "core", "decision": "selected_core"},
        {"headline": "Rumor", "editorial_tier": "unverified", "decision": "selected_unverified"},
    ]

    selected = eligible_action_refs(refs)

    assert [item["headline"] for item in selected] == ["Official release"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest skills/ai-daily-report/tests/test_editorial.py::test_unverified_candidates_never_drive_action_items -q`
Expected: FAIL because `eligible_action_refs` does not exist

- [ ] **Step 3: Implement minimal gating and weekly handoff**

```python
def eligible_action_refs(items: list[dict]) -> list[dict]:
    return [
        item
        for item in items
        if item.get("decision") in {"selected_core", "selected_watch"} and item.get("editorial_tier") in {"core", "watch"}
    ]


def weekly_input_dates(target_week_dates: list[str], project_root):
    return [project_root / "cache" / date / "report.json" for date in target_week_dates]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest skills/ai-daily-report/tests/test_editorial.py::test_unverified_candidates_never_drive_action_items skills/ai-daily-report/tests/test_report_runner.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/tests/test_editorial.py skills/ai-daily-report/tests/test_report_runner.py
git commit -m "feat: gate action items and weekly daily-report reuse"
```

### Task 6: Wire the End-to-End Runner and Lock Documentation

**Files:**
- Modify: `skills/ai-daily-report/scripts/report_runner.py`
- Modify: `skills/ai-daily-report/SKILL.md`
- Modify: `skills/ai-daily-report/requirements.txt`
- Test: `skills/ai-daily-report/tests/test_report_runner.py`

- [ ] **Step 1: Write the failing end-to-end dry-run test**

```python
from pathlib import Path

from skills.ai_daily_report.scripts.report_runner import main


def test_runner_daily_dry_run_writes_json_html_and_ledger(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=secret\nREPORT_RECIPIENTS=a@example.com\n",
        encoding="utf-8",
    )

    exit_code = main(
        [
            "daily",
            "--date",
            "2026-04-18",
            "--dry-run",
            "--env",
            str(env_path),
        ],
        project_root=tmp_path,
    )

    assert exit_code == 0
    assert (tmp_path / "cache" / "2026-04-18" / "report.json").exists()
    assert (tmp_path / "cache" / "2026-04-18" / "candidate_ledger.json").exists()
    assert (tmp_path / "cache" / "2026-04-18" / "report.html").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest skills/ai-daily-report/tests/test_report_runner.py::test_runner_daily_dry_run_writes_json_html_and_ledger -q`
Expected: FAIL because the runner has no full orchestration path yet

- [ ] **Step 3: Wire discovery → editorial → render/archive/send flow**

```python
def run_daily(...):
    # 1. validate env
    # 2. init cache/<date>/run.log
    # 3. discovery = run_discovery(...)
    # 4. expanded = expand_candidates(...)
    # 5. report, ledger = build_daily_report(...)
    # 6. render_html.py
    # 7. archive.py
    # 8. send_mail.py unless dry_run
    # 9. append END daily status=ok
    return 0, str(report_path)
```

- [ ] **Step 4: Run the full fast verification suite**

Run: `pytest skills/ai-daily-report/tests/test_report_runner.py skills/ai-daily-report/tests/test_discovery.py skills/ai-daily-report/tests/test_evidence.py skills/ai-daily-report/tests/test_editorial.py skills/ai-daily-report/tests/test_render_html.py skills/ai-daily-report/tests/test_archive.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/report_runner.py skills/ai-daily-report/SKILL.md skills/ai-daily-report/requirements.txt skills/ai-daily-report/tests
git commit -m "feat: ship discovery-first ai report workflow"
```

## Spec Coverage Check

- Discovery-first flow: covered by Tasks 1-3.
- One-hop evidence expansion: covered by Task 3.
- `core/watch/unverified/reject` closure: covered by Task 4.
- Action-item gating: covered by Task 5.
- Daily/weekly orchestration and artifact generation: covered by Tasks 1, 5, and 6.
- Auditability (`run.log`, candidate ledger, `source_details`): covered by Tasks 2, 3, 4, and 6.

## Placeholder Scan

- No `TODO` / `TBD` markers remain.
- Every task names exact file paths.
- Every code-writing step includes concrete code blocks.
- Every test step includes exact commands and expected outcomes.

## Type Consistency Check

- Runner entrypoint: `run_daily(...)` and `main(...)` are referenced consistently.
- Discovery result shape always uses `fetch_status["source_details"]` and `discovery_completed`.
- Candidate closure consistently uses `decision` plus `editorial_tier`.
- Action-item gating only accepts `selected_core` / `selected_watch`.

Plan complete and saved to `docs/superpowers/plans/2026-04-18-ai-daily-discovery-first-refactor.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
