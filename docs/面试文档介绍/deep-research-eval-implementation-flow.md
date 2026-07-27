# Deep Research Eval 具体实施流程

> 状态：方案讨论稿 v0.1  
> 目标：说明 Deep Research Eval 从建立评价基准、组装 `EvalContext`，到执行结果 Eval、过程 Eval、聚合与校准的完整实施流程。  
> 本文重点回答“具体怎么评”，指标定义参见《Deep Research Eval 评价框架：过程与结果》。

## 面试用版本：Eval 是如何做的

我会把 Deep Research 的 Eval 分成结果评价和过程评价两部分。

第一步先建立版本化的 Eval Dataset。每道题不只保存用户问题，还定义 Required Points、Critical Facts、Forbidden Claims、时间范围和来源要求，明确什么样的结果算正确。

第二步获取待评估的 Research Run，主要有两种方式：一是回放固定题目，用于版本回归、档位比较和机制消融；二是从线上真实 Run 中抽样，用于监控真实质量和发现失败模式。

第三步组装 EvalContext，把这次运行的用户问题、Intent、Plan、Work Item、Tool Call、L0/L1/L2、Evidence、Reviewer 决策、各阶段报告、Claim-Citation Manifest、Trace、Token 和版本信息统一关联起来。

第四步执行结果 Eval。先用确定性规则检查工作流是否完成、报告是否为空、引用是否可解析和可追溯；再按照 Task Spec 逐项检查 Required Point Coverage；最后把报告中的 Claim 与运行时 Evidence 关联起来，独立判断引用是否真正支持 Claim，并评价来源质量、分析深度和指令遵循。

第五步执行过程 Eval。工具调用主要看成功率、超时、重试和重复调用；Intent 和 Plan 与 Task Spec 对比；Reviewer 看 Gap 是否准确、继续搜索后是否真的关闭 Gap；Consistency 和 ClaimVerifier 看处理前后是否减少错误、是否引入信息损失；L0/L1/L2 看来源筛选和证据转化是否有效。

第六步做结果聚合和机制分析。Hard Gate 单独判断关键事实和引用安全，质量指标和成本指标分开统计。对于 Reviewer、Consistency、ClaimVerifier 等机制，通过 Before/After 或 Without/With 的配对实验判断它们是否真正提升质量，以及增益是否值得 Token 和时延成本。

最后会用人工标注样本校准自动 Judge，保存 Evaluator、Prompt、模型和数据集版本，确保结果可复现、可回归，也能定位低分到底是搜索、规划、证据处理还是报告合成阶段的问题。

一句话概括：

> 先定义题目标准，再收集或回放 Research Run，组装完整运行上下文，分别评价最终报告质量和过程决策质量，最后通过人工校准与机制消融验证这些评价是否可信、各 Agent 是否真正带来净收益。

## 1. 核心结论

一套可执行的 Deep Research Eval 应由五个步骤构成：

```text
1. 建立目标基准 Task Spec
2. 运行或选择一个 Research Run
3. 从已有数据组装 EvalContext
4. 分别执行结果 Eval 与过程 Eval
5. 聚合、人工校准并形成版本决策
```

不同评价问题使用不同方法：

| 评价问题 | 实施方法 |
|---|---|
| 动作是否执行成功 | 确定性规则 |
| 输出是否满足题目要求 | 与 Task Spec 逐项对照 |
| Claim 是否被引用支持 | Claim-Evidence 独立 Judge |
| Agent 判断是否准确 | 与外部 Eval 结果或人工标签对照 |
| Agent 是否带来改善 | Before/After 或 Baseline/Treatment 配对比较 |
| 改善是否值得成本 | 质量增量与 Token、时延增量联合计算 |

Eval 不是重新运行一遍 Reviewer、Consistency 和 ClaimVerifier，而是评价它们是否判断正确、是否改善结果。

---

# 2. 整体架构

```text
Eval Dataset / Task Spec
          │
          ├──────────────────────────────┐
          │                              │
          ▼                              ▼
Research Workflow                  Evaluator Registry
生成一个 Research Run              规则 / Judge / Delta
          │                              │
          ▼                              │
Operational Data                      │
Run / Artifact / Context / Trace       │
          │                              │
          └──────────┬───────────────────┘
                     ▼
               EvalContext Builder
                     │
                     ▼
                 EvalContext
                     │
          ┌──────────┴──────────┐
          ▼                     ▼
      结果 Eval              过程 Eval
          │                     │
          └──────────┬──────────┘
                     ▼
             Gate / Score / Details
                     │
                     ▼
          人工校准 / 实验聚合 / 决策
```

其中：

- Operational Data 负责保存“发生了什么”。
- Task Spec 负责定义“什么算正确”。
- Evaluator 负责产生“判断结果”。
- EvalContext 是把分散运行数据组装成一次评价可直接读取的只读对象。
- Eval Result 保存“如何判断、为什么这样判断、证据在哪里”。

---

# 3. 第一步：建立目标基准 Task Spec

## 3.1 为什么必须先建立基准

