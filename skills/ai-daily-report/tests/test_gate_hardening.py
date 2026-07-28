"""召回守门的判据必须信 attempts 实迹，不信自报的 final_layer_index。"""
from discovery import load_whitelist
from editorial import validate_recall_fallback_coverage

NAME = "DeepSeek"


def _report(attempts, final_layer_index):
    return {
        "fetch_status": {
            "succeeded": [NAME],
            "failed": [],
            "empty": [NAME],
            "source_details": {
                NAME: {"final_layer_index": final_layer_index, "attempts": attempts}
            },
        }
    }


def _fetch_attempts(indexes):
    return [
        {"layer_index": i, "layer_type": "webfetch", "target": "x", "result": "success_but_empty"}
        for i in indexes
    ]


def test_self_declared_final_index_cannot_bypass_chain_exhaustion():
    """只抓了 L0 却自报 final_layer_index=2 —— 判据必须按 attempts 实迹判 BLOCK。"""
    whitelist = load_whitelist()

    errors = validate_recall_fallback_coverage(_report(_fetch_attempts([0]), 2), whitelist)

    assert len(errors) == 1
    assert NAME in errors[0]


def test_empty_attempts_with_declared_index_is_fail_closed():
    whitelist = load_whitelist()

    assert len(validate_recall_fallback_coverage(_report([], 2), whitelist)) == 1


def test_stale_final_index_does_not_cause_false_block():
    """实际走完了 L0-L2，只是 final_layer_index 没更新 —— 不该误报。"""
    whitelist = load_whitelist()

    assert validate_recall_fallback_coverage(_report(_fetch_attempts([0, 1, 2]), 0), whitelist) == []
