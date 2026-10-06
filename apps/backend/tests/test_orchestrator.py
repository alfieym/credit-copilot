"""Orchestration smoke test: run_report produces a memo offline; empty-query
entity resolution rejects."""
from __future__ import annotations

from credit_copilot.agents.models import EntityResolutionError
from credit_copilot.agents.orchestrator import run_report
from credit_copilot.agents.pipeline import resolve_entity


def test_resolve_entity_empty_hint_rejects():
    try:
        resolve_entity("")
    except EntityResolutionError as e:
        assert "Could not identify an entity name" in e.message
    else:
        raise AssertionError("Empty query should be rejected")


def test_run_report_offline_returns_memo():
    memo = run_report("")
    assert memo.sections
    assert memo.sections[0].title == "Generation Failed"
