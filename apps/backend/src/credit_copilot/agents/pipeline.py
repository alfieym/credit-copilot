"""Deterministic pipeline (task decomposition ① + result validation ④):
fact collection and rule layer without LLM involvement.

OpenAI Agents SDK is an agent-loop framework and has no "deterministic DAG" primitive,
so the resolve -> collect -> rules -> validate flow lives in explicit Python functions;
the SDK only handles the LLM drafting step (memo_agent.synthesize_conclusion)
and the output guardrail.
"""
from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from credit_copilot.agents.memo_agent import synthesize_conclusion
from credit_copilot.agents.models import (
    SECTION_TITLES,
    CreditMemo,
    Entity,
    EntityResolutionError,
    Flag,
    Section,
    _grade_at_or_below,
    extract_entity_hint,
)
from credit_copilot.tools.base import ToolResult
from credit_copilot.tools.datawarehouse import (
    get_borrower_overview,
    get_exposure,
    get_facilities,
    get_group_overview,
    get_involved_parties,
    get_ratings,
    search_borrowers,
    search_groups,
)
from credit_copilot.tools.policy_search import search_policy_docs


def resolve_entity(query: str) -> Entity:
    """Resolve the query to exactly one :class:`Entity` (result-validation gate 2).

    Args:
        query: The user's report request.

    Returns:
        The uniquely matched ``Entity``.

    Raises:
        EntityResolutionError: on zero matches, or more than one match.

    Implementation: ``extract_entity_hint``, then fuzzy-search both borrowers and
    groups; 0 hits → error, >1 hit → ambiguous error (carrying the candidates), exactly
    1 → that entity. Raising mirrors an input-guardrail tripwire.
    """
    hint = extract_entity_hint(query)
    if not hint:
        raise EntityResolutionError("Could not identify an entity name in the query")
    candidates: list[Entity] = []
    b = search_borrowers(hint)
    g = search_groups(hint)
    if b.ok:
        candidates += [
            Entity(kind="borrower", id=r["borrower_id"], name_cn=r["borrower_name_cn"],
                   name_en=r["borrower_name_en"], group_id=r["group_id"])
            for r in b.data
        ]
    if g.ok:
        candidates += [
            Entity(kind="group", id=r["group_id"], name_cn=r["group_name_cn"],
                   name_en=r["group_name_en"])
            for r in g.data
        ]
    if not candidates:
        raise EntityResolutionError(f'No entity found matching "{hint}"')
    if len(candidates) > 1:
        names = ", ".join(c.name for c in candidates)
        raise EntityResolutionError(
            f"Ambiguous name: {len(candidates)} entities matched ({names}). "
            "Please be more specific.",
            candidates,
        )
    return candidates[0]


def collect_facts(entity: Entity) -> dict[str, ToolResult]:
    """Collect per-section facts (DB + RAG) in parallel, degrading instead of crashing.

    Args:
        entity: The resolved borrower or group.

    Returns:
        A ``dict`` keyed by fact name (``overview``, ``ratings``, ``facilities``,
        ``exposure``, ``parties``, ``policy``, and optionally ``group``) whose values are
        ``ToolResult`` (any error or timeout degrades to ``ToolResult.failure``).

    Implementation: fetch the overview first to derive ``group_id``/industry/name; then
    run ratings / facilities / exposure / parties / policy (plus the group overview for
    borrowers) on a 6-worker ``ThreadPoolExecutor`` with a 30s timeout; any error or
    timeout becomes a ``ToolResult.failure``.
    """
    facts: dict[str, ToolResult] = {}
    overview = (get_borrower_overview(entity.id) if entity.kind == "borrower"
                else get_group_overview(entity.id))
    facts["overview"] = overview
    row = overview.data[0] if overview.ok and overview.data else {}
    group_id = row.get("group_id") or entity.group_id
    industry = row.get("industry") or row.get("group_industry") or ""
    name_en = row.get("borrower_name_en") or row.get("group_name_en") or entity.name_en

    tasks: dict[str, Callable[[], ToolResult]] = {
        "ratings": lambda: get_ratings("borrower", entity.id) if entity.kind == "borrower"
        else get_ratings("group", entity.id),
        "facilities": lambda: get_facilities(entity.id) if entity.kind == "borrower"
        else ToolResult.failure("Group entities have no single-borrower facility detail"),
        "exposure": lambda: (get_exposure(group_id) if group_id
                             else ToolResult.failure("No associated group")),
        "parties": lambda: get_involved_parties(entity.id) if entity.kind == "borrower"
        else ToolResult.failure("Group entities have no single-borrower related parties"),
        "policy": lambda: search_policy_docs(f"{industry} {name_en}"),
    }
    if entity.kind == "borrower" and group_id is not None:
        tasks["group"] = lambda: get_group_overview(group_id)

    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {key: ex.submit(fn) for key, fn in tasks.items()}
        for key, fut in futures.items():
            try:
                facts[key] = fut.result(timeout=30)
            except Exception as e:  # noqa: BLE001 — any unexpected error degrades to failure
                facts[key] = ToolResult.failure(f"Unexpected error: {e}", fallback=True)
    return facts


