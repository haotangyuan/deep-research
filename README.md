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

研究任务使用有界异步队列执行。外层 `AgentPipeline` 只维护可恢复的业务状态机；AgentScope 负责长生命周期 Agent、`AgentState`、上下文压缩、原生任务、Leader/Worker 团队、Toolkit、Middleware 和运行时事件。`MEDIUM`、`HIGH`、`ULTRA` 预算仍由代码硬约束子研究数、搜索次数、并发数和单次结果数。

### 三档技术路线对照

| 阶段 / 技术 | MEDIUM | HIGH | ULTRA |
|---|---|---|---|
| 产品定位 | 速度与成本优先，快速形成有来源的完整报告 | 质量与耗时平衡，通过双视角降低单报告偏差 | 证据覆盖、章节一致性与过程审计优先 |
| 外层业务状态机 | `AgentPipeline`：QUEUE → SCOPE → HITL（可选）→ IN_RESEARCH → IN_REPORT → COMPLETED | 同 MEDIUM | 同一状态骨架，研究阶段增加动态轮次 |
| `ScopeAgent` | 需求澄清、生成 research brief、识别研究类型 | 同 MEDIUM | 同 MEDIUM，并用研究类型选择 ULTRA JSON 编排模板 |
| HITL | `NONE` 或 `DIRECTION_ONLY`，支持方向 APPROVE / REVISE | 同 MEDIUM | 同 MEDIUM，并支持下一轮轻干预 |
| `SupervisorAgent` | 单轮规划，最多 2 个研究任务 | 单轮规划，最多 4 个研究任务 | 每轮动态规划，模板最多 6 个研究任务；Reviewer 决定继续补强或进入报告 |
| `AgentScopeResearchTeam` | Worker 最大并发 1 | Worker 最大并发 2 | Worker 最大并发 3，跨轮复用研究状态与证据缺口 |
| `ResearcherAgent` | 每分支最多 2 次搜索；结束时提取结构化证据包 | 每分支最多 3 次搜索；结束时提取结构化证据包 | 每分支最多 4 次搜索；证据进入轮次账本和动态质量评审 |
| `SearchAgent` | Tavily 检索、网页摘要、TTL 缓存、in-flight 合并、超时降级 | 同 MEDIUM | 同 MEDIUM |
| LLM 账户并发 | 全局 `LLM_MAX_CONCURRENCY=2` | 同 MEDIUM；两个报告角度可真正并发 | 同 MEDIUM；研究、Reviewer、章节起草与修订共享账户级限流 |
| Research Context FS | 写入 L0 短摘要、L1 概览、L2 原文、`branch_summary`、`evidence` | 同 MEDIUM | 同 MEDIUM，并额外保存章节工作区、共享 claim、mailbox、初稿、修订稿和最终报告 |
| 报告上下文选择 | `ReportContextBuilder` 按章节与字符预算装配 Context FS，失败回退 `supervisor_notes` | 同 MEDIUM | 各章节 Agent 独立执行 L0 召回、L1 精排与 L2 定向下钻 |
| 报告 Agent 主链路 | 单 `ReportAgent` | `ReportAgent:comparative` + `ReportAgent:data-driven` 并行起草 → `ReportAgent:high-synthesis` 单次融合 | `ReportSectionPlanner` → 多个 `ReportSectionAgent` → `ReportConsistencyAgent` → 多个 `ReportSectionReviser` → `ReportAgent:merge` |
| 报告评审 | 不额外评审 | 不运行 `ReportJudge`，融合 Agent 直接综合两个互补视角 | 章节间共享 claim 与证据请求，由一致性 Agent 生成定向 mailbox 消息 |
| ULTRA 对抗审查 | 不启用 | 不启用 | 多个 `UltraDynamicReviewer` 按 coverage、evidence、freshness、source diversity、consistency 投票 |
| 声明交叉验证 | 不启用 | 不启用 | `ClaimVerifier` 对最终报告关键声明进行交叉验证和必要修订 |
| 失败与降级 | 单报告失败 → 兜底报告 | 双角度均失败 → 单 `ReportAgent`；融合失败 → 保留 comparative 草稿；单报告再失败 → 兜底报告 | 章节团队失败 → 完整借鉴点 C（多角度起草、Judge、融合）；再次失败 → 兜底报告 |
| 持久化与可观测性 | MySQL 状态与消息、Redis checkpoint/SSE timeline、AgentScope runtime、OTel Span | 同 MEDIUM，并记录双角度与融合事件 | 同 MEDIUM，并记录轮次、work item、decision log、evidence ledger、章节通信与声明验证事件 |

