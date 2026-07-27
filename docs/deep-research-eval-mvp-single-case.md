# Deep Research Eval 单题端到端 MVP

> 交给 GLM 实现的可展示版本：1 道题、1 个 EvalContext、1 次完整评价流程。

## 1. 目标与边界

完成后，一条命令得到：

~~~text
固定问题
→ EvalContext
→ Intent
→ Reviewer
→ Claim/Citation
→ Consistency
→ ClaimVerifier
→ 最终 JSON + Markdown 报告
~~~

本 MVP 使用离线 Fixture，不重新运行 Tavily、真实 Research Pipeline 或生产 Agent。暂不做多题统计、三档对比、在线抽样和数据库新增表。目的是先证明单题 Eval 的端到端链路成立。

## 2. 固定问题与基准

问题：

~~~text
对比 RAG 与 Fine-tuning 在企业知识问答场景的优劣，并给出选型建议。
~~~

文件：

~~~text
backend-python/evals/fixtures/mvp_single_case.json
~~~

Fixture 必须包含 Task Spec：

~~~json
{
  "case_id": "tech_comparison_demo_001",
  "query": "对比 RAG 与 Fine-tuning 在企业知识问答场景的优劣，并给出选型建议。",
  "task_type": "tech_comparison",
  "language": "zh-CN",
  "as_of_date": "2026-07-01",
  "required_points": [
    {"id": "cost", "description": "比较训练、推理、更新和维护成本", "weight": 2},
    {"id": "freshness", "description": "比较知识更新方式和时效性", "weight": 3},
    {"id": "security", "description": "比较数据安全、权限和部署风险", "weight": 2},
    {"id": "recommendation", "description": "根据企业场景给出选型建议", "weight": 3}
  ],
  "explicit_constraints": {
    "require_citations": true,
    "audience": "enterprise_technical_decision_maker"
  },
  "critical_facts": [
    {"id": "fact_rag_freshness", "description": "RAG 可通过更新外部知识库改善知识时效性"}
  ],
  "forbidden_claims": [
    "Fine-tuning 可以保证模型准确记住所有企业知识"
  ]
}
~~~

Fixture 故意设置以下问题，便于展示诊断：

1. Intent 漏掉安全约束。
2. Plan 规划了安全任务，但最终报告未使用安全 Evidence。
3. Reviewer 正确发现安全 Gap，下一轮新增了安全 Evidence。
4. 最终报告包含一个 Unsupported Claim。
5. Consistency 前有一个跨章节矛盾，后报告消除。
6. ClaimVerifier 正确发现并标记 Unsupported Claim。

Fixture 中可以有独立的 gold_annotations，作为 MVP 校准参照；生产版本不得把 Agent 自己的判断当作真值。

---

## 3. EvalContext

新增文件：

~~~text
backend-python/evals/mvp_context.py
~~~

建议结构：

~~~python
@dataclass
class MvpEvalContext:
    case: dict[str, Any]
    run: dict[str, Any]
    intent: dict[str, Any]
    plan: dict[str, Any]
    tool_calls: list[dict[str, Any]]
    context_nodes: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    review: dict[str, Any]
    rounds: list[dict[str, Any]]
    reports: dict[str, str]
    claims: list[dict[str, Any]]
    claim_verifier: list[dict[str, Any]]
    gold: dict[str, Any]
    completeness: dict[str, Any]
~~~

字段和生产数据映射：

| Context 字段 | 保存内容 | MVP 来源 | 生产来源 |
|---|---|---|---|
| case | Query、Required Points、Critical Facts、约束 | Fixture | eval_dataset_item |
| run | Run ID、状态、Token、时延、版本 | Fixture | research_run |
| intent | Scope 的目标、约束、路由 | Fixture | brief / Scope Artifact |
| plan | Plan、Work Item、优先级、状态 | Fixture | planning_round / work_item |
| tool_calls | 工具、参数、结果、错误、重试 | Fixture | Tool Span / workflow_event |
| context_nodes | L0/L1/L2、路径、内容 | Fixture | research_context_node/edge |
| sources | URL、来源类型、时间、快照 | Fixture | source_snapshot Artifact |
| evidence | Evidence 文本、Claim、Source ID | Fixture | Evidence Node / Ledger |
| review | Gap、分数、nextAction | Fixture | round_review / decision_log |
| rounds | 每轮新增来源、Evidence、Gap、Token | Fixture | planning_round / stage_usage |
| reports | Consistency、Verifier 前后报告、Final | Fixture | report Artifacts |
| claims | Claim、Citation、Evidence ID | Fixture | claim_manifest |
| claim_verifier | Verdict、理由、后处理结果 | Fixture | claim_verification Artifact |

