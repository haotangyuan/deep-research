# Deep Research Eval 最小 MVP 实施方案

> 适用项目：`/Users/admin/study/deep-research/backend-python`  
> 范围：只实现可运行、可比较、可追溯、可人工校准的最小 Eval 闭环。  
> 不建设完整 Eval 平台，不包含完整生产级可观测重构。

## 1. MVP 目标

MVP 要解决的问题不是“给报告打一个总分”，而是：

```text
固定测试题
→ 执行真实 Deep Research Workflow
→ 保存报告和证据
→ 确定性检查
→ Claim/Citation 级评价
→ 人工校准
→ 与 Baseline 比较
→ 通过 Trace 定位退化原因
```

完成后应支持：

```bash
python -m evals.runner \
  --dataset evals/datasets/deep_research_v1.jsonl \
  --experiment ultra-baseline-v1
```

输出：

```text
evals/results/ultra-baseline-v1/
├── summary.json
├── summary.md
├── cases.jsonl
└── artifacts/
    └── <case_id>/
        ├── report.md
        ├── sources.json
        ├── claims.json
        └── evaluation.json
```

MVP 不做：

- 不建设独立 Web 后台。
- 不建设线上实时 Eval 服务。
- 不训练 Reward Model。
- 不自动修改生产 Prompt。
- 不让 Eval 失败影响正常用户任务。
- 不把所有指标压成一个总分。

---

## 2. MVP 评估内容

### 2.1 最终报告质量

| 指标 | 含义 | 实现 |
|---|---|---|
| `workflow_completed` | 工作流完成且报告非空 | 确定性 |
| `citation_parse_rate` | 报告引用是否可解析 | 确定性 |
| `citation_traceability` | 引用能否映射到本次证据 | 确定性 |
| `citation_completeness` | 应引用事实是否有引用 | Claim 提取 + 规则 |
| `citation_correctness` | 引用内容是否支持事实 | 独立 LLM Judge |
| `required_point_coverage` | 是否覆盖题目核心要求 | 独立 LLM Judge |
| `critical_error_count` | 是否存在关键事实错误 | Judge + 人工复核 |

第一版不把文风、创新性和排版作为核心 Gate。

### 2.2 工作流最小可靠性

```text
technical_completion_rate
task_success_rate
degraded_rate
duration
input_tokens
output_tokens
```

定义：

```text
technical_completion_rate
= 正常产生报告的运行数 / 全部运行数

task_success_rate
= 通过全部质量 Gate 的运行数 / 全部运行数
```

`COMPLETED` 但引用不可信，只算技术完成，不能算任务成功。

---

## 3. MVP 质量 Gate

启动阈值：

```text
workflow_completed = true
citation_parse_rate = 1.00
citation_traceability >= 0.95
citation_completeness >= 0.80
citation_correctness >= 0.80
required_point_coverage >= 0.75
critical_error_count = 0
```

全部通过才设置：

```text
eval.gate.passed = true
```

这些是 MVP 启动阈值，不是行业标准。应在人工标注后校准。

失败原因使用枚举：

```text
WORKFLOW_NOT_COMPLETED
REPORT_EMPTY
CITATION_PARSE_FAILED
CITATION_NOT_TRACEABLE
CITATION_INCOMPLETE
CITATION_UNSUPPORTED
REQUIRED_POINT_MISSING
CRITICAL_FACT_ERROR
EVALUATOR_FAILED
```

`EVALUATOR_FAILED` 不能默认当成报告通过或不通过。

---

## 4. 首批 Dataset

首批创建 15 道题：

| 类型 | 数量 | 验证能力 |
|---|---:|---|
| 短答案事实检索 | 3 | 搜索和事实定位 |
| 技术/产品比较 | 4 | 多维覆盖和官方来源 |
| 市场/行业分析 | 3 | 数据口径、日期和来源质量 |
| 时效性问题 | 2 | as-of-date 和新鲜度 |
| 信息冲突或不足 | 2 | 不确定性披露 |
| 长报告综合 | 1 | 多来源综合和引用完整性 |

文件：

```text
backend-python/evals/datasets/deep_research_v1.jsonl
```

示例：

