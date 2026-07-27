#!/usr/bin/env python3
"""Deterministic discovery helpers for AI-authored report runs."""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import json
from pathlib import Path
import re
from typing import Any, Iterator

import yaml

from evidence import suggest_one_hop_targets
from source_stats import load_source_stats
from tracking import TRACKING_SURFACE_PREFIX


WHITELIST_PATH = Path(__file__).resolve().parent.parent / "sources" / "whitelist.yaml"
PROFILE_PATH = Path(__file__).resolve().parent.parent / "sources" / "profile.yaml"
GENERAL_SEARCH_SURFACE_NAME = "General Agent Search Queries"
GITHUB_TRENDING_DAILY_NAME = "GitHub Trending (daily)"
GITHUB_TRENDING_WEEKLY_NAME = "GitHub Trending (weekly)"
GOOGLE_SEARCH_PRODUCT_BLOG_NAME = "Google Search Product Blog"
HIGH_SIGNAL_MEDIA_DISCOVERY_NAME = "High-Signal Media Discovery"
RECALL_PROBE_SURFACE_NAME = "High-Recall Product/Adoption Probes"
ECOSYSTEM_DISCOVERY_NAME = "Agent Ecosystem Discovery"
LEADER_INTERVIEW_DISCOVERY_NAME = "Leader Interview Discovery"
METHODOLOGY_DISCOVERY_NAME = "Methodology Radar Discovery"
HACKER_NEWS_NAME = "Hacker News front page"
# 慢信号轨道：准入窗 7/14 天，隔日探查零实质损失；固定档比按命中率浮动更可预期。
SLOW_TRACK_SURFACES = (LEADER_INTERVIEW_DISCOVERY_NAME, METHODOLOGY_DISCOVERY_NAME)
CADENCE_INTERVALS = {"daily": 1, "every_2_days": 2, "weekly": 7}
CADENCE_WINDOW_DAYS = 30
# 长尾判定的两道保护：探测样本够（实探日）与台账观察期够（首见距今）。
CADENCE_MIN_PROBED_DAYS = 10
CADENCE_MIN_LEDGER_AGE_DAYS = 14
CADENCE_DAILY_HIT_DAYS = 3
DEFAULT_SOURCE_FAMILIES = {
    "official_release_surface": {
        "description": "官方发布页、产品公告页与一级发布入口",
        "fallback_policy": "same_entity_one_hop",
    },
    "official_changelog_surface": {
        "description": "官方 changelog、release notes 与 GitHub Releases",
        "fallback_policy": "same_entity_one_hop",
    },
    "official_product_blog_surface": {
        "description": "官方博客、news/blog 索引与产品博客",
        "fallback_policy": "same_entity_one_hop",
    },
    "hard_data_surface": {
        "description": "榜单、benchmark、pricing 与趋势硬数据入口",
        "fallback_policy": "same_entity_one_hop",
    },
    "broad_discovery_surface": {
        "description": "广义搜索、媒体发现面与社区高信号入口",
        "fallback_policy": "same_entity_one_hop",
    },
}


def source_family_catalog(whitelist: dict[str, Any]) -> dict[str, dict[str, str]]:
    configured = whitelist.get("source_families")
    if isinstance(configured, dict) and configured:
        merged = json.loads(json.dumps(DEFAULT_SOURCE_FAMILIES, ensure_ascii=False))
        for name, payload in configured.items():
            if isinstance(payload, dict):
                merged[name] = {
                    "description": payload.get("description", merged.get(name, {}).get("description", "")),
                    "fallback_policy": payload.get("fallback_policy", "same_entity_one_hop"),
                }
        return merged
    return json.loads(json.dumps(DEFAULT_SOURCE_FAMILIES, ensure_ascii=False))


def infer_source_family(source: dict[str, Any]) -> str:
    explicit = source.get("source_family")
    if explicit:
        return explicit

    if source.get("category") == "hard_data":
        return "hard_data_surface"

    fetch_chain = source.get("fetch_chain", [])
    if any(layer.get("type") == "websearch_broad" for layer in fetch_chain):
        broad_family = "broad_discovery_surface"
    else:
        broad_family = ""

    if any(layer.get("type") == "github_releases" for layer in fetch_chain):
        return "official_changelog_surface"

    targets = []
    for layer in fetch_chain:
        if layer.get("url"):
            targets.append(layer["url"].lower())
        for query in layer.get("queries", []):
            targets.append(query.lower())
    if any(token in target for target in targets for token in ("changelog", "release-notes", "/releases", "release notes")):
        return "official_changelog_surface"
    if any(token in target for target in targets for token in ("/blog", "/news", "blog.", "what's new", "whats new")):
        return "official_product_blog_surface"
    if broad_family:
        return broad_family
    return "official_release_surface"


