# Deep Research Eval 精简与过程归因设计

> 文件名：`eval_729_resume.md`  
> 目标：将 Eval 从“给最终报告打分”升级为“判断任务是否完成、评价最终报告、定位过程问题、验证复杂机制是否值得成本”的诊断体系。

## 1. 整体 Eval 在评价什么

Deep Research Eval 不应只输出一个总分。它需要回答五类问题。

### 1.1 任务是否正常完成

这是最基础的可靠性判断：

- Workflow 是否正常结束；
- 是否发生异常、超时、取消；
- 是否生成最终报告；
- 最终报告是否为空；
- 是否使用 fallback 或 degraded 路径；
- Eval 所需要的 Artifact 是否齐全。

这一层只回答“有没有完成”，不回答“报告质量好不好”。

### 1.2 最终报告质量如何

这一层评价用户最终看到的报告：

- 是否覆盖用户要求；
- 关键事实是否正确；
- 需要引用的 Claim 是否有引用；
- 引用是否真正支持对应 Claim；
- 来源是否权威、多样、符合时间要求；
- 分析是否有深度；
- 是否进行了多来源综合；
- 是否正确表达不确定性；
- 是否遵循用户指令、语言、格式和受众要求。

结果 Eval 应尽量保留分维度结果，不应只压缩成一个总分。比如“覆盖度高但事实性差”和“事实正确但分析很浅”对应完全不同的改进方向。

### 1.3 Agent 的每一个过程节点是否完成职责

这一层沿着真实工作流检查：

```text
用户问题
→ ScopeAgent
→ SupervisorAgent
→ Researcher/SearchAgent
→ Evidence
→ Reviewer/下一轮
→ ReportAgent
→ 最终报告
```

它需要回答：

- ScopeAgent 是否正确理解了用户；
- SupervisorAgent 是否把要求规划成研究任务；
- Researcher/SearchAgent 是否找到足够且可靠的 Evidence；
- ReportAgent 是否使用了已经找到的 Evidence；
- 最终问题最早在哪个过程节点出现。

### 1.4 复杂机制是否真正产生质量增益

这一层评价系统额外增加的机制：

- Reviewer 是否找到了真实 Gap；
- Reviewer 触发下一轮后，Gap 是否被关闭；
- Reviewer 指导是否优于没有 Reviewer 的普通补强；
- HIGH 双 Draft 的 Synthesis 是否优于最佳单 Draft；
- Section Revision 是否减少矛盾而没有破坏事实和引用；
- Merge 是否丢失章节中的关键信息；
- ClaimVerifier 是否减少不受支持的 Claim。

### 1.5 质量增益是否值得 Token 和时延

一个机制即使有效，也不代表值得默认开启。还需要评价：

```text
质量提升了多少？
额外消耗了多少 Token？
增加了多少时延？
是否只对某些 Task Type 有效？
是否存在更轻量的方案达到相同结果？
```

因此，整体 Eval 最终要支持：

```text
Task Type
→ 预期质量收益
→ 增量成本
→ 应选择的 Tier 或 Mechanism
```

## 2. 推荐的 Evaluator 结构

建议将真正的 evaluator 精简为三层八个。

### 2.1 任务完成层

1. `TaskCompletionEvaluator`

评价 Workflow 是否结束、报告是否存在、是否异常或降级，以及 Eval 数据是否完整。

### 2.2 最终报告质量层

2. `CoverageEvaluator`
3. `CitationFactualityEvaluator`
4. `SourceQualityEvaluator`
5. `ReportQualityEvaluator`

它们分别评价覆盖度、事实与引用、来源质量、分析与表达质量。

### 2.3 过程和机制层

6. `IntentAlignmentEvaluator`
7. `EvidencePipelineEvaluator`
8. `MechanismImpactEvaluator`

这三个 evaluator 是结果 Eval 与 Agent 过程之间的连接层，也是后续根因分析的核心。

### 2.4 不应继续算作 evaluator 的组件

以下组件仍然需要，但不应占用 evaluator 数量：

- `ClaimExtractionPreprocessor`：把报告拆成 Claim-Citation Manifest；
- `QualityGateAggregator`：汇总多个 evaluator 的结果，产生质量 Gate；
- `ExperimentCostAggregator`：在多个 Case/Variant 上计算成本收益；
- `RootCauseAnalyzer`：读取结果和过程指标，生成根因诊断。

## 3. 三个过程 Evaluator 的共同基础

三个 evaluator 不应各自创造一套互不相干的分数。它们要共享一份 Criterion Ledger。

### 3.1 Criterion 是什么

Criterion 是从用户问题和 Dataset 标注中拆出的原子评价项。

例如用户问题：

> 对比 RAG 和 Fine-tuning 在企业知识问答中的优劣，需要分析成本、维护、时效性、数据安全，并给出选型建议。

可以拆为：

```json
[
  {"criterion_id": "c1", "text": "比较成本", "weight": 1, "critical": false},
  {"criterion_id": "c2", "text": "比较维护成本和难度", "weight": 1, "critical": false},
  {"criterion_id": "c3", "text": "比较知识更新时效性", "weight": 1, "critical": false},
  {"criterion_id": "c4", "text": "分析数据安全", "weight": 2, "critical": true},
  {"criterion_id": "c5", "text": "给出企业选型建议", "weight": 2, "critical": true}
]
```

Criterion ID 属于 Eval 数据，不需要提前暴露给运行中的 Agent，避免 Agent 针对 Eval 标注生成答案。

### 3.2 Criterion Trace

对每一个 Criterion，Eval 都要追踪它在不同阶段的状态：

