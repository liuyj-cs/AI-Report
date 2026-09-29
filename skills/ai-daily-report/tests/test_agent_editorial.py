"""Synthetic contract cases; never used as published news or retrieval evidence."""
import json
from copy import deepcopy

import pytest
from bs4 import BeautifulSoup

from agent_editorial import (
    validate_agent_daily, validate_agent_weekly, validate_batch_version,
    validate_candidate_contract, validate_decision_refs, validate_report_schema,
)
from discovery import build_discovery_manifest, load_whitelist
from editorial import (
    validate_daily_artifacts, validate_weekly_item_refs, validate_weekly_references,
    validate_model_assessments, validate_sparse_day_restraint,
)
from evidence import save_response, read_response, receipt_from_output, review_coverage, validate_evidence_reviews, MAX_REVIEW_CHARS
from render_html import render
from render_markdown import render_markdown
from report_runner import run_daily_finalize


def delivered_chunk(cache, artifact, *, start, end):
    """Simulate an untruncated tool boundary only in these synthetic tests."""
    output = json.dumps(read_response(cache, artifact, start=start, end=end), ensure_ascii=False)
    return {"content": json.loads(output)["content"],
            "receipt": receipt_from_output(cache, artifact, returned_output=output)}


@pytest.fixture
def bundle(tmp_path, sample_daily_report, sample_candidate_ledger, finalized_fetch_status):
    report = deepcopy(sample_daily_report)
    report.update(version="1.2", reading_guide=[], coverage_summary="合成样例仅用于契约校验，不代表行业覆盖。")
    report["window"]["end"] = report["generated_at"]
    sections = report["sections"]
    for name in ("frontier_models", "coding_agents", "unverified", "action_items", "pattern_observations", "experiments_this_week", "agent_ecosystem", "methodology_radar"):
        sections[name]["items"] = []
    sections["decision_radar"]["decisions"] = []
    for key, value in sections["market_signals"].items():
        if isinstance(value, list):
            sections["market_signals"][key] = []
    general = {
        "product": "Fixture Office", "headline": "合成样例：文档连接器开放", "summary": "合成数据：连接器可读取获授权的文档。",
        "source_name": "Fixture Official", "source_url": "https://example.com/release",
        "published_at": report["generated_at"], "confidence": "high", "release_stage": "ga",
        "published_at_confidence": "exact", "authority_score": 5, "editorial_tier": "core",
        "use_case": "行政人员汇总已授权的会议纪要", "what_changed": "新增只读文档连接器",
        "usage_mode": "workflow", "availability": "合成企业套餐，仅测试租户",
        "impact": "可在授权范围内进行小范围试点", "evidence_limits": ["合成样例，不代表真实产品"],
    }
    sections["general_agents"] = {"title": "通用与办公 Agent", "items": [general], "empty_message": "本窗口未确认新增通用与办公 Agent 产品变化"}
    sections["policy_risk"] = {"title": "政策与风险观察", "items": [], "empty_message": "本窗口无新增政策风险信号"}
    report["fetch_status"] = finalized_fetch_status(load_whitelist())
    detail = {"final_layer_index": 0, "final_layer_type": "webfetch", "via_broad_search": False, "confidence_policy": "none",
              "attempts": [{"layer_index": 0, "layer_type": "webfetch", "target": general["source_url"], "result": "success"}]}
    report["fetch_status"]["source_details"]["Fixture Official"] = detail
    report["fetch_status"]["succeeded"].append("Fixture Official")
    cache = tmp_path / "cache" / report["date"]
    for name, source in report["fetch_status"]["source_details"].items():
        for i, attempt in enumerate(source["attempts"]):
            raw = f"SYNTHETIC RESPONSE {name} {i}: no real retrieval."
            if name == "AI HOT" and i == 0:
                raw = json.dumps({"request_url": attempt["target"], "status_code": 503,
                                  "content_type": "application/problem+json", "body": {"status": 503}})
            artifact = save_response(cache, raw, collected_at=report["generated_at"], batch_id=f"fixture-{name}-{i}", query_ids=[attempt["target"]], limitations=[])
            chunk = delivered_chunk(cache, artifact, start=0, end=len(raw))
            attempt.update(evidence_artifact=artifact, review={"status": "complete", "receipts": [chunk["receipt"]], "coverage": review_coverage(raw, [chunk["receipt"]])})
    from aihot import recompute_aihot_coverage
    detail = report["fetch_status"]["source_details"]["AI HOT"]
    detail["aihot_coverage"] = recompute_aihot_coverage(detail, window=report["window"], cache_dir=cache)
    candidate = deepcopy(sample_candidate_ledger["items"][0])
    candidate.update(candidate_id="fixture-office", headline=general["headline"], published_at=general["published_at"], proposed_section="general_agents", decision="selected_core", editorial_tier="core",
                     event_type="agent_product_update", subject_kind="product", section_reason="合成办公任务产品更新", evidence_path="primary", date_basis="official_event_date",
                     source_attempt_refs=["Fixture Official.attempts[0]"], action_eligibility="full_action",
                     claim_support=[{"claim": "合成文档连接器开放", "direct_attempt_refs": ["Fixture Official.attempts[0]"], "background_attempt_refs": [], "unresolved_questions": []}])
    ledger = {**deepcopy(sample_candidate_ledger), "version": "1.1", "date": report["date"], "items": [candidate]}
    return report, ledger, tmp_path