### 三档真实冷启动验证

以下结果使用同一 MiMo 模型、相同研究题目和 `LLM_MAX_CONCURRENCY=2`，每档测试前均重启后端以清空进程内搜索与摘要缓存。

| 档位 | 完成耗时 | 输入 Token | 输出 Token | 最终报告 | 来源 URL | 实际报告阶段 |
|---|---:|---:|---:|---:|---:|---|
| MEDIUM | 6 分 29 秒 | 81,295 | 30,425 | 9,133 字符 | 16 | 单 `ReportAgent` |
| HIGH | 12 分 02 秒 | 132,056 | 38,392 | 10,034 字符 | 24 | comparative + data-driven + high-synthesis |
| ULTRA | 24 分 41 秒 | 501,453 | 120,554 | 25,474 字符 | 54 | 5 个章节 Agent + Consistency + 5 个 Reviser + merge + ClaimVerifier |

### Ultra 章节报告团队

Ultra 模板默认启用 `report.sectionTeamEnabled`。报告阶段不再只由一个 Agent 消费统一上下文，而是：

1. 根据研究简报动态规划 3–6 个互补章节。
2. 每个章节 Agent 独立执行 L0 广泛召回、L1 精排，并在需要数字、引用、时间、冲突等细节时按 `parent_path` 读取 L2 原文摘录。
3. 章节 Agent 并行起草，将可复用声明和证据请求写入 `research://{research_id}/report/workspace/`。
4. 一致性 Agent 检查数字、术语、重复、证据冲突和跨章节依赖，通过持久化 mailbox 发送定向修订要求。
5. 章节 Agent 并行修订后，主 `ReportAgent:merge` 只负责合并、消重、统一术语和优化段落逻辑。

ULTRA 的主报告链路是章节团队；完整的借鉴点 C（多角度起草、评委打分、冠军与亮点融合）仅作为章节团队失败后的降级路径。HIGH 使用不带 Judge 的轻量借鉴点 C：比较分析与数据证据两个视角并行起草，再执行一次融合。REST、SSE 和最终报告协议在三个档位间保持一致。

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

项目描述：基于 FastAPI、AgentScope 2.0 和 React 构建多 Agent 深度研究平台，实现从需求澄清、动态研究、证据治理到协作式报告生成的完整链路。

- **分层架构设计**：将系统拆分为外层业务状态机与内层 Agent 运行时；`AgentPipeline` 负责 MySQL/Redis 状态一致性、HITL 和断点恢复，AgentScope 负责 Agent 生命周期、任务上下文、工具调用与认知执行，避免将业务事务和前端协议耦合进 Agent 框架。
- **动态工作流设计**：实现 MEDIUM、HIGH、ULTRA 三档研究策略；ULTRA 在需求澄清阶段识别研究类型并选择 JSON 编排模板，由模板控制研究轮次、任务预算、Reviewer 视角和报告策略。每轮由 Supervisor 根据上一轮证据缺口重新规划任务，多 Reviewer 从覆盖度、证据质量、时效性、来源多样性和一致性进行对抗评审，投票决定继续补强或进入报告，最后通过章节 Agent、一致性 Agent、修订 Agent 和 ClaimVerifier 完成协作式报告生成。
- **上下文与证据治理**：设计 Research Context FS，将网页材料拆分为 L0 摘要、L1 概览、L2 原文，并沉淀分支结论和结构化 evidence；报告阶段按章节和预算检索证据，解决长任务上下文膨胀、来源难追溯和一次性 Prompt 过长问题。
- **可靠状态恢复与 HITL 交互**：设计两层 HITL 机制：研究开始前支持方向 `APPROVE / REVISE`，根据用户反馈重新生成 research brief；ULTRA 研究过程中支持追加关注章节、证据补强方式和备注，并在不中断当前轮的情况下作为下一轮规划偏置生效。通过 MySQL CAS 状态迁移、Redis Checkpoint、AgentScope runtime snapshot 实现任务续跑和异常恢复，并使用 Redis ZSet、SSE、`Last-Event-ID` 支持实时进度与断线重放。
- **性能与全链路可观测性**：通过研究任务并发、`LLM_MAX_CONCURRENCY=2`、搜索/摘要 TTL 缓存、in-flight 合并和超时降级控制耗时；三档冷启动实测约为 6/12/25 分钟，并使用 OpenTelemetry + Langfuse 贯通 workflow、Agent、model、tool 链路以定位性能瓶颈和异常。

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
