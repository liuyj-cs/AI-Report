#!/usr/bin/env python3
"""Archive rendered report HTML to reports/ and clean up old cache dirs."""

import argparse
import shutil
import sys
import time
from pathlib import Path

CACHE_RETENTION_DAYS = 14


def archive(html_path: Path, report_type: str, date_tag: str, project_root: Path) -> Path:
    if report_type not in ("daily", "weekly"):
        raise ValueError(f"Unknown type: {report_type}")

    dst_dir = project_root / "reports" / report_type
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{date_tag}.html"
    shutil.copy2(html_path, dst)
    return dst


def _iter_cache_leaf_dirs(cache_dir: Path) -> list[Path]:
    leaf_dirs: list[Path] = []
    for child in cache_dir.iterdir():
        if not child.is_dir():
            continue
        if child.name == "tracking":
            continue
        if child.name == "weekly":
            for weekly_dir in child.iterdir():
                if weekly_dir.is_dir():
                    leaf_dirs.append(weekly_dir)
            continue
        leaf_dirs.append(child)
    return leaf_dirs


def cleanup_cache(project_root: Path, retention_days: int = CACHE_RETENTION_DAYS) -> int:
    cache_dir = project_root / "cache"
    if not cache_dir.exists():
        return 0
    now_days = int(time.time()) // 86400
    removed = 0
    for child in _iter_cache_leaf_dirs(cache_dir):
        mtime_days = int(child.stat().st_mtime) // 86400
        if (now_days - mtime_days) > retention_days:
            shutil.rmtree(child)
            removed += 1
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Archive HTML report and clean old cache")
    parser.add_argument("html_path", type=Path, nargs="?")
    parser.add_argument("--type", choices=["daily", "weekly"])
    parser.add_argument("--date", help="YYYY-MM-DD for daily or YYYY-W{nn} for weekly")
    parser.add_argument("--cleanup", action="store_true", help="only run cache cleanup")
    args = parser.parse_args()

    project_root = Path.cwd()

    if args.cleanup:
        removed = cleanup_cache(project_root)
        print(f"cleaned {removed} stale cache dirs")
        return 0

    if not args.html_path or not args.type or not args.date:
        parser.error("html_path, --type, and --date are required unless --cleanup")

    try:
        dst = archive(args.html_path, args.type, args.date, project_root)
    except (OSError, ValueError) as e:
        print(f"archive failed: {e}", file=sys.stderr)
        return 2

    cleanup_cache(project_root)
    print(str(dst))
    return 0


if __name__ == "__main__":
    sys.exit(main())