```json
{
  "id": "tech-compare-001",
  "input": {
    "query": "比较 A 和 B 的核心架构、适用场景和限制",
    "language": "zh-CN",
    "as_of_date": "2026-07-01",
    "budget": "high",
    "workflow_mode": "ultra"
  },
  "task_type": "tech_comparison",
  "required_points": [
    {
      "id": "architecture",
      "description": "分别说明 A 和 B 的核心架构差异",
      "weight": 3
    },
    {
      "id": "limitations",
      "description": "说明双方限制和不适用场景",
      "weight": 2
    }
  ],
  "reference_facts": [
    {
      "id": "fact-001",
      "fact": "一个稳定且可核验的关键事实",
      "importance": "critical",
      "acceptable_sources": ["https://official.example.com/doc"]
    }
  ],
  "forbidden_claims": [],
  "required_source_types": ["official"],
  "tags": ["zh", "comparison"]
}
```

要求：

- 每题必须有 `as_of_date`。
- 开放式任务用 `required_points`，不依赖唯一参考作文。
- 只给稳定事实设置 `reference_facts`。
- Dataset 进入 Git，版本可追踪。
- 不包含用户隐私和生产敏感数据。

15 题用于打通闭环和发现明显回归，不能用于宣称系统绝对准确率。

---

## 5. 运行链路

```text
读取 Dataset Item
→ 调用现有 Workflow
→ 收集 Report、Evidence、Source、Status、Token、Duration、IDs
→ 确定性 Citation 检查
→ Claim Extractor
→ Citation Judge
→ Coverage Judge
→ 计算 Gate
→ 输出 Case 和 Experiment 报告
```

所有步骤使用同一个：

```text
eval_run_id
dataset_item_id
experiment_id
research_id
run_id
trace_id
```

单个 Case 失败不得中断整个 Experiment。

---

## 6. 代码结构

```text
backend-python/evals/
├── __init__.py
├── runner.py
├── schemas.py
├── workflow_adapter.py
├── artifact_collector.py
├── evaluators/
│   ├── __init__.py
│   ├── deterministic.py
│   ├── claim_extractor.py
│   ├── citation_judge.py
│   └── coverage_judge.py
├── prompts/
│   ├── claim_extractor_v1.txt
│   ├── citation_judge_v1.txt
│   └── coverage_judge_v1.txt
├── datasets/
│   └── deep_research_v1.jsonl
├── baselines/
│   └── ultra_v1.json
└── results/
```

### 6.1 `schemas.py`

定义：

```text
EvalDatasetItem
RequiredPoint
ReferenceFact
EvalRunConfig
RunArtifact
ExtractedClaim
CitationEvaluation
CoverageEvaluation
EvalCaseResult
EvalExperimentSummary
```

核心 Claim：

```python
class ExtractedClaim(BaseModel):
    claim_id: str
    text: str
    section: str | None
    importance: Literal["critical", "major", "minor"]
    requires_citation: bool
    citation_markers: list[str]
    citation_urls: list[str]
```

核心 Artifact：

```python
class RunArtifact(BaseModel):
    dataset_item_id: str
    research_id: str
    run_id: str
    trace_id: str | None
    status: str
    outcome: str
    report: str
    sources: list[SourceArtifact]
    duration_ms: int
    input_tokens: int
    output_tokens: int
    workflow_version: str
    prompt_version: str
    generator_model: str
```

### 6.2 `workflow_adapter.py`

- 将 Dataset Item 转换为现有 Research Service 输入。
- 创建真实研究任务并等待终态。
- 不复制 Pipeline 业务逻辑。
- 支持 workflow mode、budget 和 model。
- 单 Case 设置超时。
- 测试数据与用户生产数据隔离。

### 6.3 `artifact_collector.py`

收集：

- `ResearchSession` 状态、token 和时间。
- 最终 assistant report。
- `ResearchEvidenceLedger`。
- Context FS 的 evidence/source 节点。
- planning round 和 decision log 摘要。
- run/trace ID 与版本。

证据优先级：

```text
source raw/overview snapshot
> EvidenceItem.evidence_text
> evidence ledger snippet
> 只有 URL 和标题
```

Citation Judge 应尽量读取运行时 Source Snapshot，不能只看来源标题。

### 6.4 `deterministic.py`

实现：

1. 工作流状态和报告非空检查。
2. Markdown 编号引用和 Inline URL 解析。
3. URL 规范化和去重。
4. 悬空引用检查。
5. 引用是否存在于本次 Evidence/Context Source。
6. 内部路径、Prompt、密钥等泄漏检查。

实时 URL 访问失败只作为诊断，不直接判报告错误。网页可能反爬或临时下线，离线评价以运行时快照为准。

### 6.5 `claim_extractor.py`

- 将报告拆成最小可验证 Claim。
- 判断是否需要外部引用。
- 标记 critical/major/minor。
- 继承所在句子或段落的 Citation。
- 只做提取，不判断正确性。
- 保存 Prompt、Schema 和模型版本。