如果只有用户问题和最终报告，Judge 只能凭印象评价“写得是否全面”。它无法稳定回答：

- 用户哪些要求是必须满足的。
- 哪些事实最关键。
- 哪些错误不能接受。
- 什么来源可以证明某类 Claim。
- 报告应以哪个时间点为准。

因此每个正式 Eval Case 必须有结构化 Task Spec。

## 3.2 Task Spec 应保存什么

建议结构：

```yaml
case_id: tech_comparison_001
dataset_version: v1

query: >
  对比 RAG 与 Fine-tuning 在企业知识问答场景的优劣，
  并给出选型建议。

task_type: tech_comparison
language: zh-CN
as_of_date: 2026-07-01

explicit_constraints:
  audience: enterprise_technical_decision_maker
  require_citations: true
  output_format: comparative_report

required_points:
  - id: cost
    description: 比较训练、推理、数据更新和维护成本
    weight: 2

  - id: freshness
    description: 比较知识更新方式和时效性
    weight: 3

  - id: security
    description: 比较企业数据安全、权限与部署风险
    weight: 2

  - id: recommendation
    description: 根据不同企业条件给出选型建议
    weight: 3

critical_facts:
  - id: fact_1
    description: RAG 可以通过更新外部知识库改善知识时效性
    acceptable_sources:
      - official_documentation
      - peer_reviewed_paper

forbidden_claims:
  - Fine-tuning 可以保证模型准确记住所有企业知识

source_policy:
  preferred:
    - official_documentation
    - peer_reviewed_paper
  disallowed:
    - anonymous_content_farm

clarification_expected: false
```

## 3.3 Task Spec 从哪里来

首版由人工建立：

1. 从典型线上任务和产品需求中选择 10～20 道题。
2. 产品、领域人员和研发共同拆出 Required Points。
3. 对高风险题补 Critical Facts 和 Forbidden Claims。
4. 明确 `as_of_date` 与 Source Policy。
5. 两位标注者独立检查，解决歧义后冻结 Dataset Version。

不需要为开放式任务编写唯一“标准报告”。评价标准应是：

```text 。
Required Points
+ Critical Facts
+ Forbidden Claims
+ Source Policy
+ Explicit Constraints
```

## 3.4 当前项目中的保存位置

当前可以使用：

```text
eval_dataset_item
```

已有字段包括：

```text
query_snapshot
task_type
language
as_of_date
required_points_json
reference_facts_json
forbidden_claims_json
source_policy_json
dataset_version
```

首版 JSON 数据集也可以作为源文件，数据库只负责版本化导入。

---

# 4. 第二步：选择或生成 Research Run

Eval 有两种入口。

## 4.1 回放 Eval

对 Dataset Item 重新运行研究工作流：

```text
Dataset Item
× Workflow Version
× Variant
× Repeat No.
→ Research Run
```

适合：

- 跨版本回归。
- MEDIUM/HIGH/ULTRA 对比。
- Reviewer、ClaimVerifier 等机制消融。

需要保存：

```text
dataset_item_id
experiment_id
variant_name
repeat_no
run_id
```

## 4.2 线上 Run 抽样 Eval

从已经完成的真实 Run 中抽样：

- 成功样本。
- degraded。
- fallback。
- 用户负反馈。
- needs_disclosure。
- 高成本或多轮样本。

适合：

- 发现真实分布中的失败模式。
- 监控长期质量。
- 扩充 Candidate Dataset。

线上 Run 若没有人工 Task Spec，只能先做确定性检查和部分 Claim Eval；要做严格 Coverage Eval，需要先为该样本补充 Task Spec。

---

# 5. 第三步：组装 EvalContext

## 5.1 EvalContext 是什么

`EvalContext` 是一次 Eval 的统一只读输入。

它不是新的业务事实源，也不要求新增一张大表。它可以在 Eval Worker 执行时，从已有数据库、Artifact 和 Trace 中动态组装；为了调试和复现，也可以序列化为 JSON Snapshot。

它解决的问题是：

```text
Evaluator 不需要分别理解十几张业务表
→ Context Builder 负责关联和标准化
→ 所有 Evaluator 使用同一份稳定输入
```

## 5.2 建议的完整结构

```json
{
  "case": {},
  "run": {},
  "intent": {},
  "plan": {},
  "tool_calls": [],
  "rounds": [],
  "context_nodes": [],
  "sources": [],
  "evidence": [],
  "reviewer": {},
  "reports": {},
  "claims": [],
  "usage": [],
  "lineage": {}
}
```

下面逐项说明保存内容和获取方式。

## 5.3 `case`：评价标准

保存：

```text
dataset_item_id
query
task_type
language
as_of_date
required_points
critical_facts
forbidden_claims
source_policy
explicit_constraints
clarification_expected
```

获取来源：

```text
eval_dataset_item
```

用途：

- 意图识别评价。
- Plan Coverage。
- 最终报告 Coverage。
- Critical Fact 和 Forbidden Claim 检查。
- Source Policy 检查。

