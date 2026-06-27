# Deep Research Python Backend

## 模块结构

```text
app/
├── main.py                 # FastAPI 入口和生命周期
├── api/                    # HTTP/SSE 路由及依赖组装
├── application/            # 用例层
│   ├── agents.py           # Scope/Supervisor/Researcher/Search/Report
│   ├── pipeline.py         # 队列和研究工作流
│   ├── services.py         # 用户、模型、研究服务
│   ├── prompts.py          # Agent 提示词
│   └── tools.py            # 工具契约
├── core/                   # 配置、认证、异常、序列化和时间工具
├── domain/                 # ORM 实体、API DTO、研究状态、Agent 运行时契约
└── infrastructure/         # MySQL、Redis、SSE、LLM、Tavily、OTel
```

依赖方向以 `api -> application -> domain/infrastructure` 为主。`main.py` 只负责装配和资源生命周期，不承载业务逻辑。

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

Supervisor 使用 `asyncio.gather` 和预算中的 `maxConcurrentUnits` 并发执行子研究。搜索与摘要层实现 TTL 缓存、in-flight 合并、并发摘要和超时降级。

## 可观测性

```properties
RESEARCH_OBSERVABILITY_ENABLED=true
RESEARCH_OBSERVABILITY_PROVIDER=langfuse
LANGFUSE_PUBLIC_KEY=pk-lf-xxxxx
LANGFUSE_SECRET_KEY=sk-lf-xxxxx
```

Span 层级为 `workflow -> stage -> model/tool`。也可通过 `RESEARCH_OBSERVABILITY_ENDPOINT` 指向通用 OTLP HTTP 接收端。默认不采集模型输入输出；排障时可设置 `RESEARCH_OBSERVABILITY_CAPTURE_IO=true`，采集内容会截断并脱敏。

## 测试

```bash
conda run -n deep-research-py python -m compileall -q app tests
conda run -n deep-research-py pytest -q
PYTHONUNBUFFERED=1 conda run -n deep-research-py python tests/sse_smoke.py
PYTHONUNBUFFERED=1 conda run -n deep-research-py python tests/live_workflow_smoke.py
```

`live_workflow_smoke.py` 需要 MySQL 中存在 `mimo` 模型，并可访问其模型 API 与 Tavily。

