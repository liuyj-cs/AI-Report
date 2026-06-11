# AIReport Discovery Recall Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Codex AI daily report recall so high-value in-window signals like Cursor SDK, DeepSeek vision, Zed 1.0, and Microsoft Copilot adoption are discovered, classified, rendered, and audited without weakening evidence gates.

**Architecture:** Keep search and editorial judgment in the AI agent. The repository remains a deterministic workflow layer: it exposes required discovery surfaces, validates that attempts were recorded, validates evidence/action eligibility, renders supported market-signal buckets, and blocks reports whose structured artifacts cannot explain their claims.

**Tech Stack:** Python 3, pytest, jsonschema Draft 2020-12, Jinja2, YAML source manifest, existing `skills/ai-daily-report` runner.

---

## Scope

This plan is based on the 2026-04-30 Codex vs ClaudeCode comparison:

- Codex missed Cursor TypeScript SDK, Zed 1.0, DeepSeek vision beta, and Microsoft 365 Copilot paid-seat adoption.
- Codex had stronger artifacts: `candidate_ledger.json`, `qa_diff.json`, strict `fetch_status.source_details`, and source-attempt refs.
- The improvement target is "Claude-level recall with Codex-level auditability".

Non-goals:

- Do not add a local search provider, API key, crawler, or backend.
- Do not hardcode specific daily facts into runtime logic.
- Do not replace AI editorial judgment with fixed Top N, vendor priority, or static scoring.

## File Structure

- `skills/ai-daily-report/sources/whitelist.yaml`
  - Source and query contract for the AI agent.
  - Add Cursor blog/SDK surfaces, Zed, Microsoft 365 Copilot adoption, DeepSeek vision queries, and recall probe queries.

- `skills/ai-daily-report/scripts/discovery.py`
  - Deterministic manifest and fetch-status skeleton builder.
  - Add a named high-recall probe surface so finalize can detect whether the AI agent skipped the independent recall pass.

- `skills/ai-daily-report/scripts/editorial.py`
  - Deterministic validators and QA diff builder.
  - Add adoption-signal validation, adoption hard-data keyword detection, and ref validation.

- `skills/ai-daily-report/schemas/daily_report.schema.json`
  - Add `market_signals.adoption_signals`.

- `skills/ai-daily-report/schemas/weekly_report.schema.json`
  - Add the same `market_signals.adoption_signals` contract so daily and weekly schemas stay aligned.

- `skills/ai-daily-report/templates/daily.html.j2`
  - Render adoption signals inside the market signals block.

- `skills/ai-daily-report/templates/weekly.html.j2`
  - Render adoption signals inside the weekly market signals block.

- `skills/ai-daily-report/tests/test_discovery.py`
  - Unit tests for recall sources and manifest surfaces.

- `skills/ai-daily-report/tests/test_editorial.py`
  - Unit tests for adoption-signal validation and recall-surface QA.

- `skills/ai-daily-report/tests/test_render_html.py`
  - Rendering tests for adoption signals.

- `skills/ai-daily-report/tests/fixtures/sample_daily.json`
  - Add `adoption_signals` example.

- `skills/ai-daily-report/tests/fixtures/sample_daily_empty.json`
  - Add empty `adoption_signals`.

- `skills/ai-daily-report/tests/fixtures/sample_weekly.json`
  - Add `adoption_signals` example.

- `skills/ai-daily-report/SKILL.md`
  - Update workflow wording so future runs treat recall probes as required editorial work, not optional decoration.

---

### Task 1: Add High-Recall Discovery Surfaces

**Files:**
- Modify: `skills/ai-daily-report/sources/whitelist.yaml`
- Modify: `skills/ai-daily-report/scripts/discovery.py`
- Test: `skills/ai-daily-report/tests/test_discovery.py`

- [ ] **Step 1: Write failing discovery tests**

Append these tests to `skills/ai-daily-report/tests/test_discovery.py`:

