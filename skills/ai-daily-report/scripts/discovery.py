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
# 已降频的面按稀疏节奏探测，30 天里本就只有 4-5 次；用 daily 档的样本量要求会让档位震荡。
CADENCE_MIN_SPARSE_PROBED_DAYS = 4
CADENCE_MIN_LEDGER_AGE_DAYS = 14
# due 面占比低于此值即认为 plan 不可信，覆盖校验回退 whitelist 全量（fail-closed）。
# 豁免面（核心源/tier1/hard_data/聚合面）恒 due，健康状态下占比远高于这个下限。
DUE_BASELINE_MIN_RATIO = 0.25
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

    聚合面(搜索、召回探针、source_family)本身就是召回兜底,降频等于自断退路;
    慢信号轨道(访谈、方法论发现面)例外,见 SLOW_TRACK_SURFACES。
    追踪面(TRACKING_SURFACE_PREFIX)不进 required_discovery_names,不参与调度,
    其覆盖由 tracking 的独立校验器负责。
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


def _ledger_series(stats: dict[str, Any], name: str, target: date) -> list[tuple[date, bool]]:
    """台账里该面的 (日期, 是否命中) 序列，只取**真实探测过**且**严格早于** target 的天。

    严格早于是幂等的前提：finalize 会写入当天记录，若当天记录参与分档，init 算出的
    plan 与 finalize 重算的结果就会不一致，重跑 finalize 会自我否定。语义上也只能这样
    ——用"今天探的结果"决定"今天该不该探"是因果倒置。

    未来日期同样丢弃（--date 笔误、时钟偏移）：留着会让 last_probed 跑到未来，due 的
    日期差变负，把包括核心源在内的所有面判成"今天不用探"。

    ``attempts <= 0`` 的记录是"当天记了一笔但没真去探"（面被跳过）——它是合法的审计
    留痕，但**不是实探日**。算进来会让一串跳过被读成一串"探过、没命中"，直接架空
    分档规则里"实探日 ≥10"这道样本量保护，把面误降成 weekly。
    """
    series: list[tuple[date, bool]] = []
    for day, entry in (stats.get("days") or {}).items():
        record = (entry or {}).get(name)
        if not isinstance(record, dict):
            continue
        attempts = record.get("attempts")
        if not isinstance(attempts, int) or attempts <= 0:
            continue
        try:
            parsed = date.fromisoformat(day)
        except ValueError:
            continue
        if parsed >= target:
            continue
        series.append((parsed, bool(record.get("hit"))))
    return sorted(series)


def _rank_cadence(series: list[tuple[date, bool]], target: date) -> str:
    """按近 30 天命中率分档;统计不足一律回 daily(宁多探不漏探)。"""
    if not series:
        return "daily"
    observed_days = (target - series[0][0]).days
    if observed_days < CADENCE_MIN_LEDGER_AGE_DAYS:
        return "daily"
    window = [(day, hit) for day, hit in series if 0 <= (target - day).days <= CADENCE_WINDOW_DAYS]
    hit_days = sum(1 for _, hit in window if hit)
    if hit_days >= CADENCE_DAILY_HIT_DAYS:
        return "daily"
    if hit_days:
        return "every_2_days"
    if len(window) >= CADENCE_MIN_PROBED_DAYS:
        return "weekly"
    # 已降到 weekly 的面，30 天内本来就只探 4-5 次，用 daily 档的样本量要求会把它
    # 弹回 daily、下次又降回来——档位来回震荡等于白降。但"探得稀疏"也可能是管线
    # 停摆造成的，那种稀疏不代表这个面不值得探：额外要求最近确实还在探。
    fresh = window and (target - window[-1][0]).days <= CADENCE_INTERVALS["weekly"]
    if observed_days >= CADENCE_WINDOW_DAYS and len(window) >= CADENCE_MIN_SPARSE_PROBED_DAYS and fresh:
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
    try:
        target = date.fromisoformat(target_date)
    except ValueError as exc:
        raise ValueError(f"target_date must be a valid YYYY-MM-DD date, got {target_date!r}") from exc
    exempt = _exempt_daily_names(whitelist)
    plan: dict[str, dict[str, Any]] = {}
    for name in required_discovery_names(whitelist):
        series = _ledger_series(stats, name, target)
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


