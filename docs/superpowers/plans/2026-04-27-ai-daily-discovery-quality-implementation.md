# AI Daily Discovery Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden AI daily report discovery quality so high-signal candidates are captured, date attribution is auditable, hard-data snapshots are separated from real changes, and invalid evidence chains fail before final delivery.

**Architecture:** Keep AI search and editorial judgment outside deterministic scripts. Extend schemas and validators so `candidate_ledger.json`, `fetch_status.source_details`, market-signal refs, and action references encode the evidence contract from the approved spec. Discovery changes only update manifests, fallback targets, and prompt/whitelist guidance.

**Tech Stack:** Python 3, pytest, jsonschema, PyYAML, Jinja2 templates, existing `skills/ai-daily-report` runner.

---

## File Structure

- Modify: `skills/ai-daily-report/schemas/candidate_ledger.schema.json`
  - Add required audit fields: `event_type`, `date_basis`, `evidence_path`, `why_today`, `action_eligibility`.
- Modify: `skills/ai-daily-report/tests/fixtures/sample_candidate_ledger.json`
  - Keep the baseline fixture schema-valid after required fields are added.
- Modify: `skills/ai-daily-report/tests/test_render_html.py`
  - Add schema tests for new ledger fields.
- Modify: `skills/ai-daily-report/scripts/editorial.py`
  - Add semantic validators for ledger date/evidence/action eligibility and daily hard-data refs.
- Modify: `skills/ai-daily-report/tests/test_editorial.py`
  - Add regression tests for Help Center `page_updated_at`, unverified action ineligibility, Dirac benchmark wording, and capability gap refs.
- Modify: `skills/ai-daily-report/scripts/evidence.py`
  - Expand OpenAI fallback targets to include company/infrastructure/partnership paths.
- Modify: `skills/ai-daily-report/sources/whitelist.yaml`
  - Add high-signal company, partnership, pricing, benchmark, and regulatory queries.
- Modify: `skills/ai-daily-report/tests/test_discovery.py`
  - Assert the manifest exposes the new OpenAI fallback and media discovery queries.
- Modify: `skills/ai-daily-report/SKILL.md`
  - Sync the human/AI execution contract with validators.
- No planned change: `skills/ai-daily-report/templates/daily.html.j2`
  - New ledger audit fields are validation-only and do not need visible rendering.

Implementation should start from the clean repository state after commit `b58bd23`.

---

### Task 1: Extend Candidate Ledger Schema and Fixture

**Files:**
- Modify: `skills/ai-daily-report/schemas/candidate_ledger.schema.json`
- Modify: `skills/ai-daily-report/tests/fixtures/sample_candidate_ledger.json`
- Modify: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: Add failing schema tests for new ledger audit fields**