### 6.6 `citation_judge.py`

输入：

```text
claim
对应 evidence/source snapshot
as_of_date
```

输出：

```json
{
  "label": "supported | partially_supported | unsupported | contradicted | not_verifiable",
  "reason": "判断原因",
  "evidence_excerpt": "用于判断的证据片段",
  "confidence": 0.0
}
```

规则：

- 逐个 `claim-citation` 对评价。
- `not_verifiable` 不算 supported。
- JSON 错误或超时不默认给高分。
- Judge 尽量与生成模型使用不同模型族或版本。
- temperature 固定为 0。

### 6.7 `coverage_judge.py`

对每个 Required Point 返回：

```text
covered = 1
partially_covered = 0.5
missing = 0
```

计算：

```text
required_point_coverage
= Σ(point_weight × point_score) / Σ(point_weight)
```

返回对应的报告片段和判断理由，不让 Judge 只给整篇印象分。

### 6.8 `runner.py`

- 加载和校验 Dataset。
- 默认并发 1～2，控制成本。
- 执行 Workflow 和 Evaluator。
- 支持 `--case-id` 单题调试。
- 隔离单 Case 失败。
- 保存原始 Case 结果。
- 按 task type 聚合。
- 与 Baseline 做逐题 Diff。
- 生成 JSON 和 Markdown 报告。

---

## 7. Eval MVP 需要的可观测改造

这里只补 Eval 必需字段，不在 MVP 中建设完整生产可观测体系。

### 7.1 Research、Run、Trace 标识

增加：

```text
research.id
run.id
run.attempt
run.trigger
trace_id
```

定义：

- `research.id`：用户的一次研究会话，可跨 HITL 和恢复。
- `run.id`：一次连续后台执行，每次 retry/resume 新建。
- `run.attempt`：同一 Research 的执行序号。
- `trace_id`：OTel 因果链标识。

建议修改：

- `app/domain/state.py`：增加 run 字段。
- `app/application/pipeline.py`：每次连续执行初始化 Run。
- `app/infrastructure/observability.py`：根 Span 记录字段。

Eval 必须绑定具体 Run，不能只绑定 Research。

### 7.2 统一 Outcome 和 Fallback

记录：

```text
operation.outcome = success | degraded | failed | cancelled | waiting_user
fallback.used
fallback.type
fallback.reason
retry.count
error.type
```

重点覆盖：

- Reviewer 失败后的默认投票。
- Report Judge/Draft 失败后的 fallback。
- ReportSectionTeam 回退旧报告流程。
- 搜索和页面摘要局部失败。
- `state.status=FAILED` 但函数正常返回。

### 7.3 保存版本

Run Artifact 和根 Span 至少保存：

```text
workflow.version
workflow.mode
prompt.report.version
generator_model
judge_model
evaluator.version
```

推荐再保存 Scope、Researcher、Reviewer Prompt 版本。没有版本信息，就无法归因质量回归。

### 7.4 Token 和时延

保存：

```text
run.active_duration_ms
run.wall_duration_ms
gen_ai.usage.input_tokens
gen_ai.usage.output_tokens
search.count
round.count
```

验收时确认 AgentScope 原生 Span 和手动 Model Span没有重复统计 Token。

### 7.5 Eval 关联字段

Eval Runner 触发 Workflow 时增加：

```text
eval.enabled = true
eval.dataset.name
eval.dataset.version
eval.dataset.item.id
eval.experiment.id
```

这些只放低基数 ID。Reference Answer、Required Points 和 Judge 全文不写入 Span。

### 7.6 不阻塞 MVP 的可观测工作

暂时不要求：

- 独立 OTel Collector。
- 完整 Prometheus Metrics。
- Tail Sampling。
- 线上 SLO 和告警。
- 完整结构化日志平台。
- MySQL、Redis、SSE 容量看板。
- 线上自动 Eval 抽样。

这些属于生产可观测后续建设，不应阻塞 Eval 最小闭环。

---

## 8. Eval 与 Trace 的关联

```text
EvalExperiment
└─ DatasetItem
   └─ Research
      └─ Run
         ├─ Trace
         ├─ RunArtifact
         └─ EvalCaseResult
```

Trace 只保存摘要：

```text
eval.gate.passed
eval.citation.traceability
eval.citation.completeness
eval.citation.correctness
eval.required_point.coverage
eval.critical_error.count
```

Claim、Evidence Excerpt、Judge Reason 等大对象保存在 `evaluation.json` 或 Eval Store。

