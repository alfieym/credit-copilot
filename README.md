# 信贷分析师 Copilot（Credit Analyst Copilot）

面向**对公/批发信贷域**的多工具 AI Agent。首个落地场景是**授信尽调报告自动生成（Credit Memo）**：输入一句「生成『××公司』的授信尽调报告」，Agent 自动拆解任务、跨数仓 + 政策文档取数、核验合规、成文，输出一份**带引用/出处**的结构化报告。

> 传统数仓工程师 → 大模型 Agent 开发工程师 转型作品集项目。

## 为什么做这个场景

分析师写一份授信尽调报告，要横跨 CARM / WREN / 数仓 / 政策文档手工拼装评级、额度、敞口、担保与合规条款，耗时数小时~数天、易漏条款。行业已验证这是信贷域 ROI 最明确的 Agent 场景：

- **光大银行**：传统百页授信报告 7 天 → 3 分钟，已推广 39 家分行、近 2000 名客户经理。
- **河北银行「冀银智脑」**：撰写 7 天 → 10 分钟，减轻 70% 工作量。
- **Moody's / Auquan / Evalueserve**：credit memo 自动化，首稿人工量减 30–50%，单户省 1–2 天。

本项目把这条主线做通，并把这套**工具层**设计成可复用到问答、对账、贷后预警等场景的底座。

## 报告结构（章节 = 任务拆解的粒度）

| 章节 | 数据来源 | 工具 |
|---|---|---|
| 1. 借款人及集团概况 | `dim_borrower` + `dim_borrowing_group` | DB（确定性查询） |
| 2. 评级情况 | `fact_rating`（时间维 SCD） | DB |
| 3. 授信方案 | `dim_main_facility` + `dim_sub_facility` | DB |
| 4. 敞口与限额使用 | `fact_utilization` + 集团限额 | DB |
| 5. 相关方与担保结构 | `dim_involved_party` | DB |
| 6. 政策合规核验 | 政策文档语料 | RAG |
| 7. 风险点与结论 | 上述事实 + 合规结论 | LLM 合成（非工具） |
| 数据缺口声明 | —— | 校验层（**不编造**缺失数据） |

## 四大设计原则 → 代码落点

四原则是本项目要展示的核心能力，每一条都对应到具体文件与测试：

| 设计原则 | 落点文件 | 关键实现 | 测试 |
|---|---|---|---|
| ① 任务拆解 | [scenarios/credit_memo.py](src/credit_copilot/scenarios/credit_memo.py) | 用**确定性 DAG**（LangGraph StateGraph）而非自由 ReAct；7 章节 = 7 节点，`collect_facts` 并行 fan-out | [test_credit_memo.py](tests/test_credit_memo.py) / [test_graph_smoke.py](tests/test_graph_smoke.py) |
| ② 工具调用 | [tools/datawarehouse.py](src/credit_copilot/tools/datawarehouse.py) / [tools/policy_search.py](src/credit_copilot/tools/policy_search.py) | **明确"什么交给什么"**：确定性事实 → DB（参数化 canned SQL，不让 LLM 自由写 SQL）；政策约束 → RAG（BM25 分块检索）；推理成文 → LLM | [test_policy_search.py](tests/test_policy_search.py) |
| ③ 异常处理 | [tools/base.py](src/credit_copilot/tools/base.py) | 统一 `ToolResult` 返回；`with_retry` 指数退避（仅瞬态错误重试）；`FatalError` 不重试；DB 层 `connect_timeout` + `statement_timeout`；**单章失败降级、不击穿整份报告** | [test_tools_base.py](tests/test_tools_base.py) |
| ④ 结果校验 | [guardrails/sql_guard.py](src/credit_copilot/guardrails/sql_guard.py) + 场景内 `resolve_entity`/`validate_report` | 四道关卡：SQL 只读白名单（执行前）→ 实体消歧（0 命中拒答 / 多命中列候选）→ 数值/完整性/引用校验（可回炉成文）→ 事实核验 | [test_sql_guard.py](tests/test_sql_guard.py) / [test_credit_memo.py](tests/test_credit_memo.py) |

## 架构

```
一句「生成『恒远汽车零部件』的授信尽调报告」
  → FastAPI /report/stream (SSE 逐节点进度)
    → LangGraph StateGraph（确定性 DAG）
        resolve_entity           实体消歧：0命中拒答 / >1命中列候选
        collect_facts            并行 fan-out 取数（DB 工具 + 政策检索）
        check_compliance         政策比对 → 合规 flag
        compose_report           LLM 成文（仅"风险结论+成文"交给 LLM）
        validate_report          四道校验（不过 → 回炉 compose_report）
    → 工具层（全部返回 ToolResult）
        ├─ datawarehouse：canned SQL + 只读 guardrail + 超时
        ├─ policy_search：BM25 分块检索 + chunk 引用
        └─ llm client：OpenAI 兼容 + 异常分类
```

