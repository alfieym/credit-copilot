"""Orchestration entry point: deterministic pipeline + bounded re-draft (result validation ④)."""
from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

from credit_copilot.agents.models import (
    CreditMemo,
    EntityResolutionError,
    Section,
    extract_entity_hint,
)
from credit_copilot.agents.pipeline import (
    build_compliance_flags,
    collect_facts,
    compose_report,
    resolve_entity,
    validate_report,
)

MAX_COMPOSE_ATTEMPTS = 2


def _error_memo(query: str, message: str, errs: list[str]) -> CreditMemo:
    return CreditMemo(
        entity_name=extract_entity_hint(query) or query,
        sections=[Section(title="Generation Failed", content=message)],
        data_gaps=errs,
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
    )


def run_report(query: str) -> CreditMemo:
    """Generate a report synchronously, always returning a structured CreditMemo
    (errors yield an error-bearing memo)."""
    try:
        entity = resolve_entity(query)
    except EntityResolutionError as e:
        return _error_memo(query, e.message, [e.message])

    facts = collect_facts(entity)
    flags = build_compliance_flags(entity, facts)
    report = compose_report(entity, facts, flags)
    errs = validate_report(report)
    attempts = 0
    while errs and attempts < MAX_COMPOSE_ATTEMPTS:
        report = compose_report(entity, facts, flags)
        errs = validate_report(report)
        attempts += 1
    if errs:
        report.sections.append(Section(title="Validation Failed", content="; ".join(errs)))
    return report


def run_report_stream(query: str) -> Iterator[dict]:
    """Streaming: emit per-stage progress events (for API SSE node-by-node push)."""
    yield {"stage": "resolve_entity", "status": "running"}
    try:
        entity = resolve_entity(query)
    except EntityResolutionError as e:
        yield {"stage": "resolve_entity", "status": "error", "message": e.message,
               "candidates": [c.name for c in e.candidates]}
        return
    yield {"stage": "resolve_entity", "status": "done", "entity": entity.name}

    yield {"stage": "collect_facts", "status": "running"}
    facts = collect_facts(entity)
    yield {"stage": "collect_facts", "status": "done"}

    yield {"stage": "compliance", "status": "running"}
    flags = build_compliance_flags(entity, facts)
    yield {"stage": "compliance", "status": "done", "flags": [f.rule for f in flags]}

    yield {"stage": "compose_report", "status": "running"}
    report = compose_report(entity, facts, flags)
    errs = validate_report(report)
    attempts = 0
    while errs and attempts < MAX_COMPOSE_ATTEMPTS:
        report = compose_report(entity, facts, flags)
        errs = validate_report(report)
        attempts += 1
    if errs:
        report.sections.append(Section(title="Validation Failed", content="; ".join(errs)))
    yield {"stage": "compose_report", "status": "done", "report": report}
