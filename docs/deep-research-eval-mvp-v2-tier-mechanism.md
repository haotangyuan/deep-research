# Deep Research Eval MVP v2：三档质量、机制有效性与成本收益实施方案

> 适用项目：`/Users/admin/study/deep-research/backend-python`  
> 数据来源：日常 Deep Research 问答产生的真实问题、报告、证据与运行数据。  
> MVP 目标：不仅判断报告是否可信，还要判断 MEDIUM/HIGH/ULTRA 三档以及 Reviewer、多轮、双 Draft、章节团队、ClaimVerifier 是否带来值得其成本的质量增益。

## 0. 给实现 Agent 的交接说明

这是一份可执行的工程规格，不是“所有内容均已实现”的完成报告。接手 Agent 必须先阅读：

```text
/Users/admin/study/deep-research/AGENTS.md
/Users/admin/study/deep-research/CLAUDE.md
```

### 0.1 当前真实状态

已经实现并通过定向测试：

- ULTRA 的“每轮任务预算”和“整次研究总任务预算”已经分离。
- 复杂 ULTRA 模板默认 `6/轮、12/总量`，因此第一轮用满 6 个任务后仍可进入第二轮。
- 跨轮 Task/Worker ID 已唯一化。
- Context FS 跨轮 Branch 已隔离，第二轮不会覆盖第一轮 Source/Evidence。
- 预算、轮次、Reviewer、报告机制已有一部分 OTel 属性和事件。

尚未实现，本文件后续内容均是本轮 MVP 的待办：

- `research_run` 及 Research/Run 生命周期落库。
- Git、Prompt、Template、模型请求/响应、Evaluator 版本快照。
- HIGH 双 Draft、Synthesis、Final 的稳定 Artifact 落库。
- LLM Token 的阶段级、轮次级和报告阶段级归因。
- 最终报告的 Claim-Citation Manifest。
- Eval Candidate Snapshot、Dataset、Experiment、Score 表和异步 Worker。
- 12 项报告指标、三档回放和机制消融。

接手时不得重复实现或回滚已经完成的 ULTRA 预算与跨轮隔离修复。先检查当前工作树，保留用户和前序 Agent 的未提交修改。

### 0.2 本次交付边界

本次 MVP 要交付两条互相解耦的链路：

```text
线上正常研究
→ 可靠记录 Run、版本、Token、Artifact、Source/Evidence
→ 研究主流程完成后异步冻结 Eval Candidate Snapshot

版本化 Dataset
→ 同题回放三档或机制 Variant
→ 确定性检查 + LLM Judge
→ 分数、原因、成本和 Trace 关联落库
```

不在 MVP 范围内：线上自动路由档位、自动训练模型、大规模统计显著性平台、复杂标注后台、实时执行昂贵 Judge。

### 0.3 不可破坏的工程约束

1. 不改变现有 REST/SSE 对外协议；新增字段必须向后兼容。
2. Eval 与 Snapshot 默认异步，失败不能把用户研究改成失败。
3. 一个物理 LLM 调用只能有一个 Token 事实来源，禁止手工统计和 AgentScope 统计重复相加。
4. Prompt、报告、网页正文、Reviewer Gap 等高基数内容不写入 Span；只写数据库/对象存储，Span 只放 ID、状态和计数。
5. 日常 MEDIUM/HIGH/ULTRA 均值只能用于运营观察，不能用于证明档位因果增益；档位结论必须来自同一 Dataset Item 的配对回放。
6. 所有 Eval 结果必须能反查 `dataset_item_id → case_run_id → run_id → trace_id/artifact_id`。
7. 版本信息自动采集，不能依赖运行人员手填。
8. 新表既要加入 SQLAlchemy Model，也要更新根目录 `db_deep_research.sql`。当前项目使用 `Base.metadata.create_all()`，它不会为已有表补列，因此还必须提供可对存量数据库执行的显式迁移 SQL。

### 0.4 建议的最小提交拆分

```text
Commit 1  数据模型、初始化 SQL、存量库迁移 SQL、Repository
Commit 2  Run 生命周期和自动版本快照
Commit 3  阶段级 Token 归因与总量对账
Commit 4  HIGH/ULTRA/最终报告 Artifact 持久化
Commit 5  Eval Candidate Snapshot 与 Claim Manifest
Commit 6  Eval Runner、Evaluator、6 题 Dataset 与报告
```

每个提交都应可独立测试和回滚；不要把业务主流程重构与 Judge Prompt 调整混在一个提交里。

## 1. 这版 MVP 要回答什么

上一版 Eval MVP 主要验证：

```text
报告是否完成
引用是否可追溯
引用是否支持 Claim
是否覆盖题目要求
```

这仍然不足以回答产品和架构问题：

```text
MEDIUM → HIGH 的额外 Token 是否提升了质量？
HIGH → ULTRA 的额外 Token 是否值得？
双 Draft 融合是否优于单报告？
Reviewer 找到的 Gap 是否真实？
Reviewer 说继续后，下一轮是否真的关闭 Gap？
多轮是否增加新知识，还是重复搜索和重写？
章节团队是否减少矛盾，还是只增加篇幅？
ClaimVerifier 是否降低了不受支持的 Claim？
哪些真实问题应该路由到哪个档位？
```

因此本版使用五层模型：

```text
最终报告质量
+ 工作流过程质量
+ 档位契约
+ 机制消融
+ 成本收益
```

---

## 2. 当前三个档位的真实工作流

### MEDIUM

```text
Scope
→ 单轮 Supervisor，最多 2 个研究任务
→ Researcher 并发 1，每分支最多 2 次搜索
→ 单 ReportAgent
```

### HIGH

```text
Scope
→ 单轮 Supervisor，最多 4 个研究任务
→ Researcher 并发 2，每分支最多 3 次搜索
→ comparative + data-driven 双 Draft
→ HIGH synthesis
```

HIGH 当前没有独立 Report Judge。

### ULTRA

```text
Scope + Research Type 识别
→ 选择 ULTRA Workflow Template
→ 每轮 Supervisor 规划
→ 每轮最多 6 个研究任务，并发 3，每分支最多 4 次搜索
→ 多 Lens Reviewer 对抗审查
→ continue/report 决策
→ 可选下一轮 Gap-directed Research
→ ReportSectionPlanner
→ Section Draft × N
→ Consistency Review
→ Section Revision × N
→ Merge
→ 可选 ClaimVerifier
```

三档并不都使用 Reviewer。共同链路是：

```text
Scope → Supervisor → Researcher/Search → Evidence/Context → Report
```