def add_risk(report, ledger):
    product = report["sections"]["general_agents"]["items"][0]
    risk = {k: product[k] for k in ("headline", "summary", "source_name", "source_url", "published_at", "confidence", "published_at_confidence", "authority_score", "editorial_tier")}
    risk.update(subject="合成议会", headline="合成样例：邀请出席调查", risk_kind="policy_process", event_status="收到出席请求",
                affected_scope="调查程序，未形成产品限制", decision_relevance="尚不改变产品选择", evidence_limits=["未取得邀请函"])
    report["sections"]["policy_risk"]["items"] = [risk]
    candidate = deepcopy(ledger["items"][0])
    candidate.update(candidate_id="fixture-risk", headline=risk["headline"], proposed_section="policy_risk", subject_kind="institution", event_type="compliance", action_eligibility="monitor")
    ledger["items"].append(candidate)
    return risk


def action_for(report, section, item, kind):
    return {"recommendation": "合成行动", "rationale": "合成依据", "recommendation_type": kind,
            "effort_person_days": {"min": 0.25, "max": 0.5}, "time_horizon": "this_week", "priority": "P2",
            "team_size_applicability": ["small_lt_10"], "action_delta": "新增合成对象，之前未验证",
            "references": [{"date": report["date"], "section": section, "headline": item["headline"], "editorial_tier": item["editorial_tier"], "url": item["source_url"]}]}


def test_new_bundle_passes_integrated_gate(bundle):
    report, ledger, root = bundle
    assert validate_daily_artifacts(report, ledger, load_whitelist(), root, None, build_discovery_manifest(report["date"], report["window"], load_whitelist())) == []


@pytest.mark.parametrize("field", ["use_case", "what_changed", "usage_mode", "availability", "impact", "evidence_limits"])
def test_product_fields_cannot_be_omitted(bundle, field):
    report, _, _ = bundle
    del report["sections"]["general_agents"]["items"][0][field]
    assert validate_report_schema(report)


@pytest.mark.parametrize("subject", ["institution", "research_system", "industry"])
def test_declared_nonproduct_cannot_enter_general(bundle, subject):
    report, ledger, _ = bundle
    ledger["items"][0]["subject_kind"] = subject
    assert any("requires a product" in e for e in validate_candidate_contract(report, ledger))


def test_specific_product_vulnerability_stays_product(bundle):
    report, ledger, root = bundle
    item = report["sections"]["general_agents"]["items"][0]
    item["headline"] = ledger["items"][0]["headline"] = "合成样例：特定版本连接器权限漏洞"
    ledger["items"][0]["event_type"] = "safety_incident"
    item["availability"] = "仅影响测试版本 1.0，合成已修复版本 1.1"
    assert validate_agent_daily(report, ledger, root) == []


