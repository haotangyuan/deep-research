# Deep Research Eval 评价框架：过程与结果

> 状态：讨论稿 v0.1  
> 目标：明确 Deep Research 应评价什么、评价标准从哪里来，以及如何避免重复评价和重复落库。

## 1. Eval 的核心目标

Deep Research Eval 需要回答两个顶层问题：

1. **结果评价**：最终交付给用户的报告是否正确、完整、可靠、可用。
2. **过程评价**：工作流中的 Agent 是否正确理解任务、做出合理决策、成功执行动作，并以合理成本改善最终结果。

过程评价不能只检查“Agent 是否执行过”，结果评价也不能直接复用工作流内部的自评分。

统一评价逻辑为：

```text
输入是否理解正确
→ 决策是否合理
→ 动作是否成功执行
→ 是否改善最终结果
→ 增益是否值得成本
```

## 2. 评价原则

### 2.1 事实、自评和独立 Eval 分开

项目中的数据分为三类：

| 数据类型 | 示例 | Eval 使用方式 |
|---|---|---|
| 运行事实 | 搜索结果、L0/L1/L2、Token、轮次、来源、Draft、报告 | 直接复用，不重新生产 |
| 流程内自评 | Reviewer 分数、Consistency 判断、ClaimVerifier 判断 | 作为被评价对象和诊断信号 |
| 独立评价 | Required Point Coverage、Citation Correctness、机制质量增量 | 由独立 Eval 产生 |

内部 Agent 的结果可以作为在线控制信号，但不能未经验证直接作为最终质量标签。

### 2.2 不重复评价

最终 Eval 不需要再次完整执行 Reviewer、Consistency Agent 和 ClaimVerifier。

Eval 应重点判断：

- Reviewer 判断得是否准确。
- Reviewer 的继续或停止决策是否合理。
- Consistency Agent 是否真的减少矛盾。
- ClaimVerifier 是否真的发现并修正错误。
- L0/L1/L2 的筛选是否保留了重要信息。
- 这些机制是否让最终报告提升，以及提升是否值得成本。

### 2.3 不评价不可观察的“思维过程”

Eval 不评价 Agent 隐含的推理过程，而评价可观察对象：

- 结构化意图。
- Plan 和 Work Item。
- Tool Call。
- Search Query 和搜索结果。
- Reviewer Gap 和决策。
- Draft、Revision、Merge。
- Claim、Citation 和 Evidence。
- 最终报告。

### 2.4 不把所有指标合成一个总分

关键事实错误不能被可读性、篇幅或来源数量抵消。

评价结果至少分为：

```text
Hard Gate
质量维度
过程诊断
成本效率
```

成本和质量分别报告，再通过质量—成本 Pareto 或增量收益进行决策。

---

# 3. 结果评价

结果评价的对象是用户最终收到的报告，而不是中间 Agent 的自评分。

## 3.1 Hard Gate：最低可靠性要求

以下任一关键条件失败，报告不能被判定为可靠：

| Gate | 评价内容 | 主要方法 |
|---|---|---|
| 工作流完成 | Run 正常结束并产生最终报告 | 确定性规则 |
| 报告可用 | 报告非空、可解析、满足基本格式要求 | 确定性规则 |
| 引用可解析 | 引用编号、URL 或 Marker 没有悬空 | 确定性规则 |
| 引用可追溯 | 引用能映射到本次 Source/Evidence | 确定性规则 |
| 关键事实有依据 | Critical Claim 不允许缺少必要引用 | Claim 抽取加规则 |
| 关键事实无矛盾 | Critical Claim 不得被引用证据明确反驳 | 独立 Judge，必要时人工复核 |
| 安全合规 | 不泄露 Prompt、密钥、内部路径和敏感信息 | 规则加分类器 |
| 明确指令满足 | 语言、格式、时间范围等硬约束满足 | 规则或 Task Spec 对照 |

URL 当前是否在线只能作为辅助信号。正式 Eval 应优先使用运行时保存的 Source Snapshot，避免网页变化影响重评。

## 3.2 任务完成度

评价报告是否真正回答用户的问题：

- 是否覆盖用户的核心目标。
- 是否覆盖所有必要子问题。
- 是否遗漏 Critical Facts。
- 是否回答了用户未要求的问题，却挤占关键内容。
- 是否符合时间、地区、对象、受众、长度和格式要求。

核心指标：

```text
required_point_coverage
critical_fact_recall
missing_critical_point_count
instruction_following
```

Coverage 必须依据题目专属 Task Spec，而不是让 Judge 泛泛评价文章是否“全面”。

每个 Eval Case 至少定义：

