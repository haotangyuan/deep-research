# Research Context FS 与上下文压缩优化

本文记录本次针对“研究上下文压缩超时、报告阶段输入膨胀”的修复方案。对照 GitHub 远端版本，本次核心变化不是继续扩大压缩 prompt，而是把完整研究材料移出 prompt，沉淀为可检索、可追溯、可预算装配的 Research Context FS。

## 设计目标

长研究任务中，上下文不只是 prompt 片段，而是持续产生、被筛选、被复用的研究资产。本次优化把搜索资源、网页摘要、分支记忆、证据包和报告上下文统一纳入结构化管理，目标是解决以下工程问题：

- **上下文碎片化**：不同 Agent 产生的搜索结果、摘要和分支结论缺少统一索引，后续报告阶段只能依赖大段文本拼接。
- **上下文需求激增**：研究越深入，压缩输入和报告输入越长，容易触发超时、截断和成本失控。
- **检索质量不可控**：旧流程无法按报告章节选择证据，也难以解释哪些材料被采用或丢弃。
- **过程不可观测**：上下文装配缺少结构化事件，排查报告质量问题时难以回溯检索路径。

对应改造目标：

- 用 `research://...` 路径统一标识一次研究中的来源、分支和报告上下文。
- 用 L0/L1/L2 分层节点保存摘要、概览和原始材料，替代把所有材料塞进压缩 prompt。
- 用结构化 evidence item 保存 claim/evidence/source，支持报告阶段按章节检索。
- 用 score、dropped reason 和上下文装配事件记录取舍过程，保证报告 prompt 可控且可解释。
- 保留 `supervisor_notes` 回退，避免新上下文层影响旧会话、REST/SSE 协议和前端展示。

## 背景问题

旧流程中，Researcher 在分支结束时会把搜索结果、网页摘要和研究记录尽量“近似无损”压缩成一大段 `compressed_research`；Supervisor 再把多个分支结果拼到 `supervisor_notes`；ReportAgent 最后把这些长文本整体塞入报告 prompt。

这会带来几个问题：

- 压缩阶段要求“保留全部事实和来源”，输入和输出都容易膨胀。
- 搜索结果越多，压缩 prompt 越容易超时或降级。
- 报告阶段按 `supervisor_notes` 大段拼接，无法按章节选择证据。
- 原始材料、分支摘要、报告上下文混在同一层文本里，可追溯性和预算控制都比较弱。

## 解决方向

本次引入轻量的 Research Context FS，把研究材料拆成 `research://...` 路径下的上下文节点。节点写入、检索和预算装配由本项目自己的 MySQL ORM、Pydantic DTO 和 Agent 编排完成：

- `L0 source_abstract`：短摘要，用于快速筛选来源。
- `L1 source_overview`：结构化概览，用于报告装配。
- `L2 source_raw`：原始材料截断保存；Ultra 章节 Agent 已可按 L1 `parent_path` 定向读取摘录。
- `branch_summary`：分支级结论摘要。
- `evidence`：可被报告引用的结构化 claim/evidence/source。

分支压缩不再承担“保存所有材料”的职责，而是改为提取证据包。旧报告链路仍可通过 `ReportContextBuilder` 按章节检索和预算装配 L0/L1/derived 上下文；新的 Ultra 报告团队则由多个章节 Agent 分别执行 L0 召回、L1 精排和 L2 定向下钻，再通过共享声明、持久化邮箱和一致性 Agent 协作修订。两条链路都保留 `supervisor_notes` 和原 ReportAgent 流程作为降级兜底。

## 能力拆解

| 能力 | Deep Research 落地 |
|---|---|
| 结构化上下文管理 | `research_context_node` / `research_context_edge` 两张 MySQL 表 |
| 统一资源标识 | `research://{research_id}/branches/branch-001/sources/...` 路径 |
| 分层上下文加载 | L0 `source_abstract`、L1 `source_overview` / `branch_summary`、L2 `source_raw` |
| 研究资产沉淀 | 搜索结果、网页摘要、分支证据包、报告上下文统一写入 Context FS |
| Token 成本治理 | 压缩阶段提取证据包；章节 Agent 分批消费相关 L2，避免所有原文进入单次 Prompt |
| 多 Agent 报告协作 | 动态章节规划、并行初稿、共享 claim、持久化 mailbox、一致性检查与定向修订 |
| 检索可解释性 | `ReportContext.dropped`、节点 score、`AGENT_RUNTIME` 事件记录上下文装配状态 |
| 会话/任务兼容 | 保留 `supervisor_notes`、原 REST/SSE payload、MySQL/Redis 状态机 |

## 对照 GitHub 版本的主要代码变化

当前实现同时包含 Context FS 基础能力和后续增加的章节多 Agent 报告团队。以下按领域契约、持久化、检索装配和 Agent 编排记录当前有效实现，不再依赖特定未提交文件数量。

### 新增领域契约

- `backend-python/app/domain/context.py`
  - 新增 `ContextLevel`、`ContextNodeType`、`ResearchContextPath`。
  - 新增 `EvidenceItem`、`BranchEvidencePackage`、`TypedQuery`、`SelectedContextItem`、`ReportContext`。
  - 提供 `stable_source_key()` 和 `estimate_tokens()`，用于稳定路径和预算估算。

### 新增持久化层

- `backend-python/app/domain/models.py`
  - 新增 `ResearchContextNode` 表模型，保存上下文节点、层级、路径、内容、metadata、token/char 估算。
  - 新增 `ResearchContextEdge` 表模型，预留上下文关系边。

- `backend-python/app/infrastructure/context_store.py`
  - 新增 `ResearchContextStore.put_node()`、`put_nodes()`、`link()`、`list_nodes()`、`read_raw_for_parent()`。
  - 新增 `normalize_query_terms()` 和 `score_context_text()`，用于轻量检索排序。

