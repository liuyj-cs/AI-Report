from editorial import recall_fallback_findings, validate_recall_fallback_coverage


def _whitelist(layer0, *, category="cn_labs", name="DeepSeek"):
    return {
        "cn_labs": [
            {
                "name": name,
                "category": category,
                "fetch_chain": [
                    layer0,
                    {"type": "websearch_scoped", "queries": ["DeepSeek release {date}"]},
                ],
            }
        ]
    }


def _empty_report(attempts, *, name="DeepSeek", final_layer_index=0):
    return {
        "fetch_status": {
            "succeeded": [name],
            "failed": [],
            "empty": [name],
            "source_details": {
                name: {"final_layer_index": final_layer_index, "attempts": attempts}
            },
        }
    }


STATIC_ATTEMPT = [
    {"layer_index": 0, "layer_type": "webfetch", "target": "x", "result": "success_but_empty"}
]


def test_feed_layer_empty_is_conclusive_and_does_not_block():
    whitelist = _whitelist({"type": "webfetch", "url": "https://api-docs.deepseek.com/updates", "surface_kind": "feed"})

    assert validate_recall_fallback_coverage(_empty_report(STATIC_ATTEMPT), whitelist) == []


def test_static_layer_empty_without_search_still_blocks():
    whitelist = _whitelist({"type": "webfetch", "url": "https://deepseek.com/", "surface_kind": "static"})

    errors = validate_recall_fallback_coverage(_empty_report(STATIC_ATTEMPT), whitelist)

    assert len(errors) == 1
    assert "DeepSeek" in errors[0]


def test_unlabelled_webfetch_layer_defaults_to_static():
    """未标注 = 现状行为(必须下穿),保守缺省不给漏采开口子。"""
    whitelist = _whitelist({"type": "webfetch", "url": "https://deepseek.com/"})

    assert len(validate_recall_fallback_coverage(_empty_report(STATIC_ATTEMPT), whitelist)) == 1


def test_github_releases_layer_defaults_to_feed():
    whitelist = _whitelist({"type": "github_releases", "repo": "deepseek-ai/DeepSeek-V3"})
    attempts = [
        {"layer_index": 0, "layer_type": "github_releases", "target": "x", "result": "success_but_empty"}
    ]

    assert validate_recall_fallback_coverage(_empty_report(attempts), whitelist) == []


def test_search_attempt_still_clears_a_static_layer():
    whitelist = _whitelist({"type": "webfetch", "url": "https://deepseek.com/", "surface_kind": "static"})
    attempts = STATIC_ATTEMPT + [
        {"layer_index": 1, "layer_type": "websearch_scoped", "target": "q", "result": "success_but_empty"}
    ]

    assert validate_recall_fallback_coverage(_empty_report(attempts, final_layer_index=1), whitelist) == []


def test_non_high_recall_category_never_blocks():
    """阻塞范围仍限 cn_labs / hard_data;其他类别的 surface_kind 只是 AI 的输入数据。"""
    whitelist = {
        "us_labs": [
            {
                "name": "SomeMedia",
                "category": "english_media",
                "fetch_chain": [
                    {"type": "webfetch", "url": "https://example.com/", "surface_kind": "static"},
                    {"type": "websearch_scoped", "queries": ["q"]},
                ],
            }
        ]
    }
    report = _empty_report(STATIC_ATTEMPT, name="SomeMedia")

    assert validate_recall_fallback_coverage(report, whitelist) == []


def test_final_layer_index_out_of_range_is_treated_as_static():
    whitelist = _whitelist({"type": "webfetch", "url": "u", "surface_kind": "feed"})
    attempts = [
        {"layer_index": 9, "layer_type": "webfetch", "target": "x", "result": "success_but_empty"}
    ]

    assert len(validate_recall_fallback_coverage(_empty_report(attempts, final_layer_index=9), whitelist)) == 1


def test_null_attempts_are_tolerated_and_flagged():
    whitelist = _whitelist({"type": "webfetch", "url": "u", "surface_kind": "static"})
    report = _empty_report(None)
    report["fetch_status"]["source_details"]["DeepSeek"].pop("final_layer_index")

    findings = recall_fallback_findings(report, whitelist)

    assert any(finding["source_name"] == "DeepSeek" for finding in findings)


def test_empty_is_conclusive_field_is_retired():
    """退役字段不再有豁免效力——surface_kind 是唯一真相源,避免双轨。"""
    whitelist = _whitelist({"type": "webfetch", "url": "u", "surface_kind": "static"})
    whitelist["cn_labs"][0]["empty_is_conclusive"] = True

    assert len(validate_recall_fallback_coverage(_empty_report(STATIC_ATTEMPT), whitelist)) == 1


def test_findings_stay_high_severity_and_missed_discovery():
    whitelist = _whitelist({"type": "webfetch", "url": "u", "surface_kind": "static"})

    findings = recall_fallback_findings(_empty_report(STATIC_ATTEMPT), whitelist)

    assert findings[0]["severity"] == "high"
    assert findings[0]["category"] == "missed_discovery"