Context Builder 执行顺序：

~~~text
读取 Fixture 或 EvalCaseRun
→ 读取 Task Spec
→ 读取 Run
→ 读取 Intent、Plan、Tool、Round、Review
→ 读取 L0/L1/L2、Source、Evidence
→ 读取 Reports、Claims、Verifier
→ 建立 Claim→Evidence→Source、Gap→Round 关联
→ 执行 Context Completeness Check
~~~

完整性检查至少输出：

~~~json
{
  "case_available": true,
  "intent_available": true,
  "review_available": true,
  "claims_available": true,
  "evidence_available": true,
  "consistency_pre_post_available": true,
  "verifier_pre_post_available": true,
  "missing": [],
  "evaluable": true
}
~~~

缺失字段时，相关指标为 not_evaluable，不得默认通过。

---

## 4. 单题 Runner

新增文件：

~~~text
backend-python/evals/mvp_single_case.py
backend-python/evals/mvp_evaluators.py
backend-python/evals/mvp_report.py
~~~

运行命令：

~~~bash
cd backend-python
python -m evals.mvp_single_case \
  --fixture evals/fixtures/mvp_single_case.json \
  --output evals/mvp_output
~~~

主流程：

~~~python
raw = load_fixture(path)
ctx = build_context(raw)
check_completeness(ctx)

intent = evaluate_intent(ctx)
review = evaluate_review(ctx)
claims = evaluate_claims(ctx)
consistency = evaluate_consistency(ctx)
verifier = evaluate_claim_verifier(ctx)

result = aggregate(ctx, intent, review, claims, consistency, verifier)
write_json(result)
write_markdown(render_report(result))
~~~

固定顺序：

~~~text
Context Completeness
→ Intent
→ Review
→ Claim
→ Consistency
→ ClaimVerifier
→ Aggregate
~~~

## 5. Intent Evaluator

输入：

~~~text
Task Spec 的 constraints、required_points
Fixture 中的 intent
~~~

规则比较：

- 任务类型是否正确。
- 语言、受众和引用要求是否正确。
- Required Points 是否遗漏。
- 是否错误增加用户没有提出的限制。
- 路由是否正确。

输出示例：

~~~json
{
  "metric_group": "intent",
  "constraint_precision": 1.0,
  "constraint_recall": 0.75,
  "missing_constraints": ["security"],
  "routing_accuracy": 1.0,
  "passed": false,
  "reason": "Intent 漏掉安全约束"
}
~~~

## 6. Review Evaluator

输入：

~~~text
review.blocking_gaps
review.next_action
rounds
required_points
final_report
~~~

评价：

1. Reviewer Gap 是否等于外部 Eval 发现的缺失项。
2. 下一轮是否创建对应 Work Item。
3. 是否产生相关 Evidence。
4. 最终报告是否关闭 Gap。
5. 新增 Token 后质量是否提升。

输出示例：

~~~json
{
  "metric_group": "review",
  "gap_precision": 1.0,
  "gap_recall": 1.0,
  "gap_closure_rate": 0.0,
  "new_evidence_count": 2,
  "quality_delta": 0.0,
  "reviewer_token_cost": 1800,
  "finding": "Reviewer 找对问题，但最终报告未使用新增 Evidence"
}
~~~

## 7. Claim/Citation Evaluator

输入：

~~~text
claims
evidence
sources
final_report
~~~

逐 Claim 判断：

- 是否需要引用。
- 是否存在 Citation。
- Citation 是否映射到 Evidence。
- Evidence 是否支持 Claim。
- 是否为 Critical Claim。

标签：

~~~text
supported
partially_supported
unsupported
contradicted
not_verifiable
~~~

输出示例：

~~~json
{
  "metric_group": "claim",
  "total_claims": 3,
  "supported_claims": 1,
  "unsupported_claims": 1,
  "contradicted_claims": 1,
  "citation_completeness": 0.67,
  "citation_correctness": 0.33,
  "unsupported_critical_claim_count": 1
}
~~~

Fixture 可以用 gold_support 展示流程；生产版本要换成独立 Judge 或人工标注。

## 8. Consistency Evaluator

