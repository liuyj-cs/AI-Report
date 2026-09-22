"""Reader-facing model evidence must survive schema, source closure, and rendering."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jsonschema import Draft202012Validator

from editorial import validate_model_assessments
from render_html import load_schema, render

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def report():
    data = json.loads((FIXTURES / "sample_daily.json").read_text())
    data["version"] = "1.1"
    data["reading_guide"] = [{"text": "评测有优势，也有未验证的边界。", "ref": "frontier_models[0]"}]
    for item in data["sections"]["frontier_models"]["items"]:
        item["model_assessment"] = {
            "status": "insufficient_evidence", "conclusion": "暂不能判断能力变化。",
            "strengths": [], "limitations": [], "evidence_gaps": ["尚未取得独立分项评测。"], "groups": [],
        }
    return data


def with_scores(report):
    data = deepcopy(report)
    url = "https://eval.example/model"
    data["fetch_status"]["source_details"]["Eval"] = {"final_layer_index": 0, "final_layer_type": "webfetch", "via_broad_search": False, "attempts": [{"layer_index": 0, "layer_type": "webfetch", "target": url, "result": "success"}]}
    data["sections"]["frontier_models"]["items"][0]["model_assessment"] = {
        "status": "assessed", "conclusion": "指数不是百分制。", "strengths": ["代码任务"],
        "limitations": ["工具配置不同不能直接比较"], "evidence_gaps": [],
        "groups": [{
            "title": "可核验评测", "source_name": "Evaluator", "source_url": url,
            "evidence_type": "independent", "observed_at": data["generated_at"],
            "conditions": "统一运行框架；样本量未披露。", "metrics": [{
                "benchmark": "Knowledge Index v1", "what_it_tests": "知识可靠性",
                "model_variant": "Model A high", "score": -2, "unit": "指数分",
                "direction": "higher_better", "comparators": [{"model_variant": "Model B high", "score": 0}],
                "interpretation": "负分不等于缺数据。<script>alert(1)</script>",
            }],
        }],
    }
    return data


def errors(data):
    return list(Draft202012Validator(load_schema("daily")).iter_errors(data))


def test_new_report_requires_assessment_even_for_nonmajor_models(report):
    assert not errors(report)
    report["sections"]["frontier_models"]["items"][0].pop("model_assessment")
    assert errors(report)


def test_missing_evidence_must_be_explicit(report):
    report["sections"]["frontier_models"]["items"][0]["model_assessment"]["evidence_gaps"] = []
    assert errors(report)


@pytest.mark.parametrize("field", ["score", "unit", "model_variant", "what_it_tests", "comparators", "interpretation"])
def test_metric_cannot_silently_omit_context(report, field):
    data = with_scores(report)
    assert not errors(data)
    data["sections"]["frontier_models"]["items"][0]["model_assessment"]["groups"][0]["metrics"][0].pop(field)
    assert errors(data)


def test_assessed_cannot_be_an_empty_claim(report):
    report["sections"]["frontier_models"]["items"][0]["model_assessment"]["status"] = "assessed"
    assert errors(report)


def test_exact_source_attempt_must_succeed(report):
    data = with_scores(report)
    assert validate_model_assessments(data) == []
    data["fetch_status"]["source_details"]["Eval"]["attempts"][0]["result"] = "success_but_empty"
    assert "successful exact-URL" in validate_model_assessments(data)[0]
    data["fetch_status"]["source_details"]["Eval"]["attempts"][0] = {"target": "https://eval.example", "result": "success"}
    assert validate_model_assessments(data)


def test_observation_time_and_guide_references_are_checked(report):
    data = with_scores(report)
    group = data["sections"]["frontier_models"]["items"][0]["model_assessment"]["groups"][0]
    for bad in ["invalid", "2099-01-01T00:00:00+08:00", "2026-01-01T00:00:00"]:
        group["observed_at"] = bad
        assert validate_model_assessments(data)
    group["observed_at"] = data["generated_at"]
    data["reading_guide"][0]["ref"] = "frontier_models[999]"
    assert "points past" in validate_model_assessments(data)[0]


def test_score_groups_are_readable_safe_and_linked(tmp_path, report):
    data = with_scores(report)
    assert not errors(data)
    src = tmp_path / "report.json"
    src.write_text(json.dumps(data))
    soup = BeautifulSoup(render(src).read_text(), "html.parser")
    assessment = soup.select_one(".assessment")
    assert "独立评测" in assessment.get_text()
    assert "-2指数分" in assessment.get_text()
    assert "0指数分" in assessment.get_text()
    assert not assessment.select("script")
    assert assessment.select_one("a")["href"] == "https://eval.example/model"
    assert "frontier_models[0]" not in soup.get_text()
    assert soup.select_one(".reading-guide a")["href"] == "#frontier_models-0"


def test_legacy_unresolved_reference_is_visible_without_render_crash(tmp_path, report):
    report["version"] = "1.0"
    report["sections"]["pattern_observations"]["items"][0]["supporting_item_refs"][0] = "frontier_models[999]"
    src = tmp_path / "report.json"
    src.write_text(json.dumps(report))
    soup = BeautifulSoup(render(src).read_text(), "html.parser")
    assert "引用条目不可用，需核对" in soup.get_text()
    assert not soup.select('a[href="#frontier_models-999"]')


@pytest.mark.parametrize("bad", [None, [], {"status": "assessed"}])
def test_finalize_reports_malformed_assessment_without_crashing(report, bad):
    report["sections"]["frontier_models"]["items"][0]["model_assessment"] = bad
    assert "model_assessment" in validate_model_assessments(report)[0]


def test_finalize_requires_new_assessment_but_allows_legacy(report):
    for item in report["sections"]["frontier_models"]["items"]:
        item.pop("model_assessment")
    assert validate_model_assessments(report)
    report["version"] = "1.0"
    assert validate_model_assessments(report) == []


def test_comparator_sources_need_successful_exact_fetch(report):
    data = with_scores(report)
    group = data['sections']['frontier_models']['items'][0]['model_assessment']['groups'][0]
    group['supporting_sources'] = [{'source_name': 'Comparator', 'source_url': 'https://eval.example/other'}]
    assert not errors(data)
    assert 'supporting_sources[0]' in validate_model_assessments(data)[0]
    data['fetch_status']['source_details']['Eval']['attempts'].append({'target': 'https://eval.example/other', 'result': 'success'})
    assert validate_model_assessments(data) == []


def test_model_hierarchy_survives_html_and_markdown(tmp_path, report):
    from render_markdown import render_markdown
    data = with_scores(report)
    models = data['sections']['frontier_models']['items']
    models[1]['model_assessment'] = deepcopy(models[0]['model_assessment'])
    models[1]['model_assessment']['groups'][0]['title'] = '第二款模型评测'
    src = tmp_path / 'report.json'
    src.write_text(json.dumps(data))
    html = render(src)
    soup = BeautifulSoup(html.read_text(), 'html.parser')
    for index, item in enumerate(models):
        card = soup.select_one(f'#frontier_models-{index}')
        assert card.select_one('.headline').name == 'h3'
        assert card.select_one('.assessment h4').get_text() == '能力评测与分数'
        assert card.select_one('.assessment h5').get_text().startswith(item['model_assessment']['groups'][0]['title'])
    md = render_markdown(html, tmp_path / 'report.md').read_text()
    guide = md.split('## 今日核心判断')[1].split('## 一、')[0]
    assert data['reading_guide'][0]['text'] in guide
    assert models[0]['headline'] not in guide
    assert '查看详评' not in guide
    for item in models:
        section = md.split('### ' + item['headline'])[1].split('\n### ')[0]
        assert '\n#### 能力评测与分数' in section
        assert '\n##### ' + item['model_assessment']['groups'][0]['title'] in section