| Criterion | Intent | Plan | Evidence | Reviewer | Final |
|---|---:|---:|---:|---:|---:|
| c1 成本 | 1 | 1 | 1 | - | 1 |
| c2 维护 | 1 | 1 | 1 | - | 1 |
| c3 时效性 | 1 | 1 | 0.5 | 发现 Gap | 1 |
| c4 数据安全 | 1 | 0 | 0 | 发现 Gap | 0 |
| c5 选型建议 | 1 | 1 | 1 | - | 1 |

建议统一使用：

```text
covered / full support      = 1
partial / partial support   = 0.5
missing / no support        = 0
contradicted                = -1
not_evaluable               = null
```

`not_evaluable` 不能默认当作通过，也不能默认记为 0。它表示缺少计算该指标所需的数据。

### 3.3 结果 Eval 如何参与

结果 Eval 不能只输出：

```json
{"required_point_coverage": 0.8}
```

还需要输出 Criterion 级细节：

```json
{
  "required_point_coverage": 0.8,
  "criteria": [
    {"criterion_id": "c1", "score": 1, "report_evidence": "……"},
    {"criterion_id": "c4", "score": 0, "reason": "报告未覆盖数据安全"}
  ]
}
```

Citation/Factuality Eval 也应输出 Claim 级细节：

```json
{
  "claims": [
    {
      "claim_id": "claim-8",
      "factuality": 1,
      "citation_correctness": 0.5,
      "evidence_ids": ["ev-17"]
    }
  ]
}
```

只有结果 Eval 细化到 Criterion 和 Claim，过程 Eval 才能把最终问题连接回具体步骤。

## 4. IntentAlignmentEvaluator

### 4.1 它评价什么

`IntentAlignmentEvaluator` 评价 ScopeAgent 是否正确理解了用户问题。

它主要回答：

```text
用户要求研究什么，ScopeAgent 是否识别完整？
时间、地域、语言、受众、格式等约束是否保留？
ScopeAgent 是否错误增加或修改了约束？
Research Type 是否识别正确？
Workflow Template 是否路由正确？
问题存在关键歧义时，ScopeAgent 是否正确发起澄清？
```

它评价的是“理解是否正确”，不是“最终报告是否优秀”。

### 4.2 它读取什么

Dataset 侧：

- 原始 Query；
- Required Points/Criterion；
- Task Type；
- Language；
- As-of Date；
- 地域、受众、格式、引用要求等显式约束；
- 是否需要澄清的人工标注。

运行侧：

- ScopeAgent 生成的 Research Brief；
- `research_type`；
- `type_confidence`；
- `type_candidates`；
- 选择的 Workflow Template；
- Clarification 的判断和问题。

### 4.3 它具体怎么做

#### Step 1：逐 Criterion 检查 Research Brief

对每一个 Criterion，让独立 Judge 判断 Research Brief 是否保留了该要求。

输入示例：

```json
{
  "user_query": "对比 RAG 和 Fine-tuning，需要分析成本、维护、时效性、数据安全，并给出选型建议",
  "criterion": {
    "criterion_id": "c4",
    "text": "分析数据安全"
  },
  "research_brief": "研究 RAG 和 Fine-tuning 的成本、维护和时效性，并给出选型建议"
}
```

输出示例：

```json
{
  "criterion_id": "c4",
  "status": "missing",
  "score": 0,
  "evidence": "",
  "reason": "Research Brief 未包含数据安全"
}
```

Judge 必须返回它在 Brief 中找到的对应文本，避免只给无依据分数。

#### Step 2：检查约束是否被保留或篡改

例如：

```text
用户要求：中国市场、截至 2026 年、中文报告
Scope 输出：全球市场、近几年、英文报告
```

这些不是普通漏项，而是约束冲突，应记录为 `contradicted`。

不建议简单使用“Intent Precision”惩罚所有额外研究方向，因为 ScopeAgent 可以合理扩展研究范围。更有价值的是：

- `constraint_recall`：用户约束保留了多少；
- `constraint_contradiction_rate`：输出中有多少约束与用户冲突；
- `critical_constraint_miss_count`：遗漏了多少关键约束。

#### Step 3：确定性比较 Routing

以下指标不需要 LLM：

```text
predicted_research_type == gold_task_type
selected_template == expected_template
language == expected_language
as_of_date == expected_as_of_date
```

#### Step 4：检查 Clarification

Dataset 需要对部分题目标注：

```text
should_clarify = true/false
missing_information = [...]
```

然后比较 ScopeAgent 是否：

- 对明确问题进行了不必要澄清；
- 对关键歧义没有澄清；
- 提出的澄清问题是否针对真正缺失的信息。

### 4.4 它怎么算分

Intent Coverage 使用加权 Criterion：

```text
intent_coverage
= Σ(criterion_weight × criterion_score)
  / Σ(criterion_weight)
```

例如：

| Criterion | 权重 | 分数 |
|---|---:|---:|
| 成本 | 1 | 1 |
| 维护 | 1 | 1 |
| 时效性 | 1 | 1 |
| 数据安全 | 2 | 0 |
| 选型建议 | 2 | 1 |

则：

```text
intent_coverage = 5 / 7 = 0.714
```

关键 Criterion 应提高权重，避免识别了很多小要求但漏掉一个核心要求后仍得到高分。

### 4.5 它如何利用结果 Eval

最终 Coverage Eval 会告诉系统哪些 Criterion 在最终报告中缺失。

然后做关联：

```text
Intent(c4)=0，Final(c4)=0
→ 最终漏答可能从 Scope 阶段开始

Intent(c4)=1，Final(c4)=0
→ Scope 理解正确，需要继续检查 Plan 和 Evidence
```

