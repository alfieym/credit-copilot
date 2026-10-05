.PHONY: setup data seed db-up run-api run-ui test lint

## 安装依赖（uv 会按 pyproject 托管 Python 3.11）
setup:
	uv sync

## 只生成合成 CSV 到 data/seed/（无需数据库）
data:
	uv run python data/generate_data.py

## 生成 CSV 并灌入 Postgres（需先 db-up）
seed: data
	uv run python -m credit_copilot.db.seed

## 启动 Postgres + pgvector
db-up:
	docker compose up -d postgres

## 启动可观测栈（Langfuse，阶段4）
db-up-obs:
	docker compose --profile observability up -d

## 启动 FastAPI 后端
run-api:
	uv run uvicorn credit_copilot.api.app:app --reload --port 8000

## 启动 Streamlit 前端
run-ui:
	uv run streamlit run src/credit_copilot/ui/app.py

## 运行测试
test:
	uv run pytest

## 代码检查
lint:
	uv run ruff check .
	uv run mypy src