## 5.4 `run`：运行身份和版本

保存：

```text
run_id
research_id
attempt_no
trigger_type
trace_id
outcome
workflow_mode
budget_level
request_model
response_model
workflow_commit_sha
prompt_version/hash
template_version/hash
fallback
start/end time
input/output tokens
search_count
round_count
```

获取来源：

```text
research_run
```

用途：

- 判断 Workflow 是否完成。
- 跨版本公平比较。
- 关联 Trace 和 Artifact。
- 计算成本、时延和稳定性。

## 5.5 `intent`：Scope 和需求理解

保存：

```text
research_goal
task_type
required_dimensions
time_range
region
target_entities
language
audience
output_format
clarification_required
routing_decision
research_brief
```

优先获取来源：

```text
research_artifact(type=user_query)
research_artifact(type=research_brief)
research_context_node(type=brief)
Scope Agent 对应 Workflow Event / Artifact
```

如果当前 Scope Agent 只保存自由文本 Brief，Context Builder 需要把它解析为结构化字段。长期建议 Scope Agent 同步输出 JSON，不建议每次 Eval 再从文本猜测。

用途：

- 与 Task Spec 比较 Constraint Precision/Recall。
- 检查是否正确路由。
- 检查约束是否传递到 Plan 和最终报告。

## 5.6 `plan`：规划和 Work Item

保存：

```text
rounds:
  - round_no
  - round_goal
  - planner_bias
  - plan_items
      - task_key
      - title
      - description
      - priority
      - status
      - result_summary
```

获取来源：

```text
research_planning_round
research_work_item
research_context_node(type=plan)
```

关联方式：

```text
research_id
+ round_id / round_no
+ work_item_id / task_key
```

用途：

- 评价 Plan 是否覆盖 Required Points。
- 评价任务是否重复、可执行。
- 计算 Plan Item 完成率。
- 关联 Plan → Evidence → Final Claim。

## 5.7 `tool_calls`：工具执行事实

保存：

```text
tool_call_id
agent_name
stage_name
round_no
work_item_id
tool_name
arguments_summary/hash
start/end time
outcome
error_type
retry_no
result_count
cache_hit
result_ids
```

优先获取来源：

```text
OTel Tool Span
workflow_event
搜索 Provider 的结构化调用记录
```

注意：

- Trace 中只保存了 Span 且未长期保留时，无法稳定做历史 Tool Eval。
- 如果 Tool Call 没有稳定 ID、Round 和 Work Item 关联，需要补充结构化持久化或稳定导出。
- 不建议复制网页正文；只保存调用事实和返回结果 ID。

用途：

- Tool Success Rate。
- 超时、重试和重复调用。
- 调用是否与 Plan/Gap 对应。
- Tool Result 是否进入 Source/Evidence。

## 5.8 `context_nodes`：L0/L1/L2

保存：

```text
node_id/path
node_type
level = L0/L1/L2
title
content/content_ref
parent_path
branch_index
round_no
status
metadata
```

获取来源：

```text
research_context_node
research_context_edge
```

典型 Node Type：

```text
source_abstract
source_overview
source_raw
evidence
branch_summary
report_context
```

用途：

- 计算 L0→L1→L2 转化。
- 判断哪些来源被保留或丢弃。
- 关联 Source → Evidence。
- 审计上下文选择和信息损失。

## 5.9 `sources`：运行时来源快照

每个 Source 保存：

```text
source_id/path
url
title
source_type
published_at
fetched_at
round_no
work_item_id
content/content_ref
content_sha256
fetch_outcome
```

获取来源：

```text
research_artifact(type=source_snapshot)
research_context_node(type=source_raw/source_overview/source_abstract)
research_evidence_ledger
```

用途：

- Source Freshness。
- Source Policy。
- Claim-Evidence Judge。
- Eval 重放时避免网页变化。

只有 URL 不足以做 Citation Correctness；至少需要运行时 Evidence Excerpt 或 Snapshot 内容。

## 5.10 `evidence`：结构化证据

保存：

```text
evidence_id/path
claim
evidence_text
source_id/path
source_url
source_type
strength
confidence
round_no
work_item_id
section_hint
```

获取来源：

```text
research_context_node(type=evidence)
research_artifact(type=evidence_item)
research_evidence_ledger
```

使用原则：

- Ledger 可提供来源、强度和 Snippet。
- Context Node/Artifact 提供完整 Evidence 文本和结构化 Claim。
- Context Builder 负责合并，而不是再复制一套 Evidence 表。

用途：

- Claim-Citation Support。
- Plan→Evidence 转化。
- Reviewer Gap Closure。
- Evidence→Final Claim 利用率。

## 5.11 `reviewer`：Reviewer 判断和动作

保存：

```text
round_no
lens
coverage
evidence
freshness
source_diversity
consistency
blocking_gaps
next_action
next_focus
consensus
reviewer_tokens
```

获取来源：

```text
research_artifact(type=round_review)
research_decision_log
research_stage_usage(stage=reviewer)
```

用途：

