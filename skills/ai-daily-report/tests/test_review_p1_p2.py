"""PR #5 review 发现的加固：manifest 完整性、台账 fail-open、QA 基准一致、唤醒审计。"""
import json

import pytest

from discovery import (
    due_discovery_names,
    load_whitelist,
    required_discovery_names,
)
from editorial import build_daily_qa_diff, validate_fetch_status_integrity
from source_stats import load_source_stats, record_source_stats, source_stats_path

DATE = "2026-07-28"
EMPTY_LEDGER = {"version": "1.0", "type": "candidate_ledger", "date": DATE, "items": []}


def _write_manifest(tmp_path, payload):
    cache_dir = tmp_path / "cache" / DATE
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "discovery_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )


def _full_plan(whitelist, due=True):
    return {
        name: {"cadence": "daily", "due": due, "last_probed": None}
        for name in required_discovery_names(whitelist)
    }


# --- P1-1: manifest 完整性 -------------------------------------------------


def test_partial_plan_falls_back_to_full_baseline(tmp_path, sample_whitelist):
    """plan 只覆盖一个面（whitelist 增源 / manifest 被部分覆盖）→ 不可信，回退全量。"""
    _write_manifest(tmp_path, {"date": DATE, "cadence_plan": {"OpenAI": {"cadence": "daily", "due": True, "last_probed": None}}})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_plan_missing_newly_added_surface_falls_back(tmp_path, sample_whitelist):
    """init 之后 whitelist 增源，旧 manifest 覆盖不到新面 → 回退全量，别让新源静默缺席。"""
    plan = _full_plan(sample_whitelist)
    plan.pop(next(iter(plan)))
    _write_manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_manifest_date_mismatch_falls_back(tmp_path, sample_whitelist):
    _write_manifest(tmp_path, {"date": "1999-01-01", "cadence_plan": _full_plan(sample_whitelist)})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_malformed_slot_falls_back(tmp_path, sample_whitelist):
    plan = _full_plan(sample_whitelist)
    plan[next(iter(plan))] = "not-a-slot"
    _write_manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    assert due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist) is None


def test_complete_plan_is_used(tmp_path, sample_whitelist):
    plan = _full_plan(sample_whitelist)
    cold = "Aider"
    plan[cold] = {"cadence": "weekly", "due": False, "last_probed": "2026-07-20"}
    _write_manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    due = due_discovery_names(tmp_path, DATE, whitelist=sample_whitelist)

    assert due is not None
    assert cold not in due
    assert "OpenAI" in due


def test_whitelist_omitted_keeps_backward_compatible_behaviour(tmp_path, sample_whitelist):
    """不传 whitelist 时维持旧行为（只做比例守卫），不破坏既有调用方。"""
    _write_manifest(tmp_path, {"date": DATE, "cadence_plan": _full_plan(sample_whitelist)})

    assert due_discovery_names(tmp_path, DATE) is not None


# --- P1-2: 台账结构损坏必须 fail-open --------------------------------------


@pytest.mark.parametrize("payload", ["[]", '"a string"', "42", "null", '{"days": []}', '{"days": "x"}'])
def test_structurally_invalid_ledger_reads_as_empty(tmp_path, payload):
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")

    assert load_source_stats(tmp_path) == {"version": "1.0", "days": {}}


def test_malformed_day_entries_are_dropped_not_fatal(tmp_path, sample_whitelist):
    """单天/单面记录损坏只丢那条，保留其余历史——别为一条坏数据丢掉整个调度依据。"""
    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "days": {
                    "2026-07-26": ["oops"],
                    "2026-07-27": {"OpenAI": {"attempts": 1, "hit": True}, "Aider": "bad"},
                },
            }
        ),
        encoding="utf-8",
    )

    stats = load_source_stats(tmp_path)

    assert "2026-07-26" not in stats["days"]
    assert stats["days"]["2026-07-27"] == {"OpenAI": {"attempts": 1, "hit": True}}


def test_cadence_survives_malformed_ledger(tmp_path, sample_whitelist):
    from discovery import compute_cadence

    path = source_stats_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"version": "1.0", "days": {"2026-07-27": ["oops"]}}), encoding="utf-8")

    plan = compute_cadence(sample_whitelist, load_source_stats(tmp_path), DATE)

    assert plan["OpenAI"]["cadence"] == "daily"


def test_record_source_stats_writes_atomically(tmp_path):
    """写入走同目录临时文件 + os.replace，中断不会留下半个台账。"""
    report = {
        "date": DATE,
        "fetch_status": {"succeeded": ["A"], "failed": [], "empty": [], "source_details": {"A": {"attempts": [{}]}}},
    }
    record_source_stats(report, tmp_path, DATE)

    # 允许 .lock（跨进程锁的常驻句柄），但不得留下写了一半的临时文件
    leftovers = [
        p.name
        for p in source_stats_path(tmp_path).parent.iterdir()
        if p.name not in ("source_stats.json", "source_stats.json.lock")
    ]
    assert leftovers == []
    assert load_source_stats(tmp_path)["days"][DATE]["A"]["hit"] is True


