import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from archive import cleanup_cache

SKILL_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = SKILL_ROOT / "scripts" / "archive.py"


def run_archive(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )


def setup_project(tmp_path: Path) -> Path:
    """创建一个模拟项目根：含 cache/ 和 reports/。"""
    (tmp_path / "cache").mkdir()
    (tmp_path / "reports" / "daily").mkdir(parents=True)
    (tmp_path / "reports" / "weekly").mkdir(parents=True)
    return tmp_path


def test_archive_daily_copies_to_reports(tmp_path):
    project = setup_project(tmp_path)
    html_src = project / "cache" / "2026-04-10" / "report.html"
    html_src.parent.mkdir()
    html_src.write_text("<html>daily</html>", encoding="utf-8")

    result = run_archive(str(html_src), "--type", "daily", "--date", "2026-04-10", cwd=project)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    dst = project / "reports" / "daily" / "2026-04-10.html"
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == "<html>daily</html>"


def test_archive_weekly_copies_to_reports(tmp_path):
    project = setup_project(tmp_path)
    html_src = project / "cache" / "weekly" / "2026-W15" / "report.html"
    html_src.parent.mkdir(parents=True)
    html_src.write_text("<html>weekly</html>", encoding="utf-8")

    result = run_archive(str(html_src), "--type", "weekly", "--date", "2026-W15", cwd=project)

    assert result.returncode == 0, f"stderr: {result.stderr}"
    dst = project / "reports" / "weekly" / "2026-W15.html"
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == "<html>weekly</html>"


def test_archive_cleanup_removes_old_cache(tmp_path):
    project = setup_project(tmp_path)

    # 创建 3 个 cache 子目录，分别 5 天前、14 天前、20 天前
    def mkcache(name: str, age_days: int) -> Path:
        d = project / "cache" / name
        d.mkdir()
        (d / "dummy.txt").write_text("x")
        mtime = (datetime.now() - timedelta(days=age_days)).timestamp()
        import os
        os.utime(d, (mtime, mtime))
        return d

    fresh = mkcache("2026-04-08", 5)
    boundary = mkcache("2026-03-31", 14)
    stale = mkcache("2026-03-25", 20)

    result = run_archive("--cleanup", cwd=project)

    assert result.returncode == 0
    assert fresh.exists(), "5-day-old cache should remain"
    assert boundary.exists(), "14-day-old cache is at the boundary, keep"
    assert not stale.exists(), "20-day-old cache should be removed"


def test_archive_cleanup_removes_old_weekly_leaf_only(tmp_path):
    project = setup_project(tmp_path)
    weekly_root = project / "cache" / "weekly"
    weekly_root.mkdir(exist_ok=True)

    def mkweekly(name: str, age_days: int) -> Path:
        d = weekly_root / name
        d.mkdir()
        (d / "dummy.txt").write_text("x")
        mtime = (datetime.now() - timedelta(days=age_days)).timestamp()
        import os

        os.utime(d, (mtime, mtime))
        return d

    fresh = mkweekly("2026-W15", 5)
    stale = mkweekly("2026-W01", 20)

    result = run_archive("--cleanup", cwd=project)

    assert result.returncode == 0
    assert weekly_root.exists(), "weekly root should remain"
    assert fresh.exists(), "fresh weekly leaf should remain"
    assert not stale.exists(), "stale weekly leaf should be removed"


def test_archive_deep_dive_copies_to_reports(tmp_path):
    project = setup_project(tmp_path)
    html_src = project / "cache" / "2026-06-13" / "deep_dive_claude-fable-5.html"
    html_src.parent.mkdir(parents=True)
    html_src.write_text("<html>deep</html>", encoding="utf-8")

    result = run_archive(
        str(html_src), "--type", "deep_dive", "--date", "2026-06-13-claude-fable-5", cwd=project
    )

    assert result.returncode == 0, f"stderr: {result.stderr}"
    dst = project / "reports" / "deep_dives" / "2026-06-13-claude-fable-5.html"
    assert dst.exists()
    assert dst.read_text(encoding="utf-8") == "<html>deep</html>"


def test_archive_creates_report_dir_if_missing(tmp_path):
    project = tmp_path  # 没有 reports/
    (project / "cache" / "2026-04-10").mkdir(parents=True)
    html_src = project / "cache" / "2026-04-10" / "report.html"
    html_src.write_text("<html>daily</html>", encoding="utf-8")

    result = run_archive(str(html_src), "--type", "daily", "--date", "2026-04-10", cwd=project)

    assert result.returncode == 0
    assert (project / "reports" / "daily" / "2026-04-10.html").exists()


def test_cleanup_cache_preserves_tracking_dir(tmp_path):
    cache = tmp_path / "cache"
    old_daily = cache / "2026-01-01"
    tracking = cache / "tracking"
    old_daily.mkdir(parents=True)
    tracking.mkdir(parents=True)
    (tracking / "claude-fable-5.json").write_text("{}", encoding="utf-8")
    old_time = time.time() - 90 * 86400
    os.utime(old_daily, (old_time, old_time))
    os.utime(tracking, (old_time, old_time))

    removed = cleanup_cache(tmp_path)

    assert removed == 1
    assert not old_daily.exists()
    assert tracking.exists()
    assert (tracking / "claude-fable-5.json").exists()