```python
def test_cursor_source_checks_blog_before_changelog_and_sdk_queries(sample_whitelist):
    cursor = next(
        item
        for item in sample_whitelist["coding_agents_secondary"]
        if item["name"] == "Cursor"
    )

    assert cursor["fetch_chain"][0] == {
        "type": "webfetch",
        "url": "https://cursor.com/blog",
    }
    assert cursor["fetch_chain"][1] == {
        "type": "webfetch",
        "url": "https://www.cursor.com/changelog",
    }
    scoped_queries = cursor["fetch_chain"][2]["queries"]
    broad_queries = cursor["fetch_chain"][3]["queries"]
    assert "Cursor SDK site:cursor.com/blog {date}" in scoped_queries
    assert "@cursor/sdk public beta {date}" in broad_queries


def test_whitelist_contains_deepseek_vision_zed_and_adoption_surfaces(sample_whitelist):
    deepseek = next(item for item in sample_whitelist["cn_labs"] if item["name"] == "DeepSeek")
    assert "DeepSeek vision multimodal {date}" in deepseek["fetch_chain"][2]["queries"]
    assert "DeepSeek image recognition beta {date}" in deepseek["fetch_chain"][2]["queries"]

    watchlist_names = {item["name"] for item in sample_whitelist["general_agent_watchlist"]}
    assert "Zed" in watchlist_names
    assert "Microsoft 365 Copilot Adoption" in watchlist_names

    assert "AI-native editor agent protocol {date}" in sample_whitelist["general_agent_search_queries"]
    assert "Microsoft 365 Copilot paid seats earnings call {date}" in sample_whitelist["high_signal_media_queries"]
    assert "Cursor SDK @cursor/sdk public beta {date}" in sample_whitelist["recall_probe_queries"]
    assert "Zed 1.0 AI-native editor Agent Client Protocol {date}" in sample_whitelist["recall_probe_queries"]
    assert "DeepSeek vision multimodal beta {date}" in sample_whitelist["recall_probe_queries"]
    assert "Microsoft 365 Copilot paid seats weekly engagement {date}" in sample_whitelist["recall_probe_queries"]


def test_build_discovery_manifest_includes_recall_probe_surface(sample_whitelist):
    from discovery import RECALL_PROBE_SURFACE_NAME

    window = compute_daily_window("2026-04-30", "2026-04-30T07:30:00+08:00")
    manifest = build_discovery_manifest("2026-04-30", window, sample_whitelist)

    assert RECALL_PROBE_SURFACE_NAME in manifest["required_discovery_surfaces"]
    assert manifest["recall_probe_queries"] == sample_whitelist["recall_probe_queries"]


def test_initial_fetch_status_contains_recall_probe_surface(sample_whitelist):
    from discovery import RECALL_PROBE_SURFACE_NAME

    result = initial_fetch_status(sample_whitelist)
    detail = result["source_details"][RECALL_PROBE_SURFACE_NAME]

    assert detail["final_layer_type"] == "websearch_broad"
    assert detail["via_broad_search"] is True
    assert detail["confidence_policy"] == "force_medium_plus_flag"
    assert detail["attempts"][0]["target"] == "recall_probe_queries"
    assert detail["attempts"][0]["reason"] == "pending discovery"
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_discovery.py::test_cursor_source_checks_blog_before_changelog_and_sdk_queries \
  skills/ai-daily-report/tests/test_discovery.py::test_whitelist_contains_deepseek_vision_zed_and_adoption_surfaces \
  skills/ai-daily-report/tests/test_discovery.py::test_build_discovery_manifest_includes_recall_probe_surface \
  skills/ai-daily-report/tests/test_discovery.py::test_initial_fetch_status_contains_recall_probe_surface -q
```

Expected: FAIL. The first failures should mention missing Cursor blog ordering, missing `recall_probe_queries`, or missing `RECALL_PROBE_SURFACE_NAME`.

- [ ] **Step 3: Update whitelist discovery surfaces**

In `skills/ai-daily-report/sources/whitelist.yaml`, replace the `Cursor` entry with:

```yaml
  - name: Cursor
    category: coding_agents_secondary
    weight: medium
    authority_tier: 1
    fetch_chain:
      - type: webfetch
        url: https://cursor.com/blog
      - type: webfetch
        url: https://www.cursor.com/changelog
      - type: websearch_scoped
        queries:
          - "Cursor SDK site:cursor.com/blog {date}"
          - "Cursor changelog site:cursor.com {date}"
          - "Cursor release site:cursor.com/blog {date}"
      - type: websearch_broad
        queries:
          - "@cursor/sdk public beta {date}"
          - "Cursor IDE update {date}"
```

In the `DeepSeek` broad query layer, replace the current two broad queries with:

```yaml
      - type: websearch_broad
        queries:
          - "DeepSeek new model release {date}"
          - "DeepSeek API update {yesterday}"
          - "DeepSeek vision multimodal {date}"
          - "DeepSeek image recognition beta {date}"
```