### 新增写入与检索装配

- `backend-python/app/application/context_writer.py`
  - 搜索结果写成 L0/L1/L2 三层节点。
  - 分支证据包写成 `branch_summary` 与 `evidence` 节点。
  - `branch_index_from_task_id()` 统一从任务 ID 推导分支索引。

- `backend-python/app/application/context_retrieval.py`
  - 按报告章节生成 `TypedQuery`。
  - 对节点做关键词、章节 hint、来源强度加权排序。
  - 按字符预算选择节点，超预算项记录 dropped reason。

- `backend-python/app/application/report_context.py`
  - `ReportContextBuilder` 负责按章节装配报告上下文。
  - `render_report_context()` 输出可给 ReportAgent 使用的结构化上下文文本。
  - `enforce_report_context_budget()` 控制整体报告上下文预算。

- `backend-python/app/application/report_team.py`
  - `ReportSectionPlanner` 动态生成 3–6 个互补章节。
  - 章节 Agent 按 L0 → L1 → L2 流程装配证据并并行起草。
  - 共享 claim、evidence request、mailbox、初稿和修订稿全部写回 Context FS。
  - `ReportConsistencyAgent` 生成跨章节修订消息，`ReportAgent:merge` 仅负责最终合并。

- `backend-python/app/domain/report_team.py`
  - 定义章节规划、章节产物、共享声明和 Agent 消息契约。

### 改造 Agent 流程

- `backend-python/app/application/agents.py`
  - SearchAgent 返回结果后写入 Context FS。
  - Researcher 压缩阶段改为解析 `BranchEvidencePackage`，并写入分支摘要和证据节点。
  - ReportAgent 新增 `_report_findings_text()`，优先使用 `ReportContextBuilder` 的预算上下文，失败时回退 `supervisor_notes`。
  - 发布 `AGENT_RUNTIME` 事件记录报告上下文装配情况，包括章节数、被丢弃项和估算 token。
  - 工作流模板开启 `sectionTeamEnabled` 时调度章节报告团队；团队失败时回退原多角度链路。

- `backend-python/app/application/prompts.py`
  - `COMPRESS_RESEARCH_SYSTEM_PROMPT` 从“尽量保留全部材料”改为“提取可追溯证据包”。
  - 报告 prompt 的输入命名从 `Research Findings` 调整为 `Research Context`，表达上更贴近检索装配结果。

- `backend-python/app/application/ultra_dynamic.py`
  - 证据账本优先消费 `branch_evidence_package.evidence_items`，再兼容旧的 `researcher_sources`。

### 新增配置项

- `backend-python/app/core/config.py`
  - `RESEARCH_CONTEXT_L0_MAX_CHARS`
  - `RESEARCH_CONTEXT_L1_MAX_CHARS`
  - `RESEARCH_CONTEXT_L2_MAX_CHARS`
  - `RESEARCH_CONTEXT_REPORT_MAX_CHARS`
  - `RESEARCH_CONTEXT_SECTION_MAX_CHARS`
  - `RESEARCH_CONTEXT_RAW_EXCERPT_MAX_CHARS`

### 扩展运行时状态

- `backend-python/app/domain/state.py`
  - `DeepResearchState` 新增 `branch_evidence_package`，用于分支内传递结构化证据包。

## 流程变化

```mermaid
flowchart LR
    Search["搜索与网页摘要"] --> ContextFS["Research Context FS<br/>L0/L1/L2"]
    ContextFS --> Compress["分支证据包提取"]
    Compress --> Evidence["branch_summary + evidence 节点"]
    Evidence --> Retrieve["章节 Agent<br/>L0 召回 + L1 精排"]
    Retrieve --> Raw["按 parent_path<br/>定向读取 L2"]
    Raw --> Draft["多章节并行起草"]
    Draft --> Exchange["共享 claim + mailbox<br/>一致性检查"]
    Exchange --> Revise["章节并行修订"]
    Revise --> Report["ReportAgent:merge<br/>仅合并与优化逻辑"]
```

## 兼容性

- REST、SSE 和前端协议不变。
- `supervisor_notes` 仍保留，作为 Context FS 缺失或异常时的回退输入。
- `ResearchEvidenceLedger` 继续可用，并优先接入新的 evidence items。
- 新表模型挂在现有 SQLAlchemy `Base.metadata` 下，后端启动时由 `ensure_tables()` 创建缺失表。

## 验证

建议优先运行与本次优化直接相关的测试：

```bash
cd backend-python
conda run -n deep-research-py python -m compileall -q app tests
conda run -n deep-research-py pytest -q \
  tests/test_context_domain.py \
  tests/test_context_store.py \
  tests/test_context_writer.py \
  tests/test_research_evidence_package.py \
  tests/test_branch_context_package.py \
  tests/test_context_retrieval.py \
  tests/test_report_context.py \
  tests/test_report_team.py
```

说明：完整 `pytest` 仍可能受本地 `agentscope` 版本影响。如果本地 `agentscope.__version__` 与测试锁定版本不一致，应先修环境或单独运行 Context FS 相关测试验证本次改动。

## 后续事项

- 将 `research_context_node` 和 `research_context_edge` 同步进仓库初始化 SQL dump。
- 补充真实工作流 smoke，验证长研究任务中 Context FS 节点落库和报告上下文装配事件。
- 将当前单个有界通信往返扩展为可配置多轮，同时保留消息数、超时和防死循环约束。
- 支持从 `report/workspace/sections/{section_id}` 的中间节点续跑单个章节，而不是整个 ReportAgent 阶段重新执行。

章节团队的完整路径、通信协议和运维说明见 [章节多 Agent 报告团队](report-section-agent-team.md)。