def required_source_family_names(whitelist: dict[str, Any]) -> list[str]:
    return list(source_family_catalog(whitelist).keys())


def load_whitelist(path: Path | None = None) -> dict[str, Any]:
    target = path or WHITELIST_PATH
    return yaml.safe_load(target.read_text(encoding="utf-8"))


def load_profile(path: Path | None = None) -> dict[str, Any]:
    target = path or PROFILE_PATH
    if not target.exists():
        return {}
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}


def iter_named_sources(whitelist: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for value in whitelist.values():
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict) and item.get("name") and item.get("fetch_chain"):
                yield item


def required_discovery_names(whitelist: dict[str, Any]) -> list[str]:
    names = [source["name"] for source in iter_named_sources(whitelist)]
    names.extend(
        [
            GENERAL_SEARCH_SURFACE_NAME,
            GOOGLE_SEARCH_PRODUCT_BLOG_NAME,
            HACKER_NEWS_NAME,
            GITHUB_TRENDING_DAILY_NAME,
            GITHUB_TRENDING_WEEKLY_NAME,
            HIGH_SIGNAL_MEDIA_DISCOVERY_NAME,
            RECALL_PROBE_SURFACE_NAME,
            ECOSYSTEM_DISCOVERY_NAME,
            LEADER_INTERVIEW_DISCOVERY_NAME,
            METHODOLOGY_DISCOVERY_NAME,
        ]
    )
    names.extend(required_source_family_names(whitelist))
    deduped: list[str] = []
    for name in names:
        if name not in deduped:
            deduped.append(name)
    return deduped


def _exempt_daily_names(whitelist: dict[str, Any]) -> set[str]:
    """恒每日探查的面:核心源 / tier1 官方 / hard_data / cadence pin / 聚合探针面。

    聚合面(搜索、召回探针、source_family、tracking)本身就是召回兜底,降频等于
    自断退路;慢信号轨道(访谈、方法论)例外,见 SLOW_TRACK_SURFACES。
    """
    exempt = {name for name in whitelist.get("core_sources", []) if name}
    for source in iter_named_sources(whitelist):
        if (
            source.get("authority_tier") == 1
            or source.get("category") == "hard_data"
            or source.get("cadence") == "daily"
        ):
            exempt.add(source["name"])
    named = {source["name"] for source in iter_named_sources(whitelist)}
    for name in required_discovery_names(whitelist):
        if name not in named and name not in SLOW_TRACK_SURFACES:
            exempt.add(name)
    return exempt


def _ledger_series(stats: dict[str, Any], name: str) -> list[tuple[date, bool]]:
    series: list[tuple[date, bool]] = []
    for day, entry in (stats.get("days") or {}).items():
        record = (entry or {}).get(name)
        if not isinstance(record, dict):
            continue
        try:
            series.append((date.fromisoformat(day), bool(record.get("hit"))))
        except ValueError:
            continue
    return sorted(series)


def _rank_cadence(series: list[tuple[date, bool]], target: date) -> str:
    """按近 30 天命中率分档;统计不足一律回 daily(宁多探不漏探)。"""
    if not series:
        return "daily"
    if (target - series[0][0]).days < CADENCE_MIN_LEDGER_AGE_DAYS:
        return "daily"
    window = [(day, hit) for day, hit in series if 0 <= (target - day).days <= CADENCE_WINDOW_DAYS]
    hit_days = sum(1 for _, hit in window if hit)
    if hit_days >= CADENCE_DAILY_HIT_DAYS:
        return "daily"
    if hit_days:
        return "every_2_days"
    if len(window) >= CADENCE_MIN_PROBED_DAYS:
        return "weekly"
    return "daily"


def compute_cadence(
    whitelist: dict[str, Any],
    stats: dict[str, Any],
    target_date: str,
) -> dict[str, dict[str, Any]]:
    """为每个发现面算出 cadence / due / last_probed。

    这是运维调度,不是编辑判断:cadence 只决定"今天探不探",不参与正文取舍与
    排序;非 due 面仍允许 AI 因外部信号唤醒(见 SKILL.md 采集节奏一节)。
    """
    target = date.fromisoformat(target_date)
    exempt = _exempt_daily_names(whitelist)
    plan: dict[str, dict[str, Any]] = {}
    for name in required_discovery_names(whitelist):
        series = _ledger_series(stats, name)
        last_probed = series[-1][0] if series else None
        if name in exempt:
            cadence = "daily"
        elif name in SLOW_TRACK_SURFACES:
            cadence = "every_2_days"
        else:
            cadence = _rank_cadence(series, target)
        interval = CADENCE_INTERVALS[cadence]
        due = last_probed is None or (target - last_probed).days >= interval
        plan[name] = {
            "cadence": cadence,
            "due": due,
            "last_probed": last_probed.isoformat() if last_probed else None,
        }
    return plan