@pytest.mark.parametrize("field", ["product", "product_tier", "release_stage", "heat_signal", "major_event", "expanded"])
def test_risk_does_not_accept_product_fields(bundle, field):
    report, ledger, _ = bundle
    risk = add_risk(report, ledger)
    risk[field] = "announced"
    assert validate_report_schema(report)


@pytest.mark.parametrize("direction", ["missing_report", "missing_ledger"])
def test_selected_alignment_is_bidirectional(bundle, direction):
    report, ledger, _ = bundle
    if direction == "missing_report":
        report["sections"]["general_agents"]["items"] = []
    else:
        ledger["items"] = []
    assert any("mismatch" in e for e in validate_candidate_contract(report, ledger))


def test_claim_support_cannot_borrow_unlisted_or_background_source(bundle):
    report, ledger, _ = bundle
    claim = ledger["items"][0]["claim_support"][0]
    claim["background_attempt_refs"] = claim["direct_attempt_refs"][:]
    assert any("disjoint" in e for e in validate_candidate_contract(report, ledger))
    claim["background_attempt_refs"] = ["Unlisted.attempts[0]"]
    assert any("subsets" in e for e in validate_candidate_contract(report, ledger))


@pytest.mark.parametrize("kind", ["adopt", "migrate", "experiment"])
def test_weak_reference_cannot_be_washed_by_strong_reference(bundle, kind):
    report, ledger, _ = bundle
    risk = add_risk(report, ledger)
    action = action_for(report, "policy_risk", risk, kind)
    action["references"] += action_for(report, "general_agents", report["sections"]["general_agents"]["items"][0], kind)["references"]
    report["sections"]["action_items"]["items"] = [action]
    assert any("exceeds eligibility" in e for e in validate_candidate_contract(report, ledger))


def test_confirmed_binding_rule_can_support_substantive_action(bundle):
    report, ledger, root = bundle
    risk = add_risk(report, ledger)
    risk.update(risk_kind="binding_policy", event_status="规则已生效", affected_scope="明确适用测试组织的特定产品")
    ledger["items"][-1]["action_eligibility"] = "full_action"
    report["sections"]["action_items"]["items"] = [action_for(report, "policy_risk", risk, "migrate")]
    assert validate_agent_daily(report, ledger, root) == []


def test_risk_cannot_back_product_experiment_or_relax_sparse_restraint(bundle, sample_daily_report):
    report, ledger, _ = bundle
    risk = add_risk(report, ledger)
    experiment = deepcopy(sample_daily_report["sections"]["experiments_this_week"]["items"][0])
    experiment["related_item_refs"] = ["policy_risk[0]"]
    report["sections"]["experiments_this_week"]["items"] = [experiment]
    assert validate_decision_refs(report)
    assert validate_report_schema(report)
    report["sections"]["action_items"]["items"] = [action_for(report, "policy_risk", risk, "monitor")] * 2
    assert validate_sparse_day_restraint(report)


def test_new_version_inherits_model_assessment_and_policy_requirements(bundle, sample_daily_report):
    report, _, _ = bundle
    report["sections"]["frontier_models"]["items"] = deepcopy(sample_daily_report["sections"]["frontier_models"]["items"])
    for item in report["sections"]["frontier_models"]["items"]:
        item.pop("model_assessment", None)
    assert any("model_assessment" in e for e in validate_report_schema(report))
    assert validate_model_assessments(report)
    del report["sections"]["policy_risk"]
    assert any("policy_risk" in e for e in validate_report_schema(report))


def test_230_character_preview_does_not_prove_review(tmp_path):
    raw = "x" * 230 + "重要结果在后面" * 100
    artifact = save_response(tmp_path, raw, collected_at="2026-09-28T12:00:00+08:00", batch_id="b1", query_ids=["q1", "q2"], limitations=[])
    first = delivered_chunk(tmp_path, artifact, start=0, end=230)
    review = {"status": "complete", "receipts": [first["receipt"]], "coverage": review_coverage(raw, [first["receipt"]])}
    report = {"version": "1.2", "fetch_status": {"source_details": {"test": {"attempts": [{"result": "success_but_empty", "evidence_artifact": artifact, "review": review}]}}}}
    assert any("unread" in e for e in validate_evidence_reviews(report, tmp_path))
    last = delivered_chunk(tmp_path, artifact, start=230, end=len(raw))
    review["receipts"].append(last["receipt"])
    review["coverage"] = review_coverage(raw, review["receipts"])
    assert validate_evidence_reviews(report, tmp_path) == []