ULTRA 特有机制才是 Reviewer、动态多轮、报告质量门、章节团队和 ClaimVerifier。

---

## 3. ULTRA 多轮预算 Bug 修复

### 3.1 原问题

原实现中的 `maxConductCount=6` 同时承担：

1. 单轮 Supervisor 最多规划几个任务。
2. 当前累计执行了几个任务。
3. 整个 ULTRA Workflow 的总任务预算。

第一轮规划并执行 6 个任务后：

```text
conduct_count = 6
maxConductCount = 6
```

即使 Reviewer 判断 `continue`，Pipeline 也会因为预算耗尽而停止，动态多轮退化成单轮。

### 3.2 已实施修复

预算拆为：

```text
maxConductCount       每轮任务上限
maxTotalConductCount  整次研究总任务上限
```

复杂 ULTRA 模板默认：

```text
maxConductCount = 6
maxTotalConductCount = 12
```

即默认最多执行两个满额研究轮，避免直接放大为 `6 × 5 = 30` 个任务。

`fact_lookup` 保持：

```text
maxRounds = 1
maxConductCount = 3
maxTotalConductCount = 3
```

状态增加：

```text
conduct_count        当前轮已执行任务数，每轮重置
total_conduct_count  整次研究累计任务数，不重置
```

同时修复跨轮任务 ID：

```text
<research_id>-round-<round_no>-task-<index>
researcher-r<round_no>-<index>
```

避免第二轮复用第一轮 AgentScope Task/Worker ID。

进一步修复 Context FS 跨轮覆盖：原 `branch_index_from_task_id()` 只读取任务序号，第二轮的 branch-0～5 会覆盖第一轮同名 Source/Evidence Path。现在使用：

```text
branch_index = (round_no - 1) × 1000 + task_index
```

第一轮保持 branch-0～5，第二轮使用 branch-1000～1005，从而同时保留各轮 Evidence 和 Source Snapshot。

### 3.3 当前成本护栏

一次 ULTRA 是否继续由三层条件共同决定：

```text
Reviewer 是否要求 continue
dynamic_max_rounds 是否允许
maxTotalConductCount 是否还有余额
```

这次修复保证第二轮能够执行，但不保证第二轮一定执行。Reviewer 判断已充分时仍应直接进入报告。

---

## 4. Eval 数据来源：日常真实研究

### 4.1 推荐数据链路

```text
日常用户发起 Deep Research
→ 正常执行并落业务库
→ 完成后生成不可变 Eval Candidate Snapshot
→ 脱敏与合规检查
→ 分层抽样进入 Eval Dataset
→ 人工补 Required Points / Reference Facts
→ 同一个 Dataset Item 回放 MEDIUM/HIGH/ULTRA
→ 执行机制消融
→ 保存 Eval Result 并关联原 Trace
```

### 4.2 为什么不能直接比较日常三档结果

生产流量中：

- 用户会把简单问题选 MEDIUM。
- 复杂问题更可能选 ULTRA。
- 不同用户问题、行业、时间和预期不同。

因此直接比较：

```text
线上 ULTRA 平均分 vs 线上 MEDIUM 平均分
```

存在严重选择偏差，不能证明 ULTRA 更有效。

正确做法：

1. 日常问答只负责提供真实问题分布和原始 Artifact。
2. 脱敏后冻结成 Dataset Item。
3. 同一道题用相同模型、时间边界和 Source Policy 回放三个档位。
4. 使用配对差值评价档位增益。

### 4.3 不能只收集成功样本

Eval Candidate 应按以下状态分层抽样：

```text
success
degraded
failed
cancelled
fallback
needs_disclosure
user_negative_feedback
```

如果只收集高质量成功报告，Eval 会高估系统可靠性，也无法训练回归集。

---

## 5. 当前落库是否足够

### 5.1 已经可以复用的数据

| 现有数据 | 可用于 Eval 的内容 |
|---|---|
| `research_session` | 档位、模型、状态、开始结束时间、总 Token |
| `chat_message` | 用户问题、最终 Assistant 报告 |
| `workflow_event` | 研究阶段、错误、fallback 的部分事件 |
| `research_planning_round` | ULTRA 轮次、目标、摘要 |
| `research_work_item` | 每轮任务、结果摘要、状态 |
| `research_decision_log` | Reviewer 决策、投票和 Gap Payload |
| `research_evidence_ledger` | 来源 URL、类型、强度、Snippet |
| `research_context_node` | Source L0/L1/L2、Evidence、Report Draft 等内容 |
| OTel Trace | Agent/Model/Tool 因果链、部分 Token 和时延 |

### 5.2 现有数据不足的部分

#### 缺少不可变 Run

这里必须区分两个概念：

```text
Research：用户视角的一次研究任务，ID 为 research_id，生命周期可跨越等待确认、重试和恢复。
Run：后端从开始执行到停止的一次连续尝试，ID 为 run_id；等待 HITL、异常或取消会结束当前 Run，恢复/重试会新建 Run。
```

因此关系是：

```text
Research 1 ── N Run
```

例如同一个 `research_id=R1`：首次运行到等待用户确认是 `run_id=A, attempt=1, outcome=hitl_wait`；用户确认后恢复为 `run_id=B, attempt=2, trigger=hitl_resume`。目前没有稳定的：

```text
run.id
run.attempt
run.trigger
run.outcome
trace_id
```

Eval 无法准确说明分数属于哪次执行。

#### 缺少版本

目前难以稳定回答：

```text
使用了哪个 Git 版本？
哪个 Prompt 版本？
哪个 Workflow Template 版本？
模型请求名和实际响应模型是什么？
```

没有版本就无法定位回归。

MVP 要自动记录：

```text
workflow_commit_sha + workflow_dirty
scope/supervisor/researcher/reviewer/report 的 prompt_version + prompt_sha256
template_version + template_sha256
request_model + response_model
evaluator_version + judge_model
```

#### Evidence Ledger 信息不完整

现有 Ledger 有 URL、标题、类型和 Snippet，但缺少稳定的：

```text
evidence_id
claim_text
evidence_text
source_path
source_content_hash
retrieved_at
confidence
work_item 真实关联
```

当前 `work_item_id` 在部分写入路径中仍为 `None`。

#### 缺少 Source Snapshot

只有 URL 不够：

- 网页会变化或删除。
- URL 当前不可访问不代表运行时没有内容。
- Judge 必须看到运行当时的证据文本。