```text
required_points
critical_facts
forbidden_claims
as_of_date
source_policy
explicit_constraints
```

## 3.3 Claim 与引用质量

报告需要建立以下稳定链路：

```text
Final Claim
→ Citation
→ Evidence
→ Source Snapshot
```

评价内容：

### Citation Completeness

应该引用的事实性 Claim 中，有多少带有引用。数字、日期、比较、因果和外部事实通常需要引用；观点和过渡句不一定需要。

### Citation Correctness

引用内容是否真的支持相邻 Claim：

```text
supported
partially_supported
unsupported
contradicted
not_verifiable
```

### Claim Factuality

Claim 本身是否正确。优先依据运行时 Evidence；Evidence 不足且任务允许时，才使用独立检索补充验证。

### Citation Traceability

报告引用是否能追溯到本次运行实际获取的 Source/Evidence，而不是只检查 URL 是否存在。

建议指标：

```text
citation_completeness
citation_correctness
citation_traceability
unsupported_claim_rate
contradicted_claim_rate
unsupported_critical_claim_count
```

## 3.4 来源质量

来源质量必须结合 Claim 判断，不能只使用固定的来源等级排序。

评价内容：

- 来源是否适合证明对应 Claim。
- 是否优先使用一手、权威、方法透明的来源。
- 来源发布时间和数据时间是否符合 `as_of_date`。
- 关键结论是否有跨来源印证。
- 是否过度依赖单一域名或重复来源。
- 对争议问题是否包含反面证据。

建议指标：

```text
source_claim_fit
source_freshness
authoritative_source_ratio
cross_source_corroboration
source_diversity
duplicate_source_ratio
```

来源数量只能作为诊断指标，不能直接代表来源质量。

## 3.5 分析与综合质量

评价报告是否把证据转化为有用分析，而不是简单堆砌材料：

- 是否解释数据和现象之间的关系。
- 是否进行了有效比较和权衡。
- 是否综合多个来源形成结论。
- 是否处理来源之间的冲突。
- 是否区分事实、推断和建议。
- 是否说明证据不足、适用边界和不确定性。
- 是否避免重复、空泛和过度结论。

建议指标：

```text
analysis_depth
comparison_quality
multi_source_synthesis
conflict_handling
uncertainty_calibration
decision_usefulness
redundancy_rate
```

## 3.6 表达与可用性

评价内容：

- 结构是否服务用户任务。
- 表格、标题和正文是否一致。
- 语言是否匹配用户要求。
- 表达是否清晰、简洁。
- 是否适合目标受众。

这部分不能掩盖事实和引用问题，因此只在 Hard Gate 通过后参与质量评价。

---

# 4. 过程评价

过程评价包括三个层次：

1. **执行正确性**：Agent 和工具是否成功执行。
2. **决策正确性**：Agent 的意图、规划、路由和动作选择是否合理。
3. **决策有效性**：这些动作是否真正改善最终结果，且成本是否值得。

## 4.1 Agent 通用执行质量

所有 Agent 和工具调用都应评价：

### 执行可靠性

```text
tool_success_rate
timeout_rate
retry_rate
retry_success_rate
schema_valid_rate
fallback_rate
recovery_success_rate
duplicate_execution_rate
```

### 调用合理性

- 是否选择正确的工具。
- 参数和 Query 是否符合任务目标。
- 是否存在不必要的重复调用。
- 是否遗漏必须调用的工具。
- 返回结果是否被后续 Evidence、Plan 或报告使用。

建议指标：

```text
useful_tool_call_rate
redundant_tool_call_rate
invalid_parameter_rate
tool_result_utilization
```

工具调用成功率只能证明调用成功，不能证明调用必要、参数正确或结果有用。

### Agent 交接质量

- 上游约束是否完整传递给下游。
- Source、Evidence、Claim ID 是否保持关联。
- Agent 输出是否满足下游 Schema。
- 是否发生上下文覆盖、信息丢失或重复执行。
- 错误、降级和不确定性是否正确传播。

## 4.2 意图识别与 Scope Agent

评价结构化意图是否准确表达用户需求：

- 核心研究目标是否正确。
- 显式约束是否完整识别。
- 是否错误添加用户没有要求的约束。
- 时间、地区、对象、语言、格式和受众是否正确。
- 任务类型和 Workflow 路由是否正确。
- 是否在必要时澄清、不必要时避免阻塞。
- 已识别约束是否进入 Plan 和最终报告。

建议指标：

```text
intent_accuracy
constraint_precision
constraint_recall
routing_accuracy
clarification_precision
clarification_recall
constraint_retention_to_plan
constraint_retention_to_report
```