Append these entries to `general_agent_search_queries`:

```yaml
  - "AI-native editor agent protocol {date}"
  - "AI coding editor 1.0 launch {date}"
  - "enterprise AI agent paid seats earnings call {date}"
```

Append these entries to `high_signal_media_queries`:

```yaml
  - "Cursor SDK @cursor/sdk public beta {date}"
  - "Zed 1.0 AI-native editor Agent Client Protocol {date}"
  - "DeepSeek vision multimodal beta {date}"
  - "Microsoft 365 Copilot paid seats earnings call {date}"
```

Add this top-level block after `high_signal_media_queries`:

```yaml
recall_probe_queries:
  - "Cursor SDK @cursor/sdk public beta {date}"
  - "Zed 1.0 AI-native editor Agent Client Protocol {date}"
  - "DeepSeek vision multimodal beta {date}"
  - "Microsoft 365 Copilot paid seats weekly engagement {date}"
  - "AI-native editor multiple agents Agent Client Protocol {date}"
  - "enterprise Copilot ARR paid seats weekly active users {date}"
```

Append these two sources under `general_agent_watchlist` before `Product Hunt AI`:

```yaml
  - name: Zed
    category: general_agent_watchlist
    weight: medium
    authority_tier: 1
    fetch_chain:
      - type: webfetch
        url: https://zed.dev/blog
      - type: websearch_scoped
        queries:
          - "Zed 1.0 site:zed.dev/blog {date}"
          - "Zed Agent Client Protocol site:zed.dev/blog {date}"
      - type: websearch_broad
        queries:
          - "Zed AI-native editor agent protocol {date}"

  - name: Microsoft 365 Copilot Adoption
    category: general_agent_watchlist
    weight: medium
    authority_tier: 1
    fetch_chain:
      - type: webfetch
        url: https://news.microsoft.com/source/
      - type: websearch_scoped
        queries:
          - "Microsoft 365 Copilot paid seats site:microsoft.com {date}"
          - "Microsoft Copilot weekly engagement Outlook site:microsoft.com {date}"
      - type: websearch_broad
        queries:
          - "Microsoft 365 Copilot paid seats earnings call {date}"
          - "Microsoft AI ARR Copilot seats weekly engagement {date}"
```

- [ ] **Step 4: Add recall probe surface to discovery.py**

In `skills/ai-daily-report/scripts/discovery.py`, add the constant near the other surface names:

```python
RECALL_PROBE_SURFACE_NAME = "High-Recall Product/Adoption Probes"
```

In `required_discovery_names()`, add `RECALL_PROBE_SURFACE_NAME` to the synthetic surface list:

```python
            HIGH_SIGNAL_MEDIA_DISCOVERY_NAME,
            RECALL_PROBE_SURFACE_NAME,
```

In `initial_fetch_status()`, after the `HIGH_SIGNAL_MEDIA_DISCOVERY_NAME` block, add:

```python
    source_details[RECALL_PROBE_SURFACE_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "websearch_broad",
        "via_broad_search": True,
        "confidence_policy": "force_medium_plus_flag",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "websearch_broad",
                "target": "recall_probe_queries",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
```

In `build_discovery_manifest()`, add a sibling field after `high_signal_media_queries`:

```python
        "recall_probe_queries": whitelist.get("recall_probe_queries", []),
```

Also add `RECALL_PROBE_SURFACE_NAME` to `required_discovery_surfaces` after `HIGH_SIGNAL_MEDIA_DISCOVERY_NAME`.

- [ ] **Step 5: Run discovery tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_discovery.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add skills/ai-daily-report/sources/whitelist.yaml \
  skills/ai-daily-report/scripts/discovery.py \
  skills/ai-daily-report/tests/test_discovery.py
