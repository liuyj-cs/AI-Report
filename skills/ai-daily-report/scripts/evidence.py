#!/usr/bin/env python3
"""Deterministic evidence-expansion helpers."""
from __future__ import annotations

from typing import Any

OPENAI_FALLBACK_TARGETS = {
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
    "OpenAI Codex": [
        "https://openai.com/index/",
        "site:openai.com Codex {date}",
        "site:openai.com Codex update {date}",
        "https://openai.com/sitemap.xml",
    ],
}

GOOGLE_AI_BLOG_FALLBACK_TARGETS = [
    "https://blog.google/products/search/",
    "https://blog.google/products/chrome/",
    'site:blog.google/products/search "AI Mode" {date}',
    'site:blog.google/products/chrome "AI Mode" {date}',
]

QWEN_FALLBACK_TARGETS = [
    "https://qwen.ai/blog/",
    "https://qwen.ai/",
    "site:qwen.ai/blog Qwen {date}",
    "site:qwen.ai Qwen release {date}",
]

SOURCE_SPECIFIC_FALLBACK_TARGETS = {
    "Google AI Blog": GOOGLE_AI_BLOG_FALLBACK_TARGETS,
    "阿里 Qwen": QWEN_FALLBACK_TARGETS,
}

EXTERNAL_SIGNAL_KEYS = {"hn_hot", "search_multi_hit", "media_multi_source", "partner_official"}


def _layer_targets(source_config: dict[str, Any]) -> list[str]:
    targets: list[str] = []
    for layer in source_config.get("fetch_chain", [])[1:]:
        if layer["type"] == "webfetch":
            targets.append(layer["url"])
        elif layer["type"] == "github_releases":
            targets.append(f"https://api.github.com/repos/{layer['repo']}/releases")
        else:
            targets.extend(layer.get("queries", []))
    return targets


def suggest_one_hop_targets(source_name: str, source_config: dict[str, Any] | None = None) -> list[str]:
    targets: list[str] = []
    targets.extend(OPENAI_FALLBACK_TARGETS.get(source_name, []))
    targets.extend(SOURCE_SPECIFIC_FALLBACK_TARGETS.get(source_name, []))
    if source_config:
        targets.extend(_layer_targets(source_config))

    deduped: list[str] = []
    for target in targets:
        if target not in deduped:
            deduped.append(target)
    return deduped


def expansion_required(candidate: dict[str, Any], source_detail: dict[str, Any]) -> tuple[bool, str]:
    attempts = source_detail.get("attempts", [])
    last_result = attempts[-1]["result"] if attempts else ""
    discovery_signals = set(candidate.get("discovery_signals", []))

    if last_result in {"error", "success_but_empty", "empty"} and discovery_signals.intersection(EXTERNAL_SIGNAL_KEYS):
        return True, "official_error_with_external_signal"
    return False, ""


def maybe_expand_candidate(
    candidate: dict[str, Any],
    source_detail: dict[str, Any],
    source_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    required, reason = expansion_required(candidate, source_detail)
    return {
        **candidate,
        "expansion_triggered": required,
        "expansion_reason": reason,
        "fallback_targets": suggest_one_hop_targets(candidate.get("entity", ""), source_config) if required else [],
    }
