from send_state import already_sent, load_send_state, record_sent


def test_fresh_state_nothing_sent(tmp_path):
    assert already_sent(tmp_path, "daily") is False
    assert load_send_state(tmp_path) == {"version": "1.0", "sent": {}}


def test_record_then_already_sent(tmp_path):
    record_sent(tmp_path, "daily", "AI 日报 · 2026-07-07")
    record_sent(tmp_path, "deep_dive:claude-x", "AI 深度 · X")
    assert already_sent(tmp_path, "daily") is True
    assert already_sent(tmp_path, "deep_dive:claude-x") is True
    assert already_sent(tmp_path, "deep_dive:other") is False


def test_corrupt_state_treated_as_empty(tmp_path):
    (tmp_path / "send_state.json").write_text("{broken", encoding="utf-8")
    assert already_sent(tmp_path, "daily") is False