def test_raw_response_preserves_unicode_and_crlf(tmp_path):
    raw = "第一条\r\n第二条😀\r\n"
    artifact = save_response(tmp_path, raw, collected_at="2026-09-28T12:00:00+08:00", batch_id="batch", query_ids=["query"], limitations=[])
    chunk = delivered_chunk(tmp_path, artifact, start=0, end=len(raw))
    assert chunk["content"] == raw
    assert review_coverage(raw, [chunk["receipt"]])["complete"] is True


@pytest.mark.parametrize("fault", ["missing", "corrupt", "range", "coverage", "path"])
def test_evidence_integrity_failures_are_blocking(bundle, fault):
    report, _, root = bundle
    attempt = report["fetch_status"]["source_details"]["Fixture Official"]["attempts"][0]
    path = root / "cache" / report["date"] / attempt["evidence_artifact"]["path"]
    if fault == "missing": path.unlink()
    elif fault == "corrupt": path.write_text("changed")
    elif fault == "range": attempt["review"]["receipts"][0]["end"] = 999999
    elif fault == "coverage": attempt["review"]["coverage"]["characters"] = 0
    else: attempt["evidence_artifact"]["path"] = "../outside.txt"
    assert validate_evidence_reviews(report, root / "cache" / report["date"])


@pytest.mark.parametrize("result,status,raw", [("empty", "complete", ""), ("error", "access_gap", "HTTP 403"), ("success", "complete", "retrieved results rejected by editor")])
def test_empty_failure_and_editor_rejection_are_distinct(tmp_path, result, status, raw):
    artifact = save_response(tmp_path, raw, collected_at="2026-09-28T12:00:00+08:00", batch_id="b", query_ids=["q"], limitations=[])
    receipt = delivered_chunk(tmp_path, artifact, start=0, end=len(raw))["receipt"]
    attempt = {"result": result, "evidence_artifact": artifact, "review": {"status": status, "reason": "explicit test outcome", "receipts": [receipt], "coverage": review_coverage(raw, [receipt])}}
    report = {"version": "1.2", "fetch_status": {"source_details": {"source": {"attempts": [attempt]}}}}
    assert validate_evidence_reviews(report, tmp_path) == []
    assert attempt["result"] == result


def test_truncated_tool_response_requires_coverage_caveat(bundle):
    report, _, root = bundle
    attempt = report["fetch_status"]["source_details"]["Fixture Official"]["attempts"][0]
    attempt["evidence_artifact"]["limitations"] = ["hasMore=true, next page not retrieved"]
    assert validate_evidence_reviews(report, root / "cache" / report["date"])
    attempt["review"]["reason"] = "全部已返回结果已提供；尚未取下一页，覆盖不完整"
    assert validate_evidence_reviews(report, root / "cache" / report["date"]) == []


def test_coverage_gap_remains_visible_in_html_and_full_markdown(bundle):
    report, ledger, root = bundle
    source = next(name for name in report["fetch_status"]["source_details"] if name != "Fixture Official")
    attempt = report["fetch_status"]["source_details"][source]["attempts"][0]
    attempt["evidence_artifact"]["limitations"] = ["pagination incomplete"]
    attempt["review"]["reason"] = "仅取得第一页，后续页面访问受限，不能据此宣称行业无更新。"
    report["coverage_summary"] = "该来源后续页面访问受限，本期可能遗漏新增；完整审计保留于台账。"
    assert validate_agent_daily(report, ledger, root) == []
    path = root / "coverage.json"
    path.write_text(json.dumps(report))
    html = render(path, root / "coverage.html")
    md = render_markdown(html, root / "coverage.md").read_text()
    assert "信息覆盖说明" in md and report["coverage_summary"] in md
    assert attempt["review"]["reason"] not in md