最终结果不参与计算 Intent 本身的分数，避免下游错误反过来错误惩罚 ScopeAgent。结果 Eval 只参与根因关联。

### 4.6 它输出什么

```json
{
  "intent_coverage": 0.714,
  "constraint_recall": 0.8,
  "constraint_contradiction_rate": 0,
  "research_type_correct": true,
  "template_routing_correct": true,
  "clarification_correct": true,
  "missing_criteria": [
    {"criterion_id": "c4", "text": "分析数据安全"}
  ],
  "contradicted_constraints": []
}
```

### 4.7 它能定位什么问题

它主要对应：

- Scope Prompt；
- Research Brief 生成；
- Research Type 分类；
- Workflow Template 路由；
- Clarification 判断。

## 5. EvidencePipelineEvaluator

### 5.1 它评价什么

`EvidencePipelineEvaluator` 评价：

```text
Scope 理解正确以后，
Supervisor 是否规划到，
Researcher/Search 是否研究到，
Evidence 是否足够，
最终报告是否使用了已经找到的 Evidence。
```

它连接：

```text
Intent
→ Plan
→ Evidence
→ Final Report
```

它是结果问题反向定位到具体 Agent 的核心 evaluator。

### 5.2 它读取什么

- Dataset Criterion；
- Research Brief；
- Supervisor 生成的 Research Work Items；
- 各轮 Researcher Findings；
- `evidence_item` Artifact；
- `source_snapshot` Artifact；
- Claim-Citation Manifest；
- Coverage Result 的 Criterion 级结果；
- Citation/Factuality Result 的 Claim 级结果；
- Round、Work Item、Evidence、Claim 之间的关联 ID。

### 5.3 它具体怎么做

#### Step 1：检查 Plan 是否覆盖 Criterion

把 Supervisor 的所有 Work Item 与每个 Criterion 对比。

输入示例：

```json
{
  "criterion": {
    "criterion_id": "c4",
    "text": "分析数据安全"
  },
  "work_items": [
    {"task_id": "t1", "text": "比较部署和训练成本"},
    {"task_id": "t2", "text": "比较维护和知识更新时效性"},
    {"task_id": "t3", "text": "形成企业选型建议"}
  ]
}
```

输出：

```json
{
  "criterion_id": "c4",
  "status": "missing",
  "score": 0,
  "matched_task_ids": []
}
```

这一步产生：

```text
plan_coverage
critical_plan_miss_count
criterion → task_ids 映射
```

#### Step 2：检查 Evidence 是否真正支持 Criterion

不能用搜索次数、网页数、Evidence 数量代替 Evidence 质量。

对每个 Criterion，独立 Judge 判断相关 Evidence：

```json
{
  "criterion": {
    "criterion_id": "c1",
    "text": "比较成本"
  },
  "evidence": [
    {
      "evidence_id": "ev-1",
      "claim": "Fine-tuning 初始训练成本通常高于 RAG",
      "evidence_text": "……",
      "source_type": "academic",
      "source_url": "https://..."
    }
  ]
}
```

输出：

```json
{
  "criterion_id": "c1",
  "support": "full",
  "score": 1,
  "supporting_evidence_ids": ["ev-1"],
  "source_quality": 0.9
}
```

需要区分：

```text
没有 Evidence
Evidence 相关但只部分支持
Evidence 完整支持
Evidence 与目标结论矛盾
Evidence 来源过弱
```

#### Step 3：检查 Evidence 是否具有新增价值

对于第二轮及以后，需要判断：

- 是否找到第一轮没有的新 Evidence；
- 是否只是重复旧来源；
- 是否增加了权威来源；
- 是否补强了上轮 Gap；
- 是否引入了新的冲突。

可以输出：

```text
new_supported_criteria
source_novelty
duplicate_evidence_ratio
new_authoritative_source_count
```

这些是过程诊断指标，不应直接成为最终质量 Gate。

#### Step 4：检查有效 Evidence 是否进入最终报告

通过：

```text
Evidence ID
→ Claim ID
→ Citation
→ Final Report
```

检查：

- 已找到的有效 Evidence 是否被最终报告使用；
- 最终报告是否使用了较弱 Evidence 而忽略更强 Evidence；
- Evidence 支持的 Criterion 是否最终仍然漏答；
- ReportAgent 是否改变或夸大了 Evidence 的含义。

推荐指标：

```text
criterion_evidence_utilization
= 有有效 Evidence 且最终被正确使用的 Criterion
  / 有有效 Evidence 的 Criterion
```

不建议要求所有 Evidence 都被报告使用，因为合理的报告必然会筛选材料。

#### Step 5：寻找每个最终问题的第一个失败节点

对每个 Criterion 执行：

```text
如果 Intent=0：
  first_failed_stage = intent
  suspected_component = ScopeAgent

否则如果 Plan=0：
  first_failed_stage = plan
  suspected_component = SupervisorAgent

否则如果 Evidence=0：
  first_failed_stage = evidence
  suspected_component = Researcher/SearchAgent

否则如果 Final=0：
  first_failed_stage = final
  suspected_component = ReportAgent/Synthesis/Merge
```

示例：

```json
{
  "criterion_id": "c4",
  "intent": 1,
  "plan": 0,
  "evidence": 0,
  "final": 0,
  "first_failed_stage": "plan",
  "suspected_component": "SupervisorAgent",
  "confidence": "high"
}
```

### 5.4 它怎么算分

主要指标：

```text
plan_coverage
= Σ(weight × plan_score) / Σ(weight)

evidence_coverage
= Σ(weight × evidence_score) / Σ(weight)

criterion_evidence_utilization
= 正确使用 Evidence 的 Criterion 权重
  / 有充分 Evidence 的 Criterion 权重
```