- Gap Precision/Recall。
- False Stop/False Continue。
- 下一轮是否按 Gap 执行。
- Reviewer 成本收益。

## 5.12 `rounds`：轮次前后状态

每轮保存：

```text
round_no
round_goal
plan_items
reviewer_gaps_before
sources_added
evidence_added
supported_claims_added
required_points_satisfied
quality_metrics
tokens
duration
next_action
```

数据来自：

```text
research_planning_round
research_work_item
round_review artifact
source/evidence artifact 的 round_no
research_stage_usage 的 round_no
```

其中 `required_points_satisfied` 和 `quality_metrics` 不是业务运行事实，而是由同一 Evaluator Version 对每轮 Artifact 评价后产生。

用途：

- Gap Closure。
- Round Quality Delta。
- 新来源和新 Evidence。
- 单位 Token 的边际质量。

## 5.13 `reports`：报告阶段产物

保存：

```text
single_report
drafts_by_angle
synthesis
section_drafts
consistency_messages
section_revisions
merged_report
pre_verification_report
claim_verification_results
final_report
```

获取来源：

```text
research_artifact(type=report_draft)
research_artifact(type=report_synthesis)
research_artifact(type=report_section_draft)
research_context_node(type=report_agent_message)
research_artifact(type=report_section_revision)
research_artifact(type=report_merged)
research_artifact(type=claim_verification)
research_artifact(type=report_final)
```

注意：

- 当前 Consistency 的指令主要存于 `report_agent_message` Context Node。
- 当前 ClaimVerifier 保存了逐 Claim 判断，但需要确认能够恢复 Verifier 处理前的完整报告。
- 如果无法稳定取得 Pre-Consistency 或 Pre-Verification Report，就不能计算真实 Before/After 增益；需要先补 Artifact，而不是用最终报告猜测。

## 5.14 `claims`：最终 Claim-Citation Manifest

保存：

```text
claim_id
claim_text
section_id
importance
requires_citation
citation_id
citation_url
citation_excerpt
evidence_id
source_id
verifiable
```

获取来源：

```text
research_claim_manifest
```

如果 Manifest 不存在：

1. 先运行 Claim Extractor。
2. 产出 Manifest。
3. 再执行 Citation Traceability 和 Citation Judge。

不能在空 Manifest 时把 Traceability 记为 1。

用途：

- Citation Completeness。
- Citation Correctness。
- Claim Factuality。
- Critical Unsupported Claim。
- Report Revision/Merge 中 Claim 保留率。

## 5.15 `usage`：成本事实

保存：

```text
llm_call_id
stage_name
agent_name
round_no
report_phase
reviewer_lens
section_id
input_tokens
output_tokens
duration
retry
outcome
```

获取来源：

```text
research_llm_call    # 唯一物理调用事实
research_stage_usage # 聚合投影
research_run         # Run 总计
```

用途：

- Reviewer、Round、Consistency、Verifier 成本。
- Token 对账。
- Cost per Success。
- Marginal Quality per 1K Tokens。

## 5.16 `lineage`：关联关系

Context Builder 应尽量生成：

```text
required_point_id → plan_item_id
plan_item_id → work_item_id
work_item_id → tool_call_id
tool_call_id → source_id
source_id → evidence_id
evidence_id → claim_id
reviewer_gap_id → next_round_work_item_id
```

明确 ID 关联优先；没有 ID 时才使用文本相似度或 LLM 做近似匹配，并标记：

```text
lineage_source = explicit | inferred
confidence
```

---

# 6. EvalContext 如何组装

## 6.1 Context Builder 输入

```text
case_run_id
→ eval_case_run
→ dataset_item_id + run_id
```

## 6.2 组装顺序

```text
1. 读取 EvalCaseRun
2. 读取 EvalDatasetItem，构造 case
3. 读取 ResearchRun，构造 run
4. 按 run_id 读取 ResearchArtifact
5. 按 research_id/round_no 读取 Planning、Work Item、Decision、Ledger
6. 读取 Context Node/Edge，恢复 L0/L1/L2 和 Evidence
7. 读取 Claim Manifest
8. 读取 LLM Call/Stage Usage
9. 读取或关联 Tool Span
10. 建立 Lineage
11. 做 Context Completeness Check
```

## 6.3 Context 完整性检查

在运行质量 Judge 前，先执行：

```text
case_available
run_available
final_report_available
manifest_available
evidence_text_available
source_snapshot_available
round_data_available
pre_post_artifacts_available
usage_available
```

某部分缺失时：

- 输出 `not_evaluable`。
- 记录缺失原因。
- 不把缺失当作通过。
- 只运行仍然具备输入条件的 Evaluator。

## 6.4 建议的伪代码