def test_new_batch_cannot_downgrade_and_old_render_has_no_manifest_requirement(bundle):
    report, _, _ = bundle
    manifest = build_discovery_manifest(report["date"], report["window"], load_whitelist())
    assert validate_batch_version(report, manifest) == []
    report["version"] = "1.0"
    assert validate_batch_version(report, manifest)
    assert validate_batch_version(report, None) == []


def test_new_daily_dry_run_never_calls_sender(bundle, monkeypatch):
    report, ledger, root = bundle
    cache = root / "cache" / report["date"]
    for name, value in [("report.json", report), ("candidate_ledger.json", ledger), ("discovery_manifest.json", build_discovery_manifest(report["date"], report["window"], load_whitelist()))]:
        (cache / name).write_text(json.dumps(value, ensure_ascii=False))
    env = root / "test.env"
    env.write_text("GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=fixture\nREPORT_RECIPIENTS=target@example.com\n")
    def fail_send(*args, **kwargs):
        pytest.fail("dry-run must never invoke send")
    monkeypatch.setattr("report_runner._send_mail", fail_send)
    code, message = run_daily_finalize(root, report["date"], True, env)
    assert code == 0, message
    assert (cache / "report.html").exists()
    assert not (cache / "send_state.json").exists()


def test_risk_render_markdown_and_anchors(bundle):
    report, ledger, root = bundle
    risk = add_risk(report, ledger)
    report["reading_guide"] = [{"text": "调查尚未改变产品选择", "ref": "policy_risk[0]"}]
    path = root / "report.json"
    path.write_text(json.dumps(report, ensure_ascii=False))
    html = render(path)
    soup = BeautifulSoup(html.read_text(), "html.parser")
    risk_card = soup.find(id="policy_risk-0")
    assert risk["headline"] in risk_card.get_text()
    assert "ANNOUNCED" not in risk_card.get_text()
    assert "查看详情" in soup.select_one(".guide-detail-link").get_text()
    assert len(soup.select("nav.toc a")) == 12
    assert all(soup.find(id=a["href"][1:]) for a in soup.select('a[href^="#"]'))
    md = render_markdown(html, root / "report.md").read_text()
    assert "## 四、政策与风险观察" in md
    assert risk["affected_scope"] in md and risk["evidence_limits"][0] in md
    from validate_dingtalk import validate_heading_outline, validate_readback_text
    container = soup.select_one(".container")
    for node in container.select("nav, footer"):
        node.decompose()
    payload = {"success": True, "hasMore": False, "blocks": [
        {"blockType": "heading", "element": {"heading": {"level": f"heading-{node.name[1]}", "text": node.get_text()}}}
        for node in container.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])]}
    validate_heading_outline(html, payload)
    validate_readback_text(root / "report.md", {"success": True, "markdown": md})
    payload["blocks"] = [b for b in payload["blocks"] if "政策与风险" not in b["element"]["heading"]["text"]]
    with pytest.raises(ValueError):
        validate_heading_outline(html, payload)


@pytest.fixture
def weekly_bundle(bundle, sample_weekly_report):
    report, ledger, root = bundle
    risk = add_risk(report, ledger)
    weekly = deepcopy(sample_weekly_report)
    weekly["version"] = "1.1"
    sections = weekly["sections"]
    sections["frontier_models"]["vendor_groups"] = []
    sections["coding_agents"]["product_groups"] = []
    for section in ["action_items", "pattern_observations", "experiments_this_week", "practice_digest", "methodology_radar"]:
        sections[section]["items"] = []
    for key, value in sections["market_signals"].items():
        if isinstance(value, list): sections["market_signals"][key] = []
    product = report["sections"]["general_agents"]["items"][0]
    reference = action_for(report, "general_agents", product, "monitor")["references"][0]
    sections["general_agents"] = {"title": "通用与办公 Agent", "items": [{"product": product["product"], "use_case": product["use_case"],
        "weekly_changes": product["what_changed"], "implication": product["impact"], "references": [reference]}],
        "trend_judgment": "合成样例，不能外推趋势", "implication": "仅验证聚合契约", "empty_message": "无新增"}
    risk_ref = action_for(report, "general_agents", risk, "monitor")["references"][0]
    risk_ref.update(date="2026-04-09", origin_classification_note="原日报误归通用栏，本周按监管程序重新归类")
    sections["policy_risk"] = {"title": "政策与风险观察", "items": [{k: risk[k] for k in ["subject", "headline", "risk_kind", "event_status", "affected_scope", "decision_relevance", "evidence_limits"]}], "empty_message": "无新增"}
    sections["policy_risk"]["items"][0].update(weekly_changes="合成程序增量", references=[risk_ref])
    for day in weekly["source_days"]["daily_reports_used"]:
        daily = deepcopy(report)
        daily["date"] = day
        if day != report["date"]:
            daily["version"] = "1.0"
            daily["sections"].pop("policy_risk")
            if day == "2026-04-09":
                daily["sections"]["general_agents"]["items"] = [{**risk, "product": "合成旧格式机构名称", "release_stage": "announced"}]
        cache = root / "cache" / day
        cache.mkdir(parents=True, exist_ok=True)
        (cache / "report.json").write_text(json.dumps(daily))
    (root / "cache" / report["date"] / "candidate_ledger.json").write_text(json.dumps(ledger))
    weekly["source_days"]["recall_ack"] = True
    return weekly, report, ledger, root