Append these tests to `skills/ai-daily-report/tests/test_render_html.py` after `test_candidate_ledger_invalid_decision_fails_schema`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_render_html.py::test_candidate_ledger_requires_audit_fields skills/ai-daily-report/tests/test_render_html.py::test_candidate_ledger_rejects_page_update_as_core_date_basis -q
```

Expected: first test fails because `date_basis` is not required yet; second test fails because the schema does not restrict `page_updated_at` for selected core candidates.

- [ ] **Step 3: Update the candidate ledger schema**

Edit `skills/ai-daily-report/schemas/candidate_ledger.schema.json` so `candidateRecord.required` becomes:

```json
"required": [
  "candidate_id",
  "headline",
  "proposed_section",
  "published_at",
  "source_attempt_refs",
  "verification_state",
  "editorial_tier",
  "decision",
  "decision_reason",
  "novelty_vs_yesterday",
  "event_type",
  "date_basis",
  "evidence_path",
  "why_today",
  "action_eligibility"
]
```

Add these properties inside `candidateRecord.properties`:

```json
"event_type": {
  "enum": [
    "model_release",
    "coding_release",
    "partnership",
    "pricing",
    "benchmark",
    "compliance",
    "community_signal",
    "enterprise_update",
    "research_update"
  ]
},
"date_basis": {
  "enum": [
    "official_event_date",
    "release_metadata",
    "section_date",
    "article_published_at",
    "page_updated_at",
    "community_snapshot_time",
    "inferred_from_search"
  ]
},
"evidence_path": {
  "enum": [
    "primary",
    "media_plus_official_one_hop",
    "media_only",
    "community_snapshot",
    "search_only"
  ]
},
"why_today": {"type": "string", "minLength": 1},
"action_eligibility": {"enum": ["none", "monitor", "experiment", "full_action"]}
```

Add this `allOf` array at the same level as `properties` inside `candidateRecord`:

```json
"allOf": [
  {
    "if": {
      "properties": {
        "decision": {"enum": ["selected_core", "selected_watch"]}
      },
      "required": ["decision"]
    },
    "then": {
      "not": {
        "properties": {
          "date_basis": {"const": "page_updated_at"}
        },
        "required": ["date_basis"]
      }
    }
  }
]
```

- [ ] **Step 4: Update `sample_candidate_ledger.json`**

Add these fields to the first fixture item:

```json
"event_type": "enterprise_update",
"date_basis": "official_event_date",
"evidence_path": "primary",
"why_today": "官方发布时间落在日报窗口内。",
"action_eligibility": "full_action"
```

Add these fields to the second fixture item:

```json
"event_type": "model_release",
"date_basis": "article_published_at",
"evidence_path": "media_only",
"why_today": "媒体发布时间落在日报窗口内，但没有官方确认。",
"action_eligibility": "none"
```

- [ ] **Step 5: Run schema tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_render_html.py::test_candidate_ledger_fixture_matches_schema skills/ai-daily-report/tests/test_render_html.py::test_candidate_ledger_requires_audit_fields skills/ai-daily-report/tests/test_render_html.py::test_candidate_ledger_rejects_page_update_as_core_date_basis -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/schemas/candidate_ledger.schema.json skills/ai-daily-report/tests/fixtures/sample_candidate_ledger.json skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: add candidate ledger audit fields"
```

---

### Task 2: Add Ledger Semantic Validators

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Modify: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Add failing tests for date basis and action eligibility**

