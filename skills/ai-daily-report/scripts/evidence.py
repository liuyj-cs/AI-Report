#!/usr/bin/env python3
"""Deterministic evidence-expansion helpers."""
from __future__ import annotations

from typing import Any
from pathlib import Path
import hashlib
import json
from datetime import datetime

# Bound one model-visible response, including CJK and JSON escaping overhead.
# This is a transport budget, not an editorial selection limit.
MAX_REVIEW_CHARS = 2000

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


def evidence_digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def evidence_path(cache_dir: Path, relative_path: str) -> Path:
    path = (cache_dir / relative_path).resolve()
    if not path.is_relative_to((cache_dir / "evidence").resolve()):
        raise ValueError("evidence artifact must be inside cache evidence directory")
    return path


def save_response(cache_dir: Path, response: str, *, collected_at: str,
                  batch_id: str, query_ids: list[str], limitations: list[str]) -> dict[str, Any]:
    """Save the complete tool response as received, not a selected-result summary."""
    if not batch_id or not query_ids or not collected_at:
        raise ValueError("collection timestamp, batch and query identities are required")
    digest = evidence_digest(response)
    relative = f"evidence/{digest}.txt"
    path = evidence_path(cache_dir, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.encode("utf-8"))
    return {"path": relative, "sha256": digest, "collected_at": collected_at,
            "batch_id": batch_id, "query_ids": query_ids, "limitations": limitations}


def chunk_receipt(content: str, start: int, end: int) -> dict[str, Any]:
    if not (0 <= start <= end <= len(content)):
        raise ValueError("evidence chunk range is out of bounds")
    return {"start": start, "end": end, "sha256": evidence_digest(content[start:end])}


def read_response(cache_dir: Path, artifact: dict[str, Any], *, start: int, end: int) -> dict[str, Any]:
    """Prepare one bounded chunk; preparing it does not acknowledge delivery."""
    content = evidence_path(cache_dir, artifact["path"]).read_bytes().decode("utf-8")
    if evidence_digest(content) != artifact["sha256"]:
        raise ValueError("evidence artifact hash mismatch")
    chunk_receipt(content, start, end)  # Validate the range before slicing.
    if end - start > MAX_REVIEW_CHARS:
        raise ValueError(f"return one evidence chunk of at most {MAX_REVIEW_CHARS} characters")
    return {"content": content[start:end], "start": start, "end": end,
            "response_sha256": artifact["sha256"]}


def receipt_from_output(cache_dir: Path, artifact: dict[str, Any], *, returned_output: str) -> dict[str, Any]:
    """Acknowledge the actual returned JSON, never a locally prepared chunk.

    The caller must first inspect the outer tool response for truncation. This
    comparison proves byte-preserving transport of this chunk, not comprehension.
    """
    try:
        returned = json.loads(returned_output)
    except json.JSONDecodeError as exc:
        raise ValueError("returned evidence output is truncated or is not JSON") from exc
    if not isinstance(returned, dict) or type(returned.get("start")) is not int or type(returned.get("end")) is not int:
        raise ValueError("returned evidence output lacks an exact range")
    expected = read_response(cache_dir, artifact, start=returned["start"], end=returned["end"])
    if returned != expected:
        raise ValueError("returned evidence output differs from the canonical chunk")
    return {"start": returned["start"], "end": returned["end"],
            "sha256": evidence_digest(returned["content"])}


def review_coverage(content: str, receipts: list[dict[str, Any]]) -> dict[str, Any]:
    """Recompute exact receipts and union coverage from the canonical response."""
    frontier = 0
    for receipt in receipts:
        expected = chunk_receipt(content, receipt["start"], receipt["end"])
        if receipt != expected:
            raise ValueError("evidence receipt differs from recomputed chunk")
    for receipt in sorted(receipts, key=lambda item: item["start"]):
        if receipt["start"] > frontier:
            break
        frontier = max(frontier, receipt["end"])
    return {"response_sha256": evidence_digest(content), "characters": len(content),
            "provided_through": frontier, "complete": bool(receipts) and frontier == len(content)}


def validate_evidence_reviews(report: dict[str, Any], cache_dir: Path | None) -> list[str]:
    if report.get("version") != "1.2":
        return []
    if cache_dir is None:
        return ["discovery_review: evidence cache directory is required for daily 1.2"]
    errors = []
    for name, detail in report.get("fetch_status", {}).get("source_details", {}).items():
        for index, attempt in enumerate(detail.get("attempts", [])):
            label = f"discovery_review: {name}.attempts[{index}]"
            artifact = attempt.get("evidence_artifact")
            review = attempt.get("review", {})
            if not artifact:
                errors.append(f"{label} missing evidence_artifact (including failures)")
                continue
            try:
                for field in ("collected_at", "batch_id", "query_ids"):
                    if not artifact.get(field):
                        raise ValueError(f"missing {field}")
                collected = datetime.fromisoformat(artifact["collected_at"].replace("Z", "+00:00"))
                if collected.tzinfo is None:
                    raise ValueError("collection timestamp must include timezone")
                if report.get("generated_at") and collected > datetime.fromisoformat(report["generated_at"].replace("Z", "+00:00")):
                    raise ValueError("collection timestamp cannot be after report generation")
                if not isinstance(artifact["query_ids"], list) or not all(isinstance(q, str) and q.strip() for q in artifact["query_ids"]):
                    raise ValueError("query_ids must contain actual nonempty query identities")
                if not isinstance(artifact.get("limitations"), list):
                    raise ValueError("missing tool truncation/pagination limitations")
                content = evidence_path(cache_dir, artifact["path"]).read_bytes().decode("utf-8")
                if evidence_digest(content) != artifact["sha256"]:
                    raise ValueError("evidence artifact hash mismatch")
                expected = review_coverage(content, review.get("receipts", []))
                if review.get("coverage") != expected:
                    raise ValueError("review coverage differs from recomputed response")
                if review.get("status") not in {"complete", "access_gap", "incomplete"}:
                    raise ValueError("review status must distinguish completion from access gaps")
                if review.get("status") == "complete" and not expected["complete"]:
                    raise ValueError("unread returned content cannot be declared reviewed")
                if review.get("status") != "complete" and not review.get("reason", "").strip():
                    raise ValueError("incomplete review requires an explicit gap reason")
                if attempt.get("result") in {"empty", "success_but_empty"} and review.get("status") != "complete":
                    raise ValueError("unreviewed results cannot be declared empty")
                if artifact["limitations"] and not review.get("reason", "").strip():
                    raise ValueError("limited response requires an explicit coverage caveat")
            except (OSError, ValueError, KeyError, TypeError) as exc:
                errors.append(f"{label} {exc}")
    return errors


def main() -> None:
    """One read or acknowledgement per invocation; never emit a batch of chunks."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Provide or acknowledge one evidence chunk")
    commands = parser.add_subparsers(dest="command", required=True)
    reader = commands.add_parser("read")
    reader.add_argument("path", type=Path)
    reader.add_argument("--start", type=int, required=True)
    reader.add_argument("--end", type=int, required=True)
    ack = commands.add_parser("ack")
    ack.add_argument("path", type=Path)
    args = parser.parse_args()
    path = args.path.resolve()
    if path.parent.name != "evidence":
        parser.error("path must be a saved cache evidence artifact")
    artifact = {"path": f"evidence/{path.name}", "sha256": path.stem}
    try:
        if args.command == "read":
            result = read_response(path.parent.parent, artifact, start=args.start, end=args.end)
        else:
            result = receipt_from_output(path.parent.parent, artifact, returned_output=sys.stdin.read())
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