def test_mixed_week_reclassification_preserves_original_reference(weekly_bundle):
    weekly, _, _, root = weekly_bundle
    assert validate_report_schema(weekly) == []
    assert validate_weekly_references(weekly, root) == []
    assert validate_agent_weekly(weekly, root) == []
    ref = weekly["sections"]["policy_risk"]["items"][0]["references"][0]
    del ref["origin_classification_note"]
    assert any("origin_classification_note" in e for e in validate_agent_weekly(weekly, root))


def test_weekly_items_indexes_market_boundaries_and_render(weekly_bundle, sample_weekly_report):
    weekly, _, _, root = weekly_bundle
    observation = deepcopy(sample_weekly_report["sections"]["pattern_observations"]["items"][0])
    observation["supporting_item_refs"] = ["general_agents[0]", "policy_risk[0]"]
    weekly["sections"]["pattern_observations"]["items"] = [observation]
    assert validate_weekly_item_refs(weekly) == []
    path = root / "weekly.json"
    path.write_text(json.dumps(weekly, ensure_ascii=False))
    soup = BeautifulSoup(render(path, root / "weekly.html").read_text(), "html.parser")
    assert soup.find(id="general_agents-0") and soup.find(id="policy_risk-0")
    assert "新发布 / 新爆火" not in soup.get_text() and "头部大厂动作" not in soup.get_text()
    assert all(soup.find(id=a["href"][1:]) for a in soup.select('a[href^="#"]'))
    observation["supporting_item_refs"][0] = "general_agents[1]"
    assert validate_weekly_item_refs(weekly)
    weekly["sections"]["market_signals"]["benchmark_watch"] = [{"ref": "policy_risk[0]"}]
    assert any("product reference" in e for e in validate_weekly_item_refs(weekly))


def test_weekly_actions_cannot_upgrade_or_skip_legacy_review(weekly_bundle):
    weekly, report, ledger, root = weekly_bundle
    risk = report["sections"]["policy_risk"]["items"][0]
    weekly["sections"]["action_items"]["items"] = [action_for(report, "policy_risk", risk, "migrate")]
    assert any("exceeds eligibility" in e for e in validate_agent_weekly(weekly, root))
    action = weekly["sections"]["action_items"]["items"][0]
    action["recommendation_type"] = "monitor"
    assert validate_agent_weekly(weekly, root) == []
    action["references"][0].update(date="2026-04-09", section="general_agents")
    assert any("re-review unavailable" in e for e in validate_agent_weekly(weekly, root))


def test_weekly_dry_run_keeps_send_disabled(weekly_bundle, monkeypatch):
    from report_runner import run_weekly_finalize
    weekly, _, _, root = weekly_bundle
    cache = root / "cache" / "weekly" / weekly["week_end"]
    cache.mkdir(parents=True)
    (cache / "report.json").write_text(json.dumps(weekly))
    (cache / "input_days.json").write_text(json.dumps({"expected_report_version": "1.1"}))
    env = root / "test.env"
    env.write_text("GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=fixture\nREPORT_RECIPIENTS=target@example.com\n")
    def fail_send(*args, **kwargs):
        pytest.fail("dry-run must never invoke send")
    monkeypatch.setattr("report_runner._send_mail", fail_send)
    code, message = run_weekly_finalize(root, weekly["week_end"], True, env)
    assert code == 0, message
    assert (cache / "report.html").exists()