git commit -m "feat: expand ai daily recall discovery surfaces"
```

---

### Task 2: Add Adoption Signals To Daily And Weekly Market Schema

**Files:**
- Modify: `skills/ai-daily-report/schemas/daily_report.schema.json`
- Modify: `skills/ai-daily-report/schemas/weekly_report.schema.json`
- Modify: `skills/ai-daily-report/tests/test_render_html.py`
- Modify: `skills/ai-daily-report/tests/fixtures/sample_daily.json`
- Modify: `skills/ai-daily-report/tests/fixtures/sample_daily_empty.json`
- Modify: `skills/ai-daily-report/tests/fixtures/sample_weekly.json`

- [ ] **Step 1: Write failing schema/render tests**

In `skills/ai-daily-report/tests/test_render_html.py`, add `"adoptionSignal"` to `SHARED_DEFS`:

```python
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
```

Append these tests:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_render_html.py::test_daily_schema_requires_adoption_signals_bucket \
  skills/ai-daily-report/tests/test_render_html.py::test_weekly_schema_requires_adoption_signals_bucket \
  skills/ai-daily-report/tests/test_render_html.py::test_render_daily_adoption_signals \
  skills/ai-daily-report/tests/test_render_html.py::test_render_weekly_adoption_signals -q
```

Expected: FAIL because `adoptionSignal` and `adoption_signals` do not exist.

- [ ] **Step 3: Update daily schema**

In `skills/ai-daily-report/schemas/daily_report.schema.json`, add this `$defs.adoptionSignal` block after `pricingChange`:

```json
    "adoptionSignal": {
      "type": "object",
      "required": ["vendor", "product", "metric", "value", "source", "observed_at"],
      "properties": {
        "vendor": {"type": "string"},
        "product": {"type": "string"},
        "metric": {"enum": ["paid_seats", "arr", "weekly_engagement", "customer_count", "usage_share", "other"]},
        "value": {"type": "string", "maxLength": 80},
        "source": {"type": "string"},
        "observed_at": {"type": "string"},
        "note": {"type": "string", "maxLength": 120},
        "ref": {"$ref": "#/$defs/itemRef"}
      }
    },
```

In `marketSignalsSection.required`, replace the list with:

```json
["title", "benchmark_changes", "benchmark_watch", "pricing_changes", "adoption_signals", "capability_gaps", "empty_message"]
```

In `marketSignalsSection.properties`, add:

```json
        "adoption_signals": {"type": "array", "items": {"$ref": "#/$defs/adoptionSignal"}},
```

- [ ] **Step 4: Update weekly schema**

Apply the same `adoptionSignal` definition and `marketSignalsSection` additions to `skills/ai-daily-report/schemas/weekly_report.schema.json`.

- [ ] **Step 5: Update daily fixture**

In `skills/ai-daily-report/tests/fixtures/sample_daily.json`, add `adoption_signals` inside `sections.market_signals` after `pricing_changes`:

```json
    "adoption_signals": [
      {
        "vendor": "Microsoft",
        "product": "Microsoft 365 Copilot",
        "metric": "paid_seats",
        "value": "20M paid seats",
        "source": "Microsoft earnings call transcript",
        "observed_at": "2026-04-10T06:00:00+08:00",
        "note": "示例 fixture，用于验证商业化采用率渲染",
        "ref": "general_agents[0]"
      }
    ],
```

In `skills/ai-daily-report/tests/fixtures/sample_daily_empty.json`, add:

```json
    "adoption_signals": [],
```

In `skills/ai-daily-report/tests/fixtures/sample_weekly.json`, add an adoption item inside `sections.market_signals`:

```json
    "adoption_signals": [
      {
        "vendor": "Microsoft",
        "product": "Microsoft 365 Copilot",
        "metric": "paid_seats",
        "value": "20M paid seats",
        "source": "Microsoft earnings call transcript",
        "observed_at": "2026-04-10T00:00:00+08:00",
        "note": "周报示例 fixture，用于验证采用率信号",
        "ref": "general_agents[0]"
      }
    ],
```

- [ ] **Step 6: Run schema/render tests again**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_render_html.py::test_daily_schema_requires_adoption_signals_bucket \
  skills/ai-daily-report/tests/test_render_html.py::test_weekly_schema_requires_adoption_signals_bucket \
  skills/ai-daily-report/tests/test_render_html.py::test_render_daily_adoption_signals \
  skills/ai-daily-report/tests/test_render_html.py::test_render_weekly_adoption_signals -q
```

Expected: the two schema tests PASS; the two render tests still FAIL until templates render the new bucket.

- [ ] **Step 7: Commit schema and fixture contract**

```bash
git add skills/ai-daily-report/schemas/daily_report.schema.json \
  skills/ai-daily-report/schemas/weekly_report.schema.json \
  skills/ai-daily-report/tests/fixtures/sample_daily.json \
  skills/ai-daily-report/tests/fixtures/sample_daily_empty.json \
  skills/ai-daily-report/tests/fixtures/sample_weekly.json \
  skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: add adoption signals report contract"