Context FS 中有部分 Raw/Overview，但需要统一 Snapshot ID 和 Hash，不能只靠路径约定推断。

#### 缺少最终 Claim-Citation Manifest

Manifest 是最终报告的结构化“事实索引 Sidecar”，不是给用户看的第二份报告。它把报告中的原子 Claim 与引用和运行时证据连接起来。最终报告目前只有 Markdown，没有稳定的：

```text
claim_id
claim_text
importance
section_id
citation_url
evidence_id
```

MVP 由异步 Eval Claim Extractor 从最终 Markdown 生成并落库；长期由报告 Agent 同步输出 Manifest，Eval 再独立验证，避免“自己生成、自己证明”。

#### 缺少阶段和每轮增量成本

当前只有研究总 Token，不能回答：

```text
第二轮花了多少 Token？
Reviewer 花了多少 Token？
Section Team 花了多少 Token？
ClaimVerifier 花了多少 Token？
```

不仅要按 Round，还要按 `stage/agent/report_phase/reviewer_lens/section_id` 归因，并与 Run 总 Token 对账。

#### HIGH 中间产物不完整

HIGH 的 comparative/data-driven Draft 和 Synthesis 结果没有像 ULTRA Context FS 一样形成稳定 Artifact，无法计算 Draft Complementarity、Best Draft Quality、Synthesis Uplift、Claim/Citation Retention 和 Synthesis Information Loss。MVP 必须保存：

```text
report_draft/comparative
report_draft/data-driven
report_synthesis/high
report_final
```

### 5.3 结论

现有库足够做：

```text
一次性的粗粒度报告 Eval
```

但不足以做：

```text
可复现的 Dataset
跨版本回归
档位公平比较
机制消融
多轮增量价值
Claim-Citation 级审计
```

---

## 6. 推荐落库架构

业务运行事实和 Eval 数据应分层：

```text
Operational Tables
  日常研究执行的真实事实

Eval Snapshot Tables
  从真实研究冻结、脱敏、版本化的不可变样本

Eval Result Tables
  Experiment、Case、Score、Claim/Citation 判断
```

不要让 Eval 直接长期依赖可变的业务表 Join。

### 6.1 `research_run`

一次连续后台执行一条记录：

```sql
research_run
  id                     char(32) primary key
  research_id            char(32)
  attempt_no             int
  trigger_type           varchar(32)
  trace_id               varchar(64)
  status                 varchar(32)
  outcome                varchar(32)
  workflow_mode          varchar(32)
  budget_level           varchar(16)
  request_model          varchar(256)
  response_model         varchar(256)
  workflow_commit_sha    varchar(64)
  workflow_dirty         tinyint
  prompt_version_json    text
  prompt_hash_json       text
  template_version       varchar(64)
  template_sha256        char(64)
  evaluator_version      varchar(64) null
  judge_model            varchar(256) null
  fallback_used          tinyint
  fallback_type          varchar(64)
  fallback_reason        text
  input_tokens           bigint
  output_tokens          bigint
  search_count           int
  conduct_count          int
  round_count            int
  active_duration_ms     bigint
  wall_duration_ms       bigint
  start_time             datetime
  end_time               datetime
  config_json            text
```

唯一约束：

```text
(research_id, attempt_no)
```

生命周期规则：

- 在一次连续后台执行真正开始时创建 Run，而不是创建 `research_session` 时提前创建。
- `attempt_no` 在同一 `research_id` 下事务性递增，唯一约束防止并发重复。
- 正常完成、失败、取消、降级和进入 HITL 等待时都必须在 `finally` 路径关闭 Run。
- HITL Resume、Checkpoint Resume、人工 Retry 新建 Run，并通过 `trigger_type` 区分。
- `trace_id` 在 Trace 创建后回填；无 Trace 时允许为空，但不得用 `research_id` 冒充。
- `active_duration_ms` 只统计实际执行时间；`wall_duration_ms` 不应把跨 HITL 的等待错误记入单个 Run。

推荐枚举：

```text
trigger_type = initial | hitl_resume | checkpoint_resume | retry | eval_replay
outcome = success | degraded | failed | cancelled | hitl_wait
```

### 6.2 `research_artifact`

统一保存可复现运行产物：

```sql
research_artifact
  id                     char(32) primary key
  research_id            char(32)
  run_id                 char(32)
  artifact_type          varchar(64)
  stage_name             varchar(64)
  round_no               int null
  section_id             varchar(128) null
  angle                  varchar(64) null
  content                mediumtext null
  content_ref            varchar(512) null
  content_sha256         char(64)
  request_model          varchar(256) null
  response_model         varchar(256) null
  prompt_version         varchar(64) null
  prompt_sha256          char(64) null
  input_tokens           bigint null
  output_tokens          bigint null
  duration_ms            bigint null
  outcome                varchar(32)
  fallback_used          tinyint
  metadata_json          text
  create_time            datetime
```

`artifact_type`：

```text
user_query
research_brief
source_snapshot
evidence_item
round_review
report_single
report_draft/comparative
report_draft/data-driven
report_synthesis/high
report_section_draft
report_section_revision
report_merged/ultra
report_final
claim_manifest
```

Artifact 必须满足：

- `content` 与 `content_ref` 至少一个非空；无论存在哪里都计算 `content_sha256`。
- HIGH 即使走 fallback，也保存已成功产生的 Draft，并在 Synthesis/Final Artifact 标记 `fallback_used`。
- `report_final` 是对外最终报告的不可变副本，不依赖之后可能被更新的 `chat_message`。
- 写入使用幂等键 `(run_id, artifact_type, round_no, section_id, angle, content_sha256)`。

大网页可存对象存储，数据库只存 `content_ref + sha256`。MVP 阶段也可以继续使用 MEDIUMTEXT，但必须设置大小上限。

### 6.3 `research_source_snapshot`

如果不使用通用 Artifact 表承载 Source，单独建：

```sql
research_source_snapshot
  id                     char(32) primary key
  research_id            char(32)
  run_id                 char(32)
  round_no               int
  work_item_id           bigint null
  normalized_url         varchar(1024)
  source_title           varchar(512)
  source_type            varchar(32)
  fetched_at             datetime
  published_at           datetime null
  http_status            int null
  content_ref            varchar(512) null
  content_excerpt        mediumtext null
  content_sha256         char(64)
  fetch_outcome          varchar(32)
  metadata_json          text
```

MVP 可以先让 `research_artifact(type=source_snapshot)` 承载，避免表过多。

### 6.4 `research_claim_manifest`

