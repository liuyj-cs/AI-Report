import sys
from pathlib import Path

import json
import pytest

SKILL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_ROOT))
sys.path.insert(0, str(SKILL_ROOT / "scripts"))


@pytest.fixture
def sample_whitelist():
    import yaml

    path = SKILL_ROOT / "sources" / "whitelist.yaml"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_daily_report():
    path = SKILL_ROOT / "tests" / "fixtures" / "sample_daily.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_candidate_ledger():
    path = SKILL_ROOT / "tests" / "fixtures" / "sample_candidate_ledger.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def sample_weekly_report():
    path = SKILL_ROOT / "tests" / "fixtures" / "sample_weekly.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def normalized_weekly_report(sample_weekly_report):
    payload = json.loads(json.dumps(sample_weekly_report, ensure_ascii=False))
    payload["sections"]["frontier_models"]["vendor_groups"][1]["references"][0]["editorial_tier"] = "watch"
    payload["sections"]["action_items"]["items"][1]["references"][0]["editorial_tier"] = "watch"
    payload["sections"]["action_items"]["items"][2]["references"][0]["headline"] = "Composer 2.0 内测开放"
    return payload


@pytest.fixture
def finalized_fetch_status():
    from discovery import initial_fetch_status

    def _build(whitelist):
        payload = initial_fetch_status(whitelist)
        for detail in payload["source_details"].values():
            attempts = []
            for attempt in detail.get("attempts", []):
                attempts.append(
                    {
                        **attempt,
                        "result": "success_but_empty",
                        "note": "discovery completed without candidate in fixture",
                    }
                )
                attempts[-1].pop("reason", None)
            detail["attempts"] = attempts
        payload["succeeded"] = sorted(payload["source_details"].keys())
        payload["failed"] = []
        payload["empty"] = sorted(payload["source_details"].keys())
        return payload

    return _build
