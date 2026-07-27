"""whitelist 数据守恒：surface_kind 标注齐全性与 AI HOT 结构化 API 面。

空判定必须能从 whitelist 数据读出来，而不是每天由不同会话按"体感规则"重新理解——
这些测试就是那条数据契约的机器门。
"""
from discovery import iter_named_sources

AIHOT_SELECTED_URL = "https://aihot.virxact.com/api/v1/items?mode=selected&window=24h&limit=50"
AIHOT_ALL_URL = "https://aihot.virxact.com/api/v1/items?mode=all&window=24h&limit=50"


def _source(whitelist, name):
    for source in iter_named_sources(whitelist):
        if source["name"] == name:
            return source
    raise AssertionError(f"whitelist 中找不到源 {name!r}")


def test_every_webfetch_layer_declares_surface_kind(sample_whitelist):
    offenders = []
    for source in iter_named_sources(sample_whitelist):
        for index, layer in enumerate(source["fetch_chain"]):
            if layer.get("type") != "webfetch":
                continue
            if layer.get("surface_kind") not in ("feed", "static"):
                offenders.append(f"{source['name']}.fetch_chain[{index}] -> {layer.get('surface_kind')!r}")

    assert offenders == [], f"缺 surface_kind 标注或值非法的层: {offenders}"


def test_search_layers_never_declare_surface_kind(sample_whitelist):
    """搜索层的类型即语义，标 surface_kind 是噪音，也会误导守门判据。"""
    offenders = []
    for source in iter_named_sources(sample_whitelist):
        for index, layer in enumerate(source["fetch_chain"]):
            if layer.get("type") in ("websearch_scoped", "websearch_broad") and "surface_kind" in layer:
                offenders.append(f"{source['name']}.fetch_chain[{index}]")

    assert offenders == []


def test_empty_is_conclusive_is_fully_retired(sample_whitelist):
    offenders = [
        source["name"] for source in iter_named_sources(sample_whitelist) if "empty_is_conclusive" in source
    ]

    assert offenders == [], f"已退役字段仍在使用: {offenders}"


def test_high_recall_sources_have_search_fallback(sample_whitelist):
    """cn_labs / hard_data 的 static 面空必须能下穿——链里得真有搜索层可下穿。"""
    offenders = []
    for source in iter_named_sources(sample_whitelist):
        if source.get("category") not in ("cn_labs", "hard_data"):
            continue
        types = {layer.get("type") for layer in source["fetch_chain"]}
        if not types & {"websearch_scoped", "websearch_broad"}:
            offenders.append(source["name"])

    assert offenders == []


def test_aihot_uses_structured_api_layers(sample_whitelist):
    """selected 是策展池（空≠无新闻→static，必须下穿）；all 才是全量倒序面（feed）。"""
    source = _source(sample_whitelist, "AI HOT")
    selected, full = source["fetch_chain"][0], source["fetch_chain"][1]

    assert selected == {"type": "webfetch", "url": AIHOT_SELECTED_URL, "surface_kind": "static"}
    assert full == {"type": "webfetch", "url": AIHOT_ALL_URL, "surface_kind": "feed"}


def test_aihot_keeps_search_fallback_and_daily_pin(sample_whitelist):
    source = _source(sample_whitelist, "AI HOT")

    assert source["cadence"] == "daily"
    assert source["authority_tier"] == 2  # 聚合面角色不变，候选仍走 media 降档
    assert any(
        layer["type"] in ("websearch_scoped", "websearch_broad") for layer in source["fetch_chain"]
    )


def test_aihot_no_longer_scrapes_html_home(sample_whitelist):
    source = _source(sample_whitelist, "AI HOT")
    urls = [layer.get("url", "") for layer in source["fetch_chain"]]

    assert "https://aihot.virxact.com/" not in urls
    assert "https://aihot.virxact.com/all" not in urls


def test_aihot_pin_makes_it_exempt_from_downgrade(sample_whitelist):
    """pin 的行为断言：命中率再低也留在每日档。"""
    from datetime import date, timedelta

    from discovery import compute_cadence

    target = "2026-07-27"
    days = {
        (date.fromisoformat(target) - timedelta(days=offset)).isoformat(): {
            "AI HOT": {"attempts": 1, "hit": False}
        }
        for offset in range(1, 31)
    }
    plan = compute_cadence(sample_whitelist, {"version": "1.0", "days": days}, target)

    assert plan["AI HOT"]["cadence"] == "daily"
    assert plan["AI HOT"]["due"] is True
