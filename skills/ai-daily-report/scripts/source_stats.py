#!/usr/bin/env python3
"""Deterministic helpers for the source cadence ledger: per-surface probe outcomes.

Lives at ``cache/source_stats.json`` (cache root, same convention as
``seen_repos.json``) because ``cache/{date}/`` day directories are pruned after
14 days while cadence needs a 30-day window.

Semantics differ from the seen-ledgers on purpose: those record what readers
actually received (written only after a successful send), this records what the
run actually probed — so dry-run writes here too.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, timedelta
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any

STATS_RETENTION_DAYS = 45
EMPTY_STATS: dict[str, Any] = {"version": "1.0", "days": {}}


def source_stats_path(project_root: Path) -> Path:
    return project_root / "cache" / "source_stats.json"


def _clean_record(record: Any) -> dict[str, Any] | None:
    """严格按类型校验一条面记录；任何字段损坏都丢弃整条，不做强制转换。

    强转是这里最危险的做法：把 ``attempts: "corrupt"`` 读成 0、``hit: null`` 读成
    False，等于把损坏数据解释成一次"探过、没命中"的真实负样本——连续几天就足以把
    一个面误降成 weekly。fail-open 的含义是「不知道就当没探过」（回 daily），不是
    「不知道就当探了没结果」。

    ``type(x) is int`` 而非 isinstance：bool 是 int 的子类，``attempts: True``
    必须算损坏。
    """
    if not isinstance(record, dict):
        return None
    attempts = record.get("attempts")
    hit = record.get("hit")
    if type(attempts) is not int or attempts < 0:
        return None
    if type(hit) is not bool:
        return None
    return {"attempts": attempts, "hit": hit}


def load_source_stats(project_root: Path) -> dict[str, Any]:
    """Read the ledger; anything unreadable or malformed reads as empty (fail-open).

    An empty ledger means every surface falls back to daily probing, i.e. today's
    behaviour — losing the ledger must never block a report. That contract covers
    structural damage too, not just unparseable bytes: a legal JSON ``[]`` used to
    raise ``AttributeError`` and take down every later ``init-daily``.

    Damage is contained to the smallest unit that is actually broken: a bad day (or
    a bad per-surface record) is dropped, the rest of the history survives — losing
    30 days of scheduling data over one corrupt row would be its own outage.
    """
    path = source_stats_path(project_root)
    if not path.exists():
        return dict(EMPTY_STATS)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return dict(EMPTY_STATS)
    if not isinstance(payload, dict) or not isinstance(payload.get("days"), dict):
        return dict(EMPTY_STATS)

    days: dict[str, Any] = {}
    for day, entry in payload["days"].items():
        if not isinstance(day, str) or not isinstance(entry, dict):
            continue
        cleaned = {
            name: record
            for name, raw in entry.items()
            if isinstance(name, str) and (record := _clean_record(raw)) is not None
        }
        days[day] = cleaned
    return {"version": "1.0", "days": days}


@contextmanager
def _locked(path: Path):
    """跨进程互斥整个 read→prune→update→write，避免并发 finalize 丢日期。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    with lock_path.open("w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    """同目录临时文件 + os.replace：写到一半被打断也不会留下半个台账。"""
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".source_stats-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _prune(days: dict[str, Any], today: str) -> dict[str, Any]:
    try:
        cutoff = date.fromisoformat(today) - timedelta(days=STATS_RETENTION_DAYS)
    except ValueError:
        return days
    kept = {}
    for day, payload in days.items():
        try:
            if date.fromisoformat(day) >= cutoff:
                kept[day] = payload
        except ValueError:
            continue
    return kept


def record_source_stats(report: dict[str, Any], project_root: Path, today: str) -> int:
    """Write today's per-surface {attempts, hit} into the ledger, idempotent by date.

    ``hit`` is deterministic: the surface reported success and was not empty. It
    deliberately ignores whether a candidate survived editorial judgement — that
    would make scheduling depend on how faithfully the AI filled the ledger.
    """
    fetch_status = report.get("fetch_status", {})
    succeeded = set(fetch_status.get("succeeded") or [])
    empty = set(fetch_status.get("empty") or [])
    source_details = fetch_status.get("source_details") or {}

    entry = {
        name: {
            "attempts": len(detail.get("attempts") or []),
            "hit": name in succeeded and name not in empty,
        }
        for name, detail in source_details.items()
        if isinstance(detail, dict)
    }

    path = source_stats_path(project_root)
    with _locked(path):
        stats = load_source_stats(project_root)
        days = _prune(dict(stats.get("days", {})), today)
        days[today] = entry
        _write_atomic(path, {"version": "1.0", "days": days})
    return len(entry)
