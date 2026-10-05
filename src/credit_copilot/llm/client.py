"""OpenAI 兼容 LLM 客户端（DeepSeek / 通义 / 智谱），带超时与异常分类。

「工具调用」的另一半：只有推理 / 成文才交给 LLM；这里把 SDK 异常翻译成
:mod:`credit_copilot.tools.base` 里的 TransientError / FatalError / ToolTimeout，
供 ``with_retry`` 统一处理。
"""
from __future__ import annotations

import openai
from openai import OpenAI

from credit_copilot.config import get_settings
from credit_copilot.tools.base import FatalError, ToolTimeout, TransientError


class LLMClient:
    """极薄封装：补全 + 异常分类。缺 API key 时抛 FatalError（场景层据此降级）。"""

    def __init__(self, *, temperature: float = 0.2) -> None:
        cfg = get_settings()
        self._model = cfg.llm_model
        self._temperature = temperature
        self._client = OpenAI(
            api_key=cfg.llm_api_key or "sk-missing",
            base_url=cfg.llm_base_url,
            timeout=30.0,
        )

    def complete(self, system: str, user: str) -> str:
        """同步补全，返回文本。按异常类型分类抛 ToolError。"""
        if not get_settings().llm_api_key:
            raise FatalError("未配置 LLM_API_KEY")
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
