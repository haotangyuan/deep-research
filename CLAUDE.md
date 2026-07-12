# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

基于 FastAPI + AgentScope 2.0.3 + React 的多智能体深度研究平台。覆盖需求澄清（ScopeAgent）、并行检索（Researcher/SearchAgent + Tavily）、三层 Research Context FS（L0 召回 / L1 概览 / L2 摘录）、ULTRA 动态工作流、HITL 方向确认、断点恢复、章节报告团队、Markdown 报告生成，并通过 SSE 实时回放研究链路。

## 常用命令

```bash
# 一次性环境
conda env create -f backend-python/environment.yml
cp backend-python/.env.example backend-python/.env

# 后端（绑定 conda 环境 deep-research-py）
cd backend-python
conda run -n deep-research-py python -m compileall -q app tests
conda run -n deep-research-py pytest -q                                          # 全量
conda run -n deep-research-py pytest -q tests/test_report_team.py               # 单文件
conda run -n deep-research-py pytest -q tests/test_report_team.py::test_x       # 单用例
./start-python-backend.sh                                                        # 监听 0.0.0.0:8080

# 前端
cd frontend
npm install
npm run dev                # Vite 开发服
npm run build              # tsc + vite build（生产前必跑）

# 本地基础设施（docker-compose.yml）
docker compose up -d mysql redis
```

环境预设：本地 MySQL `root/12345678`、数据库 `db_deep_research`；模型走 MySQL `model` 表（开发默认 `mimo`/MiMo V2.5 Pro），不在代码里硬编码。

## 架构骨架

外层 `AgentPipeline`（`app/application/pipeline.py`）只持有可恢复的业务状态机，状态迁移 `QUEUE → SCOPE → HITL → IN_RESEARCH → IN_REPORT → COMPLETED`，通过 MySQL CAS + Redis ZSet 时间线 + `Last-Event-ID` 断线重放保证一致性和 SSE 续传。

内层 AgentScope 负责认知执行：Scope / Supervisor / Researcher / Search / Report Agent 的长生命周期、隔离 `AgentState`、`ContextConfig`、原生 `TaskContext` 任务状态、Leader/Worker 团队、Toolkit、Middleware 与 tracing。Checkpoint 同时保存业务状态、AgentScope 任务状态和有界 runtime snapshot；网页摘要的 AgentState 不写入 checkpoint，避免正文被复制。

报告阶段（Ultra 模板默认 `report.sectionTeamEnabled=true`）走 `ReportSectionPlanner → 章节 Agent 并行 L0/L1/L2 → 共享 claim + evidence mailbox → ReportConsistencyAgent → 章节修订 → ReportAgent:merge`，失败时回退原多角度起草链路。

依赖方向：`api → application → {domain, infrastructure}`，`core` 不承载业务状态。`main.py` 只做装配和资源生命周期。

## 代码边界

- `app/api`：协议适配（REST、SSE、依赖注入）。**不写业务流程**。
- `app/application`：研究用例、Agent、Pipeline、ULTRA 编排、章节团队、提示词、工具契约。
- `app/domain`：ORM 实体、API DTO、研究状态、运行时契约。
- `app/infrastructure`：MySQL、Redis、SSE Hub、AgentScope Runtime、LLM、Tavily、可观测性。
- `app/core`：配置、认证、异常、JSON、时间、序列化等无业务状态的通用工具。

## 修改红线

修改 **REST、SSE、MySQL、Redis** 任何一处时，必须保持现有前端协议、字段命名和持久化结构兼容（前端协议在 `frontend/src/` + `notebook/contract/API与数据契约.md`，持久化结构在 `db_deep_research.sql` 与 `app/domain/models.py`）。

性能相关改动必须保留：
- 预算并发（`maxConcurrentUnits`、`LLM_MAX_CONCURRENCY`）
- 搜索/摘要 TTL 缓存（`TAVILY_*`、`RESEARCH_SEARCH_SUMMARY_*`）
- 超时降级与 in-flight 合并（`RESEARCH_SEARCH_SUMMARY_TIMEOUT_SECONDS`）
- 报告输入上限（`RESEARCH_REPORT_FINDINGS_MAX_CHARS`、`RESEARCH_CONTEXT_L*_MAX_CHARS`、`RESEARCH_CONTEXT_RAW_EXCERPT_MAX_CHARS`）

可观测性必须维持 `workflow → stage → model/tool` Span 链路。应用与 AgentScope 共享全局 OTel Provider，导出由 `RESEARCH_OBSERVABILITY_*` + Langfuse/OTLP 控制；默认不采集 I/O。

## 测试约定

- 一律走真实请求链路，**不 mock** MySQL/Redis/Tavily/LLM/sse-starlette。
- `live_hybrid_workflow_smoke.py` 需要数据库里存在 `mimo` 模型且能访问其 API 与 Tavily；`VERIFY_REVISE=false` 可只验证 HITL 批准分支。
- 单测优先跑上下文/报告团队相关文件：`test_context_*`、`test_research_evidence_package`、`test_branch_context_package`、`test_report_context`、`test_report_team`、`test_ultra_dynamic_online`、`test_ultra_interventions`。

## 进一步阅读

- 架构与运行时契约：[`notebook/architecture/架构设计.md`](notebook/architecture/架构设计.md)
- API/SSE/MySQL 数据契约：[`notebook/contract/API与数据契约.md`](notebook/contract/API与数据契约.md)
- ULTRA 动态工作流 + 轻干预：[`notebook/features/ULTRA动态工作流与轻干预.md`](notebook/features/ULTRA动态工作流与轻干预.md)
- HITL 方向确认：[`notebook/features/hitl.md`](notebook/features/hitl.md)
- 性能与可观测性：[`notebook/operations/性能与可观测性.md`](notebook/operations/性能与可观测性.md)
- Research Context FS 实施：[`docs/research-context-fs-implementation-summary.md`](docs/research-context-fs-implementation-summary.md)
- 章节报告团队：[`docs/report-section-agent-team.md`](docs/report-section-agent-team.md)
- 后端 README：[`backend-python/README.md`](backend-python/README.md)