但这个 evaluator 最有价值的输出不是平均分，而是每个 Criterion 的完整链路和断点。

### 5.5 它如何利用结果 Eval

它直接使用：

- Coverage Eval 的 Final Criterion 状态；
- Citation/Factuality Eval 的 Claim 支持状态；
- Source Quality Eval 的 Source Pool 和 Used Source 质量。

例如：

```text
Source Pool 质量高，Used Source 质量低
→ 更可能是 ReportAgent 的来源选择问题

Source Pool 本身质量低
→ 更可能是 Search/Researcher 问题

Evidence 支持 c4，但 Final(c4)=0
→ ReportAgent 没有利用已有 Evidence
```

### 5.6 它输出什么

```json
{
  "plan_coverage": 0.8,
  "evidence_coverage": 0.7,
  "criterion_evidence_utilization": 0.6,
  "source_pool_quality": 0.82,
  "used_source_quality": 0.64,
  "criterion_traces": [
    {
      "criterion_id": "c4",
      "intent": 1,
      "plan": 0,
      "evidence": 0,
      "final": 0,
      "first_failed_stage": "plan",
      "suspected_component": "SupervisorAgent"
    },
    {
      "criterion_id": "c5",
      "intent": 1,
      "plan": 1,
      "evidence": 1,
      "final": 0,
      "first_failed_stage": "final",
      "suspected_component": "ReportAgent"
    }
  ]
}
```

### 5.7 它能定位什么问题

它主要对应：

- Supervisor 任务拆解；
- 下一轮 Focus 到 Work Item 的转换；
- Researcher 研究执行；
- Search Query 和 Source 选择；
- Evidence 提取和结构化；
- ReportAgent 的 Evidence 使用；
- Citation 与 Evidence 的关联。

## 6. MechanismImpactEvaluator

### 6.1 它评价什么

`MechanismImpactEvaluator` 评价系统增加的复杂机制是否真的带来质量提升：

- Reviewer；
- Multi-round；
- HIGH 双 Draft/Synthesis；
- Section Revision；
- Section Merge；
- ClaimVerifier。

它不是检查“机制有没有运行”，而是检查：

```text
运行之前结果怎样？
运行之后结果怎样？
哪些指标变好？
哪些指标退化？
花了多少 Token？
如果没有该机制，结果是否可能一样好？
```

### 6.2 统一评价方法

所有机制都使用相同结构：

```text
Before Artifact
→ Mechanism
→ After Artifact
```

然后：

1. 对 Before 和 After 运行相同版本的结果 Eval；
2. 比较每一个质量维度；
3. 记录新增和退化的 Criterion；
4. 读取该机制的 Token 和时延；
5. 在有对照 Variant 时计算机制的因果增益。

不能用“修改后文本更长”“Claim 更多”“引用更多”代替质量提升。

### 6.3 Reviewer 的具体评价

Reviewer 需要分四层评价。

#### 第一层：Reviewer 找问题是否准确

在 Reviewer 执行前，让独立外部 Judge 评价当前累计 Evidence 或 Shadow Report，得到真实 Gap：

```text
D_r = 外部 Eval 在第 r 轮发现的 Gap
G_r = Reviewer 在第 r 轮提出的 Gap
```

例如：

```text
外部真实 Gap：
{时效性, 数据安全, 选型建议}

Reviewer Gap：
{数据安全, 选型建议, 增加更多案例}
```

计算：

```text
reviewer_gap_precision = |G_r ∩ D_r| / |G_r|
reviewer_gap_recall    = |G_r ∩ D_r| / |D_r|
```

关键 Gap 应按权重计算，防止 Reviewer 找到很多小问题却漏掉核心问题。

#### 第二层：Reviewer 建议是否进入下一轮计划

检查：

```text
Reviewer Gap
→ nextFocus
→ 下一轮 Supervisor Work Item
```

计算：

```text
gap_to_plan_rate
= 被下一轮 Work Item 覆盖的有效 Reviewer Gap
  / Reviewer 提出的有效 Gap
```

Reviewer 找对问题但下一轮没有安排对应任务，说明问题可能在 Reviewer 到 Supervisor 的交接。

#### 第三层：下一轮是否找到 Evidence 并关闭 Gap

继续检查：

```text
Reviewer Gap
→ 下一轮新增 Evidence
→ 下一轮结束后的外部 Eval
```

计算：

```text
gap_to_evidence_rate
= 得到有效新 Evidence 的 Gap
  / 进入下一轮计划的 Gap

gap_closure_rate
= 下一轮被外部 Eval 判定为已解决的 Gap
  / Reviewer 提出的有效 Gap
```

如果 Reviewer 找对问题：

- 下一轮无对应任务：交接/Supervisor 问题；
- 有任务但无 Evidence：Researcher/Search 问题；
- 有 Evidence 但 Final 仍失败：ReportAgent 问题。

#### 第四层：Reviewer 指导是否真的优于普通补强

单纯比较：

```text
第二轮质量 - 第一轮质量
```

不能证明 Reviewer 有效，因为第二轮还增加了搜索、Researcher 和 Token。

理论上需要三个配对 Variant：

```text
A：第一轮后直接生成报告
B：不使用 Reviewer Gap，进行普通第二轮补强
C：使用 Reviewer Gap，进行定向第二轮补强
```

分别得到：

```text
Q_stop
Q_generic
Q_reviewer
```

计算：

```text
total_round_uplift
= Q_reviewer - Q_stop

reviewer_guidance_uplift
= Q_reviewer - Q_generic
```

其中：

- `total_round_uplift` 包含多一轮研究的全部收益；
- `reviewer_guidance_uplift` 才更接近 Reviewer 指导本身的收益。