```python
async def build_eval_context(case_run_id: str) -> EvalContext:
    case_run = load_eval_case_run(case_run_id)
    case = load_dataset_item(case_run.dataset_item_id)
    run = load_research_run(case_run.run_id)

    artifacts = load_artifacts(run.id)
    planning = load_planning(run.research_id)
    context_nodes = load_context_nodes(run.research_id)
    decisions = load_decisions(run.research_id)
    evidence_ledger = load_evidence_ledger(run.research_id)
    manifest = load_claim_manifest(run.id)
    usage = load_llm_usage(run.id)
    tool_calls = load_tool_spans(run.trace_id)

    context = normalize_and_link(
        case=case,
        run=run,
        artifacts=artifacts,
        planning=planning,
        context_nodes=context_nodes,
        decisions=decisions,
        evidence_ledger=evidence_ledger,
        manifest=manifest,
        usage=usage,
        tool_calls=tool_calls,
    )

    context.completeness = check_completeness(context)
    return context
```

---

# 7. 第四步 A：结果 Eval 怎么执行

结果 Eval 的输入是：

```text
Task Spec
+ Final Report
+ Claim Manifest
+ Evidence / Source Snapshot
```

建议按依赖顺序执行。

## 7.1 Step 1：Claim Extractor

条件：

- 如果 `research_claim_manifest` 已存在，直接复用。
- 如果不存在，从最终报告提取 Atomic Claims 和 Citation Marker。

输出：

```text
claim_manifest
manifest_available
claim_extraction_success
```

Claim Extractor 必须先于 Citation Traceability 和 Hard Gate。

## 7.2 Step 2：确定性 Hard Checks

用代码判断：

```text
workflow_completed
report_non_empty
citation_parse_rate
citation_traceability
manifest_available
no_sensitive_data_leak
explicit_format_constraints
```

输出必须包含失败明细，例如：

```json
{
  "metric": "citation_traceability",
  "score": 0.92,
  "passed": false,
  "reason": "24 个引用中 2 个无法映射到本次 Evidence",
  "failed_items": ["citation-17", "citation-22"]
}
```

## 7.3 Step 3：Required Point Coverage

不能让 Judge 直接给报告一个总体 Coverage 分。

对每个 Required Point 单独评价：

```text
输入：
  Query
  Required Point
  Final Report

输出：
  satisfied
  partially_satisfied
  not_satisfied
  contradicted
  reason
  report_evidence_span
  confidence
```

聚合：

```text
satisfied = 1
partially_satisfied = 0.5
not_satisfied / contradicted = 0

required_point_coverage
= Σ(point_score × weight) / Σ(weight)
```

同时输出：

```text
missing_required_point_ids
contradicted_required_point_ids
```

## 7.4 Step 4：Critical Fact 与 Forbidden Claim

对每个 Critical Fact 判断：

- 报告是否提及。
- 是否准确表达。
- 是否被有效引用支持。

对每个 Forbidden Claim 判断：

- 报告是否出现同义或等价错误表达。

输出：

```text
critical_fact_recall
critical_fact_error_count
forbidden_claim_count
```

## 7.5 Step 5：Claim-Citation Support

对每个 Claim-Citation Pair 单独执行。

Judge 输入：

```json
{
  "claim": "...",
  "importance": "critical",
  "citation": {
    "url": "...",
    "evidence_text": "...",
    "source_type": "official",
    "published_at": "..."
  },
  "as_of_date": "2026-07-01"
}
```

Judge 输出：

```json
{
  "label": "partially_supported",
  "reason": "来源支持收入增长，但不支持报告给出的因果解释",
  "evidence_span": "...",
  "confidence": 0.93
}
```

标签：

```text
supported
partially_supported
unsupported
contradicted
not_verifiable
```

聚合：

```text
citation_correctness
citation_completeness
unsupported_claim_rate
contradicted_claim_rate
unsupported_critical_claim_count
```

## 7.6 Step 6：Source Quality

先做确定性指标：

```text
freshness
duplicate_domain_ratio
source_type_distribution
source_policy_violation
```

再按 Claim 做语义判断：

```text
这个来源是否适合证明这个 Claim
是否需要第二来源交叉印证
```

不能简单使用：

```text
官方来源永远高于其他来源
```

例如公司官网可以证明“公司如何声称”，但未必能独立证明公司声称为真。

## 7.7 Step 7：分析和表达

在 Hard Gate 和事实评价之后运行：

- 多来源综合。
- 比较质量。
- 冲突处理。
- 不确定性。
- 指令遵循。
- 结构和可读性。

这部分优先输出逐 Rubric 判断，不直接产生不可解释的总分。

## 7.8 Step 8：结果 Gate 聚合

示例：

```text
Gate 必须满足：
workflow_completed = true
report_non_empty = true
manifest_available = true
citation_traceability >= 0.95
unsupported_critical_claim_count = 0
contradicted_critical_claim_count = 0
required_point_coverage >= threshold
critical_fact_error_count = 0
```

如果 Judge 未运行、Evidence 缺失或 Manifest 失败：

```text
gate_status = incomplete
```

不能因为缺少评价数据而默认通过。

---

# 8. 第四步 B：过程 Eval 怎么执行

过程 Eval 使用四种参照：

```text
确定性运行事实
Task Spec
外部结果 Eval
Before/After 或消融实验
```

