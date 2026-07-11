# Deep Research 深度研究

基于 FastAPI、AgentScope 2.x 和 React 的多智能体深度研究平台。系统覆盖需求澄清、研究方向确认、并行资料检索、三层上下文管理、跨章节 Agent 协作和 Markdown 报告生成，并通过 SSE 实时展示执行过程。

![Deep Research](img.png)

## 技术栈

- 后端：Python 3.11、FastAPI、Uvicorn、AgentScope 2.0.3
- 数据：MySQL、SQLAlchemy Async、Redis
- 前端：React、TypeScript、Vite、Tailwind CSS
- 搜索：Tavily Search
- 可观测性：OpenTelemetry、OTLP、Langfuse
- 测试：Pytest、真实 SSE smoke、真实 Mimo 工作流 smoke

## 项目结构

```text
deep-research-main/
├── backend-python/          # 当前后端
│   ├── app/
│   │   ├── api/             # REST/SSE 路由
│   │   ├── application/     # Agent、工作流、服务与工具
│   │   ├── core/            # 配置、认证、错误与通用工具
│   │   ├── domain/          # ORM、DTO、状态与运行时契约
│   │   └── infrastructure/  # DB、Redis、LLM、搜索与可观测性
│   └── tests/
├── frontend/                # React 前端
├── notebook/                # 项目文档与开发笔记
│   ├── architecture/        # 架构设计
│   ├── contract/            # API 与数据契约
│   ├── features/            # 功能设计（HITL、ULTRA 动态工作流）
│   ├── operations/          # 性能与可观测性
│   └── dev/                 # 开发日志
├── docs/                    # Context FS、报告团队与实施计划文档
└── db_deep_research.sql     # 数据库 schema
```

## 工作流

```mermaid
flowchart LR
    User["用户问题"] --> Scope["ScopeAgent<br/>澄清与研究简报"]
    Scope -->|"方向确认模式"| HITL["人工确认 / 修订"]
    HITL --> Supervisor
    Scope --> Supervisor["Supervisor Leader<br/>AgentScope TaskContext"]
    Supervisor --> Researcher["Researcher Workers<br/>AgentScope Research Team"]
    Researcher --> Search["SearchAgent<br/>Tavily 检索与摘要"]
    Search --> Researcher
    Researcher --> ContextFS["Research Context FS<br/>L0 / L1 / L2 / evidence"]
    ContextFS --> SectionTeam["章节报告团队<br/>并行起草与交叉修订"]
    SectionTeam --> Report["ReportAgent:merge<br/>合并与优化逻辑"]
```

研究任务使用有界异步队列执行。外层 `AgentPipeline` 只维护可恢复的业务状态机；AgentScope 负责长生命周期 Agent、`AgentState`、上下文压缩、原生任务、Leader/Worker 团队、Toolkit、Middleware 和运行时事件。`MEDIUM`、`HIGH`、`ULTRA` 预算仍由代码硬约束子研究数、搜索次数、并发数和单次结果数。

### Ultra 章节报告团队

Ultra 模板默认启用 `report.sectionTeamEnabled`。报告阶段不再只由一个 Agent 消费统一上下文，而是：

1. 根据研究简报动态规划 3–6 个互补章节。
2. 每个章节 Agent 独立执行 L0 广泛召回、L1 精排，并在需要数字、引用、时间、冲突等细节时按 `parent_path` 读取 L2 原文摘录。
3. 章节 Agent 并行起草，将可复用声明和证据请求写入 `research://{research_id}/report/workspace/`。
4. 一致性 Agent 检查数字、术语、重复、证据冲突和跨章节依赖，通过持久化 mailbox 发送定向修订要求。
5. 章节 Agent 并行修订后，主 `ReportAgent:merge` 只负责合并、消重、统一术语和优化段落逻辑。

章节团队失败时会自动回退原 Ultra 多角度起草/评审/融合链路，REST、SSE 和最终报告协议不变。

## AgentScope 当前角色

AgentScope 已不再只是底层 Agent 调用适配器，而是项目的 **Agent 运行时与团队执行层**：

| 能力 | 初版接入 | 当前实现 |
|---|---|---|
| Agent 生命周期 | 每次调用临时执行 | 按研究会话复用 Scope、Supervisor、Researcher、Search、Report Agent |
| 状态 | 业务状态自行维护 | 业务状态与隔离 `AgentState`、版本化 runtime snapshot 协同 |
| 多 Agent 任务 | 自定义并发函数 | AgentScope `AgentState.tasks_context/Task` 承载任务状态，项目 Team 协调器按稳定 Worker ID 并发调度 |
| 运行治理 | 外层循环控制 | `ContextConfig`、Middleware、单次工具预算、失败隔离 |
| 可观测性 | 项目 Span 为主 | 同一 OTel Trace 中组合 workflow/stage 与 AgentScope agent/model/tool Span |

业务 Workflow 仍由 `AgentPipeline` 掌握，因为 QUEUE、HITL、断点恢复、MySQL/Redis 一致性属于产品状态机；AgentScope 掌握认知执行、任务上下文和运行时治理。这个边界避免把数据库事务和前端协议耦合到框架内部，同时让框架承担足够多的核心职责。

## 简历项目描述（协作维护）

> 以下五条是当前实现的唯一标准版本。后续技术升级时直接同步修改本节，项目协作者可据此更新简历。