#### Reviewer 的 false stop/false continue

Reviewer 选择 `report`，但外部 Eval 仍发现关键 Gap：

```text
potential_false_stop = true
```

只有对照实验确认继续研究后确实显著改善，才能标为：

```text
confirmed_false_stop = true
```

Reviewer 选择 `continue`，但下一轮：

- 没有新增有效 Evidence；
- 没有关闭 Gap；
- 质量提升低于最小有效阈值；
- 消耗大量 Token；

则：

```text
false_continue = true
```

#### Reviewer 核心指标

建议主报告只保留：

```text
reviewer_gap_precision
reviewer_gap_recall
reviewer_gap_closure_rate
reviewer_guidance_uplift
reviewer_guidance_roi
false_stop
false_continue
```

投票一致率和各 Reviewer 自评分只保留为诊断信息，不能证明 Reviewer 正确。

### 6.4 每轮结果如何比较

当前流程每轮结束后有 Evidence 和 Reviewer 结果，但没有正式报告。可分两阶段实现。

#### 低成本方案：Evidence Readiness

对每轮累计 Evidence 运行相同外部 Judge：

```text
Q_r = 第 r 轮结束后的 Criterion Evidence Readiness
```

比较：

```text
coverage_readiness_delta
evidence_support_delta
source_quality_delta
conflict_resolution_delta
```

它能说明研究材料是否变好，但不能完全代表最终报告是否变好。

#### 高可信方案：Shadow Report

Eval 阶段使用固定模型和固定 Report Prompt：

```text
第 r 轮累计 Evidence
→ shadow_report_r

第 r+1 轮累计 Evidence
→ shadow_report_r+1
```

对两份 Shadow Report 运行同一套结果 Eval：

- Coverage；
- Citation/Factuality；
- Source Quality；
- Report Quality。

这样才能直接回答“Reviewer 纠正后第二次报告是否更好”。

为降低生成随机性，应固定模型、Prompt、温度和版本，并对重要实验重复运行。

### 6.5 HIGH Synthesis 如何评价

比较：

```text
best(comparative_draft, data_driven_draft)
vs
report_synthesis
```

对 Draft 和 Synthesis 运行相同结果 Eval：

```text
coverage_delta
factuality_delta
citation_delta
analysis_delta
instruction_following_delta
```

如果 Synthesis 只是增加篇幅和 Claim 数，但 Coverage、Factuality、Analysis 没有提升，就不应判定有效。

### 6.6 Section Revision 如何评价

比较同一章节：

```text
section_draft
vs
section_revision
```

检查：

- 是否关闭 Consistency Agent 指出的矛盾；
- 是否提高本章节 Criterion Coverage；
- 是否破坏事实和引用；
- 是否产生新的重复或冲突；
- 是否只是改写措辞而没有实质提升。

单独的 Claim/Citation 保留率只作为诊断。删除错误 Claim 可能使保留率下降，但实际质量变好。

### 6.7 Merge 如何评价

构造 Before：

```text
所有 Section Revision 的直接组合
```

After：

```text
report_merged
```

对两者运行相同结果 Eval。

如果各章节分别都覆盖完整，但 Merge 后漏掉关键 Criterion 或 Citation，根因应指向 Merge Agent。

### 6.8 ClaimVerifier 如何评价

必须保存：

```text
report_pre_verification
report_final
```

然后比较：

```text
unsupported_claim_count_before/after
contradicted_claim_count_before/after
citation_correctness_before/after
coverage_before/after
false_warning_count
```

Verifier 有价值的表现是：

- 减少不受支持或矛盾 Claim；
- 没有误伤正确 Claim；
- 没有显著降低 Coverage；
- 增益值得额外 Token。

### 6.9 成本收益怎么计算

需要区分：

```text
reviewer_tokens
= Reviewer 调用本身的 Token

review_path_tokens
= Reviewer
  + 下一轮 Supervisor
  + 下一轮 Researcher/Search
```

计算：

```text
reviewer_path_roi
= (Q_reviewer - Q_stop)
  / review_path_tokens
  × 1000

reviewer_guidance_roi
= (Q_reviewer - Q_generic)
  / reviewer_tokens
  × 1000
```

最好分别报告 Coverage、Factuality、Citation 等维度的收益，不要只看一个总质量分。

### 6.10 它输出什么

```json
{
  "reviewer": {
    "gap_precision": 0.67,
    "gap_recall": 0.67,
    "gap_to_plan_rate": 1,
    "gap_closure_rate": 0.5,
    "guidance_uplift": 0.08,
    "guidance_roi": 0.004,
    "false_stop": false,
    "false_continue": false
  },
  "high_synthesis": {
    "coverage_delta": 0.1,
    "factuality_delta": -0.02,
    "analysis_delta": 0.04,
    "token_cost": 8500
  },
  "section_revision": {
    "criterion_gain_count": 2,
    "criterion_regression_count": 1,
    "citation_correctness_delta": -0.05
  },
  "section_merge": {
    "coverage_delta": -0.1,
    "lost_criteria": ["c4"]
  },
  "claim_verifier": {
    "unsupported_claim_delta": -3,
    "citation_correctness_delta": 0.1,
    "coverage_delta": 0,
    "token_cost": 12000
  }
}
```

## 7. Root Cause Analyzer

`RootCauseAnalyzer` 不是新的 evaluator，而是消费前面各 evaluator 的结构化结果。

### 7.1 Criterion 级规则

```text
Final 失败，Intent 失败
→ ScopeAgent

Final 失败，Intent 正常，Plan 失败
→ SupervisorAgent

Final 失败，Plan 正常，Evidence 失败
→ Researcher/SearchAgent

Final 失败，Evidence 正常，Final 失败
→ ReportAgent/Synthesis/Merge
```