```sql
research_claim_manifest
  id                     char(32) primary key
  research_id            char(32)
  run_id                 char(32)
  report_artifact_id     char(32)
  claim_id               varchar(64)
  section_id             varchar(128)
  claim_text             mediumtext
  importance             varchar(16)
  requires_citation      tinyint
  citation_id            varchar(64) null
  citation_marker        varchar(64) null
  citation_url           varchar(1024) null
  source_snapshot_id     char(32) null
  evidence_id            varchar(128) null
  evidence_excerpt       mediumtext null
  citation_markers_json  text
  citation_urls_json     text
  evidence_ids_json      text
  extractor_version      varchar(64)
  create_time            datetime
```

MVP 中该表可以由 Eval Claim Extractor 离线生成；长期应由报告阶段直接输出 Manifest。

一个 Claim 可以对应多个 Citation。首版为了减少表数，可以“一行一个 Claim-Citation Pair”；没有引用的 Claim 也保留一行，Citation 字段为空。`citation_*_json` 只用于兼容聚合视图，不能替代可查询的 Pair。

Manifest 示例：

```json
{
  "claim_id": "claim-17",
  "claim_text": "目标公司 2025 年收入同比增长 18%。",
  "section_id": "financials",
  "importance": "critical",
  "requires_citation": true,
  "citations": [
    {
      "marker": "[12]",
      "url": "https://example.com/annual-report",
      "source_snapshot_id": "src-12",
      "evidence_id": "ev-33",
      "excerpt": "Revenue increased by 18% year over year..."
    }
  ]
}
```

它是计算 `citation_completeness`、`citation_correctness`、`claim_factuality`、`cross_source_corroboration` 以及 HIGH/ULTRA 合成阶段 Claim 保留率的基础。

### 6.5 `research_llm_call`

每个物理模型调用先落一条不可重复的事实记录，这是 Token 的唯一事实源：

```sql
research_llm_call
  llm_call_id            char(32) primary key
  run_id                 char(32)
  stage_name             varchar(64)
  agent_name             varchar(128) null
  round_no               int null
  report_phase           varchar(64) null
  reviewer_lens          varchar(64) null
  section_id             varchar(128) null
  request_model          varchar(256)
  response_model         varchar(256) null
  attempt_no             int
  input_tokens           bigint
  output_tokens          bigint
  duration_ms            bigint
  outcome                varchar(32)
  error_type             varchar(128) null
  start_time             datetime
  end_time               datetime
```

同一个 Provider 请求从开始、重试到回调必须复用同一个 `llm_call_id`；新的物理 Retry 使用新的 `llm_call_id` 和递增 `attempt_no`。数据库主键负责最终去重。

### 6.6 `research_stage_usage`

阶段级 Token 使用独立表保存；每个物理模型调用先产生唯一 Usage Fact，再聚合到本表：

```sql
research_stage_usage
  id                     bigint primary key auto_increment
  run_id                 char(32)
  stage_name             varchar(64)
  agent_name             varchar(128) null
  round_no               int null
  report_phase           varchar(64) null
  reviewer_lens          varchar(64) null
  section_id             varchar(128) null
  request_count          int
  retry_count            int
  input_tokens           bigint
  output_tokens          bigint
  duration_ms            bigint
  outcome                varchar(32)
  create_time            datetime
  update_time            datetime
```

`stage_name` 最少覆盖：

```text
scope
supervisor
researcher
search_summary
reviewer
report_draft
report_judge
report_synthesis
section_planner
section_draft
consistency_review
section_revision
section_merge
claim_verifier
```

Token 规则：

1. 唯一事实源应位于底层 LLM 调用完成处，以 `llm_call_id` 去重。
2. 上层 Agent、Pipeline 和 OTel 只能引用或聚合该事实，不能再次新增 Token。
3. `sum(research_stage_usage)` 必须与 `research_run.input/output_tokens` 对账；允许流式中断等已解释误差，但必须记录 `token_reconciliation_delta`。
4. Retry 的每次物理调用都计入 Token，`retry_count` 单独记录，不能只保留最后一次。

### 6.7 `eval_dataset_item`

从日常研究冻结出的题目：

```sql
eval_dataset_item
  id                     char(32) primary key
  dataset_name           varchar(128)
  dataset_version        varchar(64)
  source_research_id     char(32)
  source_run_id          char(32)
  query_snapshot         mediumtext
  query_sha256           char(64)
  task_type              varchar(64)
  language               varchar(16)
  as_of_date             date
  required_points_json   text
  reference_facts_json   text
  forbidden_claims_json  text
  source_policy_json     text
  original_budget_level  varchar(16)
  privacy_status         varchar(32)
  annotation_status      varchar(32)
  sample_reason          varchar(64)
  split_name             varchar(32)
  create_time            datetime
```

状态：

```text
candidate
privacy_reviewed
annotating
ready
retired
```

### 6.8 `eval_experiment`

```sql
eval_experiment
  id                     char(32) primary key
  name                   varchar(128)
  dataset_name           varchar(128)
  dataset_version        varchar(64)
  experiment_type        varchar(64)
  baseline_experiment_id char(32) null
  workflow_version       varchar(64)
  evaluator_version      varchar(64)
  judge_model            varchar(256)
  config_json            text
  status                 varchar(32)
  create_time            datetime
  complete_time          datetime null
```

`experiment_type`：

```text
tier_comparison
high_report_ablation
reviewer_ablation
multi_round_ablation
section_team_ablation
claim_verifier_ablation
```

### 6.9 `eval_case_run`

```sql
eval_case_run
  id                     char(32) primary key
  experiment_id          char(32)
  dataset_item_id        char(32)
  research_id            char(32)
  run_id                 char(32)
  variant_name           varchar(128)
  repeat_no              int
  gate_passed            tinyint
  failure_reasons_json   text
  total_score            decimal(8,4) null
  input_tokens           bigint
  output_tokens          bigint
  duration_ms            bigint
  estimated_cost         decimal(12,6) null
  result_json            mediumtext
  create_time            datetime
```

### 6.10 `eval_score`

通用分数表：

```sql
eval_score
  id                     bigint primary key auto_increment
  case_run_id            char(32)
  metric_name            varchar(128)
  metric_group           varchar(64)
  score_value            decimal(10,6) null
  label_value            varchar(64) null
  passed                 tinyint null
  evaluator_name         varchar(128)
  evaluator_version      varchar(64)
  judge_model            varchar(256) null
  reason                 text null
  details_json           mediumtext null
  create_time            datetime
```

