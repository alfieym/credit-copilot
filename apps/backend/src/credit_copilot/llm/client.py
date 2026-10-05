"""多提供商 LLM 客户端（默认 OpenAI；DeepSeek/通义/智谱走 OpenAI 兼容；Claude 走 Bedrock）。

「工具调用」的另一半：只有推理 / 成文才交给 LLM；这里把 SDK 异常翻译成
:mod:`credit_copilot.tools.base` 里的 TransientError / FatalError / ToolTimeout，
供 ``with_retry`` 统一处理。
"""
from __future__ import annotations

import openai
from openai import OpenAI

from credit_copilot.config import Settings, get_settings
from credit_copilot.tools.base import FatalError, ToolTimeout, TransientError


def has_llm_key(cfg: Settings) -> bool:
    """是否具备可用的 LLM 凭证（Bedrock 走 AWS 默认凭证链，恒视为可用）。"""
    if cfg.llm_provider == "bedrock":
        return True
    if cfg.llm_provider == "openai":
        return bool(cfg.openai_api_key or cfg.llm_api_key)
    return bool(cfg.llm_api_key)


class LLMClient:
    """补全 + 异常分类。缺 key 时抛 FatalError（场景层据此降级）。"""

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
        """同步补全，返回文本。按异常类型分类抛 ToolError。"""
        cfg = get_settings()
        if not has_llm_key(cfg):
            raise FatalError("未配置 LLM API key（LLM_API_KEY / OPENAI_API_KEY）")
        if cfg.llm_provider == "bedrock":
            return self._complete_bedrock(system, user)
        return self._complete_openai(system, user)

    def _complete_openai(self, system: str, user: str) -> str:
        assert self._client is not None  # 由 __init__ 保证
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
            raise TransientError(f"限流: {e}") from e
        except openai.APIConnectionError as e:
            raise TransientError(f"连接失败: {e}") from e
        except openai.AuthenticationError as e:
            raise FatalError(f"鉴权失败: {e}") from e
        except openai.BadRequestError as e:
            raise FatalError(f"参数错误: {e}") from e
        except openai.APIStatusError as e:
            if e.status_code >= 500:
                raise TransientError(f"服务端 {e.status_code}") from e
            raise FatalError(f"请求被拒 {e.status_code}: {e}") from e
        content = resp.choices[0].message.content
        return content or ""

    def _complete_bedrock(self, system: str, user: str) -> str:
        try:
            import boto3  # 可选依赖，见 pyproject [project.optional-dependencies].bedrock
        except ImportError as e:
            raise FatalError("使用 Bedrock 需先安装 boto3：uv sync --extra bedrock") from e
        try:
            client = boto3.client("bedrock-runtime", region_name=self._cfg.aws_region)
            resp = client.converse(
                modelId=self._cfg.bedrock_model,
                messages=[{"role": "user", "content": [{"text": user}]}],
                system=[{"text": system}],
            )
            return resp["output"]["message"]["content"][0]["text"]
        except Exception as e:  # noqa: BLE001 —— Bedrock 调用失败按致命错误处理
            raise FatalError(f"Bedrock 调用失败: {e}") from e