### 7.2 Reviewer 链路规则

```text
外部真实 Gap 存在，Reviewer 未发现
→ Reviewer

Reviewer 发现 Gap，下一轮 Plan 未覆盖
→ Reviewer→Supervisor 交接或 Supervisor

Plan 覆盖，未获得有效 Evidence
→ Researcher/Search

获得有效 Evidence，Final 仍失败
→ ReportAgent
```

### 7.3 输出

```json
{
  "observed_failure": "required_point_missing",
  "criterion_id": "c4",
  "suspected_component": "SupervisorAgent",
  "confidence": "high",
  "evidence": {
    "intent": 1,
    "plan": 0,
    "evidence": 0,
    "final": 0
  },
  "recommended_experiment": "planner_prompt_ablation"
}
```

只有最终结果、没有过程 Artifact 时，根因置信度最多标为 `low`。

## 8. 一次完整 Eval 的运行顺序

```text
1. TaskCompletionEvaluator
   判断任务是否正常完成、数据是否可评估

2. ClaimExtractionPreprocessor
   生成 Claim-Citation Manifest

3. 最终结果 Evaluators
   Coverage
   Citation/Factuality
   Source Quality
   Report Quality

4. IntentAlignmentEvaluator
   填写 Criterion 的 Intent 状态

5. EvidencePipelineEvaluator
   填写 Plan、Evidence、Final 使用状态

6. MechanismImpactEvaluator
   比较 Reviewer、Round、Synthesis、Revision、Merge、Verifier 前后

7. RootCauseAnalyzer
   为每个最终问题寻找第一个失败节点

8. ExperimentCostAggregator
   在 Variant/Experiment 级计算质量增益与成本收益
```

## 9. 最终 Eval 输出应包含什么

一次 Case 不应只输出总分，而应包含五部分。

### 9.1 执行结果

```json
{
  "status": "completed",
  "fallback_used": false,
  "eval_data_complete": true
}
```

### 9.2 最终报告质量

```json
{
  "coverage": 0.8,
  "factuality": 0.9,
  "citation_correctness": 0.75,
  "source_quality": 0.8,
  "analysis_depth": 0.7
}
```

### 9.3 过程质量

```json
{
  "intent_coverage": 1,
  "plan_coverage": 0.8,
  "evidence_coverage": 0.7,
  "criterion_evidence_utilization": 0.6
}
```

### 9.4 机制有效性

```json
{
  "reviewer_gap_recall": 0.8,
  "reviewer_gap_closure_rate": 0.5,
  "reviewer_guidance_uplift": 0.04,
  "synthesis_coverage_delta": -0.02
}
```

### 9.5 根因诊断

```json
{
  "failures": [
    {
      "criterion_id": "c4",
      "final_problem": "未覆盖数据安全",
      "first_failed_stage": "plan",
      "suspected_component": "SupervisorAgent",
      "confidence": "high"
    }
  ]
}
```

## 10. 这套过程 Eval 能否真实代表过程

它评价的不是模型隐藏的 Chain of Thought，而是可观察、可复现的过程产物：

- Research Brief；
- Work Item；
- Evidence；
- Reviewer Gap；
- 下一轮 Plan；
- Draft/Revision/Merged/Final Report；
- Token 和时延。

可信度分三层。

### 10.1 过程职责评价

通过直接检查阶段输入和输出，判断 Agent 是否完成职责。例如 Scope 是否漏要求、Plan 是否覆盖 Criterion。

### 10.2 单次运行前后效果

使用同一版本的外部结果 Eval 比较 Before/After，判断一个机制之后结果是否变好。

### 10.3 因果效果

只有配对消融才能较可靠地证明“正是这个机制导致提升”：

```text
相同 Dataset Item
相同初始 Evidence
相同模型和预算
无机制 vs 有机制
```

因此应使用准确措辞：

```text
单次前后比较：
“Reviewer 路径之后结果提升”

配对消融：
“Reviewer 指导相对通用补强产生额外提升”
```

## 11. Eval 运行前的 Dataset 如何构建

这里的 Dataset 是运行 Eval 之前冻结好的测试输入和人工评价标准，不是 Eval 跑完以后从结果中生成的数据。

### 11.1 同一题必须配对回放三个档位

一个 Dataset Item 默认声明：

```json
{
  "eligible_variants": ["MEDIUM", "HIGH", "ULTRA"]
}
```

同一题在固定 Query、As-of Date、Source Policy、模型和 Evaluator Version 下分别运行三个档位，比较 Case 级差值。三个档位使用同一套质量标准，不能为 ULTRA 降低或改变事实安全标准。

### 11.2 Required Points 必须升级为结构化 Criterion

```json
{
  "criterion_id": "data_security",
  "text": "比较数据安全",
  "weight": 2,
  "critical": true,
  "acceptance": "讨论数据外发、私有化部署或敏感数据训练风险"
}
```

每个 Criterion 至少包含：

- 稳定 ID；
- 明确描述；
- 权重；
- 是否关键；
- 什么算满足。

这组 Criterion 同时服务于结果 Coverage、Intent Alignment、Plan Coverage、Evidence Coverage 和根因分析。

### 11.3 每条 Item 还需要 Evaluation Contract

```json
{
  "expected_intent": {
    "research_type": "tech_comparison",
    "should_clarify": false
  },
  "constraints": {
    "require_citations": true,
    "language": "zh",
    "as_of_date": "2026-06-01"
  },
  "mechanism_tags": {
    "reviewer_applicable": true,
    "multi_round_applicable": true,
    "synthesis_applicable": true
  }
}
```