Claim-Citation 明细可以先放 `details_json`；数据量变大后拆成 `eval_claim` 和 `eval_claim_citation`。

### 6.11 版本快照的自动采集规则

版本必须在 Run 创建时冻结，不能在 Eval 时读取“当前版本”：

| 版本 | 采集方式 | 备注 |
|---|---|---|
| Workflow | 优先读取部署注入的 `GIT_COMMIT_SHA`/`APP_VERSION`；本地开发才 fallback 到 `git rev-parse HEAD` | 另存 `workflow_dirty`，生产镜像不应依赖存在 `.git` |
| Prompt | 每类 Prompt 定义显式语义版本，并对规范化后的完整 Prompt 计算 SHA-256 | Scope/Supervisor/Researcher/Reviewer/Report 分开记录 |
| Template | 保存模板声明版本，并对排序规范化后的 JSON 计算 SHA-256 | 不能只保存模板文件名 |
| Model | 同时保存请求模型和 Provider 实际响应模型 | 处理别名、路由和模型升级 |
| Evaluator | 代码/规则版本 + Judge Prompt Hash + Judge Model | 同一生成结果可由不同 Evaluator 重评 |

建议新增 `app/core/build_info.py` 和集中式 `prompt_registry.py`，由一个 `VersionSnapshot` 值对象统一产生字段，避免每个 Agent 自己拼版本。版本采集失败时使用明确值 `unknown` 并发出告警，不能静默留空。

---

## 7. 最终报告质量指标

### 7.1 硬 Gate

所有档位统一：

```text
workflow_completed
report_non_empty
citation_parse_rate = 1
citation_traceability >= 0.95
unsupported_critical_claim_count = 0
contradicted_critical_claim_count = 0
no_sensitive_data_leak = true
```

档位不同不能降低事实安全底线。

### 7.2 Information Recall

```text
required_point_coverage
critical_fact_recall
subtopic_coverage
missing_critical_points
effective_citation_count
supported_claim_count
```

### 7.3 Factuality 与 Citation

```text
claim_factuality
citation_completeness
citation_correctness
citation_traceability
citation_utilization
unsupported_claim_rate
contradicted_claim_rate
```

### 7.4 Source Quality

```text
authoritative_source_ratio
source_diversity
source_freshness
cross_source_corroboration
duplicate_source_ratio
source_claim_fit
```

### 7.5 Analysis

```text
analysis_depth
multi_source_synthesis
comparison_quality
conflict_handling
uncertainty_calibration
objectivity
insight_quality
decision_usefulness
redundancy_rate
```

### 7.6 Presentation

```text
instruction_following
language_match
structure_quality
readability
audience_fit
table_consistency
internal_consistency
report_concision
```

### 7.7 MVP 核心 12 指标

避免一次运行调用过多 Judge，首版真正参与主报告的指标为：

```text
required_point_coverage
critical_fact_recall
claim_factuality
citation_completeness
citation_correctness
effective_citation_count
source_quality
source_freshness
analysis_depth
multi_source_synthesis
uncertainty_calibration
instruction_following
```

其他指标先作为诊断项按需运行。

---

## 8. 三档评价契约

### 8.1 共同标准

三档使用同一套：

- Hard Gate。
- Claim/Citation 评价。
- Required Points。
- Critical Fact。
- Instruction Following。

### 8.2 MEDIUM

目标：低成本完成范围明确的问题。

核心：

```text
task_success_rate
critical_error_count
required_point_coverage
citation_correctness
latency
cost_per_success
```

### 8.3 HIGH

目标：通过更多研究预算和双视角报告提升比较完整性。

额外指标：

```text
draft_complementarity
best_draft_quality
synthesized_report_quality
synthesis_uplift
claim_retention
citation_retention
synthesis_information_loss
incremental_effective_citations
```

```text
synthesis_uplift
= final_synthesis_quality - max(draft_quality)
```

### 8.4 ULTRA

目标：通过 Gap-driven 多轮、对抗评审、章节协作和 Claim Verification 提升复杂任务可靠性。

除了最终报告，还必须评价 Reviewer、Round、Section Team 和 ClaimVerifier。

---

## 9. ULTRA 机制指标

### 9.1 Reviewer

```text
reviewer_gap_precision
reviewer_gap_recall
reviewer_external_eval_agreement
reviewer_false_stop_rate
reviewer_false_continue_rate
reviewer_consensus_predictiveness
reviewer_token_cost
```

定义：

```text
false_stop
= Reviewer 选择 report，但外部 Eval 仍发现关键可修复 Gap

false_continue
= Reviewer 选择 continue，但下一轮没有关闭 Gap 或提升质量
```

Reviewer 一致率只作诊断，不能证明 Reviewer 正确。

### 9.2 多轮

```text
quality_delta_per_round
gap_closure_rate
new_supported_claims
new_effective_citations
new_authoritative_sources
source_novelty
criterion_incorporation_rate
criterion_regression_rate
net_criterion_gain
marginal_quality_per_1k_tokens
```

```text
gap_closure_rate
= 本轮解决的上轮 Gap / 上轮全部 Gap

net_criterion_gain
= 新满足 Criterion 数 - 退化 Criterion 数

marginal_quality_per_1k_tokens
= 本轮质量增量 / 本轮 Token × 1000
```

第二轮开始前和结束后必须使用同一 Evaluator Version 计算 Rubric，才能得到真实增量。

### 9.3 Section Team

```text
cross_section_contradictions_before_after
terminology_consistency
duplicate_claim_rate
section_coverage
claim_retention_after_revision
citation_retention_after_revision
merge_information_loss
section_team_token_cost
```

### 9.4 ClaimVerifier

```text
unsupported_claim_detection_precision
unsupported_claim_detection_recall
claim_correction_rate
false_warning_rate
post_verification_quality_delta
verification_token_cost
```

---

## 10. 消融实验矩阵

### 10.1 三档整体对比

相同 Dataset Item、模型、时间边界：

```text
MEDIUM
HIGH
ULTRA
```

回答产品问题：升级档位是否整体更好。

不能回答具体哪个机制有效。

### 10.2 HIGH 双 Draft

冻结同一份 Evidence：

```text
HIGH budget + single ReportAgent
vs
HIGH budget + comparative/data-driven + synthesis
```

### 10.3 Reviewer

冻结同一份 Round Evidence：

```text
无 Reviewer
单 Reviewer
三个相同 Lens Reviewer
三个不同 Lens Reviewer
```

无 Reviewer Variant 可以使用外部 Rubric 判断是否应继续；用于离线比较，不直接替代线上控制。

