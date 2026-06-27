# CLAUDE.md

本仓库当前开发入口是 `backend-python/` 和 `frontend/`。

## 常用命令

```bash
cd backend-python
conda run -n deep-research-py python -m compileall -q app tests
conda run -n deep-research-py pytest -q
./start-python-backend.sh

cd ../frontend
npm install
npm run dev
npm run build
```

## 代码边界

- `app/api`：协议适配，不写业务流程。
- `app/application`：研究用例、Agent 和任务编排。
- `app/domain`：实体、DTO、状态和运行时契约。
- `app/infrastructure`：数据库、缓存、外部模型、搜索、SSE 和可观测性。
- `app/core`：配置、认证、异常及无业务状态的通用工具。

修改 REST、SSE、MySQL 或 Redis 交互时，必须保持现有前端协议和持久化结构兼容。性能相关改动需保留预算并发、搜索缓存、摘要缓存、超时降级和报告输入上限。可观测性需保持 `workflow -> stage -> model/tool` 链路。