def test_concurrent_writers_do_not_lose_days(tmp_path):
    """两个日期并发 finalize：文件锁保证后写者看到先写者的结果。"""
    import multiprocessing

    def _worker(day):
        import sys
        sys.path.insert(0, str(SCRIPTS))
        from source_stats import record_source_stats as rec

        rec(
            {"date": day, "fetch_status": {"succeeded": [day], "failed": [], "empty": [], "source_details": {day: {"attempts": [{}]}}}},
            tmp_path,
            day,
        )

    from pathlib import Path as _P

    SCRIPTS = _P(__file__).resolve().parent.parent / "scripts"
    ctx = multiprocessing.get_context("fork")
    procs = [ctx.Process(target=_worker, args=(d,)) for d in ("2026-07-26", "2026-07-27")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=30)

    days = load_source_stats(tmp_path)["days"]
    assert set(days) == {"2026-07-26", "2026-07-27"}


# --- P2-3: QA 与阻塞校验共用同一 due 基准 ----------------------------------


def test_qa_diff_does_not_flag_legitimately_skipped_surface(tmp_path, finalized_fetch_status):
    whitelist = load_whitelist()
    fs = finalized_fetch_status(whitelist)
    cold = "Aider"
    fs["source_details"].pop(cold)
    fs["succeeded"] = [n for n in fs["succeeded"] if n != cold]
    fs["empty"] = [n for n in fs["empty"] if n != cold]

    plan = _full_plan(whitelist)
    plan[cold] = {"cadence": "weekly", "due": False, "last_probed": "2026-07-20"}
    _write_manifest(tmp_path, {"date": DATE, "cadence_plan": plan})

    qa = build_daily_qa_diff(
        {"date": DATE, "fetch_status": fs, "sections": {}}, EMPTY_LEDGER, whitelist, project_root=tmp_path
    )

    assert not any(cold in (f.get("source_name") or "") for f in qa["findings"])
    assert not any(cold in (f.get("reason") or "") for f in qa["findings"])


def test_qa_diff_still_flags_missing_due_surface(tmp_path, finalized_fetch_status):
    whitelist = load_whitelist()
    fs = finalized_fetch_status(whitelist)
    hot = "Aider"
    fs["source_details"].pop(hot)
    fs["succeeded"] = [n for n in fs["succeeded"] if n != hot]
    fs["empty"] = [n for n in fs["empty"] if n != hot]
    _write_manifest(tmp_path, {"date": DATE, "cadence_plan": _full_plan(whitelist)})

    qa = build_daily_qa_diff(
        {"date": DATE, "fetch_status": fs, "sections": {}}, EMPTY_LEDGER, whitelist, project_root=tmp_path
    )

    assert any(hot in (f.get("source_name") or "") for f in qa["findings"])


# --- P2-5: 唤醒必须留下理由 -------------------------------------------------


def test_awakened_surface_without_reason_is_rejected(finalized_fetch_status):
    whitelist = load_whitelist()
    fs = finalized_fetch_status(whitelist)
    cold = "Aider"
    plan = _full_plan(whitelist)
    plan[cold] = {"cadence": "weekly", "due": False, "last_probed": "2026-07-20"}

    errors = validate_fetch_status_integrity(
        {"fetch_status": fs}, whitelist, due_names=[n for n in plan if plan[n]["due"]], cadence_plan=plan
    )

    assert any(cold in error and "wakeup_reason" in error for error in errors)


def test_awakened_surface_with_reason_passes(finalized_fetch_status):
    whitelist = load_whitelist()
    fs = finalized_fetch_status(whitelist)
    cold = "Aider"
    fs["source_details"][cold]["attempts"][0]["wakeup_reason"] = "媒体报道指向该源当日有发布"
    plan = _full_plan(whitelist)
    plan[cold] = {"cadence": "weekly", "due": False, "last_probed": "2026-07-20"}

    errors = validate_fetch_status_integrity(
        {"fetch_status": fs}, whitelist, due_names=[n for n in plan if plan[n]["due"]], cadence_plan=plan
    )

    assert not any(cold in error for error in errors)


def test_due_surface_never_needs_wakeup_reason(finalized_fetch_status):
    whitelist = load_whitelist()
    fs = finalized_fetch_status(whitelist)
    plan = _full_plan(whitelist)

    errors = validate_fetch_status_integrity(
        {"fetch_status": fs}, whitelist, due_names=list(plan), cadence_plan=plan
    )

    assert not any("wakeup_reason" in error for error in errors)