### 10.4 Multi-round

```text
Round 1 only
Round 2 with generic self-reflection
Round 2 with Reviewer Gap-directed research
```

该实验必须真实执行第二轮搜索，不能只重写报告。

### 10.5 Section Team

冻结同一份 Evidence：

```text
single ReportAgent
vs
Section Team
```

### 10.6 ClaimVerifier

冻结同一份 Pre-Verification Report：

```text
without verifier
vs
with verifier
```

### 10.7 公平性控制

- 同一 Dataset Item 配对比较。
- 固定生成模型和 Judge 版本。
- 固定 as-of-date 和 Source Snapshot Policy。
- 保存真实 Prompt/Template/Workflow 版本。
- 对随机模型至少做重复运行。
- 同时报告自然预算和 Budget-matched 结果。
- 使用 Case 级 Pair Difference，不只比较全局均值。

---

## 11. MVP 数据集与执行规模

### 11.1 Candidate 来源

从日常研究按任务类型、档位和 Outcome 分层抽样。

### 11.2 第一阶段 Dataset

先选 6 道真实问题：

```text
事实检索 × 1
技术比较 × 1
市场分析 × 1
学术综述 × 1
趋势预测 × 1
证据冲突/不足 × 1
```

每题完成：

- 隐私脱敏。
- Task Type 核验。
- Required Points。
- Critical Reference Facts。
- Source Policy。
- as-of-date。

### 11.3 三档运行

```text
6 Cases × 3 Tiers = 18 Runs
```

这是方向性 MVP，不用于宣称统计意义上的绝对性能。

### 11.4 机制实验

优先三组：

1. HIGH Single vs Dual Draft。
2. ULTRA Round 1 vs Gap-directed Round 2。
3. ULTRA Single Report vs Section Team。

ClaimVerifier 和 Reviewer 判断可以优先通过冻结 Artifact 做离线重放，减少重复搜索成本。

---

## 12. Token 与成本收益

当前单题实测参考：

| Tier | Input | Output | Total |
|---|---:|---:|---:|
| MEDIUM | 81K | 30K | 111K |
| HIGH | 132K | 38K | 170K |
| ULTRA | 501K | 120K | 621K |

需要计算：

```text
cost_per_pass
= 总成本 / Gate Passed Cases

incremental_cost_per_success
= (Cost_B - Cost_A) / (SuccessRate_B - SuccessRate_A)

marginal_quality_per_1k_tokens
= (Quality_B - Quality_A) / (Tokens_B - Tokens_A) × 1000
```

机制级：

```text
reviewer_quality_uplift / reviewer_tokens
round_quality_uplift / round_tokens
section_team_quality_uplift / section_team_tokens
verifier_quality_uplift / verifier_tokens
```

决策规则：

- 成本更高且质量无显著提升：被低档位支配。
- 只对复杂任务提升：建立 Task Router，不全量升级。
- 第二轮有效、第三轮退化：限制轮数并增加 Headroom Gate。
- Reviewer 不能预测外部 Gap：减少 Reviewer 或更换 Lens/模型。
- Section Team 只增加篇幅：回退轻量报告。
- ClaimVerifier 明显降低 Unsupported Claims：只验证 Critical Claims 以控制成本。

---

## 13. 可观测需要补什么

完整报告和网页正文应落数据库/对象存储，不应写入 Span。

Trace 增加以下低基数字段和计数。

### 13.1 Run

```text
research.id
run.id
run.attempt
run.trigger
operation.outcome
fallback.used
fallback.type
workflow.version
workflow.dirty
template.version
template.hash
prompt.version
prompt.hash
model.request
model.response
trace_id
```

### 13.2 Budget

```text
budget.conduct.per_round_limit
budget.conduct.total_limit
budget.conduct.round_used
budget.conduct.total_used
budget.search.limit
```

### 13.3 Round

```text
round.no
round.goal.type
round.task.count
round.search.count
round.unique_source.count
round.input_tokens
round.output_tokens
round.duration_ms
round.new_evidence.count
round.new_supported_claim.count
round.gap.input.count
round.gap.closed.count
round.outcome
```

### 13.4 Reviewer

```text
review.lens.count
review.success.count
review.failure.count
review.continue.votes
review.report.votes
review.consensus
review.gaps.count
review.decision
review.input_tokens
review.output_tokens
review.duration_ms
```

Gap 正文和 Rationale 落 `research_decision_log`，不进 Span。

### 13.5 Report Mechanism

```text
report.path = single | high_dual | ultra_section_team | fallback
report.draft.count
report.section.count
report.revision.count
report.claim.count
report.citation.count
report.verifier.enabled
report.verifier.checked.count
report.verifier.flagged.count
report.fallback.used
```

### 13.6 Token 归因

每个 LLM 调用必须只有一个 Token 事实来源，先消除手动 Chat Span 与 AgentScope Chat Span 可能的重复统计。

聚合时按：

```text
run.id
stage.name
agent.name
round.no
report.phase
reviewer.lens
section.id
```

归因。必须覆盖 Scope、Supervisor、Researcher、Search Summary、Reviewer、HIGH Draft/Synthesis、ULTRA Section Planner/Draft/Consistency/Revision/Merge 和 ClaimVerifier。

推荐同时记录：

```text
llm.call.id
llm.request.count
llm.retry.count
llm.input_tokens
llm.output_tokens
llm.duration_ms
llm.outcome
```

其中 `llm.call.id` 是去重键，不作为 Prometheus Metric Label；只能进入 Trace/Event 或数据库。

---

## 14. Eval Worker

日常请求完成后只创建 Candidate，不同步执行昂贵 Judge：

```text
Workflow Completed
→ enqueue eval-candidate snapshot job
→ Snapshot Worker 冻结 Artifact
→ Privacy/Eligibility Filter
→ Dataset Curator 选入版本化 Dataset
→ Experiment Runner 回放
→ Evaluator Worker 打分
→ Score 写库并关联 Trace
```

Snapshot 失败不能修改用户 Research 状态。

需要幂等键：

```text
(run_id, artifact_type, content_sha256)
(experiment_id, dataset_item_id, variant_name, repeat_no)
(case_run_id, metric_name, evaluator_version)
```

---

## 15. 隐私与数据治理

日常问答转 Eval Dataset 前必须：

- 删除 user_id、用户名、IP、邮箱、手机号和账号标识。
- 检测 Prompt、Report、URL Query 中的敏感信息。
- 不复制 API Key、Cookie、Authorization Header。
- 记录 `privacy_status` 和处理版本。
- 支持 Dataset Item 退役和来源删除。
- Eval Dataset 与生产业务库逻辑隔离。
- 高风险行业和私人数据默认不进入 Dataset。