评价标准来自 Eval Case 的人工 Task Spec。意图识别不与某段固定标准文本比较，而与结构化约束比较。

## 4.3 Planning / Supervisor

规划没有唯一正确答案，因此不评价“是否与标准 Plan 相同”，而评价必要性质和下游效果。

### 规划质量

- **Goal Coverage**：是否覆盖用户目标和 Required Points。
- **Decomposability**：Work Item 是否明确、可独立执行。
- **Non-overlap**：任务之间是否大量重复。
- **Dependency Correctness**：任务顺序和依赖是否合理。
- **Evidence Orientation**：是否明确需要寻找什么证据。
- **Feasibility**：当前模型、工具和预算能否完成。
- **Source Strategy**：是否为不同问题规划合适来源。
- **Budget Allocation**：是否把预算分配给关键和高风险问题。
- **Adaptability**：新证据或 Gap 出现后能否调整。

### 规划执行效果

```text
plan_item_completion_rate
plan_to_evidence_conversion
plan_to_supported_claim_conversion
required_point_coverage_after_plan
duplicate_work_item_rate
unplanned_critical_gap_rate
```

Plan Judge 的分数只能作为语义评价；Plan 是否有效最终要通过 Evidence 产出、最终 Coverage 和成本验证。

## 4.4 Researcher、Search 与 L0/L1/L2

L0/L1/L2 应被视为信息漏斗，不需要重新分类或重复落库：

```text
Search Result L0
→ 筛选/摘要 L1
→ 深度证据 L2
→ Evidence
→ Supported Claim
```

评价内容：

- Query 是否对应 Plan 和 Gap。
- 搜索结果是否相关、有新信息。
- L1 是否错误淘汰权威或关键来源。
- L2 是否形成可引用 Evidence。
- Evidence 是否被最终报告使用。
- 多轮搜索是否增加新证据，而不是重复已有来源。
- 关键 Claim 是否可以回溯到搜索结果。

建议指标：

```text
query_relevance
source_novelty
duplicate_search_rate
L0_to_L1_retention
L1_to_L2_promotion_precision
authoritative_source_discard_rate
L2_to_evidence_conversion
evidence_to_supported_claim_conversion
evidence_utilization
```

数量转化直接使用现有数据；“被丢弃的来源是否重要”需要抽样独立审计。

## 4.5 Reviewer

已有 coverage、evidence、freshness、source diversity、consistency 分数直接复用。Eval 不重新生产同一套分数，而评价这些判断是否准确。

### Gap 识别准确性

```text
reviewer_gap_precision
reviewer_gap_recall
reviewer_external_eval_agreement
```

### 停止和继续决策

```text
false_stop_rate
false_continue_rate
```

- False Stop：Reviewer 选择生成报告，但独立 Eval 仍发现关键可修复 Gap。
- False Continue：Reviewer 要求继续，但下一轮没有关闭 Gap 或提升质量。

### Reviewer 带来的价值

```text
gap_closure_rate
new_supported_claims
new_effective_citations
quality_delta_after_review
reviewer_token_cost
marginal_quality_per_1k_tokens
```

Reviewer 一致率只能作为诊断，不能证明 Reviewer 判断正确。

## 4.6 多轮研究

评价第二轮及后续轮次是否产生增量价值：

- 是否关闭上一轮 Gap。
- 是否增加新的有效 Evidence。
- 是否增加 Supported Claim。
- 是否引入新的权威来源。
- 是否只是重复搜索或扩写。
- 是否导致旧的正确标准退化。
- 每轮质量增益是否值得新增成本。

建议指标：

```text
gap_closure_rate
new_supported_claims
new_effective_citations
source_novelty
criterion_incorporation_rate
criterion_regression_rate
net_criterion_gain
marginal_quality_per_1k_tokens
```

多轮价值必须比较同一道题的 Round 1 与后续轮次，不能只比较不同线上任务的均值。

## 4.7 Report Agent 与 Section Team

评价从 Evidence 到 Draft、Revision、Merge 的信息转化：

- Draft 是否覆盖 Required Points。
- 多 Draft 是否具有真实互补性。
- Synthesis 是否优于最佳单 Draft。
- 合成是否丢失正确 Claim 和 Citation。
- 章节团队是否减少重复并保持术语一致。
- Merge 是否引入无依据的新事实。

建议指标：

```text
draft_complementarity
synthesis_uplift
claim_retention
citation_retention
merge_information_loss
duplicate_claim_rate
section_coverage
report_team_token_cost
```

## 4.8 Consistency Agent

