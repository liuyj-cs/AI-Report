import json

from source_stats import (
    STATS_RETENTION_DAYS,
    load_source_stats,
    record_source_stats,
    source_stats_path,
)


def _report(date, succeeded, empty, attempts_by_name):
    return {
        "date": date,
        "fetch_status": {
            "succeeded": succeeded,
            "failed": [],
            "empty": empty,
            "source_details": {
                name: {"attempts": [{"layer_index": i} for i in range(count)]}
                for name, count in attempts_by_name.items()
            },
        },
    }


def test_hit_is_succeeded_and_not_empty(tmp_path):
    report = _report(
        "2026-07-27",
        succeeded=["A", "B"],
        empty=["B"],
        attempts_by_name={"A": 1, "B": 3, "C": 2},
    )
    recorded = record_source_stats(report, tmp_path, "2026-07-27")
    assert recorded == 3

    stats = load_source_stats(tmp_path)
    day = stats["days"]["2026-07-27"]
    assert day["A"] == {"attempts": 1, "hit": True}
    assert day["B"] == {"attempts": 3, "hit": False}
    assert day["C"] == {"attempts": 2, "hit": False}


def test_rerun_same_date_overwrites_not_accumulates(tmp_path):
    first = _report("2026-07-27", succeeded=["A"], empty=[], attempts_by_name={"A": 2})
    record_source_stats(first, tmp_path, "2026-07-27")
    second = _report("2026-07-27", succeeded=[], empty=[], attempts_by_name={"A": 5})
    record_source_stats(second, tmp_path, "2026-07-27")

    stats = load_source_stats(tmp_path)
    assert list(stats["days"]) == ["2026-07-27"]
    assert stats["days"]["2026-07-27"]["A"] == {"attempts": 5, "hit": False}


def test_prunes_entries_older_than_retention(tmp_path):
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "days": {
                    "2026-01-01": {"Old": {"attempts": 1, "hit": True}},
                    "2026-07-20": {"Recent": {"attempts": 1, "hit": True}},
                },
            }
        ),
        encoding="utf-8",
    )
    report = _report("2026-07-27", succeeded=["A"], empty=[], attempts_by_name={"A": 1})
    record_source_stats(report, tmp_path, "2026-07-27")

    days = load_source_stats(tmp_path)["days"]
    assert "2026-01-01" not in days
    assert set(days) == {"2026-07-20", "2026-07-27"}


def test_retention_boundary_keeps_exactly_retention_days_old(tmp_path):
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "days": {
                    "2026-06-12": {"Boundary": {"attempts": 1, "hit": True}},
                    "2026-06-11": {"TooOld": {"attempts": 1, "hit": True}},
                },
            }
        ),
        encoding="utf-8",
    )
    assert STATS_RETENTION_DAYS == 45
    report = _report("2026-07-27", succeeded=[], empty=[], attempts_by_name={"A": 1})
    record_source_stats(report, tmp_path, "2026-07-27")

    days = load_source_stats(tmp_path)["days"]
    assert "2026-06-12" in days
    assert "2026-06-11" not in days


def test_corrupt_ledger_reads_as_empty(tmp_path):
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    assert load_source_stats(tmp_path) == {"version": "1.0", "days": {}}


def test_missing_ledger_reads_as_empty(tmp_path):
    assert load_source_stats(tmp_path) == {"version": "1.0", "days": {}}


def test_corrupt_ledger_is_replaced_not_raised(tmp_path):
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    report = _report("2026-07-27", succeeded=["A"], empty=[], attempts_by_name={"A": 1})

    assert record_source_stats(report, tmp_path, "2026-07-27") == 1
    assert load_source_stats(tmp_path)["days"]["2026-07-27"]["A"]["hit"] is True


def test_report_without_source_details_records_nothing(tmp_path):
    report = _report("2026-07-27", succeeded=[], empty=[], attempts_by_name={})

    assert record_source_stats(report, tmp_path, "2026-07-27") == 0
    assert load_source_stats(tmp_path)["days"]["2026-07-27"] == {}


def test_ledger_lives_at_cache_root(tmp_path):
    assert source_stats_path(tmp_path) == tmp_path / "cache" / "source_stats.json"