可使用不可逆 `query_sha256` 去重，不需要保存用户身份。

---

## 16. 实现目录

```text
backend-python/evals/
├── runner.py
├── schemas.py
├── candidate_snapshot.py
├── artifact_collector.py
├── tier_variants.py
├── mechanism_variants.py
├── evaluators/
│   ├── deterministic.py
│   ├── claim_extractor.py
│   ├── citation_judge.py
│   ├── coverage_judge.py
│   ├── report_quality_judge.py
│   ├── reviewer_effectiveness.py
│   ├── round_delta.py
│   └── cost_effectiveness.py
├── prompts/
├── datasets/
├── baselines/
└── reports/
```

应用侧新增：

```text
app/application/eval_snapshot.py
app/application/run_recorder.py
app/core/build_info.py
app/core/prompt_registry.py
app/domain/eval_models.py 或并入 app/domain/models.py
app/infrastructure/eval_repository.py
backend-python/migrations/<date>_eval_mvp_v2.sql
```

Eval 业务不能写进 API 层或 `main.py`。

### 16.1 代码接入点

| 文件/模块 | 最小改动 |
|---|---|
| `app/domain/models.py` | 新表 Model、唯一约束、索引和枚举字段 |
| 根目录 `db_deep_research.sql` | 为全新数据库补齐建表 SQL |
| `backend-python/migrations/...sql` | 为已有数据库提供幂等 `CREATE TABLE/ALTER` 脚本；`create_all()` 不会修改旧表 |
| `app/application/pipeline.py` | 连续执行入口创建 Run；完成/失败/取消/HITL 在 `finally` 关闭；恢复时新建 Attempt |
| `app/infrastructure/llm.py` 或实际统一 LLM 出口 | 产生带唯一 `llm_call_id` 的 Usage Fact，保存请求/响应模型 |
| `app/application/agents.py` | 调用 LLM 时传 Stage Context；保存 HIGH 两个 Draft、Synthesis、Final Artifact |
| ULTRA 报告相关模块 | 保存 Section Draft/Revision/Merge、ClaimVerifier Artifact，并携带 Round/Section 维度 |
| `app/application/eval_snapshot.py` | 主流程结束后异步冻结 Query/Brief/Source/Evidence/Report/版本，不反向修改 Research 状态 |
| `app/infrastructure/eval_repository.py` | 幂等写入 Run、Usage、Artifact、Manifest、Dataset、Score |
| `backend-python/evals/` | 离线回放、确定性检查、Judge、配对统计和报告生成 |

### 16.2 推荐索引与数据边界

至少建立：

```text
research_run              UNIQUE(research_id, attempt_no), INDEX(trace_id, outcome, start_time)
research_artifact         INDEX(run_id, artifact_type, round_no), INDEX(content_sha256)
research_llm_call         PRIMARY KEY(llm_call_id), INDEX(run_id, stage_name, round_no)
research_stage_usage      INDEX(run_id, stage_name, round_no, report_phase)
research_claim_manifest   INDEX(run_id, report_artifact_id, claim_id), INDEX(source_snapshot_id)
eval_dataset_item         INDEX(dataset_name, dataset_version, split_name, task_type)
eval_case_run             UNIQUE(experiment_id, dataset_item_id, variant_name, repeat_no)
eval_score                UNIQUE(case_run_id, metric_name, evaluator_version)
```

数据库保存结构化元数据和受控大小正文；超限网页和大 Artifact 保存到对象存储，数据库保存 `content_ref + sha256`。不要把用户原始内容写进日志、Metric Label 或 Span Attribute。

---

## 17. 实施顺序

### Phase 0：修复多轮预算

- [x] 拆分每轮和总任务预算。
- [x] 复杂 ULTRA 默认 6/轮、12/总量。
- [x] Fact Lookup 保持 3/3、单轮。
- [x] 跨轮 Task/Worker ID 唯一。
- [x] 定向测试覆盖第二轮与总护栏。

### Phase 1：Run 与 Artifact 落库

- 在 SQLAlchemy Model、`db_deep_research.sql` 和存量库迁移 SQL 中同时建立 `research_run`、`research_artifact`、`research_llm_call`、`research_stage_usage`、`research_claim_manifest`。
- 实现 Repository 和幂等写入；先写 Repository 测试，再接 Pipeline。
- 在连续后台执行入口创建 Run，在统一退出路径关闭 Run；HITL Resume/Retry 新建 Attempt。
- 自动冻结 Workflow/Prompt/Template/Model 版本，不允许 API 调用方手填。
- 在统一 LLM 出口产生 Usage Fact，完成阶段归因和 Run 总量对账。
- 保存所有档位 Final；额外保存 HIGH 双 Draft/Synthesis、ULTRA Section/Revision/Merge。
- Research 结束后异步冻结 Query、Brief、Report、Source、Evidence，并补 Source Snapshot Hash。

验收：

1. 同一 Research 首次运行、HITL Resume 和 Retry 能查到不同 Run/Attempt。
2. 任意成功、失败、取消、降级 Run 都有关闭时间、Outcome、版本和 Trace 关联。
3. HIGH 正常路径能查到两个 Draft、Synthesis、Final；Fallback 路径仍保留已经生成的 Artifact。
4. Stage Token 之和与 Run 总 Token 可对账，重复上报不增加总数。
5. 只依赖 Snapshot 就能还原评价输入；Snapshot 失败不改变用户研究状态。

### Phase 2：Candidate Dataset

- 建 `eval_dataset_item`、`eval_experiment`、`eval_case_run`、`eval_score`。
- 分层抽样日常研究。
- 脱敏和去重。
- 人工标注 6 个 MVP Case 的 Required Points 和 Critical Facts。

验收：Dataset 不依赖用户身份，题目可重复回放。

### Phase 3：报告 Eval

- 确定性 Citation Parser。
- 异步 Claim Extractor 生成结构化 Claim-Citation Manifest。
- Citation/Fact Judge。
- Required Point Judge。
- Report Quality Judge。
- 12项核心指标与 Hard Gate。

验收：Golden Report 能识别悬空引用、不支持 Claim、漏答和关键事实错误。

### Phase 4：三档对比

- 6题分别运行三个档位。
- 保存每个 Run Artifact。
- 生成配对质量差值和成本差值。
- 计算 Task Success 与 Cost per Pass。

