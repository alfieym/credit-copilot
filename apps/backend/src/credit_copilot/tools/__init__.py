"""Tool layer: framework-agnostic, reusable tools.

Deliberately imports nothing from the Agents SDK, so the tools can be reused verbatim
for later scenarios (T1 Q&A / T3 workflow automation). Contains:
- ``base.py`` — ToolResult + retry/backoff + exception taxonomy.
- ``datawarehouse.py`` — deterministic canned SQL + entity resolution.
- ``policy_search.py`` — BM25 chunk retrieval over the policy corpus.
"""