```

---

### Task 3: Render Adoption Signals In Daily And Weekly HTML

**Files:**
- Modify: `skills/ai-daily-report/templates/daily.html.j2`
- Modify: `skills/ai-daily-report/templates/weekly.html.j2`
- Test: `skills/ai-daily-report/tests/test_render_html.py`

- [ ] **Step 1: Update daily market macro**

In `skills/ai-daily-report/templates/daily.html.j2`, replace the `has_any` line in `market_signals_block(ms)` with:

```jinja2
  {% set has_any = ms.benchmark_changes or ms.benchmark_watch or ms.pricing_changes or ms.adoption_signals or ms.capability_gaps %}
```

After the pricing section and before capability gaps, add:

```jinja2
    {% if ms.adoption_signals %}<h3>采用率 / 商业化信号</h3>
    {% for a in ms.adoption_signals %}
    <div class="signal-row">
      <span class="vendor">{{ a.vendor }}</span>
      <span class="model">{{ a.product }}</span>
      <span>{{ a.metric }}</span>
      <span>{{ a.value }}</span>
      <span class="model">· {{ a.source }}</span>
      {% if a.ref %}<span class="model">· {{ ref_link(a.ref) }}</span>{% endif %}
      {% if a.note %}<span class="model">· {{ a.note }}</span>{% endif %}
    </div>
    {% endfor %}{% endif %}
```

- [ ] **Step 2: Update weekly market macro**

Apply the same `has_any` and adoption rendering block to `skills/ai-daily-report/templates/weekly.html.j2`.

- [ ] **Step 3: Run adoption render tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_render_html.py::test_render_daily_adoption_signals \
  skills/ai-daily-report/tests/test_render_html.py::test_render_weekly_adoption_signals -q
```

Expected: PASS.

- [ ] **Step 4: Run full render tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_render_html.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/templates/daily.html.j2 \
  skills/ai-daily-report/templates/weekly.html.j2 \
  skills/ai-daily-report/tests/test_render_html.py
git commit -m "feat: render adoption signals"
```

---

### Task 4: Validate Adoption Signals And Hard-Data Coverage

**Files:**
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Modify: `skills/ai-daily-report/schemas/candidate_ledger.schema.json`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Write failing editorial tests**

Append these tests to `skills/ai-daily-report/tests/test_editorial.py`:

```python
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

    errors = validate_daily_artifacts(report, sample_candidate_ledger, whitelist)

    assert any("hard-data signal without market_signals coverage" in error for error in errors)


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_accepts_adoption_signal_with_ref \
  skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_adoption_language_without_market_signal \
  skills/ai-daily-report/tests/test_editorial.py::test_validate_daily_artifacts_rejects_adoption_signal_ref_out_of_range -q
```

Expected: FAIL. The failures should mention schema rejection for `event_type`, missing adoption keyword detection, or missing adoption ref validation.

- [ ] **Step 3: Allow adoption candidate event type**

In `skills/ai-daily-report/schemas/candidate_ledger.schema.json`, add `"adoption_signal"` to the `event_type` enum:

```json
        "event_type": {"enum": ["model_release", "coding_release", "partnership", "pricing", "benchmark", "compliance", "community_signal", "enterprise_update", "adoption_signal", "research_update"]},
```

- [ ] **Step 4: Update editorial hard-data keywords**

In `skills/ai-daily-report/scripts/editorial.py`, extend `HARD_DATA_KEYWORDS` with:

```python
    "paid seats",
    "seat",
    "seats",
    "arr",
    "weekly engagement",
    "weekly active",
    "usage",
    "adoption",
    "customer count",
    "付费席位",
    "席位",
    "周活跃",
    "采用率",
    "商业化",
```

- [ ] **Step 5: Include adoption refs/entities**

In `_market_signal_refs()`, add this loop after the existing `capability_gaps` loop and before `return refs`:

```python
    for item in market_signals.get("adoption_signals", []):
        ref = item.get("ref")
        if ref:
            refs.add(ref)
```

In `_market_signal_entities()`, replace the current loop with:

```python
    for bucket_name in ("benchmark_changes", "benchmark_watch", "pricing_changes"):
        for item in market_signals.get(bucket_name, []):
            for key in ("vendor", "model"):
                value = str(item.get(key, "")).strip().lower()
                if value:
                    entities.add(value)
    for item in market_signals.get("adoption_signals", []):
        for key in ("vendor", "product"):
            value = str(item.get(key, "")).strip().lower()
            if value:
                entities.add(value)