def rolling_week_dates(week_end: str) -> list[str]:
    """Return the 7 calendar dates ending at week_end (ascending).

    Shared by report_runner (CLI --end-date) and editorial (weekly validation).
    fromisoformat (py>=3.11) accepts ISO week strings like "2026-W20"; require
    plain YYYY-MM-DD so the single guard lives here, not duplicated per caller.
    """
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", week_end):
        raise ValueError(f"week_end must be YYYY-MM-DD, got {week_end!r}")
    end = datetime.fromisoformat(week_end).date()
    return [(end - timedelta(days=offset)).isoformat() for offset in range(6, -1, -1)]


def compute_daily_window(target_date: str, now_iso: str) -> dict[str, str]:
    now = datetime.fromisoformat(now_iso)
    start_date = datetime.fromisoformat(target_date).date() - timedelta(days=1)
    start = datetime.combine(start_date, time(hour=7), tzinfo=now.tzinfo)
    return {
        "start": start.isoformat(),
        "end": now.isoformat(),
        "timezone": str(now.tzinfo),
    }


def _format_target(layer: dict[str, Any]) -> str:
    if layer["type"] == "webfetch":
        return layer["url"]
    if layer["type"] == "github_releases":
        return f"https://api.github.com/repos/{layer['repo']}/releases"
    queries = layer.get("queries", [])
    return queries[0] if queries else layer["type"]


def _blank_source_detail(source: dict[str, Any]) -> dict[str, Any]:
    first_layer = source["fetch_chain"][0]
    return {
        "final_layer_index": 0,
        "final_layer_type": first_layer["type"],
        "via_broad_search": False,
        "confidence_policy": "none",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": first_layer["type"],
                "target": _format_target(first_layer),
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }


