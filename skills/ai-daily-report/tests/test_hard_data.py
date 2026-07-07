import json

from hard_data import (
    compute_hard_data_delta,
    find_previous_snapshot,
    load_snapshot,
    snapshot_path,
)


def _write_snapshot(project_root, day, sources):
    path = snapshot_path(project_root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": "1.0", "date": day, "sources": sources}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_load_snapshot_missing_returns_none(tmp_path):
    assert load_snapshot(tmp_path, "2026-07-07") is None


def test_find_previous_snapshot_skips_gaps(tmp_path):
    _write_snapshot(tmp_path, "2026-07-04", {"lmarena": {"models": []}})
    found = find_previous_snapshot(tmp_path, "2026-07-07")
    assert found is not None
    assert found[0] == "2026-07-04"


def test_find_previous_snapshot_respects_lookback(tmp_path):
    _write_snapshot(tmp_path, "2026-06-20", {"lmarena": {"models": []}})
    assert find_previous_snapshot(tmp_path, "2026-07-07", lookback_days=7) is None


def test_compute_delta_reports_changes_and_new_entries():
    prev = {"sources": {"lmarena": {"models": [{"model": "m1", "elo": 1400, "rank": 2}]}}}
    curr = {
        "sources": {
            "lmarena": {
                "models": [
                    {"model": "m1", "elo": 1415, "rank": 1},
                    {"model": "m2", "elo": 1380, "rank": 5},
                ]
            }
        }
    }
    deltas = compute_hard_data_delta(prev, curr)
    changed = [d for d in deltas if d["status"] == "changed"]
    new = [d for d in deltas if d["status"] == "new_entry"]
    assert {(d["model"], d["metric"], d["delta"]) for d in changed} == {("m1", "elo", 15), ("m1", "rank", -1)}
    assert {(d["model"], d["metric"]) for d in new} == {("m2", "elo"), ("m2", "rank")}


def test_compute_delta_without_baseline_marks_all_new():
    curr = {"sources": {"openrouter": {"models": [{"model": "m1", "input_price_per_mtok": 1.2}]}}}
    deltas = compute_hard_data_delta(None, curr)
    assert deltas == [
        {
            "source": "openrouter", "model": "m1", "metric": "input_price_per_mtok",
            "old": None, "new": 1.2, "delta": None, "status": "new_entry",
        }
    ]


def test_runner_hard_data_delta_subcommand(tmp_path, capsys):
    from report_runner import main

    _write_snapshot(tmp_path, "2026-07-06", {"lmarena": {"models": [{"model": "m1", "elo": 1400}]}})
    _write_snapshot(tmp_path, "2026-07-07", {"lmarena": {"models": [{"model": "m1", "elo": 1410}]}})

    exit_code = main(["--project-root", str(tmp_path), "hard-data-delta", "--date", "2026-07-07"])
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["baseline_date"] == "2026-07-06"
    assert payload["deltas"][0]["delta"] == 10


def test_runner_hard_data_delta_missing_snapshot(tmp_path, capsys):
    from report_runner import main

    exit_code = main(["--project-root", str(tmp_path), "hard-data-delta", "--date", "2026-07-07"])
    assert exit_code == 1