```

- [ ] **Step 6: Validate adoption signal refs**

In `validate_daily_market_signal_refs()`, after the pricing/capability validation and before `return errors`, add:

```python
    for index, item in enumerate(market_signals.get("adoption_signals", [])):
        ref = item.get("ref")
        if not ref:
            continue
        errors.extend(_validate_item_ref(f"adoption_signals[{index}].ref", ref, counts))
```

- [ ] **Step 7: Run editorial tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py \
  skills/ai-daily-report/schemas/candidate_ledger.schema.json \
  skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: validate adoption signal coverage"
```

---

### Task 5: Add Recall QA Regression For Missing Probe Execution

**Files:**
- Modify: `skills/ai-daily-report/tests/test_editorial.py`
- Modify: `skills/ai-daily-report/scripts/editorial.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Write failing QA test**

Append this test to `skills/ai-daily-report/tests/test_editorial.py`:

```python
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
    assert any(
        finding["source_name"] == RECALL_PROBE_SURFACE_NAME
        and "缺少该 discovery surface" in finding["reason"]
        for finding in qa_diff["findings"]
    )
```

- [ ] **Step 2: Run test**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_build_daily_qa_diff_reports_missing_recall_probe_surface -q
```

Expected: PASS after Task 1, because `missing_fetch_status_coverage()` already drives `build_daily_qa_diff()`. If it fails, verify Task 1 added `RECALL_PROBE_SURFACE_NAME` to `required_discovery_names()`.

- [ ] **Step 3: Add stale-empty QA for configured recall probes**

Append this helper to `skills/ai-daily-report/scripts/editorial.py` near the other QA helpers:

```python
def recall_probe_findings(report: dict[str, Any], whitelist: dict[str, Any]) -> list[dict[str, Any]]:
    probe_queries = whitelist.get("recall_probe_queries", [])
    if not probe_queries:
        return []

    source_details = report.get("fetch_status", {}).get("source_details", {})
    probe_detail = source_details.get("High-Recall Product/Adoption Probes", {})
    attempts = probe_detail.get("attempts", [])
    if not attempts:
        return [
            _make_finding(
                "missed_discovery",
                "high",
                "recall_probe_queries 已配置，但 High-Recall Product/Adoption Probes 没有记录任何 attempt。",
                source_name="High-Recall Product/Adoption Probes",
                suggested_fix="运行 recall_probe_queries，并把搜索结果或空结果写入 fetch_status.source_details。",
            )
        ]

    attempted_targets = " ".join(str(attempt.get("target", "")) for attempt in attempts)
    if "recall_probe_queries" not in attempted_targets and not any(query in attempted_targets for query in probe_queries):
        return [
            _make_finding(
                "missed_discovery",
                "high",
                "High-Recall Product/Adoption Probes 未指向 recall_probe_queries 或具体 probe query。",
                source_name="High-Recall Product/Adoption Probes",
                suggested_fix="把 recall_probe_queries 的执行摘要写入该 surface 的 attempts。",
            )
        ]
    return []
```

In `build_daily_qa_diff()`, add this line after the pending-discovery loop:

```python
    findings.extend(recall_probe_findings(report, whitelist))
```

- [ ] **Step 4: Write and run target-specific stale-empty test**

Append this test:

```python
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
```

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_build_daily_qa_diff_reports_missing_recall_probe_surface \
  skills/ai-daily-report/tests/test_editorial.py::test_build_daily_qa_diff_rejects_recall_probe_attempt_without_probe_target -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/ai-daily-report/scripts/editorial.py \
  skills/ai-daily-report/tests/test_editorial.py