def initial_fetch_status(whitelist: dict[str, Any]) -> dict[str, Any]:
    source_details = {source["name"]: _blank_source_detail(source) for source in iter_named_sources(whitelist)}
    source_details[GENERAL_SEARCH_SURFACE_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "websearch_broad",
        "via_broad_search": True,
        "confidence_policy": "force_medium_plus_flag",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "websearch_broad",
                "target": GENERAL_SEARCH_SURFACE_NAME,
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
    source_details[GOOGLE_SEARCH_PRODUCT_BLOG_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "webfetch",
        "via_broad_search": False,
        "confidence_policy": "none",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "webfetch",
                "target": "https://blog.google/products/search/",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
    source_details[HIGH_SIGNAL_MEDIA_DISCOVERY_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "websearch_broad",
        "via_broad_search": True,
        "confidence_policy": "force_medium_plus_flag",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "websearch_broad",
                "target": "high_signal_media_queries",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
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
    source_details[ECOSYSTEM_DISCOVERY_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "websearch_broad",
        "via_broad_search": True,
        "confidence_policy": "force_medium_plus_flag",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "websearch_broad",
                "target": "ecosystem_search_queries",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
    source_details[LEADER_INTERVIEW_DISCOVERY_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "websearch_broad",
        "via_broad_search": True,
        "confidence_policy": "force_medium_plus_flag",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "websearch_broad",
                "target": "interview_search_queries",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
    source_details[METHODOLOGY_DISCOVERY_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "websearch_broad",
        "via_broad_search": True,
        "confidence_policy": "force_medium_plus_flag",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "websearch_broad",
                "target": "methodology_search_queries",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
    source_details[HACKER_NEWS_NAME] = {
        "final_layer_index": 0,
        "final_layer_type": "webfetch",
        "via_broad_search": False,
        "confidence_policy": "none",
        "attempts": [
            {
                "layer_index": 0,
                "layer_type": "webfetch",
                "target": "https://hacker-news.firebaseio.com/v0/topstories.json",
                "result": "empty",
                "reason": "pending discovery",
            }
        ],
    }
    for name, target in (
        (GITHUB_TRENDING_DAILY_NAME, "https://github.com/trending?since=daily"),
        (GITHUB_TRENDING_WEEKLY_NAME, "https://github.com/trending?since=weekly"),
    ):
        source_details[name] = {
            "final_layer_index": 0,
            "final_layer_type": "webfetch",
            "via_broad_search": False,
            "confidence_policy": "none",
            "attempts": [
                {
                    "layer_index": 0,
                    "layer_type": "webfetch",
                    "target": target,
                    "result": "empty",
                    "reason": "pending discovery",
                }
            ],
        }
    for name in required_source_family_names(whitelist):
        source_details[name] = {
            "final_layer_index": 0,
            "final_layer_type": "webfetch",
            "via_broad_search": name == "broad_discovery_surface",
            "confidence_policy": "force_medium_plus_flag" if name == "broad_discovery_surface" else "none",
            "attempts": [
                {
                    "layer_index": 0,
                    "layer_type": "surface_summary",
                    "target": name,
                    "result": "success_but_empty",
                    "note": "surface coverage tracked via member sources",
                }
            ],
        }
    return {"succeeded": [], "failed": [], "empty": [], "source_details": source_details}


def build_discovery_manifest(
    target_date: str,
    window: dict[str, str],
    whitelist: dict[str, Any],
    active_tracking: list[dict[str, Any]] | None = None,
    reader_profile: dict[str, Any] | None = None,
    cadence_plan: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    source_families = source_family_catalog(whitelist)
    plan = cadence_plan or {}
    default_slot = {"cadence": "daily", "due": True, "last_probed": None}
    sources = []
    for source in iter_named_sources(whitelist):
        source_family = infer_source_family(source)
        slot = plan.get(source["name"], default_slot)
        sources.append(
            {
                "name": source["name"],
                "category": source["category"],
                "source_family": source_family,
                "authority_tier": source.get("authority_tier"),
                "verify_before_use": source.get("verify_before_use", False),
                "fallback_policy": source.get("fallback_policy", source_families.get(source_family, {}).get("fallback_policy", "same_entity_one_hop")),
                "cadence": slot["cadence"],
                "due": slot["due"],
                "last_probed": slot["last_probed"],
                "fetch_chain": source["fetch_chain"],
                "one_hop_fallback_targets": suggest_one_hop_targets(source["name"], source),
            }
        )

    return {
        "version": "1.0",
        "type": "daily_discovery_manifest",
        "date": target_date,
        "window": window,
        "active_tracking": active_tracking or [],
        "reader_profile": reader_profile or {},
        "cadence_plan": plan,
        "cadence_summary": {
            "due": sum(1 for slot in plan.values() if slot["due"]),
            "skipped": sum(1 for slot in plan.values() if not slot["due"]),
        },
        "required_sources": sources,
        "source_families": source_families,
        "general_agent_search_queries": whitelist.get("general_agent_search_queries", []),
        "high_signal_media_queries": whitelist.get("high_signal_media_queries", []),
        "recall_probe_queries": whitelist.get("recall_probe_queries", []),
        "ecosystem_search_queries": whitelist.get("ecosystem_search_queries", []),
        "interview_search_queries": whitelist.get("interview_search_queries", []),
        "interview_zh_transcript_queries": whitelist.get("interview_zh_transcript_queries", []),
        "methodology_search_queries": whitelist.get("methodology_search_queries", []),
        "required_discovery_surfaces": [
            "white-list first pass",
            *required_source_family_names(whitelist),
            GENERAL_SEARCH_SURFACE_NAME,
            GOOGLE_SEARCH_PRODUCT_BLOG_NAME,
            "Hacker News top 50",
            GITHUB_TRENDING_DAILY_NAME,
            GITHUB_TRENDING_WEEKLY_NAME,
            HIGH_SIGNAL_MEDIA_DISCOVERY_NAME,
            RECALL_PROBE_SURFACE_NAME,
            ECOSYSTEM_DISCOVERY_NAME,
            LEADER_INTERVIEW_DISCOVERY_NAME,
            METHODOLOGY_DISCOVERY_NAME,
            *[f"{TRACKING_SURFACE_PREFIX}{event['event_slug']}" for event in (active_tracking or [])],
        ],
    }


def write_discovery_manifest(cache_dir: Path, manifest: dict[str, Any]) -> Path:
    path = cache_dir / "discovery_manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def missing_fetch_status_coverage(report: dict[str, Any], whitelist: dict[str, Any]) -> list[str]:
    source_details = report.get("fetch_status", {}).get("source_details", {})
    return [name for name in required_discovery_names(whitelist) if name not in source_details]


def append_run_log(run_log: Path, line: str) -> None:
    run_log.parent.mkdir(parents=True, exist_ok=True)
    with run_log.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")