需要关联：

```text
Consistency 前报告
→ Consistency 判断
→ 修改后报告
```

评价内容：

- 报告的问题中多少是真问题。
- 真正的跨章节矛盾漏掉多少。
- 修改后矛盾是否减少。
- 是否引入新错误。
- 是否误删正确信息。
- Claim 和 Citation 是否在修改中丢失。

建议指标：

```text
consistency_issue_precision
consistency_issue_recall
cross_section_contradictions_before_after
terminology_consistency
claim_retention_after_revision
citation_retention_after_revision
new_regression_count
post_consistency_quality_delta
consistency_token_cost
```

## 4.9 ClaimVerifier

需要关联：

```text
Pre-Verification Report
→ Verifier Decisions
→ Post-Verification Report
```

评价内容：

- Unsupported Claim 检测准确率和召回率。
- 是否漏掉 Critical Error。
- 是否误报正确 Claim。
- 被发现的问题是否正确修复。
- 是否错误删除、弱化正确 Claim。
- 修正后 Coverage、Citation 和整体质量是否退化。
- 全量验证是否值得成本，或只需验证 Critical Claim。

建议指标：

```text
unsupported_detection_precision
unsupported_detection_recall
critical_error_miss_count
false_warning_rate
claim_correction_rate
claim_retention
citation_retention
post_verification_quality_delta
verification_token_cost
```

ClaimVerifier 的内部标签不是自身准确性的证据，需要独立 Judge 或人工标注校准。

## 4.10 运行可靠性与恢复

除 Agent 决策外，还要评价系统能否稳定产出合格结果：

```text
technical_completion_rate
task_success_rate
degraded_rate
timeout_rate
empty_report_rate
recovery_success_rate
fallback_success_rate
```

需要测试：

- 模型超时和重试。
- 搜索部分失败和降级。
- 单个 Researcher 失败。
- Section 生成失败。
- HITL Resume。
- Checkpoint Resume。
- SSE 断连重连。

恢复成功不仅要求最后返回文本，还要求状态一致、无重复副作用、不重复计费，且最终报告仍通过质量 Gate。

## 4.11 成本与效率

成本不混入质量总分，单独评价：

```text
active_duration
wall_duration
input_tokens
output_tokens
search_count
round_count
estimated_cost
cost_per_success
marginal_quality_per_1k_tokens
```

每个昂贵机制都要回答：

```text
增加了多少质量
增加了多少成本
是否降低了严重错误风险
在哪些任务类型下值得启用
```

---

# 5. 评价标准从哪里来

不同指标不能使用同一种标准。建议分为四层：

## 5.1 确定性规则

适用于：

- 状态、超时、重试和 Tool Error。
- Schema、ID 和引用解析。
- Source/Evidence 可追溯性。
- Token 对账。
- Plan Item 是否执行。
- Claim/Citation 是否在合成中丢失。

这类指标可信度最高，可以作为工程 Gate。

## 5.2 人工 Task Spec 与题目 Rubric

适用于：

- 意图和约束识别。
- Required Point Coverage。
- Critical Fact Recall。
- 是否需要澄清。
- Plan 是否覆盖核心目标。
- 明确指令是否满足。

这类标准由版本化 Eval Dataset 维护。

## 5.3 独立 LLM Judge

适用于：

- Claim 是否被 Evidence 支持。
- Plan 是否可执行、重复或遗漏。
- Reviewer Gap 是否成立。
- 分析深度和多来源综合。
- 不确定性是否合理。

Judge 必须输出：

```text
label
reason
evidence_span
confidence
```

并允许 `not_enough_information`，不能强迫所有样本得到确定结论。

## 5.4 下游结果和消融实验

用于回答机制是否真正有价值：

```text
With Agent
vs
Without Agent
```

或：

```text
Before Action
vs
After Action
```

控制相同题目、模型、初始 Evidence、时间边界和 Evaluator，比较质量增量和成本增量。

对于没有唯一答案的意图、规划和搜索策略，消融和下游效果比“是否等于标准答案”更可靠。

---

# 6. 如何验证 Eval 标准本身

自动 Eval 不能天然被认为正确，需要进行 Meta-Eval。

## 6.1 人工校准集

人工标注一批：

- 意图和约束。
- Plan。
- Search Query。
- Reviewer Gap。
- Consistency Issue。
- ClaimVerifier 判断。
- Claim-Citation Pair。

比较自动 Judge 的 Precision、Recall、F1、与人工一致率和关键错误漏检数。

## 6.2 双人独立标注

同一批样本由两位标注者独立评价。如果人工之间一致率低，应先修改 Rubric，而不是直接更换 Judge。