## 8.1 Agent 和 Tool 通用执行评价

输入：

```text
tool_calls
workflow events
LLM calls
stage usage
```

代码计算：

```text
tool_success_rate
timeout_rate
retry_rate
retry_success_rate
schema_valid_rate
duplicate_execution_rate
fallback_rate
stage_token_cost
```

Tool Call 是否有用，通过 Lineage 判断：

```text
Tool Call
→ Source
→ Evidence
→ Final Claim
```

分类：

```text
used_in_evidence
used_for_exclusion
apparently_unused
unknown
```

`apparently_unused` 只能作为待审计信号，不能直接等于无效调用。

## 8.2 意图识别评价

输入：

```text
Task Spec
Scope/Intent 输出
Plan
Final Report
```

逐字段比较：

| 字段 | 标准 | Agent 输出 | 评价方法 |
|---|---|---|---|
| 任务类型 | Task Spec | Intent | 精确匹配或枚举映射 |
| 时间、地区、语言 | Explicit Constraints | Intent | 规则 |
| 核心目标 | Required Points | Intent | 逐项 Judge |
| 是否澄清 | clarification_expected | Agent 决策 | 人工标准对照 |
| Workflow 路由 | task_type + complexity | routing | 规则/Rubric |

然后检查约束保持：

```text
Task Spec
→ Intent
→ Plan
→ Final Report
```

输出：

```text
constraint_precision
constraint_recall
routing_accuracy
clarification_accuracy
constraint_retention_to_plan
constraint_retention_to_report
```

## 8.3 Planning 评价

规划没有唯一正确文本，因此分两部分。

### Plan 本身

对每个 Required Point 判断是否有对应 Plan Item：

```text
required_point_id
→ matched_plan_item_ids
→ coverage label
```

Judge 再判断：

- Work Item 是否可执行。
- 是否重复。
- 依赖是否合理。
- 是否明确证据目标。
- 是否符合预算。

### Plan 下游效果

根据 Lineage 计算：

```text
Plan Item
→ Work Item
→ Evidence
→ Supported Claim
```

输出：

```text
plan_item_completion_rate
plan_to_evidence_conversion
plan_to_supported_claim_conversion
duplicate_work_item_rate
unplanned_critical_gap_rate
```

这可以区分：

- Planning 漏规划。
- Researcher 执行失败。
- Evidence 已找到但 Report Agent 丢失。

## 8.4 Search 与 L0/L1/L2 评价

按 Context Node 和 Edge 计算漏斗：

```text
L0 搜索结果
→ L1 概览
→ L2 原文/摘录
→ Evidence
→ Supported Claim
```

确定性计算：

```text
L0_to_L1_retention
L1_to_L2_conversion
L2_to_evidence_conversion
evidence_to_claim_conversion
duplicate_source_ratio
source_novelty_by_round
```

抽样语义审计：

1. 从被 L1/L2 淘汰的来源中抽样。
2. 让独立 Judge 结合 Required Point 判断是否其实是关键来源。
3. 估计权威来源错误丢弃率。

这样避免重新跑一次 L0/L1/L2。

## 8.5 Reviewer 评价

输入：

```text
Round N 的 Evidence 和报告状态
Reviewer Gap
Reviewer nextAction
Round N+1 的 Plan、Source 和 Evidence
最终结果 Eval
```

### Gap 准确性

把 Reviewer Gap 与外部 Eval Gap 匹配：

```text
Reviewer Gap
vs
Missing Required Point
Unsupported Claim
Source Policy Gap
Conflict Gap
```

输出：

```text
reviewer_gap_precision
reviewer_gap_recall
```

### 决策准确性

```text
False Stop：
Reviewer 选择 report
但外部 Eval 仍发现关键、可修复 Gap

False Continue：
Reviewer 选择 continue
但下一轮没有关闭 Gap，也没有质量提升
```

### 动作效果

```text
Reviewer Gap
→ 下一轮 Plan Item
→ 新 Evidence
→ 最终 Gap 是否关闭
```

输出：

```text
gap_closure_rate
new_supported_claims
quality_delta
reviewer_token_cost
marginal_quality_per_1k_tokens
```

## 8.6 多轮研究评价

对每轮使用同一 Evaluator Version 计算：

```text
Required Point Coverage
Supported Claim
Citation Correctness
Source Quality
```

然后比较：

```text
Round N
vs
Round N+1
```

计算：

```text
new_required_points_satisfied
new_supported_claims
new_effective_citations
source_novelty
criterion_regression
net_criterion_gain
quality_delta
marginal_quality_per_1k_tokens
```

如果没有保存每轮可评价的 Artifact，只能统计新增来源，不能评价真实质量增量。

## 8.7 Section Team 与 Synthesis

输入：

```text
各 Draft
各 Section Draft
Revision
Synthesis/Merge
Final Report
```

对每个版本使用同一套结果 Evaluator：

```text
Coverage
Claim Support
Citation Correctness
```

再计算：