它用于评价 Intent、路由和机制适用性，不是运行中的 Agent 输入。

### 11.4 Dataset 不能只有唯一参考报告

Deep Research 往往没有唯一正确写法。Dataset 应冻结：

- 必须回答的 Criterion；
- 关键事实或事实核验口径；
- 禁止出现的错误 Claim；
- 来源策略；
- 用户显式约束；
- 任务类型与机制适用性。

最终报告可以有不同结构，只要满足相同评价标准。

### 11.5 Dataset 分为正式端到端集合和机制抽样子集

当前不单独建设 Process Diagnostic Fixture Dataset。正式 Dataset 由两部分组成：

```text
End-to-End Benchmark：
40 道题，同题运行 MEDIUM/HIGH/ULTRA，评价完成度、结果质量、成本和档位增益。

Mechanism/Ablation Subset：
直接从 40 道题中按机制适用性抽取 Reviewer、Multi-round、Synthesis、
Section Team 和 ClaimVerifier 实验题。
```

机制子集可以重叠，但每个机制必须单独做配对消融，不能用一次复杂 Run 同时声称多个
机制的因果效果。Reviewer 机制实验仍需冻结共同的第一轮输入，确保不同 Variant 从同一
起点继续执行。

### 11.6 采样要求

Dataset 需要按以下维度分层：

- Task Type；
- 难度；
- 时间敏感性；
- 是否存在证据冲突；
- 是否适合多轮；
- 成功、降级、失败和 fallback；
- 典型错误类型。

当前 6 题保留为契约 Smoke Dataset。正式 Dataset 为
`backend-python/evals/datasets/formal_v1_40questions.json`，包括 40 道端到端题目：

- 事实查询 6 题；
- 技术比较 8 题；
- 市场分析 7 题；
- 学术综述 7 题；
- 趋势预测 6 题；
- 证据冲突 6 题。

其中 10 题用于 Evaluator 校准，30 题用于正式 Test。第一版三档各运行 1 次，共 120 次
主实验 Run；机制实验再按 `mechanism_suites` 独立抽样。后续只对高波动题补充重复运行。

## 12. 精简后的 Eval 核心表

Eval 只依赖 8 张核心表。

| 表 | 唯一职责 |
|---|---|
| `research_run` | Run、Outcome、版本、模型和总成本 |
| `research_artifact` | 所有阶段正文和结构化过程 Artifact |
| `research_llm_call` | 单次 LLM Token/时延/错误事实 |
| `research_claim_manifest` | Final Claim、Citation、Evidence 关联 |
| `eval_dataset_item` | Eval 前冻结的题目、Criterion 和 Evaluation Contract |
| `eval_experiment` | 三档比较或机制消融定义 |
| `eval_case_run` | Dataset Item × Variant × Repeat |
| `eval_score` | 指标、原因和 Criterion/Claim 明细 |

### 12.1 `research_artifact` 是唯一过程事实源

核心 Artifact Type：

```text
user_query
research_brief
research_plan
source_snapshot
evidence_item
round_review
report_draft
report_synthesis
report_section_draft
report_section_revision
report_merged
report_pre_verification
report_final
claim_verification
```

Brief 的 metadata 保存意图识别；Plan 保存每轮任务；Evidence 保存 task_key；Round Review 保存完整 Gap 和决策。Evaluator 不再从 Event、Span 和多张业务过程表拼同一事实。

### 12.2 Token 只认 `research_llm_call`

`research_llm_call` 是 Token 唯一事实源。`research_stage_usage` 可以继续作为业务查询和看板投影，但 Eval Runner 不依赖它，必要时可由 LLM Call 重建。

### 12.3 退出核心 Eval 依赖的表

以下表保留原有业务或可观测用途，但不再作为核心 Eval 数据源：

| 表 | 保留用途 |
|---|---|
| `research_planning_round` | ULTRA 业务状态与 UI |
| `research_work_item` | ULTRA 任务执行状态 |
| `research_decision_log` | 业务决策查询 |
| `research_evidence_ledger` | 业务 Evidence 索引 |
| `research_context_node/edge` | Context FS 运行与深度排障 |
| `research_stage_usage` | Token 聚合投影 |
| `workflow_event` | SSE/UI |
| `chat_message` | 用户会话 |
| `research_session` | 用户视角研究生命周期 |

`research_span_attribute` 没有业务读取方，且内容已经存在于 `round_review` Artifact 和
OTel/Langfuse Span 属性中，因此已删除本地表及对应双写代码。其他退出核心 Eval 的表
仍然保留，避免破坏现有运行链路。

### 12.4 Dataset 表只增加一个统一 Contract 字段

`eval_dataset_item` 增加：

```text
evaluation_contract_json
```

它统一承载 Constraints、Expected Intent、适用 Variant 和 Mechanism Tags，避免为每个新标注增加一列或新表。

### 12.5 核心表字段精简

为避免同一事实多处落库，核心表进一步按以下规则收敛：

- `research_artifact` 不保存 Token 和时延；这些字段只从 `research_llm_call` 聚合；
- `eval_case_run` 不重复保存 Run 的 input/output Token、时延和报告正文；
- `eval_case_run` 不重复保存 `research_id`，统一通过 `run_id` 获取；
- `eval_score` 不重复保存 `trace_id` 和 `report_artifact_id`；
- `eval_dataset_item` 不保存与三档配对无关的原始预算档位；
- Score 通过 `case_run_id → eval_case_run.run_id → research_run/research_artifact` 回溯；
- `research_llm_call.id` 已是主键，不再保留 `(run_id, id)` 冗余唯一索引；
- `eval_dataset_item` 使用 `(dataset_name, dataset_version, query_sha256)` 唯一约束；
- CaseRun 的 Experiment、Dataset Item、Variant，以及 Score 的 Case、Metric、
  Evaluator Name/Version 均为非空字段。

