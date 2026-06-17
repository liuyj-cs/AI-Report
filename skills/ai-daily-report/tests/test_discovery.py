import pytest

from discovery import (
    GENERAL_SEARCH_SURFACE_NAME,
    GOOGLE_SEARCH_PRODUCT_BLOG_NAME,
    GITHUB_TRENDING_WEEKLY_NAME,
    HIGH_SIGNAL_MEDIA_DISCOVERY_NAME,
    append_run_log,
    build_discovery_manifest,
    compute_daily_window,
    initial_fetch_status,
    missing_fetch_status_coverage,
    required_discovery_names,
    required_source_family_names,
    rolling_week_dates,
)


def test_rolling_week_dates_returns_seven_ascending_days_ending_at_week_end():
    assert rolling_week_dates("2026-06-13") == [
        "2026-06-07", "2026-06-08", "2026-06-09", "2026-06-10",
        "2026-06-11", "2026-06-12", "2026-06-13",
    ]


def test_rolling_week_dates_crosses_month_boundary():
    assert rolling_week_dates("2026-05-03") == [
        "2026-04-27", "2026-04-28", "2026-04-29", "2026-04-30",
        "2026-05-01", "2026-05-02", "2026-05-03",
    ]


def test_rolling_week_dates_rejects_iso_week_string():
    # fromisoformat would silently accept "2026-W20"; the shared guard must reject it
    with pytest.raises(ValueError):
        rolling_week_dates("2026-W20")


def test_initial_fetch_status_contains_all_required_sources_with_pending_skeleton(sample_whitelist):
    result = initial_fetch_status(sample_whitelist)
    required = required_discovery_names(sample_whitelist)
    family_names = set(required_source_family_names(sample_whitelist))
    assert sorted(result["source_details"]) == sorted(required)
    for name, detail in result["source_details"].items():
        for attempt in detail["attempts"]:
            if name in family_names:
                assert attempt.get("note") == "surface coverage tracked via member sources"
            else:
                assert attempt.get("reason") == "pending discovery"


def test_build_discovery_manifest_includes_openai_fallback_and_queries(sample_whitelist):
    window = compute_daily_window("2026-04-18", "2026-04-18T07:30:00+08:00")
    manifest = build_discovery_manifest("2026-04-18", window, sample_whitelist)

    openai = next(item for item in manifest["required_sources"] if item["name"] == "OpenAI")
    assert "https://openai.com/index/" in openai["one_hop_fallback_targets"]
    assert "https://openai.com/index/?topic=company" in openai["one_hop_fallback_targets"]
    assert any("OpenAI Microsoft partnership" in query for query in manifest["high_signal_media_queries"])
    assert any("AI acquisition regulation" in query for query in manifest["high_signal_media_queries"])
    assert manifest["general_agent_search_queries"] == sample_whitelist["general_agent_search_queries"]
    assert "Hacker News top 50" in manifest["required_discovery_surfaces"]
    assert GOOGLE_SEARCH_PRODUCT_BLOG_NAME in manifest["required_discovery_surfaces"]
    assert HIGH_SIGNAL_MEDIA_DISCOVERY_NAME in manifest["required_discovery_surfaces"]
    assert "official_release_surface" in manifest["source_families"]


def test_build_discovery_manifest_includes_qwen_and_google_product_fallbacks(sample_whitelist):
    window = compute_daily_window("2026-04-18", "2026-04-18T07:30:00+08:00")
    manifest = build_discovery_manifest("2026-04-18", window, sample_whitelist)

    qwen = next(item for item in manifest["required_sources"] if item["name"] == "阿里 Qwen")
    google_ai = next(item for item in manifest["required_sources"] if item["name"] == "Google AI Blog")

    assert "https://qwen.ai/blog/" in qwen["one_hop_fallback_targets"]
    assert "https://qwen.ai/" in qwen["one_hop_fallback_targets"]
    assert "https://blog.google/products/search/" in google_ai["one_hop_fallback_targets"]
    assert "https://blog.google/products/chrome/" in google_ai["one_hop_fallback_targets"]


def test_required_discovery_names_contains_sources_and_synthetic_surfaces(sample_whitelist):
    names = required_discovery_names(sample_whitelist)
    assert "OpenAI" in names
    assert GENERAL_SEARCH_SURFACE_NAME in names
    assert GITHUB_TRENDING_WEEKLY_NAME in names
    assert GOOGLE_SEARCH_PRODUCT_BLOG_NAME in names
    assert HIGH_SIGNAL_MEDIA_DISCOVERY_NAME in names
    assert "official_changelog_surface" in names
    assert "hard_data_surface" in names


def test_missing_fetch_status_coverage_reports_missing_required_names(sample_whitelist, sample_daily_report):
    missing = missing_fetch_status_coverage(sample_daily_report, sample_whitelist)
    assert "OpenAI" not in missing
    assert GOOGLE_SEARCH_PRODUCT_BLOG_NAME in missing
    assert HIGH_SIGNAL_MEDIA_DISCOVERY_NAME in missing
    assert "official_release_surface" in missing


def test_append_run_log_appends_lines(tmp_path):
    path = tmp_path / "run.log"
    append_run_log(path, "line-1")
    append_run_log(path, "line-2")
    assert path.read_text(encoding="utf-8") == "line-1\nline-2\n"


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
    broad = next(layer for layer in deepseek["fetch_chain"] if layer.get("type") == "websearch_broad")
    assert "DeepSeek vision multimodal {date}" in broad["queries"]
    assert "DeepSeek image recognition beta {date}" in broad["queries"]

    watchlist_names = {item["name"] for item in sample_whitelist["general_agent_watchlist"]}
    assert "Zed" in watchlist_names
    assert "Microsoft 365 Copilot Adoption" in watchlist_names

    assert "AI-native editor agent protocol {date}" in sample_whitelist["general_agent_search_queries"]
    assert "Microsoft 365 Copilot paid seats earnings call {date}" in sample_whitelist["high_signal_media_queries"]
    assert "Cursor SDK @cursor/sdk public beta {date}" in sample_whitelist["recall_probe_queries"]
    assert "Zed 1.0 AI-native editor Agent Client Protocol {date}" in sample_whitelist["recall_probe_queries"]
    assert "DeepSeek vision multimodal beta {date}" in sample_whitelist["recall_probe_queries"]
    assert "Microsoft 365 Copilot paid seats weekly engagement {date}" in sample_whitelist["recall_probe_queries"]


def test_whitelist_contains_ai_hot_media_source(sample_whitelist):
    ai_hot = next(item for item in sample_whitelist["chinese_media"] if item["name"] == "AI HOT")

    assert ai_hot["authority_tier"] == 2
    assert ai_hot["source_family"] == "broad_discovery_surface"
    assert ai_hot["weight"] == "high"
    assert ai_hot["fetch_chain"][0] == {
        "type": "webfetch",
        "url": "https://aihot.virxact.com/",
    }
    assert ai_hot["fetch_chain"][1] == {
        "type": "webfetch",
        "url": "https://aihot.virxact.com/all",
    }
    assert "AI HOT site:aihot.virxact.com {date}" in ai_hot["fetch_chain"][2]["queries"]


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