def test_legacy_action_can_use_isolated_re_review_without_rewriting_origin(weekly_bundle):
    import shutil
    weekly, report, ledger, root = weekly_bundle
    risk = report["sections"]["policy_risk"]["items"][0]
    action = action_for(report, "general_agents", risk, "monitor")
    action["references"][0]["date"] = "2026-04-09"
    weekly["sections"]["action_items"]["items"] = [action]
    original_path = root / "cache" / "2026-04-09" / "report.json"
    original = original_path.read_bytes()
    review_cache = root / "cache" / "weekly" / weekly["week_end"] / "evidence_reviews" / "cache" / "2026-04-09"
    review_cache.mkdir(parents=True)
    shutil.copytree(root / "cache" / report["date"] / "evidence", review_cache / "evidence")
    reviewed = {**deepcopy(report), "date": "2026-04-09"}
    reviewed_ledger = {**deepcopy(ledger), "date": "2026-04-09"}
    (review_cache / "report.json").write_text(json.dumps(reviewed))
    (review_cache / "candidate_ledger.json").write_text(json.dumps(reviewed_ledger))
    assert validate_agent_weekly(weekly, root) == []
    assert original_path.read_bytes() == original
    action["recommendation_type"] = "migrate"
    assert any("exceeds eligibility" in e for e in validate_agent_weekly(weekly, root))


def test_runner_rejects_downgrade_before_render_or_send(bundle, monkeypatch):
    report, ledger, root = bundle
    cache = root / "cache" / report["date"]
    report["version"] = "1.0"
    for name, value in [("report.json", report), ("candidate_ledger.json", ledger), ("discovery_manifest.json", build_discovery_manifest(report["date"], report["window"], load_whitelist()))]:
        (cache / name).write_text(json.dumps(value))
    env = root / "test.env"
    env.write_text("GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=fixture\nREPORT_RECIPIENTS=target@example.com\n")
    def forbidden(*args, **kwargs):
        pytest.fail("downgraded new report must stop before rendering or sending")
    monkeypatch.setattr("report_runner.render", forbidden)
    monkeypatch.setattr("report_runner._send_mail", forbidden)
    code, message = run_daily_finalize(root, report["date"], True, env)
    assert code == 1 and "batch version requires 1.2" in message


def test_workplace_matrix_resolves_shared_sources(sample_whitelist):
    from discovery import load_profile, required_discovery_names
    names = set(required_discovery_names(sample_whitelist))
    for entry in load_profile()["workplace_task_coverage"]:
        assert set(entry["sources"]) <= names


def test_prepared_chunk_is_not_a_receipt_and_truncated_output_cannot_ack(tmp_path):
    raw = '中文返回\\n"quote"\r\n' * 100
    artifact = save_response(tmp_path, raw, collected_at="2026-09-28T12:00:00+08:00", batch_id="transport", query_ids=["q"], limitations=[])
    prepared = read_response(tmp_path, artifact, start=0, end=len(raw))
    assert "receipt" not in prepared
    actual = json.dumps(prepared, ensure_ascii=False)
    for broken in [actual[:230], actual + "Warning: truncated output", json.dumps({**prepared, "content": prepared["content"][:230]})]:
        with pytest.raises(ValueError):
            receipt_from_output(tmp_path, artifact, returned_output=broken)
    receipt = receipt_from_output(tmp_path, artifact, returned_output=actual)
    assert review_coverage(raw, [receipt])["complete"]