## 领域模型

| 表 | 含义 |
|---|---|
| `dim_borrowing_group` | 借款集团（风险合并单元） |
| `dim_borrower` | 借款人/债务人 |
| `dim_main_facility` | 主额度（Revolving/Term/Trade/Bridge） |
| `dim_sub_facility` | 子额度（LC/Guarantee/Cash/Term/Aval） |
| `fact_rating` | 评级（时间维 SCD） |
| `dim_involved_party` | 相关方（借款人/担保人/代理行/牵头行） |
| `map_carm_wren` | 跨系统实体映射（含未匹配，演示数据质量痛点） |
| `fact_utilization` | 额度使用/敞口（月度时间维） |

## 快速开始

```bash
# 0. 前置：uv、Docker
cp .env.example .env          # 填入 LLM_API_KEY（DeepSeek 等）
make setup                    # 安装依赖
make data                     # 生成合成 CSV 到 data/seed/（无需数据库）
make db-up                    # 启动 Postgres+pgvector
make seed                     # 生成 + 灌库

# 1. 起 API
make run-api

# 2. 同步生成报告（JSON）
curl -s -X POST localhost:8000/report \
  -H 'Content-Type: application/json' \
  -d '{"query":"生成『恒远汽车零部件有限公司』的授信尽调报告"}'

# 3. 流式生成（SSE，逐节点进度）
curl -N -X POST localhost:8000/report/stream \
  -H 'Content-Type: application/json' \
  -d '{"query":"生成『恒远汽车零部件有限公司』的授信尽调报告"}'
```

## 项目结构

```
src/credit_copilot/
  guardrails/sql_guard.py       # 只读 SQL 白名单 / 行数上限（结果校验）
  tools/base.py                 # ToolResult + with_retry（异常处理）
  tools/datawarehouse.py        # canned SQL 工具（工具调用）
  tools/policy_search.py        # BM25 政策检索 + chunk 引用（工具调用）
  llm/client.py                 # OpenAI 兼容客户端 + 异常分类
  scenarios/credit_memo.py      # 授信尽调 DAG（任务拆解 + 结果校验）
  api/app.py                    # FastAPI /report、/report/stream
docs/policy/*.md                # 政策文档语料（RAG 依据）
tests/                          # 26 个单测，覆盖四原则
```

## 技术栈

- **Agent 编排**：LangGraph（确定性 DAG + 条件回边）
- **LLM**：DeepSeek（OpenAI 兼容，通义/智谱可无缝切换）
- **检索**：BM25-lite（离线、零 embedding key 降级），阶段1 可叠 BGE-M3 向量初筛 + 重排
- **向量库 + 数仓**：PostgreSQL 16 + pgvector
- **后端/前端**：FastAPI（SSE）/ Streamlit
- **可观测/评估**：Langfuse / RAGAS + SQL 黄金集（阶段4）

## 路线图

- [x] 阶段0 · 地基与数据（星型模型 + 合成数据 + 脚手架）
- [~] 阶段1 · RAG 管线（分块 + BM25 检索已落地；hybrid 向量 + rerank 待补）
- [~] 阶段2 · Text-to-SQL（报告走 canned SQL 已落地；自由 Text-to-SQL 留给 T1 问答）
- [~] 阶段3 · Agent 编排（首个场景「授信尽调报告」DAG + Guardrails + API 已落地；T1 问答 Router、T3 流程自动化待做）
- [ ] 阶段4 · 评估与可观测（RAGAS + SQL 黄金集 + Langfuse）
- [ ] 阶段5 · 企业化抽象（DataSource/DocumentSource 接口 + 文档）

### 场景蓝图（同一套工具层可复用）

| 层级 | 场景 | 状态 |
|---|---|---|
| T2 报告 ★主攻 | **授信尽调报告生成** | ✅ 已实现 |
| T2 报告 | 集团敞口与集中度月报 / 评级迁移分析 | 待做 |
| T1 问答 | 一句话问答（评级/额度/敞口/政策） | 待做 |
| T3 流程自动化 | 跨系统对账 / 贷后预警 / 到期提醒 | 待做 |

## 边界说明

- **财务分析章节**：当前数据模型无财务报表，报告以 `data_gaps` 显式声明「无财务数据/待补充」——这本身是**结果校验不编造**的正面演示；如需补全，扩展 `fact_financial` 表 + 财报 PDF 解析。
- **行业分析**：暂以政策文档中的行业准入描述代替，依赖外部行业库的部分留待后续。