def _valid_cadence_slot(slot: Any, target: date) -> bool:
    """slot 必须类型合法**且语义可能**——manifest 是我们自己算出来的,直接验算一遍。

    只查类型不够:`{"cadence":"daily","due":false,"last_probed":null}` 每个字段都合规,
    却与 compute_cadence 的语义直接矛盾(daily 面间隔 1 天、last_probed 最早也只能是
    昨天,不可能不到期;从没探过的面更不可能不到期)。这种 slot 只能来自伪造或损坏,
    放行就等于让一份"看起来正常"的窄 due 名单去做阻塞校验。

    把 due 重新推导一遍再比对,一条不变量覆盖全部组合:daily 恒 due、last_probed 为空
    恒 due、其余按间隔算——都是这个等式的特例。
    """
    if not isinstance(slot, dict):
        return False
    cadence = slot.get("cadence")
    if cadence not in CADENCE_INTERVALS:
        return False
    due = slot.get("due")
    if type(due) is not bool:
        return False

    last_probed = slot.get("last_probed")
    if last_probed is None:
        return due is True
    if not isinstance(last_probed, str):
        return False
    try:
        probed = date.fromisoformat(last_probed)
    except ValueError:
        return False
    # last_probed 是"往日":compute_cadence 只取严格早于 target 的记录,当日或未来都是坏数据
    if probed >= target:
        return False
    return due is ((target - probed).days >= CADENCE_INTERVALS[cadence])


def trusted_cadence_plan(
    project_root: Path,
    target_date: str,
    whitelist: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """当日 manifest 的 cadence_plan;任何不可信迹象都返回 None。

    **判据是重算比对,不是逐字段校验。** `cadence_plan` 是本流程自己用
    `compute_cadence(whitelist, stats, date)` 算出来再序列化到磁盘的,所以"这份 plan
    可不可信"等价于"它是不是那个纯函数的输出"——唯一完备的验证就是重新调一次再比。
    逐字段规则(类型、语义自洽、策略一致…)都只是在用近似逼近这个等价判断,近似必然
    留缝:PR #5 的四轮 review 在同一个函数上找到 5 个绕过,每个都是上一版规则没覆盖到
    的那一小块。改判据本身,这条路才收敛。

    传 whitelist 才能重算;不传时退回结构与比例守卫(向后兼容,调用方自负)。

    **收窄覆盖基准的方向必须 fail-closed**:比对不符只意味着"这份 plan 不是我算的"
    (whitelist 变了、manifest 被改、台账被动过),此时回退 whitelist 全量多报几条缺失,
    远好于用一份来路不明的短名单去放行漏采日报。

    QA 与阻塞校验必须共用本函数的结果,否则合法跳过的面会被 QA 报成漏采,诱导第二天
    补跑、抵消调度收益。
    """
    path = project_root / "cache" / target_date / "discovery_manifest.json"
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(manifest, dict):
        return None
    # 日期必须显式对上:缺 date 的 manifest 无从判断是不是复制来的旧文件
    if manifest.get("date") != target_date:
        return None
    plan = manifest.get("cadence_plan")
    if not isinstance(plan, dict) or not plan:
        return None
    try:
        target = date.fromisoformat(target_date)
    except ValueError:
        return None

    if whitelist is not None:
        # 完备判据：重算一次，逐字段全等才采信。任何偏离——类型、语义、固定 cadence
        # 策略、伪造的 last_probed、多一个面少一个面——都在这一次比较里被拒。
        expected = compute_cadence(whitelist, load_source_stats(project_root), target_date)
        return expected if plan == expected else None

    # 未传 whitelist：无从重算，退回结构与比例守卫（弱判据，仅为向后兼容保留）
    if not all(_valid_cadence_slot(slot, target) for slot in plan.values()):
        return None
    due = [name for name, slot in plan.items() if slot["due"]]
    # 兜底:结构全合法但 due 仍塌到远少于面总数(坏台账、同日重跑残留)。这只是最后
    # 一道网,不能替代上面的类型校验——`due: null` 会被 truthiness 读成"不用探",
    # 精心构造的比例甚至能擦过这道阈值。
    if not due or len(due) < len(plan) * DUE_BASELINE_MIN_RATIO:
        return None
    return plan


def due_discovery_names(
    project_root: Path,
    target_date: str,
    whitelist: dict[str, Any] | None = None,
) -> list[str] | None:
    """当日 due=true 的面名单;manifest 不可信时返回 None（调用方回退全量基准）。"""
    plan = trusted_cadence_plan(project_root, target_date, whitelist)
    if plan is None:
        return None
    return [name for name, slot in plan.items() if slot.get("due")]


def missing_fetch_status_coverage(
    report: dict[str, Any],
    whitelist: dict[str, Any],
    due_names: list[str] | None = None,
) -> list[str]:
    source_details = report.get("fetch_status", {}).get("source_details", {})
    required = required_discovery_names(whitelist) if due_names is None else due_names
    return [name for name in required if name not in source_details]


def append_run_log(run_log: Path, line: str) -> None:
    run_log.parent.mkdir(parents=True, exist_ok=True)
    with run_log.open("a", encoding="utf-8") as handle:
        handle.write(line.rstrip() + "\n")
