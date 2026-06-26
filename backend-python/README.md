# Deep Research Python Backend

Python 后端是 Java 后端的并行迁移版本，保留原有前端协议、数据库表结构、Redis timeline/checkpoint 结构和 Agent 工作流语义。Java 版本不删除，后续本地开发推荐启动本目录下的 FastAPI 版本。

## 技术栈映射

| 原 Java 技术栈 | Python 版本 |
|---|---|
| Spring Boot | FastAPI + Uvicorn |
| MyBatis-Plus | SQLAlchemy Async + aiomysql |
| agentscope-java | agentscope 2.x Python |
| jjwt | PyJWT |
| Spring SSE | sse-starlette |
| Lettuce Redis | redis-py asyncio |
| OpenTelemetry Java | OpenTelemetry Python + OTLP HTTP |

## 本地环境

前置依赖：MySQL、Redis、Conda。默认数据库沿用 Java 版 `db_deep_research`，本地 MySQL 密码按当前项目约定使用 `12345678`。

```bash
cd /Users/haosiyuan/Documents/Study/agent-study/deep-research-main

# 首次创建环境
conda env create -f backend-python/environment.yml

# 后续同步依赖
conda env update -f backend-python/environment.yml --prune

# 配置环境变量
cp backend-python/.env.example backend-python/.env
```

关键配置：

```properties
DB_URL=jdbc:mysql://127.0.0.1:3306/db_deep_research?useUnicode=true&characterEncoding=utf8&serverTimezone=Asia/Shanghai
DB_USERNAME=root
DB_PASSWORD=12345678
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
```

研究模型不硬编码在 Python 后端里，仍从 `model` 表读取。真实链路测试会复制数据库中已有的 `mimo` 模型配置给临时用户。

## 启动

```bash
cd backend-python
./start-python-backend.sh
```

等价手动命令：

```bash
cd backend-python
conda run -n deep-research-py uvicorn app.main:app --host 127.0.0.1 --port 8080
```

启动后：

- Health: `http://127.0.0.1:8080/health`
- OpenAPI: `http://127.0.0.1:8080/v3/api-docs`
- Scalar: `http://127.0.0.1:8080/scalar/index.html`

前端继续使用原目录：

```bash
cd frontend
npm install
npm run dev
```

如 `5173` 被占用，Vite 会自动切到下一个端口。

## 协议兼容

REST 路径保持不变：

- `/api/v1/user/register`
- `/api/v1/user/login`
- `/api/v1/user/me`
- `/api/v1/models`
- `/api/v1/research/create`
- `/api/v1/research/list`
- `/api/v1/research/{id}`
- `/api/v1/research/{id}/messages`
- `/api/v1/research/{id}/direction-action`
- `/api/v1/research/{id}/cancel`
- `/api/v1/research/sse`

响应仍为：

```json
{
  "code": 0,
  "message": "success",
  "data": {}
}
```

SSE 仍使用请求头：

- `Authorization: Bearer <token>`
- `X-Research-Id: <researchId>`
- `X-Client-Id: <clientId>`
- `Last-Event-ID: <sequenceNo>`

事件名保持 `message`、`event`、`report-stream`，结束包保持 `[DONE] <status>`。

Redis key 保持：

- `research:{id}:timeline`
- `research:{id}:checkpoint`
- `user:{userId}:researches`

## Agent 工作流

Python 版保持三阶段：

1. `ScopeAgent`：分析需求，必要时澄清；`DIRECTION_ONLY` 时保存 checkpoint 并等待确认。
2. `SupervisorAgent`：生成子研究任务，按预算并发执行。
3. `ReportAgent`：整合研究材料并生成 Markdown 报告。

性能相关迁移点：

- MEDIUM/HIGH/ULTRA 预算与 Java 默认值一致。
- `SupervisorAgent` 使用 `asyncio.gather` 按 `maxConcurrentUnits` 并发执行子研究。
- `SearchAgent` 保留 Tavily 查询缓存、URL + 内容级网页摘要缓存、in-flight 合并、摘要并发、短超时降级。
- 网页摘要输入通过 `RESEARCH_SEARCH_SUMMARY_RAW_CONTENT_MAX_CHARS` 截断。
- 最终报告材料通过 `RESEARCH_REPORT_FINDINGS_MAX_CHARS` 做上限保护，避免最后一步超大上下文拖慢。

## 可观测链路

Python 版集成 OpenTelemetry，span 层级为：

```text
deep_research.workflow
  -> deep_research.stage <StageName>
    -> deep_research.tool <ToolName>
    -> deep_research.model <ModelName>
```

启用 Langfuse：

```properties
RESEARCH_OBSERVABILITY_ENABLED=true
RESEARCH_OBSERVABILITY_PROVIDER=langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxx
LANGFUSE_INGESTION_VERSION=4
```

如果使用自建 OTLP HTTP 后端：

```properties
RESEARCH_OBSERVABILITY_ENABLED=true
RESEARCH_OBSERVABILITY_ENDPOINT=http://127.0.0.1:4318/v1/traces
```

默认不采集模型输入输出。需要排查时可开启：

```properties
RESEARCH_OBSERVABILITY_CAPTURE_IO=true
RESEARCH_OBSERVABILITY_IO_MAX_CHARS=500
```

输入输出摘要会脱敏 `Authorization`、`api_key`、`secret`、`token` 等敏感字段。

## 测试

普通合约测试，不触发真实 LLM：

```bash
cd backend-python
conda run -n deep-research-py python -m compileall -q app tests
conda run -n deep-research-py pytest -q
```

真实 HTTP SSE smoke，需要后端已在 `8080` 启动：

```bash
cd backend-python
PYTHONUNBUFFERED=1 conda run -n deep-research-py python tests/sse_smoke.py
```

真实 Mimo 工作流 smoke，需要数据库中已有 `mimo` 模型配置、Tavily key 可用、后端已在 `8080` 启动：

```bash
cd backend-python
PYTHONUNBUFFERED=1 conda run -n deep-research-py python tests/live_workflow_smoke.py
```

前端构建：

```bash
cd frontend
npm run build
```

