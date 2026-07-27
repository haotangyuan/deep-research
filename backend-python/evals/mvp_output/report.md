# Deep Research Eval 单题端到端 MVP 报告

**Case ID**: real_71630da4e306

## Case / Task Spec

- Query: 我想研究在企业知识问答场景下，RAG（检索增强生成）与 Fine-tuning（微调）两种技术的优劣对比，并基于分析给出选型建议。需要调查的具体维度包括：实现成本、数据需求、部署与维护难度、响应质量与准确性、可扩展性、实时更新能力、隐私与安全、场景适用性等。请优先参考近2-3年（2024-2026）的技术文档、对比实验、企业应用案例及行业最佳实践。
- Task Type: general  |  Language: zh-CN  |  As-of: 
- Required Points: 
- Explicit Constraints: {'require_citations': True, 'audience': 'enterprise_technical_decision_maker'}
- Critical Facts: []
- Forbidden Claims: []

## EvalContext 完整性

- evaluable: **False**
  - case_available: False
  - intent_available: True
  - review_available: True
  - claims_available: True
  - evidence_available: True
  - consistency_pre_post_available: False
  - verifier_pre_post_available: False
- missing: ['case', 'consistency_pre_post', 'verifier_pre_post']

## Intent

- constraint_recall: 1.0
- constraint_precision: 1.0
- routing_accuracy: 1.0
- passed: 1
- reason: Intent 约束齐全

## Review

- review_gap_precision: 0.0  |  gap precision=0.00
- review_gap_recall: 1.0  |  gap recall=1.00 actual_gaps=['可扩展性与实时更新能力维度仍缺乏官方量化基准（如高并发下的p99延迟、QPS、成本增量）', '缺少AWS、Azure、Google Cloud等云厂商官方的高并发压力测试报告（p99延迟、QPS对比）', '部分量化数据仍来自公司博客（Actian、Meilisearch等），权威性不足', '高并发延迟与可扩展性维度缺少任何云厂商或标准组织在1000并发、百万级文档库场景下的官方压力测试对比数据，仅有工具和定性分析']
- review_gap_closure_rate: 0.0  |  gap closure=0.00 closed=[]
- review_new_evidence_count: 0.0  |  为 gap 新增 evidence=0
- review_quality_delta: 0.0  |  MVP 占位 delta，生产用真实评分
- reviewer_token_cost: 1800.0  |  reviewer_tokens=1800
- finding: Reviewer 找对问题，但最终报告未使用新增 Evidence

## Claims / Citations / Evidence

- total_claims: 7.0
- supported: 4.0
- partially_supported: 0.0
- unsupported: 0.0
- contradicted: 0.0
- not_verifiable: 3.0
- citation_completeness: 0.0
- citation_correctness: 0.0
- unsupported_critical_claim_count: 0.0

| claim_id | verdict | mapped | evidence_id |
|---|---|---|---|
| claim-4583eea95158 | supported | False | None |
| claim-6195843f8e8a | not_verifiable | False | None |
| claim-697e5e3c5565 | not_verifiable | False | None |
| claim-7a1f0d1b599b | supported | False | None |
| claim-7e10e6812c2b | supported | False | None |
| claim-c9fd514722be | not_verifiable | False | None |
| claim-e8f90ab570f2 | supported | False | None |

## Consistency 前后

- consistency_issues_reported: 0.0  |  issues_reported=0
- consistency_issues_resolved: 0.0  |  issues_resolved=0
- consistency_contradictions_before: 0.0  |  contradictions_before=0
- consistency_contradictions_after: 0.0  |  contradictions_after=0
- consistency_claim_retention: 1.0  |  claim_retention=1.00
- consistency_citation_retention: 1.0  |  citation_retention=1.00
- consistency_new_regressions: 0.0  |  new_regressions=0

## ClaimVerifier

- verifier_checked_claims: 7.0  |  checked_claims=7
- verifier_unsupported_detection_precision: 1.0  |  detection precision=1.00
- verifier_unsupported_detection_recall: 1.0  |  detection recall=1.00 detected=['', 'claim-4583eea95158']
- verifier_claim_correction_rate: 1.0  |  correction_rate=1.00
- verifier_false_warning_count: 6.0  |  false_warning=6
- verifier_coverage_regression: 0.0  |  coverage_regression=0.00

## Hard Gate

- hard_gate: **failed**
- failure_codes: ['citation_incorrect']
- required_point_coverage: 1.0
- citation_correctness: 0.0
- unsupported_critical_claim_count: 0

## 最终诊断

1. Reviewer 正确发现安全 Gap，但最终报告未使用新增 Evidence
2. ClaimVerifier 正确发现并标记 Unsupported Claim（修正率=1.00）

## Cost

- input_tokens: 725305  |  output_tokens: 143298  |  reviewer_tokens: 1800