def build_compliance_flags(entity: Entity, facts: dict[str, ToolResult]) -> list[Flag]:
    """Apply the deterministic compliance rules and return :class:`Flag` objects.

    Args:
        entity: The resolved entity (used to name the entity in flag details).
        facts: Collected fact results (``collect_facts`` output).

    Returns:
        A ``list[Flag]`` of triggered compliance flags (may be empty).

    Implementation (three rule blocks): (1) ``industry == "Real Estate"`` → access
    restriction; (2) current internal rating ``≤ BB-`` → error, negative outlook →
    warning; (3) consolidated exposure ratio ``> 100%`` → error, ``≥ 80%`` → warning.
    """
    flags: list[Flag] = []
    overview = facts.get("overview")
    row = overview.data[0] if overview and overview.ok and overview.data else {}

    # 1. Industry access
    industry = row.get("industry") or row.get("group_industry") or ""
    if industry == "Real Estate":
        flags.append(Flag("warning", "Real Estate Access Restriction",
                          "industry-access-policy#Real Estate Access",
                          f"{entity.name} is in the real estate industry; "
                          "new credit must be approved by head office"))

    # 2. Rating threshold + outlook
    ratings = facts.get("ratings")
    if ratings and ratings.ok:
        current = [r for r in ratings.data if r.get("valid_to") is None]
        internal = [r for r in current if r.get("agency") == "internal"] or current
        if internal:
            g = internal[0]
            if _grade_at_or_below(g["grade"], "BB-"):
                flags.append(Flag("error", "Rating Access Threshold",
                                  "rating-access-policy#Rating Threshold",
                                  f"Internal rating {g['grade']} ≤ BB-; new credit is prohibited"))
            if g.get("outlook") == "Negative":
                flags.append(Flag("warning", "Negative Rating Outlook",
                                  "rating-access-policy#Outlook Management",
                                  "Outlook Negative; strengthen post-lending "
                                  "monitoring from quarterly to monthly"))

    # 3. Limits and concentration
    exposure = facts.get("exposure")
    if exposure and exposure.ok and exposure.data:
        e = exposure.data[0]
        limit, used = e.get("consolidated_exposure_limit"), e.get("total_utilized")
        if limit and used is not None:
            ratio = used / limit
            if ratio > 1.0:
                flags.append(Flag("error", "Group Exposure Over Limit",
                                  "exposure-limits-and-concentration-policy#Single Group Limit",
                                  f"Consolidated exposure {_money(used)} exceeds the limit "
                                  f"{_money(limit)} ({ratio:.1%})"))
            elif ratio >= 0.8:
                flags.append(Flag("warning", "Concentration Warning",
                                  "exposure-limits-and-concentration-policy#Concentration Warning",
                                  f"Consolidated exposure utilization {ratio:.1%} ≥ 80%"))
    return flags


def _money(v) -> str:
    """Format an amount in millions (e.g. ``2_500_000 -> "2.50 million"``).

    Args:
        v: A numeric amount (or any value).

    Returns:
        ``f"{value / 1_000_000:,.2f} million"``, or ``str(v)`` when ``v`` is not numeric.

    Implementation: divides by 1,000,000 and formats with two decimals; ``TypeError`` /
    ``ValueError`` fall through to ``str(v)``.
    """
    try:
        return f"{float(v) / 1_000_000:,.2f} million"
    except (TypeError, ValueError):
        return str(v)


