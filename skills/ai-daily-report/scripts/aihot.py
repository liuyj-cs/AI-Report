#!/usr/bin/env python3
"""Recompute AI HOT discovery coverage from saved HTTP responses; never select news."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from evidence import evidence_digest, evidence_path


SOURCE_NAME = "AI HOT"
QUERY = {"mode": "all", "window": "7d", "by": "published"}
SUCCESS_RESULTS = {"success", "success_but_empty", "empty"}


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp missing")
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timestamp has no timezone")
    return result


def _query(url: str) -> dict[str, list[str]]:
    if not isinstance(url, str):
        raise ValueError("request URL must be a string")
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.netloc not in {"aihot.virxact.com", "aihot.news"}
            or parsed.path != "/api/v1/items"):
        raise ValueError("request is not the AI HOT items endpoint")
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(query.get(key) != [value] for key, value in QUERY.items()):
        raise ValueError("request must use mode=all&window=7d&by=published")
    if set(query) - {*QUERY, "limit", "cursor"} or any(len(values) != 1 for values in query.values()):
        raise ValueError("filtered, unknown or repeated request parameters")
    limit = query.get("limit", [""])[0]
    if not limit.isdigit() or not 1 <= int(limit) <= 100:
        raise ValueError("request limit must be between 1 and 100")
    if query.get("cursor") == [""]:
        raise ValueError("empty cursor")
    return query


def summarize_aihot_pages(records: list[dict[str, Any]], *, window: dict[str, str]) -> dict[str, Any]:
    """Inspect actual ordered page records, not a caller-supplied completion flag.

    Each record contains request_url, requested_at, status_code, content_type,
    body and the evidence artifact's collected_at. The body is the complete response.
    Completion covers this public surface at collection time, not an immutable
    snapshot or everything the upstream has yet to process.
    """
    start, end = _timestamp(window["start"]), _timestamp(window["end"])
    if start > end:
        raise ValueError("invalid report window")
    summary: dict[str, Any] = {
        "status": "error", "stop_reason": "no_pages", "pages_fetched": 0,
        "items_seen": 0, "in_window_count": 0, "inferred_time_count": 0,
        "next_cursor": None,
    }
    expected_cursor = None
    seen_cursors: set[str] = set()
    seen_ids: set[str] = set()
    previous_time: datetime | None = None
    endpoint: tuple[str, str, str] | None = None
    for index, record in enumerate(records):
        try:
            if "load_error" in record:
                raise ValueError(record["load_error"])
            if type(record.get("status_code")) is not int or record["status_code"] != 200:
                raise ValueError("HTTP response is not 200")
            if str(record.get("content_type", "")).split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("response is not application/json")
            body = record.get("body")
            if not isinstance(body, dict) or type(body.get("schemaVersion")) is not int or body["schemaVersion"] != 1:
                raise ValueError("invalid schemaVersion or response object")
            query = _query(record.get("request_url", ""))
            parsed = urlsplit(record["request_url"])
            current_endpoint = (parsed.scheme, parsed.netloc, parsed.path)
            if endpoint is not None and current_endpoint != endpoint:
                raise ValueError("endpoint changed between pages")
            if query.get("cursor", [None])[0] != expected_cursor:
                raise ValueError("cursor does not continue the previous page")
            if body.get("query") != {**QUERY, "category": None, "q": None, "ordering": "publishedAtDesc"}:
                raise ValueError("response query does not match the request")
            collected = _timestamp(record.get("collected_at"))
            requested = _timestamp(record.get("requested_at"))
            if requested > collected:
                raise ValueError("request time is later than response collection")
            if requested < end or collected - timedelta(days=7) > start:
                raise ValueError("rolling 7d query does not cover the locked report window")
            items, page = body.get("items"), body.get("page")
            if not isinstance(items, list) or not isinstance(page, dict):
                raise ValueError("items/page missing or invalid")
            limit = int(query["limit"][0])
            if type(page.get("count")) is not int or page["count"] != len(items) or len(items) > limit:
                raise ValueError("page count does not match items/limit")
            more, cursor = page.get("hasMore"), page.get("nextCursor")
            if type(more) is not bool or "nextCursor" not in page:
                raise ValueError("invalid pagination fields")
            if more and (len(items) != limit or not isinstance(cursor, str) or not cursor or cursor in seen_cursors):
                raise ValueError("invalid or repeated continuation cursor")
            if not more and cursor is not None:
                raise ValueError("exhausted page must have null nextCursor")
            page_ids: set[str] = set()
            page_times: list[datetime] = []
            in_window = inferred = 0
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"]:
                    raise ValueError("item identity missing")
                if item["id"] in seen_ids | page_ids:
                    raise ValueError("duplicate item across the response chain")
                if "publishedAt" not in item or type(item.get("selected")) is not bool:
                    raise ValueError("item publishedAt/selected missing or invalid")
                if not isinstance(item.get("title"), str) or not item["title"]:
                    raise ValueError("item title missing")
                source, links = item.get("source"), item.get("links")
                if not isinstance(source, dict) or not isinstance(source.get("name"), str):
                    raise ValueError("item source missing")
                if not isinstance(links, dict) or any(not isinstance(links.get(key), str) or not links[key]
                                                     for key in ("original", "aihot")):
                    raise ValueError("item original/AI HOT links missing")
                discovered = _timestamp(item.get("discoveredAt"))
                timestamp = discovered if item["publishedAt"] is None else _timestamp(item["publishedAt"])
                if not requested - timedelta(days=7) <= timestamp <= collected:
                    raise ValueError("item time cannot belong to this rolling 7d response")
                prior = page_times[-1] if page_times else previous_time
                if prior is not None and timestamp > prior:
                    raise ValueError("items are not ordered by descending published/discovered time")
                page_ids.add(item["id"])
                page_times.append(timestamp)
                if start <= timestamp <= end:
                    in_window += 1
                    inferred += item["publishedAt"] is None
            # Commit counts only after the entire page passes validation.
            endpoint = current_endpoint
            seen_ids.update(page_ids)
            if cursor:
                seen_cursors.add(cursor)
            previous_time = page_times[-1] if page_times else previous_time
            expected_cursor = cursor
            summary.update(status="partial", stop_reason="more_pages", next_cursor=cursor)
            summary["pages_fetched"] += 1
            summary["items_seen"] += len(items)
            summary["in_window_count"] += in_window
            summary["inferred_time_count"] += inferred
            crossed = bool(page_times and page_times[-1] < start)
            if not more or crossed:
                summary.update(status="complete", stop_reason="target_window_passed" if more else "exhausted")
                break  # Later attempts cannot erase the already observed target-window boundary.
        except (ValueError, TypeError) as exc:
            summary.update(status="partial" if summary["pages_fetched"] else "error",
                           stop_reason=f"page_{index + 1}: {exc}")
            # A failed request never advances the cursor. A later saved response
            # can recover only by continuing from that same expected cursor.
    return summary


def recompute_aihot_coverage(source_detail: dict[str, Any], *, window: dict[str, str],
                             cache_dir: Path) -> dict[str, Any]:
    records = []
    for attempt in source_detail.get("attempts", []):
        if attempt.get("layer_type") != "webfetch" or attempt.get("layer_index") != 0:
            continue
        try:
            artifact = attempt["evidence_artifact"]
            content = evidence_path(cache_dir, artifact["path"]).read_bytes().decode("utf-8")
            if evidence_digest(content) != artifact["sha256"]:
                raise ValueError("saved response hash mismatch")
            record = json.loads(content)
            if not isinstance(record, dict) or record.get("request_url") != attempt.get("target"):
                raise ValueError("saved response request_url differs from attempt target")
            records.append({**record, "collected_at": artifact["collected_at"]})
        except (OSError, UnicodeError, KeyError, TypeError, ValueError):
            records.append({"load_error": "saved HTTP response missing, invalid or hash mismatch"})
    return summarize_aihot_pages(records, window=window)


def validate_aihot_discovery(report: dict[str, Any], *, manifest: dict[str, Any] | None,
                             cache_dir: Path) -> list[str]:
    """Enforce the contract locked in new manifests, leaving old manifests readable."""
    if not isinstance(manifest, dict):
        return ["AI HOT coverage validation requires the locked discovery manifest"]
    sources = manifest.get("required_sources")
    if not isinstance(sources, list):
        return ["AI HOT manifest required_sources must be a list"]
    matches = [row for row in sources if isinstance(row, dict) and row.get("name") == SOURCE_NAME]
    if len(matches) != 1:
        return ["AI HOT manifest must lock exactly one AI HOT source"]
    source = matches[0]
    chain = source.get("fetch_chain")
    first_layer = chain[0] if isinstance(chain, list) and chain and isinstance(chain[0], dict) else {}
    try:
        locked_url = first_layer["url"]
        _query(locked_url)
    except (KeyError, IndexError, TypeError, ValueError):
        historical_urls = {
            f"https://aihot.virxact.com/api/v1/items?mode={mode}&window=24h&limit=50"
            for mode in ("selected", "all")
        }
        if first_layer.get("url") in historical_urls:
            return []
        return ["AI HOT manifest has an unsupported or malformed discovery contract"]
    fetch = report.get("fetch_status", {})
    detail = fetch.get("source_details", {}).get(SOURCE_NAME, {})
    try:
        summary = recompute_aihot_coverage(detail, window=manifest["window"], cache_dir=cache_dir)
    except (KeyError, TypeError, ValueError):
        return ["AI HOT coverage validation requires a valid locked daily window"]
    errors = []
    if detail.get("aihot_coverage") != summary:
        errors.append("AI HOT aihot_coverage must equal recomputed saved-response coverage")
    attempts = detail.get("attempts", [])
    api_success = any(attempt.get("layer_index") == 0 and attempt.get("layer_type") == "webfetch"
                      and attempt.get("result") in SUCCESS_RESULTS for attempt in attempts)
    fallback_success = any(attempt.get("layer_index", 0) > 0
                           and attempt.get("layer_type") in {"websearch_scoped", "websearch_broad"}
                           and attempt.get("result") in SUCCESS_RESULTS for attempt in attempts)
    if summary["status"] != "complete":
        if api_success:
            errors.append("AI HOT incomplete/error API coverage cannot claim API success or empty")
        if SOURCE_NAME in fetch.get("empty", []):
            errors.append("AI HOT incomplete/error API coverage cannot claim an empty public pool")
        if SOURCE_NAME in fetch.get("succeeded", []) and not fallback_success:
            errors.append("AI HOT source success needs complete API coverage or a successful search fallback")
    else:
        if not api_success or SOURCE_NAME not in fetch.get("succeeded", []):
            errors.append("AI HOT complete API coverage must be recorded as successful discovery")
        if any(isinstance(row, dict) and row.get("name") == SOURCE_NAME for row in fetch.get("failed", [])):
            errors.append("AI HOT complete API coverage contradicts the failed source list")
        if SOURCE_NAME in fetch.get("empty", []) and summary["in_window_count"]:
            errors.append("AI HOT nonempty public pool cannot be recorded as empty")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path, required=True)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    print(json.dumps(recompute_aihot_coverage(report["fetch_status"]["source_details"][SOURCE_NAME],
          window=manifest["window"], cache_dir=args.cache_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
