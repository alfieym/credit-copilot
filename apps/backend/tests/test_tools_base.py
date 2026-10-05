"""异常处理：with_retry 的重试 / 降级 / 不重试语义。"""
from __future__ import annotations

from credit_copilot.tools.base import FatalError, TransientError, with_retry


def test_fatal_no_retry():
    calls = {"n": 0}

    @with_retry
    def f():
        calls["n"] += 1
        raise FatalError("boom")

    r = f()
    assert r.ok is False
    assert r.fallback_applied is False
    assert calls["n"] == 1  # 致命错误不重试


def test_transient_retries_then_fallback(monkeypatch):
    monkeypatch.setattr("credit_copilot.tools.base.time.sleep", lambda s: None)
    calls = {"n": 0}

    @with_retry
    def f():
        calls["n"] += 1
        raise TransientError("flaky")

    r = f()
    assert r.ok is False
    assert r.fallback_applied is True
    assert calls["n"] == 4  # retries=3 → 共 4 次尝试


def test_success():
    @with_retry
    def f():
        return 42

    r = f()
    assert r.ok is True
    assert r.data == 42


def test_recovers_after_one_transient(monkeypatch):
    monkeypatch.setattr("credit_copilot.tools.base.time.sleep", lambda s: None)
    calls = {"n": 0}

    @with_retry
    def f():
        calls["n"] += 1
        if calls["n"] == 1:
            raise TransientError("flaky")
        return "ok"

    r = f()
    assert r.ok is True
    assert r.data == "ok"
    assert calls["n"] == 2