git commit -m "feat: require recall probe audit trail"
```

---

### Task 6: Add 2026-04-30 Recall Regression Fixture Test

**Files:**
- Modify: `skills/ai-daily-report/tests/test_editorial.py`
- Test: `skills/ai-daily-report/tests/test_editorial.py`

- [ ] **Step 1: Write regression test**

Append this test to `skills/ai-daily-report/tests/test_editorial.py`:

```python
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
```

- [ ] **Step 2: Run regression test**

Run:

```bash
python -m pytest skills/ai-daily-report/tests/test_editorial.py::test_2026_04_30_recall_regression_accepts_cursor_zed_deepseek_and_m365 -q
```

Expected: PASS after Tasks 1-5.

- [ ] **Step 3: Commit**

```bash
git add skills/ai-daily-report/tests/test_editorial.py
git commit -m "test: cover 2026-04-30 recall regression"
```

---

### Task 7: Update Skill Instructions For Future Daily Runs

**Files:**
- Modify: `skills/ai-daily-report/SKILL.md`
- Test: `python -m pytest skills/ai-daily-report/tests -q`

- [ ] **Step 1: Add workflow wording**

In `skills/ai-daily-report/SKILL.md`, in the discovery section near the existing `high_signal_media_queries` wording, add:

```markdown
   - **召回探针必须执行**：除逐源白名单、`general_agent_search_queries`、`high_signal_media_queries` 外，日报还必须执行 `recall_probe_queries`，并把结果写入 `fetch_status.source_details["High-Recall Product/Adoption Probes"].attempts[]`。
   - `recall_probe_queries` 不是固定正文规则，只是独立召回面。命中的候选仍由 AI 基于窗口、证据路径、产品相关性和团队可行动性决定进入正文、观察区、`unverified` 或拒绝。
   - 对 Cursor / Zed / IDE 平台化类信号，不要只看 changelog；官方 blog、release post、SDK 公告和 Agent Client Protocol 一类入口都属于 coding/general agent 候选面。
   - 对 DeepSeek / Qwen / Kimi 等中文头部模型，若官方 API update 为空但主流媒体给出明确日期和产品事实，应进入 `candidate_ledger`，再按 `media_plus_official_one_hop` 或 `media_only` 降级，不要直接在首层空结果后判定“无内容”。
   - 对 Microsoft 365 Copilot、企业 agent 席位、ARR、weekly engagement 等商业采用率信号，优先写入 `market_signals.adoption_signals`，并通过正文 item `ref` 连接到 `general_agents` 或 `frontier_models`。引用必须指向能承载该数字的一手或电话会转录来源；普通新闻稿若不含数字，不可单独作为数字证据。
```

- [ ] **Step 2: Run full tests**

Run:

```bash
python -m pytest skills/ai-daily-report/tests -q
```

Expected: PASS.

- [ ] **Step 3: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 4: Commit**

```bash
git add skills/ai-daily-report/SKILL.md
git commit -m "docs: clarify recall probe workflow"
```

---

### Task 8: End-To-End Dry-Run Verification

**Files:**
- No code files changed in this task.
- Runtime artifacts expected under `cache/2026-04-30/`.

- [ ] **Step 1: Run full unit test suite**

Run:

```bash
python -m pytest skills/ai-daily-report/tests -q
```

Expected: PASS.

- [ ] **Step 2: Initialize a dry-run report workspace**

Run:

```bash
python skills/ai-daily-report/scripts/report_runner.py init-daily --date 2026-04-30 --now 2026-04-30T10:58:00+08:00
```

Expected:

```text
cache/2026-04-30/discovery_manifest.json
cache/2026-04-30/run.log
```

Open `cache/2026-04-30/discovery_manifest.json` and verify these keys exist:

```bash
jq '{recall_probe_queries, has_recall_surface: (.required_discovery_surfaces | index("High-Recall Product/Adoption Probes") != null)}' cache/2026-04-30/discovery_manifest.json
```

Expected:

```json
{
  "recall_probe_queries": [
    "Cursor SDK @cursor/sdk public beta {date}",
    "Zed 1.0 AI-native editor Agent Client Protocol {date}",
    "DeepSeek vision multimodal beta {date}",
    "Microsoft 365 Copilot paid seats weekly engagement {date}",
    "AI-native editor multiple agents Agent Client Protocol {date}",
    "enterprise Copilot ARR paid seats weekly active users {date}"
  ],
  "has_recall_surface": true
}
```

- [ ] **Step 3: Rebuild the 2026-04-30 artifacts manually through AI judgment**

Use the normal daily workflow:

1. Read `cache/2026-04-30/discovery_manifest.json`.
2. Execute the listed whitelist, high-signal, general-agent, and recall-probe surfaces with AI search/browsing.
3. Write `cache/2026-04-30/report.json`.
4. Write `cache/2026-04-30/candidate_ledger.json`.
5. Ensure these 2026-04-30 candidates are either selected or explicitly rejected with a `decision_reason`:
   - Cursor TypeScript SDK public beta.
   - Zed 1.0.
   - DeepSeek vision beta.
   - Microsoft 365 Copilot paid seats / weekly engagement.

Required ledger evidence policy:

```json
{
  "Cursor TypeScript SDK": {
    "evidence_path": "primary",
    "action_eligibility": "experiment"
  },
  "Zed 1.0": {
    "evidence_path": "primary",
    "action_eligibility": "experiment"
  },
  "DeepSeek vision beta": {
    "evidence_path": "media_plus_official_one_hop",
    "action_eligibility": "monitor"
  },
  "Microsoft 365 Copilot paid seats": {
    "event_type": "adoption_signal",
    "evidence_path": "media_plus_official_one_hop",
    "action_eligibility": "monitor"
  }
}
```

- [ ] **Step 4: Run finalize dry-run**

Run:

```bash
python skills/ai-daily-report/scripts/report_runner.py finalize-daily --date 2026-04-30 --dry-run
```

Expected:

```text
QA qa_diff.json ok
RENDER report.html ok
ARCHIVE reports/daily/2026-04-30.html ok
EMAIL skipped (dry-run)
END daily status=ok
```

Verify QA summary:

```bash
jq '.summary' cache/2026-04-30/qa_diff.json
```

Expected:

```json
{
  "total_findings": 0,
  "blocking_findings": 0,
  "categories": {
    "missed_discovery": 0,
    "downgraded_evidence": 0,
    "duplicate_rejected": 0,
    "weak_evidence_rejected": 0,
    "hard_data_gap": 0,
    "reference_integrity_gap": 0
  }
}
```

- [ ] **Step 5: Inspect rendered HTML for recalled signals**

Run:

```bash
python - <<'PY'
from pathlib import Path
html = Path("cache/2026-04-30/report.html").read_text(encoding="utf-8")
for token in ["Cursor", "Zed", "DeepSeek", "Microsoft 365 Copilot", "采用率 / 商业化信号"]:
    print(token, token in html)
