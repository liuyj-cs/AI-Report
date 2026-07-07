#!/usr/bin/env python3
"""Per-run send-state ledger：finalize 重跑不再重发已送达邮件（日报正文 / deep_dive / 周报）。

访谈的跨天幂等仍由全局 cache/interview_seen.json 承担；本台账只管"同一份产物重复 finalize"。
dry-run 与发送失败不写入，语义与 seen-ledger 的 send-then-record 一致。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SEND_STATE_FILENAME = "send_state.json"


def _state_path(cache_dir: Path) -> Path:
    return cache_dir / SEND_STATE_FILENAME


def load_send_state(cache_dir: Path) -> dict[str, Any]:
    path = _state_path(cache_dir)
    if not path.exists():
        return {"version": "1.0", "sent": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": "1.0", "sent": {}}
    if not isinstance(payload.get("sent"), dict):
        return {"version": "1.0", "sent": {}}
    return payload


def already_sent(cache_dir: Path, key: str) -> bool:
    return bool(load_send_state(cache_dir)["sent"].get(key))


def record_sent(cache_dir: Path, key: str, subject: str) -> None:
    state = load_send_state(cache_dir)
    state["sent"][key] = {"subject": subject}
    path = _state_path(cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
