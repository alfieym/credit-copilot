"""Multi-provider LLM client (default OpenAI; DeepSeek/Qwen/Zhipu via
OpenAI-compatible endpoint; Claude via Bedrock).

The other half of tool-calling: only reasoning / drafting goes to the LLM; here SDK
exceptions are translated into TransientError / FatalError / ToolTimeout from
:mod:`credit_copilot.tools.base` for uniform handling by ``with_retry``.
"""
from __future__ import annotations

import openai
from openai import OpenAI

from credit_copilot.config import Settings, get_settings
from credit_copilot.tools.base import FatalError, ToolTimeout, TransientError


def has_llm_key(cfg: Settings) -> bool:
    """Whether usable LLM credentials exist
    (Bedrock uses the default AWS credential chain, treated as always available)."""
    if cfg.llm_provider == "bedrock":
        return True
    if cfg.llm_provider == "openai":
        return bool(cfg.openai_api_key or cfg.llm_api_key)
    return bool(cfg.llm_api_key)


class LLMClient:
    """Completion + exception classification.
    Missing key raises FatalError (scenario layer degrades on it)."""

    def __init__(self, *, temperature: float = 0.2) -> None:
        self._cfg = get_settings()
        self._temperature = temperature
        self._client: OpenAI | None = None
        if self._cfg.llm_provider != "bedrock":
            base_url, model, key = self._openai_compat_target()
            self._model = model
            self._client = OpenAI(api_key=key or "sk-missing", base_url=base_url, timeout=30.0)

    def _openai_compat_target(self) -> tuple[str, str, str]:
        cfg = self._cfg
        if cfg.llm_provider == "openai":
            return cfg.openai_base_url, cfg.openai_model, cfg.openai_api_key or cfg.llm_api_key
        return cfg.llm_base_url, cfg.llm_model, cfg.llm_api_key

    def complete(self, system: str, user: str) -> str:
        """Synchronous completion returning text. Classifies exceptions into ToolError subtypes."""
        cfg = get_settings()
        if not has_llm_key(cfg):
            raise FatalError("No LLM API key configured (LLM_API_KEY / OPENAI_API_KEY)")
        if cfg.llm_provider == "bedrock":
            return self._complete_bedrock(system, user)
        return self._complete_openai(system, user)

    def _complete_openai(self, system: str, user: str) -> str:
        assert self._client is not None  # guaranteed by __init__
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self._temperature,
            )
        except openai.APITimeoutError as e:
            raise ToolTimeout(str(e)) from e
        except openai.RateLimitError as e:
            raise TransientError(f"Rate limited: {e}") from e
        except openai.APIConnectionError as e:
            raise TransientError(f"Connection failed: {e}") from e
        except openai.AuthenticationError as e:
            raise FatalError(f"Authentication failed: {e}") from e
        except openai.BadRequestError as e:
            raise FatalError(f"Bad request: {e}") from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientError(f"Server error {e.status_code}") from e
            raise FatalError(f"Request rejected {e.status_code}: {e}") from e
        content = resp.choices[0].message.content
        return content or ""

    def _complete_bedrock(self, system: str, user: str) -> str:
        try:
            import boto3  # optional dependency (see pyproject optional-dependencies bedrock)
        except ImportError as e:
            raise FatalError("Bedrock requires boto3; install it with: "
                             "uv sync --extra bedrock") from e
        try:
            client = boto3.client("bedrock-runtime", region_name=self._cfg.aws_region)
            resp = client.converse(
                modelId=self._cfg.bedrock_model,
                messages=[{"role": "user", "content": [{"text": user}]}],
                system=[{"text": system}],
            )
            return resp["output"]["message"]["content"][0]["text"]
        except Exception as e:  # noqa: BLE001 — Bedrock failure is treated as fatal
            raise FatalError(f"Bedrock call failed: {e}") from e
