"""LLM client: degrade gracefully when the API key is missing (no network call)."""
from __future__ import annotations

import pytest

from credit_copilot.llm.client import LLMClient
from credit_copilot.tools.base import FatalError


def test_missing_api_key_raises_fatal():
    with pytest.raises(FatalError):
        LLMClient().complete("system", "user")