这使核心 Eval 保持 8 张表，同时避免为了少一次查询复制 Trace、报告、Token 和时延事实。

## 13. 当前项目仍需补充的数据

1. Coverage Judge 输出 Criterion 级结果；
2. Citation Judge 输出 Claim 级结果，并读取真实 Evidence/Snapshot；
3. Reviewer Gap 增加稳定 Gap ID；
4. 每轮保存累计 Evidence Snapshot，或离线生成 Shadow Report；
5. ClaimVerifier 前保存 `report_pre_verification`；
6. 缺少输入时输出 `not_evaluable`，不能默认通过。

## 14. 推荐实施顺序

### Phase 1：先打通 Criterion 级结果

- Coverage Eval 输出 Criterion 明细；
- Citation Eval 输出 Claim 明细；
- 实现 Intent、Plan、Evidence、Final 的 Criterion Trace。

完成后即可定位 Scope、Supervisor、Researcher/Search、Report 的主要问题。

### Phase 2：实现 Reviewer 单次链路评价

- 外部 Gap vs Reviewer Gap；
- Reviewer Gap → Next Plan；
- Next Plan → New Evidence；
- Gap Closure；
- 每轮 Evidence Readiness；
- Reviewer 和下一轮 Token。

### Phase 3：实现报告机制前后比较

- Best Draft vs Synthesis；
- Section Draft vs Revision；
- Revision 集合 vs Merge；
- Pre-Verification vs Final。

### Phase 4：实现 Reviewer 配对消融

```text
Round 1 Stop
Generic Round 2
Reviewer-guided Round 2
```

计算 Reviewer 指导的真实增量收益和成本。

### Phase 5：校准与稳定性验证

- 使用人工标注校准 Judge；
- 固定 Evaluator Prompt/Model/Version；
- 对随机运行做重复实验；
- 报告均值、方差和 Case 级差异；
- 检查过程诊断是否能指导真实 Agent 修改。

## 15. 最终目标

这套 Eval 最终不是为了回答：

```text
Agent 得了多少分？
```

而是为了回答：

```text
最终报告哪里不好？
对应哪个 Criterion 或 Claim？
这个问题最早在哪个过程节点出现？
应该修改哪个 Agent、Prompt、路由或机制？
修改后是否真的改善了结果？
改善是否值得额外成本？
```

最终形成：

```text
最终问题
→ Criterion/Claim
→ 第一个失败节点
→ 对应 Agent/Mechanism
→ 修复建议
→ 配对实验验证
```

## 16. Eval 迭代过程如何沉淀

每次正式 Eval 完成后，都以 `experiment_id` 为主键生成一对记录：

- `backend-python/evals/iterations/<experiment_id>.json`：供脚本和后续分析读取；
- `backend-python/evals/iterations/<experiment_id>.md`：供人工复盘；
- `backend-python/evals/iterations/index.json`：轻量索引。

记录固定回答五个问题：

1. 跑了什么：Dataset、Item、档位、Run ID、状态和 Token；
2. 出了什么问题：根因码、受影响 Case 和 Agent 模块；
3. 怎么看出来：保留触发诊断的具体 Eval 指标，不只写自然语言结论；
4. 怎么改的：关联问题码、修改摘要和文件；
5. 改完是否正常：测试、定向复评、前后指标以及 `passed/partial/failed` 状态。

`run_live_pilot.py` 在生成 Eval JSON/Markdown 后自动建立或更新记录。重复生成诊断不会覆盖
已经填写的修改和复验信息。对既有 Run 的引用修复可使用
`evals.backfill_claim_manifest`，然后用 `evals.validate_citation_gate` 按 Hard Gate 的确定性
指标口径复验；这类定向复验只验证引用链路，不应被描述为完整报告质量复评。

### 16.1 指标如何转成 Agent 优化建议

诊断层不新增一套评分，而是读取已经生成的结果指标和过程指标，通过显式规则完成：

```text
异常指标
→ 根因码
→ 可能出问题的 Agent 模块
→ 有针对性的优化建议
→ 同题复评验证
```

具体做法：

1. **指标是证据**：先记录失败指标、数值、受影响 Case 和过程产物，不能只写“报告不好”；
2. **组合判断根因**：结合结果和过程指标区分问题来源。例如报告事实质量较高，但
   `citation_traceability` 很低，优先判断为引用关联链路问题，而不是检索质量问题；
3. **映射 Agent 模块**：每个根因码固定对应最可能负责的模块。例如意图错误对应
   `ScopeAgent`，证据不足对应 `Researcher/SearchAgent`，引用关联错误对应
   `ReportAgent/ClaimManifestPersistence`；
4. **生成可执行建议**：建议必须指向具体 Prompt、路由、持久化字段或 Agent 机制，
   不能只写“继续优化”；
5. **修改后复评**：使用相同 Dataset Item、档位和 Evaluator 口径比较修改前后指标。
   全部恢复记为 `passed`，部分改善但仍有真实问题记为 `partial`，没有改善或出现回归记为
   `failed`。

例如：

```text
citation_traceability = 0
且 claim_factuality 较高
→ citation_claim_linkage_failure
→ ReportAgent / ClaimManifestPersistence
→ 修复 [n]、URL 与 Claim Manifest 的映射
→ 回填后重新计算 traceability 和 unsupported critical claim
```

这种方式使每条优化结论都能回到原始指标，也能在修改后明确判断问题是否真正解决。
