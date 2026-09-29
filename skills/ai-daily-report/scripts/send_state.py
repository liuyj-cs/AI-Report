#!/usr/bin/env python3
"""Durable SMTP receipts shared by the sender and finalize.

A process holds the ledger lock throughout an attempt. Before entering SMTP DATA,
its recipients are durably marked unknown; interruption can never imply unsent.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator
import uuid

SEND_STATE_FILENAME = "send_state.json"
_RECIPIENT_STATES = {"not_submitted", "accepted", "refused", "unknown"}


class SendStateError(RuntimeError):
    """An unreadable or unresolved ledger must stop delivery, not reset it."""


def _state_path(cache_dir: Path) -> Path:
    return cache_dir / SEND_STATE_FILENAME


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _outcome(recipients: dict[str, str]) -> str:
    values = set(recipients.values())
    if "unknown" in values:
        return "unknown"
    if values == {"accepted"}:
        return "sent"
    if "accepted" in values:
        return "partial"
    return "not_submitted"


def load_send_state(cache_dir: Path) -> dict[str, Any]:
    path = _state_path(cache_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"version": "1.0", "sent": {}}
    except (OSError, UnicodeError) as exc:
        raise SendStateError("send_state cannot be read; delivery blocked") from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SendStateError("send_state is invalid JSON; delivery blocked") from exc
    if (not isinstance(payload, dict) or not isinstance(payload.get("version"), str)
            or payload["version"] not in {"1.0", "2.0"}
            or not isinstance(payload.get("sent"), dict)
            or not all(isinstance(v, dict) and isinstance(v.get("subject"), str) and v["subject"]
                       and ("html_sha256" not in v or _is_hash(v["html_sha256"]))
                       for v in payload["sent"].values())
            or not isinstance(payload.get("deliveries", {}), dict)
            or (payload["version"] == "2.0" and "deliveries" not in payload)):
        raise SendStateError("send_state has an invalid structure; delivery blocked")
    for key, entry in payload.get("deliveries", {}).items():
        if (not isinstance(entry, dict) or not isinstance(entry.get("recipients"), dict)
                or not entry["recipients"]
                or not all(_is_hash(v) for v in entry["recipients"])
                or not _is_hash(entry.get("html_sha256")) or not _is_hash(entry.get("sender_sha256"))
                or not all(isinstance(v, str) and v in _RECIPIENT_STATES for v in entry["recipients"].values())
                or not all(isinstance(entry.get(k), str) and entry[k]
                           for k in ("html_sha256", "sender_sha256", "message_id", "subject"))
                or not isinstance(entry.get("attempts"), list) or not entry["attempts"]
                or not all(isinstance(attempt, dict) and isinstance(attempt.get("recipients"), dict)
                           and attempt["recipients"] and set(attempt["recipients"]) <= set(entry["recipients"])
                           and all(isinstance(v, str) and v in _RECIPIENT_STATES
                                   for v in attempt["recipients"].values())
                           and attempt.get("status") == _outcome(attempt["recipients"])
                           for attempt in entry["attempts"])
                or entry.get("status") != _outcome(entry["recipients"])):
            raise SendStateError("send_state contains an invalid delivery receipt; delivery blocked")
        sent = payload["sent"].get(key)
        if (entry["status"] == "sent") != bool(sent) or (
                sent and sent.get("html_sha256") != entry["html_sha256"]):
            raise SendStateError("send_state receipts disagree; delivery blocked")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def locked_ledger(path: Path) -> Iterator[None]:
    """Serialize updates to a persistent JSON ledger on the local filesystem."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with (path.parent / f".{path.stem}.lock").open("a", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked_state(cache_dir: Path) -> Iterator[dict[str, Any]]:
    with locked_ledger(_state_path(cache_dir)):
        yield load_send_state(cache_dir)


def already_sent(cache_dir: Path, key: str) -> bool:
    return bool(load_send_state(cache_dir)["sent"].get(key))


def record_sent(cache_dir: Path, key: str, subject: str, *, artifact_path: Path | None) -> None:
    """Record a local completion or import a known legacy receipt, never overwrite it."""
    with _locked_state(cache_dir) as state:
        if state["sent"].get(key):
            return  # Never backfill a legacy receipt from today's potentially changed HTML.
        if key in state.get("deliveries", {}):
            raise SendStateError("SMTP receipt must be completed by the sender")
        entry = {"subject": subject}
        if artifact_path is not None:
            entry["html_sha256"] = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        state["sent"][key] = entry
        atomic_write_json(_state_path(cache_dir), state)