输入：

~~~text
pre_consistency_report
consistency_messages
post_consistency_report
~~~

MVP 使用 Before/After：

- 修改前矛盾数量。
- 修改后矛盾数量。
- 问题解决数量。
- Claim 保留率。
- Citation 保留率。
- 是否产生新回归。

输出示例：

~~~json
{
  "metric_group": "consistency",
  "issues_reported": 1,
  "issues_resolved": 1,
  "contradictions_before": 1,
  "contradictions_after": 0,
  "claim_retention": 1.0,
  "citation_retention": 1.0,
  "new_regressions": 0
}
~~~

MVP 不重新调用 Consistency Agent，而评价已有前后产物。

## 9. ClaimVerifier Evaluator

输入：

~~~text
claims
claim_verifier verdicts
pre_verification_report
post_verification_report
~~~

评价：

1. 是否发现预置 Unsupported Claim。
2. Verdict 是否正确。
3. 后报告是否披露、删除或修正该 Claim。
4. 是否误删其他正确 Claim。

输出示例：

~~~json
{
  "metric_group": "claim_verifier",
  "checked_claims": 3,
  "unsupported_detection_precision": 1.0,
  "unsupported_detection_recall": 1.0,
  "claim_correction_rate": 1.0,
  "false_warning_count": 0,
  "coverage_regression": 0.0
}
~~~

---

## 10. 最终聚合和报告

不要只输出一个总分，输出：

~~~json
{
  "case_id": "tech_comparison_demo_001",
  "context_complete": true,
  "result_eval": {
    "hard_gate": "failed",
    "required_point_coverage": 0.75,
    "citation_correctness": 0.33,
    "unsupported_critical_claim_count": 1
  },
  "process_eval": {
    "intent": {},
    "review": {},
    "consistency": {},
    "claim_verifier": {}
  },
  "diagnosis": [
    "Intent 漏掉安全约束",
    "Reviewer 正确发现安全 Gap",
    "第二轮产生了安全 Evidence，但最终报告未使用",
    "最终报告存在 Unsupported Critical Claim"
  ],
  "cost": {
    "input_tokens": 12000,
    "output_tokens": 3000,
    "reviewer_tokens": 1800
  }
}
~~~

Markdown 报告必须包含：

~~~text
Case / Task Spec
EvalContext 完整性
Intent
Review
Claims/Citations/Evidence
Consistency 前后
ClaimVerifier
Hard Gate
最终诊断
~~~

每个结论都要能回溯到 Claim ID、Evidence ID、Review Gap 或 Artifact ID。

---

## 11. 文件和验收标准

建议新增：

~~~text
backend-python/evals/fixtures/mvp_single_case.json
backend-python/evals/mvp_context.py
backend-python/evals/mvp_evaluators.py
backend-python/evals/mvp_single_case.py
backend-python/evals/mvp_report.py
backend-python/evals/mvp_output/.gitkeep
~~~

验收：

1. 一条命令可运行单题 Eval。
2. 能输出完整 EvalContext 摘要和缺失字段。
3. 能指出 Intent 遗漏的安全约束。
4. 能说明 Reviewer Gap 是否准确、下一轮是否关闭。
5. 能逐条输出至少 3 个 Claim 的支持状态。
6. 能输出 Consistency 前后矛盾和保留率。
7. 能输出 ClaimVerifier 检测、修正和误报。
8. 能输出最终 Hard Gate 和失败原因。
9. 结果包含 Token/成本字段。
10. 能回溯到 Claim、Evidence、Gap 或 Artifact。
11. 不依赖数据库、Tavily 或真实 LLM。
12. 至少一个端到端测试验证关键结论。

## 12. 交给 GLM 的任务描述

请在不修改生产研究流程的前提下，实现一个单题离线 Eval MVP：创建上述 Fixture；实现 Context Builder、Completeness Check、Intent、Review、Claim、Consistency、ClaimVerifier 五个 Evaluator；按固定顺序执行；输出 JSON 和 Markdown；提供运行命令和端到端测试；不要求重新搜索、不要求真实 LLM、不要求新增数据库表。

MVP 的完成标准不是分数看起来很高，而是能够清楚展示：

~~~text
哪里识别正确
哪里识别错误
Reviewer 做了什么判断
Evidence 是否支持 Claim
Consistency 是否减少矛盾
ClaimVerifier 是否发现并修正问题
最终报告为什么通过或失败
~~~
