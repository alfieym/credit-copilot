"""LLM 客户端：缺 key 时优雅降级（不发起网络调用）。"""
from __future__ import annotations

import pytest

from credit_copilot.llm.client import LLMClient
from credit_copilot.tools.base import FatalError


def test_missing_api_key_raises_fatal():
    with pytest.raises(FatalError):
        LLMClient().complete("system", "user")