class DeliveryAttempt:
    def __init__(self, cache_dir: Path, state: dict[str, Any], key: str, entry: dict[str, Any],
                 recipients: list[str]):
        self.cache_dir = cache_dir
        self.state = state
        self.key = key
        self.entry = entry
        self.recipients = recipients
        self.message_id = entry["message_id"]

    def _save(self) -> None:
        atomic_write_json(_state_path(self.cache_dir), self.state)

    def submitting(self) -> None:
        """Persist uncertainty before SMTP can accept any content."""
        self.record_result({address: "unknown" for address in self.recipients},
                           retries=0, error="submission_in_progress", smtp_codes={})

    def record_result(self, recipients: dict[str, str], *, retries: int,
                      error: str | None, smtp_codes: dict[str, int]) -> None:
        if set(recipients) != set(self.recipients) or not set(recipients.values()) <= _RECIPIENT_STATES:
            raise ValueError("SMTP result does not cover this attempt's recipients")
        hashed = {_fingerprint(address): status for address, status in recipients.items()}
        self.entry["recipients"].update(hashed)
        self.entry["status"] = _outcome(self.entry["recipients"])
        self.entry["attempts"][-1].update({
            "recipients": hashed, "status": _outcome(hashed), "retries": retries,
            "error": error, "smtp_codes": {_fingerprint(address): code for address, code in smtp_codes.items()},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        if self.entry["status"] == "sent":
            self.state["sent"][self.key] = {k: self.entry[k] for k in ("subject", "html_sha256", "message_id")}
        self._save()


@contextmanager
def delivery_attempt(cache_dir: Path, key: str, subject: str, html_bytes: bytes,
                     sender: str, recipients: list[str]) -> Iterator[DeliveryAttempt | None]:
    """None means a prior accepted receipt exists; every other path is locked and durable."""
    if not key or not subject or not sender or not recipients:
        raise ValueError("delivery identity and recipients are required")
    recipients = list(dict.fromkeys(recipients))
    html_hash = hashlib.sha256(html_bytes).hexdigest()
    recipient_keys = {_fingerprint(address) for address in recipients}
    with _locked_state(cache_dir) as state:
        if state["sent"].get(key):
            yield None
            return
        state["version"] = "2.0"
        entries = state.setdefault("deliveries", {})
        entry = entries.get(key)
        if entry:
            if entry["status"] == "unknown":
                raise SendStateError("SMTP outcome unknown; reconcile the existing receipt before retrying")
            if (entry["html_sha256"] != html_hash or entry["subject"] != subject
                    or entry["sender_sha256"] != _fingerprint(sender)
                    or set(entry["recipients"]) != recipient_keys):
                raise SendStateError("delivery revision or envelope changed; existing receipt must be reconciled")
        else:
            entry = {"subject": subject, "html_sha256": html_hash, "sender_sha256": _fingerprint(sender),
                     "message_id": f"<ai-report-{uuid.uuid4().hex}@reports.local>",
                     "recipients": {address: "not_submitted" for address in sorted(recipient_keys)},
                     "status": "not_submitted", "attempts": []}
            entries[key] = entry
        pending = [address for address in recipients if entry["recipients"][_fingerprint(address)] != "accepted"]
        entry["attempts"].append({"started_at": datetime.now(timezone.utc).isoformat(),
                                  "status": "not_submitted", "retries": 0,
                                  "recipients": {_fingerprint(address): "not_submitted" for address in pending}})
        attempt = DeliveryAttempt(cache_dir, state, key, entry, pending)
        attempt._save()
        yield attempt


def record_delivery_result(cache_dir: Path, key: str, artifact_path: Path, outcome: str) -> dict[str, Any]:
    """Record this run separately from historical SMTP-accepted revisions."""
    if outcome not in {"dry_run", "sent", "skipped_existing", "failed", "partial", "unknown"}:
        raise ValueError("unknown delivery outcome")
    current = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
    with _locked_state(cache_dir) as state:
        recorded = state["sent"].get(key, {}).get("html_sha256")
        result = {"kind": key, "outcome": outcome, "current_html_sha256": current,
                  "sent_html_sha256": recorded,
                  "current_revision_delivered": current == recorded if recorded and outcome not in {"failed", "partial", "unknown"} else None}
        delivery = state.get("deliveries", {}).get(key)
        if delivery:
            result["smtp_status"] = delivery["status"]
        path = (cache_dir / "delivery_result.json" if key in {"daily", "weekly"}
                else cache_dir / "delivery_results" / f"{_fingerprint(key)}.json")
        atomic_write_json(path, result)
    return result
