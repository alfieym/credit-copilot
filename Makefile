.PHONY: setup data seed db-up db-up-obs run-api web-setup web-dev web-build test test-all lint

# 后端位于 apps/backend（uv 托管 Python 3.11），前端位于 apps/web（npm 托管）
BACKEND := apps/backend
WEB := apps/web

## 安装后端依赖（uv 按 pyproject 托管 Python 3.11）
setup:
	cd $(BACKEND) && uv sync

## 只生成合成 CSV 到 apps/backend/data/seed/（无需数据库）
data:
	cd $(BACKEND) && uv run python data/generate_data.py

## 生成 CSV 并灌入 Postgres（需先 db-up）
seed: data
	cd $(BACKEND) && uv run python -m credit_copilot.db.seed

## 启动 Postgres + pgvector
db-up:
	docker compose up -d postgres

## 启动可观测栈（Langfuse，阶段4）
db-up-obs:
	docker compose --profile observability up -d

## 启动 FastAPI 后端
run-api:
	cd $(BACKEND) && uv run uvicorn credit_copilot.api.app:app --reload --port 8000

## 安装前端依赖
web-setup:
	cd $(WEB) && npm install

## 启动 Next.js 前端（开发）
web-dev:
	cd $(WEB) && npm run dev

## 构建前端
web-build:
	cd $(WEB) && npm run build

## 运行后端测试
test:
	cd $(BACKEND) && uv run pytest

## 后端代码检查（ruff + mypy）
lint:
	cd $(BACKEND) && uv run ruff check .
	cd $(BACKEND) && uv run mypy src

## 全量检查（后端 + 前端）
test-all: test lint web-build
