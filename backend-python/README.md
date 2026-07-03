# Deep Research Python Backend

## 模块结构

```text
app/
├── main.py                 # FastAPI 入口和生命周期
├── api/                    # HTTP/SSE 路由及依赖组装
├── application/            # 用例层
│   ├── agents.py           # Scope/Supervisor/Researcher/Search/Report
│   ├── pipeline.py         # 队列和研究工作流
│   ├── research_team.py    # AgentScope Leader/Worker 团队
│   ├── services.py         # 用户、模型、研究服务
│   ├── prompts.py          # Agent 提示词
│   └── tools.py            # 工具契约
├── core/                   # 配置、认证、异常、序列化和时间工具
├── domain/                 # ORM 实体、API DTO、研究状态、Agent 运行时契约
└── infrastructure/         # MySQL、Redis、SSE、AgentScope Runtime、Tavily、OTel
```

依赖方向以 `api -> application -> domain/infrastructure` 为主。`main.py` 只负责装配和资源生命周期，不承载业务逻辑。

## AgentScope 混合工作流

外层 `AgentPipeline` 保留 QUEUE、SCOPE、HITL、IN_RESEARCH、IN_REPORT、COMPLETED 等持久业务状态；内层 AgentScope 2.0.3 负责：

- 每个研究会话的长生命周期 Agent 和隔离 `AgentState`
- `ContextConfig` 上下文压缩与工具结果边界
- Supervisor 原生 `TaskContext` 任务状态
- 受预算和 Semaphore 约束的 Leader/Researcher Worker 团队
- Toolkit、权限和 ReAct 循环
- Middleware、原生 tracing 与 `AGENT_RUNTIME` 事件摘要

Checkpoint 保存业务状态、AgentScope TaskContext 和有界运行时摘要；网页摘要 AgentState 不写入 checkpoint，避免复制网页正文导致 Redis 和 Token 膨胀。项目只使用 AgentScope 公共 API，不依赖 `agentscope.app._*` 私有 Team 实现。

## 环境

```bash
conda env create -f environment.yml
conda env update -f environment.yml --prune
cp .env.example .env
```

关键配置：

```properties
DB_URL=jdbc:mysql://127.0.0.1:3306/db_deep_research?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai
DB_USERNAME=root
DB_PASSWORD=12345678
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
TAVILY_API_KEY=
```

模型由数据库 `model` 表管理，后端不硬编码研究模型。

## 启动

```bash
./start-python-backend.sh
```

等价命令：

```bash
conda run -n deep-research-py uvicorn app.main:app --host 127.0.0.1 --port 8080
```

## 性能参数

| 变量 | 默认值 | 作用 |
|---|---:|---|
| `RESEARCH_SEARCH_MAX_RESULTS_PER_QUERY` | `3` | 单次搜索结果上限 |
| `RESEARCH_SEARCH_SUMMARY_TIMEOUT_SECONDS` | `60` | 网页摘要超时与降级阈值 |
| `RESEARCH_SEARCH_SUMMARY_RAW_CONTENT_MAX_CHARS` | `12000` | 单页摘要输入上限 |
| `RESEARCH_SEARCH_SUMMARY_CACHE_ENABLED` | `true` | 网页摘要缓存 |
| `TAVILY_CACHE_ENABLED` | `true` | 搜索查询缓存 |
| `RESEARCH_REPORT_FINDINGS_MAX_CHARS` | `20000` | 报告材料输入上限 |

`AgentScopeResearchTeam` 使用原生 TaskContext 记录任务，并通过 `asyncio.gather` 和预算中的 `maxConcurrentUnits` 并发执行隔离 Worker。搜索与摘要层实现 TTL 缓存、in-flight 合并、每网页独立 AgentState、并发摘要和超时降级。

## 可观测性

```properties
RESEARCH_OBSERVABILITY_ENABLED=true
RESEARCH_OBSERVABILITY_PROVIDER=langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxx
```

Span 层级为项目的 `workflow -> stage` 加 AgentScope `invoke_agent -> chat/execute_tool` 原生链路。应用和 AgentScope 复用同一个全局 OpenTelemetry Provider，再通过 OTLP 导出 Langfuse；也可通过 `RESEARCH_OBSERVABILITY_ENDPOINT` 指向通用 OTLP HTTP 接收端。默认不采集模型输入输出；排障时可设置 `RESEARCH_OBSERVABILITY_CAPTURE_IO=true`，采集内容会截断并脱敏。

## 测试

```bash
conda run -n deep-research-py python -m compileall -q app tests
conda run -n deep-research-py pytest -q
conda run -n deep-research-py python tests/api_feature_smoke.py
PYTHONPATH=. conda run -n deep-research-py python tests/observability_smoke.py
PYTHONUNBUFFERED=1 conda run -n deep-research-py python tests/live_hybrid_workflow_smoke.py
```

`live_hybrid_workflow_smoke.py` 需要 MySQL 中存在 `mimo` 模型，并可访问其模型 API 与 Tavily。设置 `VERIFY_REVISE=false` 可只验证 HITL 批准，不重复验证修订分支。
