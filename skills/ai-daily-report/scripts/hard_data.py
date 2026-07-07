#!/usr/bin/env python3
"""Deterministic hard-data snapshot & cross-day delta helpers.

AI 抓取 LMArena / Artificial Analysis / OpenRouter 时把原始数字落盘为
cache/{date}/hard_data_snapshot.json；本模块只做确定性的跨日数值对比，
"是否值得写进 benchmark_changes / pricing_changes" 仍由 AI 判断。
"""
from __future__ import annotations

from datetime import date, timedelta
import json
from pathlib import Path
from typing import Any

SNAPSHOT_FILENAME = "hard_data_snapshot.json"
DEFAULT_LOOKBACK_DAYS = 7
NUMERIC_FIELDS = ("elo", "rank", "index_score", "input_price_per_mtok", "output_price_per_mtok")


def snapshot_path(project_root: Path, day: str) -> Path:
    return project_root / "cache" / day / SNAPSHOT_FILENAME


def load_snapshot(project_root: Path, day: str) -> dict[str, Any] | None:
    path = snapshot_path(project_root, day)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload.get("sources"), dict):
        return None
    return payload


def find_previous_snapshot(
    project_root: Path, day: str, lookback_days: int = DEFAULT_LOOKBACK_DAYS
) -> tuple[str, dict[str, Any]] | None:
    target = date.fromisoformat(day)
    for offset in range(1, lookback_days + 1):
        prev_day = (target - timedelta(days=offset)).isoformat()
        payload = load_snapshot(project_root, prev_day)
        if payload is not None:
            return prev_day, payload
    return None


def _model_index(source_payload: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    if not source_payload:
        return {}
    return {
        str(entry.get("model", "")): entry
        for entry in source_payload.get("models", [])
        if entry.get("model")
    }


def compute_hard_data_delta(
    prev: dict[str, Any] | None, curr: dict[str, Any]
) -> list[dict[str, Any]]:
    deltas: list[dict[str, Any]] = []
    prev_sources = (prev or {}).get("sources") or {}
    for source_name, curr_payload in (curr.get("sources") or {}).items():
        prev_models = _model_index(prev_sources.get(source_name))
        for model, entry in _model_index(curr_payload).items():
            baseline = prev_models.get(model)
            for field in NUMERIC_FIELDS:
                if field not in entry:
                    continue
                new_value = entry[field]
                old_value = baseline.get(field) if baseline else None
                if old_value is None:
                    deltas.append(
                        {
                            "source": source_name, "model": model, "metric": field,
                            "old": None, "new": new_value, "delta": None, "status": "new_entry",
                        }
                    )
                elif (
                    isinstance(old_value, (int, float))
                    and isinstance(new_value, (int, float))
                    and old_value != new_value
                ):
                    deltas.append(
                        {
                            "source": source_name, "model": model, "metric": field,
                            "old": old_value, "new": new_value,
                            "delta": round(new_value - old_value, 4), "status": "changed",
                        }
                    )
    return deltas