**智能深度研究平台｜项目负责人**<br>
**FastAPI、AgentScope 2.0、React、MySQL、Redis、OpenTelemetry、Langfuse**

项目描述：构建基于多 Agent 协作的自动化深度研究平台，覆盖需求澄清、任务规划、并行检索、网页摘要、报告生成、人工确认、断点恢复与实时链路展示。

- **分层架构设计**：采用「业务状态机 + Agent 运行时」分层架构——外层 `AgentPipeline` 基于 MySQL/Redis 维护 QUEUE、SCOPE、HITL、IN_RESEARCH、IN_REPORT、COMPLETED 等可恢复的业务状态机，内层 AgentScope 2.0.3 负责 Agent 生命周期、隔离 `AgentState`、原生 `TaskContext`、Leader/Worker 团队、Toolkit、Middleware 与 tracing；该边界把数据库事务、前端协议与框架内部解耦，让框架承担认知执行，业务层掌控持久化与一致性。
- **ULTRA 动态工作流档位**：设计质量优先的动态研究编排：ScopeAgent 在生成 research brief 时同步识别研究类型，并选择 JSON 模板控制轮次、预算、reviewer lens、章节团队与声明验证策略；Researcher 输出结构化 findings + sources 供证据账本消费，Supervisor 通过多 reviewer 对抗审查和 5 维质量评分决定「继续补强 / 进入报告」；报告阶段由章节 Agent 并行下钻 L2、起草、交换共享声明和证据请求，经一致性 Agent 路由修订后由主 ReportAgent 仅做逻辑合并，同时保留原多角度链路降级、关键声明交叉验证、用户轻干预和证据缺口披露。
- **HITL 与可靠状态恢复**：实现研究方向 APPROVE/REVISE 确认（范围分析后暂停等待用户反馈）、失败续跑与取消清理；将业务 checkpoint、AgentScope 任务状态及有界 runtime snapshot 保存至 Redis，通过数据库 CAS 限制合法状态迁移，避免重复执行与并发误操作，断点恢复时优先复用 checkpoint 跳过已完成阶段。
- **可解释进度与用户可干预研究过程**：设计 MySQL + Redis ZSet 双写时间线和 `Last-Event-ID` 断线重放，保证 SSE 断线后无损恢复；通过 Event Bridge 将动态决策、任务批次、干预事件和采纳结果映射为兼容事件，前端分层展示研究进度、决策依据与下一轮调整回显，使多轮研究过程对用户全程透明可干预。
- **上下文治理与全链路可观测性**：针对长研究任务中的上下文碎片化、检索黑盒、Token 膨胀和“近似无损压缩”超时问题，设计面向 Agent 的 Research Context FS，以 `research://...` 统一组织搜索资源、分支记忆、证据包和报告协作产物；通过 L0 摘要召回、L1 概览精排、L2 原文定向下钻降低 Token 消耗，并将章节证据快照、共享 claim、mailbox、初稿、修订稿和最终报告全部持久化；同时保留 `supervisor_notes` 回退和原 ReportAgent 降级链路，配套预算限流、搜索/摘要 TTL 缓存、in-flight 合并、网页 AgentState 隔离和超时降级，并以 OpenTelemetry 贯通 `workflow → stage → AgentScope agent → model/tool` 全链路。

## 快速开始

前置依赖：Conda、MySQL 8.0+、Redis 6.0+。默认数据库为 `db_deep_research`，本地 MySQL 账号为 `root`，密码为 `12345678`。

```bash
conda env create -f backend-python/environment.yml
cp backend-python/.env.example backend-python/.env

cd backend-python
./start-python-backend.sh
```

另开终端启动前端：

```bash
cd frontend
npm install
npm run dev
```

- 后端：`http://127.0.0.1:8080`
- 健康检查：`http://127.0.0.1:8080/health`
- Scalar API 文档：`http://127.0.0.1:8080/scalar/index.html`
- OpenAPI：`http://127.0.0.1:8080/v3/api-docs`

模型配置从 MySQL `model` 表读取，完整链路测试默认查找数据库中的 `mimo` 模型。

## 测试

```bash
cd backend-python
conda run -n deep-research-py python -m compileall -q app tests
conda run -n deep-research-py pytest -q
conda run -n deep-research-py python tests/api_feature_smoke.py
PYTHONPATH=. conda run -n deep-research-py python tests/observability_smoke.py
PYTHONUNBUFFERED=1 conda run -n deep-research-py python tests/live_hybrid_workflow_smoke.py
conda run -n deep-research-py pytest -q \
  tests/test_context_domain.py \
  tests/test_context_store.py \
  tests/test_context_writer.py \
  tests/test_research_evidence_package.py \
  tests/test_branch_context_package.py \
  tests/test_context_retrieval.py \
  tests/test_report_context.py \
  tests/test_report_team.py

cd ../frontend
npm run build
```

## 文档

- [后端开发与配置](backend-python/README.md)
- [架构设计](notebook/architecture/架构设计.md)
- [API 与数据契约](notebook/contract/API与数据契约.md)
- [性能与可观测性](notebook/operations/性能与可观测性.md)
- [ULTRA 动态工作流与轻干预](notebook/features/ULTRA动态工作流与轻干预.md)
- [HITL 方向确认](notebook/features/hitl.md)
- [Research Context FS 与上下文压缩优化](docs/research-context-fs-implementation-summary.md)
- [章节多 Agent 报告团队](docs/report-section-agent-team.md)