def _display_name(name_cn, name_en) -> str:
    """Display name: English first, with the Chinese name in parentheses when present.

    Args:
        name_cn: Chinese name field (may be empty).
        name_en: English name field (may be empty).

    Returns:
        ``"<name_en> (<name_cn>)"`` when ``name_cn`` is non-empty, else ``name_en``.
    """
    name_en = name_en or ""
    name_cn = name_cn or ""
    return f"{name_en} ({name_cn})" if name_cn else name_en


def _tr(facts: dict[str, ToolResult], key: str) -> ToolResult:
    """Fetch a collected fact by key, yielding a "Not collected" failure when absent.

    Args:
        facts: The collected fact map.
        key: The fact name to look up.

    Returns:
        The matching ``ToolResult``, or ``ToolResult.failure("Not collected")``.
    """
    return facts.get(key, ToolResult.failure("Not collected"))


def compose_report(entity: Entity, facts: dict[str, ToolResult], flags: list[Flag]) -> CreditMemo:
    """Assemble the :class:`CreditMemo`: chapters 1–6 deterministic, chapter 7 via LLM.

    Args:
        entity: The resolved entity.
        facts: Collected fact results.
        flags: Compliance flags from ``build_compliance_flags``.

    Returns:
        A ``CreditMemo`` with 7 sections, citations, compliance flags, and data gaps.

    Implementation: walks the collected facts chapter by chapter, rendering rows into
    bullet lists with ``[t:table#id]`` citations; a missing fact emits "No data" and is
    recorded as a data-gap. Chapter 6 renders the compliance flags, chapter 7 calls
    ``synthesize_conclusion``, and a financial-data gap is always declared.
    """
    gaps: list[str] = []
    sections: list[Section] = []

    overview = _tr(facts, "overview")
    row = overview.data[0] if overview.ok and overview.data else {}

    # 1. Overview
    if overview.ok and row:
        borrower = (_display_name(row.get("borrower_name_cn"),
                                  row.get("borrower_name_en"))
                    or entity.name)
        group = _display_name(row.get("group_name_cn"), row.get("group_name_en"))
        sections.append(Section(
            title=SECTION_TITLES[0],
            content=(f"Borrower: {borrower}; "
                     f"Group: {group or '—'}; "
                     f"Industry: {row.get('industry') or '—'}; "
                     f"Legal form: {row.get('legal_type') or '—'}; "
                     f"Country/Region: {row.get('country') or '—'}."),
            citations=[f"[t:dim_borrower#{row.get('borrower_id', '')}]"],
        ))
    else:
        gaps.append("Borrower overview data missing")
        sections.append(Section(title=SECTION_TITLES[0], content="No data"))

    # 2. Ratings
    ratings = _tr(facts, "ratings")
    if ratings.ok and ratings.data:
        lines, cites = [], set()
        for r in ratings.data:
            current = "Current" if r.get("valid_to") is None else "Historical"
            lines.append(f"- {r.get('agency')} {r.get('grade')}"
                         f" ({current}, outlook {r.get('outlook') or '—'})")
            cites.add(f"[t:fact_rating#{r.get('rating_id')}]")
        sections.append(Section(title=SECTION_TITLES[1], content="\n".join(lines),
                                citations=sorted(cites)))
    else:
        gaps.append("Rating data missing")
        sections.append(Section(title=SECTION_TITLES[1], content="No data"))

    # 3. Credit facilities
    facilities = _tr(facts, "facilities")
    if facilities.ok and facilities.data:
        mains: dict[int, dict] = {}
        subs: dict[int, list[dict]] = {}
        for f in facilities.data:
            mid = f["main_facility_id"]
            mains.setdefault(mid, f)
            if f.get("sub_facility_id"):
                subs.setdefault(mid, []).append(f)
        lines = []
        for mid, f in mains.items():
            lines.append(f"- {f.get('facility_name')}"
                         f" ({f.get('facility_type')}, {f.get('currency')}, "
                         f"{_money(f.get('committed_amount'))}, matures {f.get('maturity_date')})")
            for s in subs.get(mid, []):
                lines.append(f"  · Sub-facility {s.get('sub_type')}: "
                             f"limit {_money(s.get('limit_amount'))}, "
                             f"utilized {_money(s.get('utilization_amount'))}")
        sections.append(Section(title=SECTION_TITLES[2], content="\n".join(lines),
                                citations=[f"[t:dim_main_facility#{mains[m]['main_facility_id']}]"
                                           for m in mains]))
    else:
        gaps.append("Credit facility data missing")
        sections.append(Section(title=SECTION_TITLES[2], content="No data"))

    # 4. Exposure & limit
    exposure = _tr(facts, "exposure")
    if exposure.ok and exposure.data:
        e = exposure.data[0]
        sections.append(Section(
            title=SECTION_TITLES[3],
            content=(f"Group consolidated exposure limit: "
                     f"{_money(e.get('consolidated_exposure_limit'))}; "
                     f"currently utilized exposure: {_money(e.get('total_utilized'))}"),
            citations=[f"[t:dim_borrowing_group#{e.get('group_id')}]",
                       "[t:fact_utilization]"],
        ))
    else:
        gaps.append("Exposure data missing")
        sections.append(Section(title=SECTION_TITLES[3], content="No data"))

    # 5. Related parties & guarantees
    parties = _tr(facts, "parties")
    if parties.ok and parties.data:
        lines = [f"- {p.get('role')}: {p.get('party_name')}"
                 + (f" (ownership {p.get('ownership_pct')}%)" if p.get("ownership_pct") else "")
                 for p in parties.data]
        sections.append(Section(title=SECTION_TITLES[4], content="\n".join(lines),
                                citations=["[t:dim_involved_party]"]))
    else:
        gaps.append("Related-party data missing")
        sections.append(Section(title=SECTION_TITLES[4], content="No data"))

    # 6. Policy & compliance check
    if flags:
        sections.append(Section(
            title=SECTION_TITLES[5],
            content="\n".join(f"- [{f.level}] {f.rule}: {f.detail}" for f in flags),
            citations=sorted({f"[p:{f.policy_ref}]" for f in flags}),
        ))
    else:
        sections.append(Section(title=SECTION_TITLES[5],
                                content="No compliance restrictions triggered"))

    # 7. Risk points & conclusion (LLM synthesis, degrades to rule summary)
    conclusion, concl_cites, flag_txt = synthesize_conclusion(entity, flags)
    if flags:
        conclusion += "\n\nCompliance conclusion detail:\n" + flag_txt
    sections.append(Section(title=SECTION_TITLES[6], content=conclusion, citations=concl_cites))

    # Data-gap disclosure (result validation: never fabricate financial data)
    gaps.append("No financial data (the current data model does not cover "
                "financial statements; manual supplement required)")
    if not _tr(facts, "policy").ok:
        gaps.append("Policy-document search unavailable; "
                    "compliance check based on deterministic rules only")

    return CreditMemo(
        entity_name=entity.name,
        sections=sections,
        compliance_flags=[f"[{f.level}] {f.rule}" for f in flags],
        data_gaps=gaps,
        generated_at=dt.datetime.now().isoformat(timespec="seconds"),
    )


