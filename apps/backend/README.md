# credit-copilot backend

信贷分析师 Copilot 的后端：FastAPI + OpenAI Agents SDK。

- **模块结构**：`api/`（HTTP/SSE）、`agents/`（Agent 编排 + guardrails）、`tools/`（DB/RAG 工具）、`guardrails/`（SQL 只读白名单）、`llm/`（多提供商客户端）、`db/`（schema + seed）、`config.py`（pydantic-settings）。
- **运行**：见根目录 [README](../../README.md) 的「快速开始」。

## 开发

```bash
uv sync                 # 安装依赖
uv run pytest -q        # 单测（26 个，离线可跑）
uv run ruff check .     # lint
uv run mypy src         # 类型检查
uv run uvicorn credit_copilot.api.app:app --reload --port 8000
```
