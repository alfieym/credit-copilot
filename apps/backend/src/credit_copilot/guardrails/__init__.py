"""Guardrails: defensive pre-execution checks that stop bad SQL before it runs.

Contains the read-only SQL whitelist (``sql_guard.py``). Agent-side input/output
guardrails live in ``agents/guardrails.py`` (Agents SDK decorators).
"""