Append these tests to `skills/ai-daily-report/tests/test_editorial.py` after `test_build_daily_qa_diff_classifies_duplicate_and_weak_evidence`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_page_updated_at_for_selected_candidate skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_unverified_action_eligibility skills/ai-daily-report/tests/test_editorial.py::test_build_daily_qa_diff_reports_ledger_semantic_errors -q
```

Expected: all three tests fail because the semantic validator does not exist yet.

- [ ] **Step 3: Add `validate_candidate_ledger_semantics`**

In `skills/ai-daily-report/scripts/editorial.py`, add this function after `validate_source_attempt_refs`:

```python
def validate_candidate_ledger_semantics(ledger: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for index, item in enumerate(ledger.get("items", [])):
        decision = item.get("decision")
        date_basis = item.get("date_basis")
        evidence_path = item.get("evidence_path")
        action_eligibility = item.get("action_eligibility")
        label = f"candidate_ledger.items[{index}] {item.get('headline', '')!r}"

        if decision in {"selected_core", "selected_watch"} and date_basis == "page_updated_at":
            errors.append(f"{label} date_basis='page_updated_at' cannot support {decision}")
        if decision == "selected_core" and evidence_path != "primary":
            errors.append(f"{label} selected_core requires evidence_path='primary'")
        if decision == "selected_unverified" and action_eligibility != "none":
            errors.append(f"{label} selected_unverified must have action_eligibility='none'")
        if evidence_path in {"media_only", "community_snapshot", "search_only"} and action_eligibility == "full_action":
            errors.append(f"{label} evidence_path={evidence_path!r} cannot have action_eligibility='full_action'")
    return errors
```

- [ ] **Step 4: Wire the validator into daily validation and QA**

In `validate_daily_artifacts`, add:

```python
    errors.extend(validate_candidate_ledger_semantics(ledger))
```

directly after `validate_source_attempt_refs(report, ledger)`.

In `build_daily_qa_diff`, add:

```python
    reference_errors.extend(validate_candidate_ledger_semantics(ledger))
```

directly after `validate_source_attempt_refs(report, ledger)`.

- [ ] **Step 5: Run semantic validator tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_page_updated_at_for_selected_candidate skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_unverified_action_eligibility skills/ai-daily-report/tests/test_editorial.py::test_build_daily_qa_diff_reports_ledger_semantic_errors -q
```

Expected: all selected tests pass.

- [ ] **Step 6: Run existing editorial tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py -q
```

Expected: all editorial tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: validate candidate ledger semantics"
```

---

### Task 3: Validate Daily Market Signal References

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Modify: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Add failing tests for hard-data ref closure**

Append these tests to `skills/ai-daily-report/tests/test_editorial.py` after the Task 2 tests:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_capability_gap_without_ref skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_market_signal_ref_out_of_range -q
```

Expected: both tests fail because daily market-signal refs are not validated yet.

- [ ] **Step 3: Add daily item-ref helpers**

In `skills/ai-daily-report/scripts/editorial.py`, add these helpers before `validate_market_signals_consistency`:

```python
def _daily_item_counts(report: dict[str, Any]) -> dict[str, int]:
    sections = report.get("sections", {})
    return {
        "frontier_models": len(sections.get("frontier_models", {}).get("items", [])),
        "coding_agents": len(sections.get("coding_agents", {}).get("items", [])),
        "general_agents": len(sections.get("general_agents", {}).get("items", [])),
    }


def _validate_item_ref(label: str, ref: str, counts: dict[str, int]) -> list[str]:
    match = ITEM_REF_PATTERN.match(ref or "")
    if not match:
        return [f"{label} has invalid itemRef {ref!r}"]
    section_name = match.group("section")
    item_index = int(match.group("index"))
    if item_index >= counts[section_name]:
        return [f"{label} points past {section_name}[{item_index}]"]
    return []


def validate_daily_market_signal_refs(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    counts = _daily_item_counts(report)
    market_signals = report.get("sections", {}).get("market_signals", {})

    for index, item in enumerate(market_signals.get("benchmark_watch", [])):
        ref = item.get("ref")
        if ref:
            errors.extend(_validate_item_ref(f"benchmark_watch[{index}].ref", ref, counts))

    for index, item in enumerate(market_signals.get("capability_gaps", [])):
        ref = item.get("ref")
        text = _join_text([item.get("text", ""), item.get("evidence", "")])
        if ref:
            errors.extend(_validate_item_ref(f"capability_gaps[{index}].ref", ref, counts))
            continue
        if _has_hard_data_signal({"text": text}, ("text",)):
            has_market_bucket = bool(
                market_signals.get("benchmark_changes")
                or market_signals.get("benchmark_watch")
                or market_signals.get("pricing_changes")
            )
            if not has_market_bucket:
                errors.append(f"capability_gaps[{index}] has hard-data language but no ref")
    return errors
```

- [ ] **Step 4: Wire the validator into daily validation and QA**

In `validate_daily_artifacts`, add:

```python
    errors.extend(validate_daily_market_signal_refs(report))
```

directly before `validate_market_signals_consistency(report, "daily")`.

In `build_daily_qa_diff`, add:

```python
    reference_errors.extend(validate_daily_market_signal_refs(report))
```

directly before `validate_source_closure(report, ledger)`.

- [ ] **Step 5: Run market-signal tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_capability_gap_without_ref skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_market_signal_ref_out_of_range -q
```

Expected: both selected tests pass.

- [ ] **Step 6: Run editorial tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py -q
```

Expected: all editorial tests pass.

- [ ] **Step 7: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: validate daily market signal refs"
```

---

### Task 4: Expand Discovery Fallbacks and High-Signal Queries

**Files:**
- Modify: `skills/ai-daily-report/scripts/evidence.py`
- Modify: `skills/ai-daily-report/sources/whitelist.yaml`
- Modify: `skills/ai-daily-report/tests/test_discovery.py`

- [ ] **Step 1: Add failing discovery tests**

Modify `test_build_discovery_manifest_includes_openai_fallback_and_queries` in `skills/ai-daily-report/tests/test_discovery.py` to include these assertions:

```python
    assert "https://openai.com/index/" in openai["one_hop_fallback_targets"]
    assert "https://openai.com/index/?topic=company" in openai["one_hop_fallback_targets"]
    assert any("OpenAI Microsoft partnership" in query for query in manifest["high_signal_media_queries"])
    assert any("AI acquisition regulation" in query for query in manifest["high_signal_media_queries"])
```

- [ ] **Step 2: Run the discovery test and verify it fails**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_discovery.py::test_build_discovery_manifest_includes_openai_fallback_and_queries -q
```

Expected: FAIL because company fallback and high-signal queries are not present yet.

- [ ] **Step 3: Expand OpenAI fallback targets**

In `skills/ai-daily-report/scripts/evidence.py`, update `OPENAI_FALLBACK_TARGETS["OpenAI"]` to:

```python
"OpenAI": [
    "https://openai.com/index/",
    "https://openai.com/index/?topic=company",
    "https://openai.com/news/product/",
    "https://openai.com/business/",
    "https://openai.com/sitemap.xml",
    "https://openai.com/rss.xml",
    "site:openai.com Microsoft partnership OpenAI {date}",
    "site:openai.com OpenAI cloud partnership {date}",
],
```

- [ ] **Step 4: Add high-signal media queries**

In `skills/ai-daily-report/sources/whitelist.yaml`, extend `high_signal_media_queries` with:

```yaml
  - "OpenAI Microsoft partnership {date}"
  - "OpenAI cloud infrastructure partnership {date}"
  - "AI acquisition regulation {date}"
  - "AI agent acquisition blocked regulator {date}"
  - "AI benchmark leaderboard Terminal-Bench {date}"
  - "GitHub Trending skills AI agent {date}"
```

- [ ] **Step 5: Run discovery tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_discovery.py skills/ai-daily-report/tests/test_evidence.py -q
```

Expected: all selected discovery and evidence tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/scripts/evidence.py skills/ai-daily-report/sources/whitelist.yaml skills/ai-daily-report/tests/test_discovery.py
git commit -m "feat: expand daily discovery signals"
```

---

### Task 5: Sync Skill Guidance With New Evidence Contract

**Files:**
- Modify: `skills/ai-daily-report/SKILL.md`

- [ ] **Step 1: Add guidance text for high-signal official/company actions**

In `skills/ai-daily-report/SKILL.md`, under the existing whitelist role and evidence expansion sections, add:

```markdown
   - **高信号官方 / 公司动作补漏**
     - 对 OpenAI、Anthropic、Google、Microsoft、Meta、DeepMind 等源，不只查模型发布，也要查 partnership / infrastructure / cloud / enterprise / pricing / compliance / benchmark 这类公司级信号。
     - 若官方入口 403 或空壳，但媒体或搜索结果指向明确官方页面、合作方公告或监管页面，应沿同一实体一跳补证，并把媒体面和补证面都写入 `source_details` 与 `candidate_ledger.source_attempt_refs`。
     - 这类候选进入正文时默认最多 `watch`，除非直接官方页面给出清楚日期与事实链。
```

- [ ] **Step 2: Add guidance text for ledger audit fields**

In `skills/ai-daily-report/SKILL.md`, under “候选台账要求”, add:

```markdown
     - 每条候选还必须记录 `event_type`、`date_basis`、`evidence_path`、`why_today`、`action_eligibility`。
     - `page_updated_at` 不能单独作为 `selected_core` 或 `selected_watch` 的日期依据；Help Center / release notes / changelog / docs 页面必须优先取小节日期、release metadata 或正文明确事件日期。
     - `media_only`、`community_snapshot`、`search_only` 与 `selected_unverified` 不能驱动 action；`media_plus_official_one_hop` 只能驱动 monitor / experiment。
```

- [ ] **Step 3: Add guidance text for hard-data layering**

In `skills/ai-daily-report/SKILL.md`, under “抓取并解析硬数据”, add:

```markdown
   - `benchmark_changes` 只写有前后基线的真实变化；没有 old/new 或 rank delta 时，不得写“上升、下降、扩大领先、超越”等变化性措辞。
   - `benchmark_watch` 写新评分、新上榜、当天快照或缺稳定基线的榜单观察，必须有 `observed_at` 与 source。
   - `capability_gaps` 是解释层；涉及 benchmark / leaderboard / score / pricing 时，必须引用 `benchmark_changes`、`benchmark_watch`、`pricing_changes` 或正文 item ref。
```

- [ ] **Step 4: Verify no formatting issues**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/SKILL.md
git commit -m "docs: clarify daily evidence contract"
```

---

### Task 6: Add 2026-04-27 Regression Fixture Tests

**Files:**
- Modify: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Add helper builders for 2026-04-27 regressions**

Add these helper functions near the top of `skills/ai-daily-report/tests/test_editorial.py`, after imports:

```python
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
    report["sections"]["general_agents"]["items"] = []
    report["sections"]["unverified"]["items"] = []
    report["sections"]["action_items"]["items"] = []
    report["sections"]["market_signals"]["benchmark_changes"] = []
    report["sections"]["market_signals"]["benchmark_watch"] = []
    report["sections"]["market_signals"]["pricing_changes"] = []
    report["sections"]["market_signals"]["capability_gaps"] = []
    return report
```

- [ ] **Step 2: Add OpenAI-Microsoft positive regression**

Append this test:

```python
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
```

- [ ] **Step 3: Add Help Center negative regression**

Append this test:

```python
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
```

- [ ] **Step 4: Add Dirac benchmark regression**

Append this test:

```python
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
            "hard_data_note": "只有社区快照，缺少稳定前一日基线，不写成今日登顶。",
        }
    ]
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
            "action_eligibility": "experiment",
        }
    ]

    errors = validate_daily_artifacts(report, ledger, whitelist)

    assert errors == []
```

- [ ] **Step 5: Run regression tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_2026_04_27_openai_microsoft_partnership_can_be_selected skills/ai-daily-report/tests/test_editorial.py::test_2026_04_27_help_center_page_update_cannot_select_window_out_item skills/ai-daily-report/tests/test_editorial.py::test_2026_04_27_dirac_benchmark_without_delta_needs_watch_ref -q
```

Expected: all selected regression tests pass.

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/tests/test_editorial.py
git commit -m "test: cover ai daily discovery regressions"
```

---

### Task 7: Full Verification and Representative Dry Run

**Files:**
- No planned source modifications unless verification exposes a bug.

- [ ] **Step 1: Run full skill test suite**

Run:

```bash
python -m pytest skills/ai-daily-report/tests -q
```

Expected: all tests pass.

- [ ] **Step 2: Run diff whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 3: Run a representative daily finalize dry-run with existing 2026-04-27 artifacts**

Run:

```bash
python skills/ai-daily-report/scripts/report_runner.py finalize-daily --date 2026-04-27 --env .env --dry-run
```

Expected: if existing `cache/2026-04-27/candidate_ledger.json` has not yet been migrated to the new required audit fields, this should fail with schema or validator errors. That is acceptable and confirms the new gate is active.

- [ ] **Step 4: If dry-run fails only because old local artifacts predate the new schema, record the expected migration note**

Add no code. Record the exact failure in the implementation summary:

```text
Existing cache/2026-04-27 artifacts predate the new candidate_ledger audit fields. New reports must rebuild report.json and candidate_ledger.json before finalize. This is expected after the schema hardening.
```

- [ ] **Step 5: If dry-run fails for a source-code bug, fix the bug with a focused test**

Only use this step if the failure is not old-artifact schema drift. Add a failing test that reproduces the bug, implement the minimal fix, and rerun:

```bash
python -m pytest skills/ai-daily-report/tests -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit any verification-only fix**

If Step 5 changed files, run:

```bash
git add skills/ai-daily-report
git commit -m "fix: align daily discovery quality validation"
```

If Step 5 changed no files, do not create an empty commit.

---

### Task 8: Final Implementation Summary

**Files:**
- No source modifications.

- [ ] **Step 1: Capture final git status**

Run:

```bash
git status --short
```

Expected: clean worktree, or only intentionally generated report artifacts if the implementer reran a full daily generation.

- [ ] **Step 2: Capture recent commits**

Run:

```bash
git log --oneline -8
```

Expected: includes commits from Tasks 1-6 and any Task 7 fix commit.

- [ ] **Step 3: Report verification results**

Final response should include:

```text
Implemented the AI daily discovery quality hardening plan.

Key changes:
- Candidate ledger now records event_type/date_basis/evidence_path/why_today/action_eligibility.
- Daily validators reject page_updated_at as selected evidence, unverified action eligibility, unresolved market-signal refs, and hard-data capability gaps without backing refs.
- Discovery guidance now includes company/partnership/infrastructure/regulatory signals.
- Regression tests cover OpenAI-Microsoft, Help Center page update misattribution, and Dirac benchmark watch handling.

Verification:
- python -m pytest skills/ai-daily-report/tests -q: passed
- git diff --check: passed
- finalize-daily --dry-run for 2026-04-27: failed as expected because existing cache artifacts predate the new candidate_ledger audit fields
```