Eval 写回失败不得改变原 Workflow 状态。

---

## 9. 测试和人工校准

### 9.1 单元测试

覆盖：

- 编号引用和 Inline URL。
- 悬空引用。
- URL 规范化和重复 URL。
- Citation 能/不能映射 Evidence。
- 空报告。
- Claim Extractor 非法 JSON。
- Judge 超时、非法 Label、缺字段。
- Coverage 权重聚合。
- Gate 边界值。
- 单 Case 失败隔离。

### 9.2 Golden 报告

准备三份小报告：

1. 引用、证据和覆盖均正确，应通过。
2. URL 存在但内容不支持 Claim，应失败。
3. 内容流畅但漏掉 Required Point，应失败。

Golden 测试只验证 Evaluator，不调用真实 Workflow。

### 9.3 人工校准

从 15 题中选择 5 题，人工标注至少 50 个 Claim-Citation 对：

```text
supported
partially_supported
unsupported
contradicted
not_verifiable
```

计算 Judge 的 Precision、Recall、F1，并单独统计 Critical Error 漏检。

如果一致性不足，先修改 Rubric、拆分任务或更换 Judge，不能直接把自动分接入发布门禁。

---

## 10. 实施顺序

### Step 1：打通运行和 Artifact

- 定义 Schema。
- 建立 3 道 Smoke Dataset。
- 实现 Workflow Adapter。
- 实现 Artifact Collector。
- 补 Research/Run/Trace 和版本字段。

验收：三道题都能产生 Run Artifact，失败任务也保存错误信息。

### Step 2：确定性 Eval

- Citation Parser。
- Citation-to-Evidence 映射。
- 状态、空报告和泄漏检查。
- Gate Reason Code。

验收：不调用 Judge，也能识别空报告、悬空引用和不可追溯来源。

### Step 3：Claim 和 Citation Judge

- Claim Extractor。
- Citation Support Judge。
- Claim 级明细和聚合分。
- 保存 Judge 版本、失败和成本。

验收：Golden 报告中不支持 Claim 的引用可以被检出。

### Step 4：Coverage 和 Experiment Report

- Required Point 逐项评价。
- 计算 Task Success Rate。
- 按 Task Type 聚合。
- Baseline Diff。
- JSON/Markdown 报告。

验收：能够比较两个 Experiment 并展示逐题退化原因。

### Step 5：扩展到 15 题并人工校准

- 完成正式 v1 Dataset。
- 人工标注 5 题。
- 校准 Judge Prompt 和 Gate。
- 固化 `ultra_v1` Baseline。

验收：形成第一份 Baseline 报告和 Judge 一致性报告。

---

## 11. MVP 完成标准

- [ ] 存在版本化的 15 题 Dataset。
- [ ] 一条命令执行完整 Experiment。
- [ ] 每个 Case 保存报告、来源、Claim 和评价结果。
- [ ] Citation Parser 和 Evidence Mapping 有单元测试。
- [ ] 能检测“引用存在但不支持事实”。
- [ ] 能根据 Required Points 检测漏答。
- [ ] Eval 结果绑定 Research/Run/Trace。
- [ ] 保存 Workflow、Prompt、生成模型和 Judge 版本。
- [ ] 区分 Technical Completion 和 Task Success。
- [ ] 支持与 Baseline 逐题 Diff。
- [ ] 至少 5 题经过人工 Claim 级标注。
- [ ] 形成 Judge 与人工一致性报告。
- [ ] Eval 失败不影响其他 Case 或生产 Workflow。
- [ ] LLM Token 没有重复统计。

---

## 12. MVP 之后的演进

1. 同题运行 3 次，增加稳定性和方差指标。
2. 增加 LLM、Search、Redis、Checkpoint 故障注入。
3. Dataset 扩充到 50～100 题。
4. 对稳定题保存 Source Snapshot，降低网页漂移。
5. 报告生成阶段输出结构化 Claim-Citation Manifest。
6. 将生产失败样本脱敏后加入 Challenge Set。
7. 设置 Task Type 级发布回归门禁。
8. 最后建设线上抽样 Eval、标注平台和质量看板。

长期结构：

```text
final_report_manifest
  report_id
  claims[]
    claim_id
    claim_text
    importance
    section_id
    citations[]
      source_url
      source_path
      evidence_id
      evidence_excerpt
```

最小 MVP 的核心不是“让 LLM 给一个分”，而是建立可复现、可追溯、经过人工校准、能够指导工程决策的质量闭环。