验收：能够回答每道题是否值得从 MEDIUM 升级到 HIGH/ULTRA。

### Phase 5：机制消融

- HIGH Single vs Dual Draft。
- ULTRA Round 1 vs Gap-directed Round 2。
- ULTRA Single Report vs Section Team。
- 再扩展 Reviewer 和 ClaimVerifier Variant。

验收：每个昂贵机制都有 Uplift、Token 和失败样本。

### Phase 6：校准

- 人工标注至少50个 Claim-Citation Pair。
- 人工审核至少20个 Reviewer Gap。
- 计算 Judge Precision/Recall/F1。
- 校准 Gate。

验收：Judge 误差可量化，Critical Error 漏检被单独报告。

### 17.1 实施依赖顺序

接手 Agent 按以下顺序实现，不能先写 Judge 再补不可复现的数据基础：

```text
Schema/Migration
→ Repository
→ Run 生命周期与版本快照
→ LLM Usage Fact 与阶段归因
→ Report/Source/Evidence Artifact
→ 异步 Candidate Snapshot
→ Claim-Citation Manifest
→ Dataset/Runner/Evaluator
→ 三档配对与机制消融
```

### 17.2 最小测试矩阵

必须新增或扩展以下测试：

| 测试 | 必须证明 |
|---|---|
| Run lifecycle | Initial/HITL Resume/Retry 是同一 Research 的不同 Attempt；所有退出路径会关闭 Run |
| Version snapshot | Git/Prompt/Template Hash 稳定；内容改变会改变 Hash；缺失版本为 `unknown` 并告警 |
| Usage dedup | 相同 `llm_call_id` 重放不会重复计费；Retry 会计入真实物理调用 |
| Token reconciliation | Stage 合计与 Run 总量一致或有明确 Delta/原因 |
| HIGH artifacts | comparative、data-driven、synthesis、final 均可查询；Fallback 仍留存前序产物 |
| Manifest | 多 Claim、多 Citation、无 Citation Claim、悬空 Marker 都能结构化表达 |
| Snapshot idempotency | 同一 Run 重试 Snapshot 不重复写 Artifact |
| Async isolation | Snapshot/Eval 抛错不改变 Research 的成功状态和最终响应 |
| Tier replay | 同一 Dataset Item 能生成 MEDIUM/HIGH/ULTRA 三个 Case Run |
| Evaluator versioning | 同一报告可被不同 Evaluator Version 重评且结果不互相覆盖 |

沿用项目现有测试约束，不为“让测试通过”引入绕过真实行为的假实现。完成后至少执行：

```bash
cd /Users/admin/study/deep-research/backend-python
python -m compileall app evals tests
pytest -q tests/test_ultra_dynamic_online.py tests/test_context_writer.py tests/test_context_store.py tests/test_branch_context_package.py tests/test_report_team.py tests/observability_smoke.py
pytest -q <本次新增的 run/artifact/usage/snapshot/eval 测试文件>
git diff --check
```

如果新增测试文件名不同，用实际文件名替换占位符；交付说明中必须列出执行过的精确命令和结果。

---

## 18. MVP 完成定义

- [ ] 日常 Research 完成后可以异步生成 Eval Candidate Snapshot。
- [ ] Snapshot 包含 Query、Report、Evidence、Source、版本、Run 和 Trace ID。
- [ ] Source 有运行时内容或 Content Ref 与 SHA-256。
- [ ] 一个 Research 的 Retry/Resume 能区分不同 Run。
- [ ] Workflow/Prompt/Template/请求模型/响应模型/Evaluator 版本均自动冻结且可查询。
- [ ] HIGH 的 comparative Draft、data-driven Draft、Synthesis 和 Final 均形成不可变 Artifact。
- [ ] 最终报告生成结构化 Claim-Citation Manifest，并能连接 Source Snapshot/Evidence。
- [ ] 6个真实脱敏问题进入 Dataset v1。
- [ ] 同一道题可以回放三个档位。
- [ ] 12项核心报告指标可计算。
- [ ] Hard Gate 和失败原因码可查询。
- [ ] HIGH 双 Draft 可以计算 Synthesis Uplift。
- [ ] ULTRA 每轮可以计算 Gap Closure 和 Quality Delta。
- [ ] Section Team 可以计算 Revision/Merge Information Loss。
- [ ] Token 可以按 Round、Reviewer、Report Phase 归因。
- [ ] Token 还可以按 Stage、Agent、Reviewer Lens、Section 归因，并与 Run 总量完成去重对账。
- [ ] 可以计算 Cost per Pass 和 Marginal Quality per 1K Tokens。
- [ ] 至少三组机制消融完成。
- [ ] Judge 经过人工标注校准。
- [ ] 结果可以跳转到对应 Trace 和 Artifact。
- [ ] Eval/Snapshot 失败不影响用户研究状态。

---

## 19. 最终决策输出

MVP 报告最后不能只给分数，必须形成工程决策：

```text
MEDIUM 适合哪些 Task Type？
HIGH 的双 Draft 在哪些题上有正 Uplift？
ULTRA 的第二轮关闭了哪些真实 Gap？
第三轮是否还有 Headroom？
Reviewer 哪个 Lens 有效，哪个只增加 Token？
Section Team 是否减少跨章节矛盾？
ClaimVerifier 是否值得全量运行，还是只检查 Critical Claims？
哪种机制被更轻量 Variant 支配？
路由到更高档位的最低预期收益是多少？
```

最终目标不是让 ULTRA 永远得分最高，而是建立：

```text
Task Complexity
→ Expected Quality Uplift
→ Incremental Cost
→ Tier/Mechanism Routing Decision
```

---

## 20. 参考方法

- [DeepResearch Bench](https://deepresearch-bench.github.io/static/papers/deepresearch-bench.pdf)：RACE 使用 Comprehensiveness、Depth、Instruction Following、Readability；FACT 使用 Citation Accuracy 和 Effective Citations。
- [DeepResearch Bench II](https://agentresearchlab.com/benchmarks/deepresearch-bench-ii/index.html)：将报告评价拆为 Information Recall、Analysis 和 Presentation 的细粒度 Rubric。
- [Multi-Turn Evaluation of Deep Research Agents](https://arxiv.org/abs/2606.09748)：多轮中应跟踪 Criterion Incorporation、Regression 和 Net Gain；额外研究活动本身不保证质量提升。
- [Efficient Agents](https://arxiv.org/abs/2508.02694)：使用 Cost-of-Pass 分析 Agent 复杂度与效果的成本收益。