## 6.3 预测有效性

过程指标必须能够解释或预测最终结果：

- Plan Score 高是否对应更高 Coverage。
- Reviewer 判定 Ready 是否对应更高 Gate Pass Rate。
- Evidence Score 高是否对应更少 Unsupported Claim。
- 更多 Tool Call 是否真的带来更高质量。

与最终结果长期无关的内部指标，应降级为诊断项或删除。

## 6.4 消融有效性

通过关闭或替换某个机制判断其净收益：

- Without / With Reviewer。
- Round 1 / Gap-directed Round 2。
- Without / With Consistency。
- Without / With ClaimVerifier。
- Single ReportAgent / Section Team。

报告配对差值，不只比较全局平均分。

## 6.5 Judge 运行要求

- Evaluator Prompt、模型和规则必须版本化。
- Judge 尽量与生产生成模型解耦。
- A/B 比较采用盲测并交换候选顺序。
- Judge 失败不能默认记为通过。
- 高风险、低置信度和 Critical Error 必须进入人工复核。

---

# 7. 现有数据复用与信息缺口

## 7.1 直接复用，不重复落库

- `research_session` 中的模式、状态、模型、Token 和时间。
- `workflow_event` 和 Trace 中的阶段、异常、fallback 和调用链。
- `research_planning_round` 和 `research_work_item`。
- L0/L1/L2、Evidence Ledger 和 Context Node。
- Reviewer 分数、投票、Gap 和决策。
- Section Draft、Revision、Merge。
- Consistency Agent 结果。
- ClaimVerifier 结果。
- 最终报告。

## 7.2 完整 Eval 必须具备的信息

需要确认现有数据能否提供：

```text
唯一 Run/Attempt ID
Workflow、Prompt、Model 版本
Source 抓取时间与内容 Hash
Final Claim → Citation → Evidence → Source 关联
Consistency 处理前后报告
ClaimVerifier 处理前后报告
Round 前后 Artifact
```

缺失时优先在现有结构中增加字段、ID 或 Artifact 类型，不优先复制整套数据。

## 7.3 最小新增 Eval 数据

### `eval_dataset_item`

保存题目和独立评价标准：

```text
query_snapshot
as_of_date
required_points
critical_facts
forbidden_claims
source_policy
explicit_constraints
dataset_version
```

这是必要数据，因为业务运行记录通常不包含外部评价标准。

### `eval_result`

保存独立 Eval 产生的新结论：

```text
target_type
target_id
metric
score_or_label
evaluator_version
judge_model
reason
evidence_span
confidence
human_review_status
```

它不能复制报告、来源、Token 和内部 Agent 分数。

### `eval_experiment_case`

开始做回归和消融时保存：

```text
dataset_item_id
baseline_run_id
treatment_run_id
variant
repeat_no
experiment_version
```

MVP 可以先使用版本化 JSONL 和实验结果文件，确认查询和实验需求后再正式建表。

---

# 8. 推荐实施顺序

## 阶段一：验证数据能否支撑 Eval

1. 检查 Run、版本和 Artifact 关联。
2. 检查 Claim-Citation-Evidence-Source 链路。
3. 检查 Reviewer、Consistency、Verifier 的输入、输出和修改前后版本。
4. 检查 Token 是否有唯一事实源。

## 阶段二：结果 Eval MVP

1. 建立小规模版本化 Dataset。
2. 实现确定性 Hard Gate。
3. 实现 Required Point Coverage。
4. 实现 Claim-Citation 独立评价。
5. 人工校准部分 Claim 和 Coverage。

## 阶段三：过程 Eval MVP

1. Agent 和 Tool 执行可靠性。
2. 意图与约束识别。
3. Planning Coverage 和下游转化。
4. L0/L1/L2 信息漏斗。
5. Reviewer Gap 和停止/继续准确性。
6. Consistency、ClaimVerifier 的 Before/After 效果。

## 阶段四：机制消融与成本决策

1. 做同题配对对照。
2. 计算质量增量、错误风险变化和成本增量。
3. 明确各机制的启用条件，而不是默认全量运行。

---

# 9. 最终定义

Deep Research Eval 不应成为另一套重复的 Reviewer，而应成为对整个研究系统的独立验证层：

> 结果评价判断最终报告是否可靠、完整和有用；过程评价判断每个 Agent 是否理解正确、决策合理、执行成功，并且真正以合理成本改善了最终结果。

项目已有数据主要用于回答“发生了什么”；Eval 新增的数据只用于回答“评价标准是什么、这些判断是否正确、机制是否产生净收益”。