```text
synthesis_uplift
= quality(synthesis) - max(quality(draft_i))

claim_retention
citation_retention
merge_information_loss
```

不能仅用 Claim 数量或 Citation 数量增加代表质量提升；它们只能作为诊断代理。

## 8.8 Consistency Agent

输入：

```text
Pre-Consistency Sections
Consistency Messages
Post-Consistency Revisions
Merged Report
```

执行：

1. 独立 Judge 判断每个 Consistency Issue 是否成立。
2. 判断对应 Revision 是否解决问题。
3. 比较修改前后跨章节矛盾。
4. 检查 Claim/Citation 是否丢失。
5. 检查是否引入新错误。

输出示例：

```text
发现问题数：5
真实问题数：4
正确修复数：3
未修复数：1
新增退化：1
净修复数：2
新增 Token：8,000
```

聚合：

```text
issue_precision
issue_recall
resolution_rate
new_regression_count
post_consistency_quality_delta
consistency_token_cost
```

## 8.9 ClaimVerifier

输入：

```text
Pre-Verification Report
Verifier Claim/Verdict
Evidence
Post-Verification Report
```

执行：

1. 独立 Claim-Evidence Judge 重评同一 Claim。
2. 将独立标签与 Verifier Verdict 比较。
3. 检查错误 Claim 是否正确修正或披露。
4. 检查正确 Claim 是否被误删。
5. 对 Pre/Post Report 使用同一结果 Eval。

输出：

```text
unsupported_detection_precision
unsupported_detection_recall
false_warning_rate
critical_error_miss_count
claim_correction_rate
coverage_regression
post_verification_quality_delta
verification_token_cost
```

## 8.10 运行可靠性和故障恢复

这部分通过批量 Run 和故障注入完成，而不是评价单篇报告：

```text
模型第一次超时
搜索部分失败
单个 Researcher 失败
Section 失败
HITL Resume
Checkpoint Resume
SSE 重连
```

检查：

```text
状态是否正确
是否重复执行
是否重复计费
是否明确降级
是否最终通过结果 Gate
```

---

# 9. 第五步：Eval Result 如何保存

每条结果至少保存：

```json
{
  "case_run_id": "...",
  "target_type": "claim",
  "target_id": "claim-17",
  "metric_name": "citation_support",
  "label": "unsupported",
  "score": 0,
  "passed": false,
  "evaluator_name": "claim_evidence_judge",
  "evaluator_version": "2.0.0",
  "judge_model": "...",
  "reason": "...",
  "evidence_span": "...",
  "confidence": 0.94,
  "details": {},
  "trace_id": "...",
  "artifact_id": "..."
}
```

## 9.1 为什么必须保存明细

只保存：

```text
citation_correctness = 0.82
```

无法回答：

- 哪个 Claim 错了。
- 哪个引用不支持。
- Judge 依据什么判断。
- 人工应复核什么。
- 新版本修复了什么。

因此聚合分数必须能够回溯到 Criterion、Claim、Gap 或 Artifact 明细。

## 9.2 当前表如何使用

可以继续使用：

```text
eval_score
```

聚合指标一行一个 Metric；逐 Claim/Required Point 明细先存 `details_json`。

当明细量和查询需求增大后，再考虑拆：

```text
eval_item_judgement
eval_claim_judgement
```

MVP 不必立即新增。

---

# 10. 聚合规则

## 10.1 结果侧

输出四层：

```text
1. Hard Gate
2. Coverage / Factuality / Source / Analysis
3. 失败原因和明细
4. 成本
```

关键事实错误不能被其他分数抵消。

## 10.2 过程侧

按 Agent 输出：

```text
执行是否成功
判断是否准确
动作是否有效
质量增量
成本增量
```

不要形成一个无解释的“过程总分”。

## 10.3 实验侧

同一道题做配对差值：

```text
Treatment Metric - Baseline Metric
```

例如：

```text
With Reviewer Coverage - Without Reviewer Coverage
With Verifier Critical Errors - Without Verifier Critical Errors
With Section Team Quality - Single Agent Quality
```

同时报告：

```text
质量差值
严重错误差值
Token 差值
时延差值
```

---

# 11. 如何保证评价可信

## 11.1 人工校准集

从首批 Dataset 中人工标注：

```text
Required Point 判断
Claim-Citation Support
Reviewer Gap
Consistency Issue
ClaimVerifier Verdict
```

首版建议至少：

```text
5～10 道完整 Case
50～100 个 Claim-Citation Pair
20～30 个 Reviewer/Consistency Gap
```

## 11.2 校准指标

```text
Precision
Recall
F1
与人工一致率
Critical Error 漏检数
低置信度比例
```

如果人工之间一致率都低，说明 Rubric 不清晰，应先修改标准。

## 11.3 Judge 运行规范

- Prompt、模型和输出 Schema 版本化。
- 必须返回 Reason 和 Evidence Span。
- 支持 `not_verifiable/not_enough_information`。
- Judge 失败不能默认通过。
- A/B 采用盲测并交换候选顺序。
- 高风险和低置信度样本进入人工复核。