def test_batched_long_response_is_rejected_and_missing_middle_cannot_complete(tmp_path):
    raw = "真实长批次模拟" * 5000
    artifact = save_response(tmp_path, raw, collected_at="2026-09-28T12:00:00+08:00", batch_id="large", query_ids=["q"], limitations=[])
    with pytest.raises(ValueError, match="at most"):
        read_response(tmp_path, artifact, start=0, end=len(raw))
    receipts = []
    for start in range(0, len(raw), MAX_REVIEW_CHARS):
        if start == MAX_REVIEW_CHARS:
            continue  # A truncated middle response never earns an acknowledgement.
        actual = json.dumps(read_response(tmp_path, artifact, start=start, end=min(start + MAX_REVIEW_CHARS, len(raw))))
        receipts.append(receipt_from_output(tmp_path, artifact, returned_output=actual))
    assert not review_coverage(raw, receipts)["complete"]
    actual = json.dumps(read_response(tmp_path, artifact, start=MAX_REVIEW_CHARS, end=2 * MAX_REVIEW_CHARS))
    receipts.append(receipt_from_output(tmp_path, artifact, returned_output=actual))
    assert review_coverage(raw, receipts)["complete"]


def test_many_audit_notes_do_not_flood_reader_output_and_empty_messages_survive(bundle):
    report, _, root = bundle
    attempt = deepcopy(report["fetch_status"]["source_details"]["Fixture Official"]["attempts"][0])
    for i in range(163):
        a = deepcopy(attempt)
        a["evidence_artifact"]["limitations"] = ["source page is an excerpt"]
        a["review"]["reason"] = f"内部逐次审计记录{i}：完整保留但不逐条发给读者。"
        report["fetch_status"]["source_details"][f"Synthetic source {i}"] = {**deepcopy(report["fetch_status"]["source_details"]["Fixture Official"]), "attempts": [a]}
    report["coverage_summary"] = "飞书正文与日期尚未补齐，不能据此判断没有办公产品更新。"
    for key in ["frontier_models", "coding_agents", "unverified"]:
        report["sections"][key]["empty_message"] = f"{key}本期未确认新增，仍有明确覆盖缺口。"
    path = root / "reader.json"
    path.write_text(json.dumps(report))
    html = render(path)
    md = render_markdown(html, root / "reader.md").read_text()
    soup = BeautifulSoup(html.read_text(), "html.parser")
    assert len(soup.select("#coverage-summary")) == 1
    assert report["coverage_summary"] in md
    assert "内部逐次审计记录" not in md
    for key in ["frontier_models", "coding_agents", "unverified"]:
        assert report["sections"][key]["empty_message"] in md


def test_new_report_requires_editorial_coverage_summary(bundle):
    report, _, _ = bundle
    del report["coverage_summary"]
    assert any("coverage_summary" in e for e in validate_report_schema(report))


def test_daily_skip_records_unknown_historical_revision_without_resending(bundle, monkeypatch):
    from send_state import record_sent
    report, ledger, root = bundle
    cache = root / "cache" / report["date"]
    for name, value in [("report.json", report), ("candidate_ledger.json", ledger), ("discovery_manifest.json", build_discovery_manifest(report["date"], report["window"], load_whitelist()))]:
        (cache / name).write_text(json.dumps(value))
    record_sent(cache, "daily", "previous report", artifact_path=None)
    record_sent(cache, "ledger", "recorded", artifact_path=None)
    previous = (cache / "send_state.json").read_bytes()
    env = root / "test.env"
    env.write_text("GMAIL_USER=test@example.com\nGMAIL_APP_PASSWORD=fixture\nREPORT_RECIPIENTS=target@example.com\n")
    from send_state import delivery_attempt

    def skip_sender(project_root, html_path, subject, env_path, cache_dir, state_key):
        with delivery_attempt(cache_dir, state_key, subject, html_path.read_bytes(),
                              "test@example.com", ["target@example.com"]) as attempt:
            assert attempt is None, "legacy acceptance receipt must prevent a new SMTP submission"
        return 0, json.dumps({"outcome": "skipped_existing"})

    monkeypatch.setattr("report_runner._send_mail", skip_sender)
    code, message = run_daily_finalize(root, report["date"], False, env)
    assert code == 0, message
    result = json.loads((cache / "delivery_result.json").read_text())
    assert result["outcome"] == "skipped_existing"
    assert result["sent_html_sha256"] is None
    assert result["current_revision_delivered"] is None
    assert (cache / "send_state.json").read_bytes() == previous
