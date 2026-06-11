import json
from pathlib import Path

from evidence import maybe_expand_candidate, suggest_one_hop_targets

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "discovery"


def test_openai_403_with_external_signal_triggers_one_hop_fallback():
    fixture = json.loads((FIXTURE_DIR / "official_openai_403.json").read_text(encoding="utf-8"))
    candidate = {
        "entity": fixture["entity"],
        "headline": fixture["headline"],
        "discovery_signals": fixture["discovery_signals"],
    }

    expanded = maybe_expand_candidate(candidate, fixture["source_detail"])

    assert expanded["expansion_triggered"] is True
    assert expanded["expansion_reason"] == "official_error_with_external_signal"
    assert "https://openai.com/index/" in expanded["fallback_targets"]


def test_suggest_one_hop_targets_uses_fetch_chain_and_openai_special_cases(sample_whitelist):
    source = next(item for item in sample_whitelist["coding_agents_primary"] if item["name"] == "OpenAI Codex")
    targets = suggest_one_hop_targets("OpenAI Codex", source)

    assert "https://openai.com/index/" in targets
    assert any("site:openai.com Codex" in target for target in targets)
    assert any("OpenAI Codex release site:openai.com" in target for target in targets)


def test_suggest_one_hop_targets_covers_qwen_and_google_product_blogs(sample_whitelist):
    qwen = next(item for item in sample_whitelist["cn_labs"] if item["name"] == "阿里 Qwen")
    google_ai = next(item for item in sample_whitelist["us_labs"] if item["name"] == "Google AI Blog")

    qwen_targets = suggest_one_hop_targets("阿里 Qwen", qwen)
    google_targets = suggest_one_hop_targets("Google AI Blog", google_ai)

    assert "https://qwen.ai/blog/" in qwen_targets
    assert "https://qwen.ai/" in qwen_targets
    assert "https://blog.google/products/search/" in google_targets
    assert "https://blog.google/products/chrome/" in google_targets