---

# 12. 当前项目实现与目标实现的主要差距

## 12.1 Context 装配不完整

当前 Runner 主要装配最终报告、部分 Artifact、Manifest 和 Dataset Item，尚未完整装配：

```text
Intent
Plan/Work Item
Tool Call
L0/L1/L2
Evidence 正文
Reviewer Decision
Round Delta 输入
Consistency/Verifier Pre-Post
Stage Usage
```

因此很多过程 Evaluator 即使存在，也缺少真实输入。

## 12.2 Claim Extractor 执行顺序

如果 Manifest 不存在，应先抽取 Claim，再运行确定性 Citation 检查。

目标顺序：

```text
Context Completeness
→ Claim Extractor
→ Deterministic Checks
→ Coverage/Citation Judges
→ Process Evaluators
→ Hard Gate
```

## 12.3 Citation Judge 缺少 Evidence

仅向 Judge 提供 Claim 和 URL，无法判断引用是否支持 Claim。必须提供运行时 Evidence Text 或 Source Snapshot。

## 12.4 Judge 输出过于聚合

当前通用 Judge 主要返回每个 Metric 的 0～1 分。目标实现应先产生逐 Required Point、逐 Claim 的 Label、Reason、Evidence Span，再由代码聚合。

## 12.5 部分机制指标使用弱代理

Claim/Citation 数量和文本子串保留率可作为诊断，但不能直接代表：

```text
真实报告质量
真实 Synthesis Uplift
语义 Claim Retention
```

真正的 Uplift 应使用同一套结果 Evaluator 对 Before/After 分别评价。

---

# 13. 推荐 MVP 实施顺序

## Phase 0：数据可评价性

1. 扩展 Context Builder。
2. 加 Context Completeness Check。
3. 打通 Claim→Citation→Evidence→Source。
4. 确认 Reviewer、Consistency、Verifier 的前后 Artifact。

## Phase 1：结果 Eval 闭环

1. 完善 10～20 道 Task Spec。
2. Claim Extractor。
3. 确定性 Hard Checks。
4. 逐 Required Point Coverage。
5. 逐 Claim-Evidence Support。
6. Hard Gate。
7. 人工校准。

## Phase 2：过程 Eval 闭环

优先 Reviewer：

```text
Reviewer Gap
→ 下一轮 Plan
→ 新 Evidence
→ Gap Closure
→ Final Quality Delta
→ Token Delta
```

随后：

1. Intent/Planning。
2. ClaimVerifier。
3. Consistency。
4. L0/L1/L2。
5. Section Team。

## Phase 3：消融和版本决策

```text
Without / With Reviewer
Without / With ClaimVerifier
Without / With Consistency
Single Agent / Section Team
Round 1 / Gap-directed Round 2
```

使用同一 Dataset、生成模型、Evidence Policy、Evaluator Version 做配对比较。

---

# 14. 一道题的完整执行示例

```text
题目：
对比 RAG 与 Fine-tuning，并给出企业选型建议

Step 1：读取 Task Spec
Required Points = 成本、时效、安全、选型建议

Step 2：运行 ULTRA
生成 run_id=R100

Step 3：Context Builder
读取 Intent、Plan、2 轮搜索、L0/L1/L2、Reviewer、
Evidence、Section Draft、Verifier 和 Final Report

Step 4：结果 Eval
成本：满足
时效：满足
安全：缺失
选型建议：部分满足
Coverage = 0.625

提取 20 个 Claim
16 supported
2 partially_supported
1 unsupported
1 contradicted critical claim
Hard Gate = failed

Step 5：过程 Eval
Intent 已识别安全要求
Plan 也规划了安全任务
Researcher 找到 2 条安全 Evidence
Final Report 没有使用
→ 问题定位为报告合成丢失，而不是意图或搜索失败

Reviewer 第一轮发现“安全证据不足”
第二轮新增 2 条安全 Evidence
但报告仍未使用
→ Reviewer Gap 正确、Research 动作有效、Report Merge 失败

Step 6：成本
第二轮新增 12K Token
Evidence 增加但最终 Coverage 未增加
→ 本次边际质量/Token 为低

Step 7：结果保存
保存逐 Required Point、逐 Claim、Reviewer Gap、
失败 Agent 阶段和对应 Artifact ID
```

这类输出才真正回答：

```text
报告哪里错了
错误在哪个阶段产生
Agent 判断是否正确
后续动作是否有效
成本是否值得
```

---

# 15. 最终实施定义

Deep Research Eval 的具体实施不是“把报告再次交给一个 LLM 打分”，而是：

> 先用 Task Spec 建立外部评价基准；再从已有 Run、Artifact、Context、Decision、Manifest 和 Usage 中组装可复现的 EvalContext；结果 Eval 逐 Required Point 和 Claim-Evidence 判断最终报告；过程 Eval 通过运行事实、外部结果、前后版本和消融实验判断 Agent 是否正确、有效和值得；最后保存可追溯明细，并使用人工标注校准自动 Judge。
