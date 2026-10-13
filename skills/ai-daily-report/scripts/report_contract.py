"""Versioned report structure; product classification is always editorial judgment."""
from typing import Any

DAILY_VERSION = "1.3"
WEEKLY_VERSION = "1.2"
LEDGER_VERSION = "1.2"


def uses_agent_taxonomy(report: dict[str, Any]) -> bool:
    return report.get("version") == (DAILY_VERSION if report.get("type") == "daily" else WEEKLY_VERSION)


def has_editorial_contract(report: dict[str, Any]) -> bool:
    versions = ("1.2", DAILY_VERSION) if report.get("type") == "daily" else ("1.1", WEEKLY_VERSION)
    return report.get("version") in versions


def product_sections(report: dict[str, Any]) -> tuple[str, ...]:
    if uses_agent_taxonomy(report):
        return ("frontier_models", "general_agents", "vertical_agents")
    return ("frontier_models", "coding_agents", "general_agents")


def decision_sections(report: dict[str, Any]) -> tuple[str, ...]:
    sections = product_sections(report)
    return (*sections, "policy_risk") if has_editorial_contract(report) else sections


def expected_ledger_version(report: dict[str, Any]) -> str:
    return LEDGER_VERSION if uses_agent_taxonomy(report) else "1.1"