PY
```

Expected:

```text
Cursor True
Zed True
DeepSeek True
Microsoft 365 Copilot True
采用率 / 商业化信号 True
```

- [ ] **Step 6: Commit verification notes if artifacts are intentionally tracked**

If runtime artifacts remain untracked by repository policy, do not commit them. If the repo has a tracked QA evidence doc, append the command outputs there and commit that doc.

Commit command for tracked source changes only:

```bash
git status --short
git add skills/ai-daily-report
git commit -m "test: verify ai daily recall hardening"
```

Expected: commit includes source, schema, template, tests, fixtures, and skill docs. It should not include secrets or `.env`.

---

## Final Verification Checklist

- [ ] `python -m pytest skills/ai-daily-report/tests -q` passes.
- [ ] `git diff --check` exits 0.
- [ ] `cache/2026-04-30/discovery_manifest.json` includes `recall_probe_queries`.
- [ ] `cache/2026-04-30/report.json` includes `market_signals.adoption_signals`.
- [ ] `cache/2026-04-30/candidate_ledger.json` records Cursor, Zed, DeepSeek vision, and Microsoft Copilot adoption as selected or explicitly rejected.
- [ ] `cache/2026-04-30/qa_diff.json` has `blocking_findings=0`.
- [ ] `cache/2026-04-30/report.html` renders adoption signals.

## Self-Review

Spec coverage:

- Cursor SDK miss: Task 1 expands Cursor source, Task 6 regression validates selected Cursor item.
- Zed 1.0 miss: Task 1 adds Zed source and recall probes, Task 6 validates selected Zed item.
- DeepSeek vision miss: Task 1 adds vision queries, Task 6 validates downgraded watch handling.
- Microsoft Copilot adoption miss: Tasks 2-4 add adoption contract, Task 6 validates M365 adoption item.
- Codex audit strength: Tasks 4-5 keep candidate ledger, source attempts, QA diff, and hard-data gates.
- Avoid local search backend: every task keeps searching in AI workflow and only strengthens deterministic artifacts.

Placeholder scan:

- No task contains an unresolved implementation marker.
- Every code-changing task includes exact test code, implementation snippets, commands, and expected results.

Type consistency:

- `adoption_signals` appears in daily schema, weekly schema, fixtures, templates, and validators.
- `adoption_signal` appears in candidate ledger schema and regression ledger.
- `RECALL_PROBE_SURFACE_NAME` appears in discovery tests, discovery implementation, and editorial QA tests.
