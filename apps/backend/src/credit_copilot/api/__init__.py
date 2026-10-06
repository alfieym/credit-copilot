"""FastAPI API layer (``app.py``).

Exposes the report-generation endpoints:
- ``GET /health`` — liveness probe.
- ``POST /report`` — synchronous credit-memo generation (structured JSON).
- ``POST /report/stream`` — streaming generation over SSE (per-stage progress).
"""