def validate_report(report: CreditMemo) -> list[str]:
    """Run result validation and return a list of error strings (empty = valid).

    Args:
        report: The assembled memo.

    Returns:
        ``list[str]`` of validation errors; empty list means the report passed.

    Implementation: checks that all 7 ``SECTION_TITLES`` are present, and that citation
    coverage (``_citation_coverage``) meets the 0.9 threshold.
    """
    errs: list[str] = []
    have = {s.title for s in report.sections}
    missing = [t for t in SECTION_TITLES if t not in have]
    if missing:
        errs.append(f"Missing sections: {', '.join(missing)}")
    cov = _citation_coverage(report)
    if cov < 0.9:
        errs.append(f"Citation coverage insufficient: {cov:.0%}")
    return errs


def _citation_coverage(report: CreditMemo) -> float:
    """Compute the fraction of citable sections that carry at least one citation.

    Args:
        report: The assembled memo.

    Returns:
        A float in ``[0.0, 1.0]``; 0.0 when there are no citable sections.

    Implementation: every section except "Risk Points & Conclusion" must have a non-empty
    ``citations`` list; returns 0.0 when there are no citable sections.
    """
    must = [s for s in report.sections if s.title != SECTION_TITLES[6]]
    if not must:
        return 0.0
    return sum(1 for s in must if s.citations) / len(must)
