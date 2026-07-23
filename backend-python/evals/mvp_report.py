"""Deep Research Eval 单题端到端 MVP — 聚合与报告。

按规格 docs/deep-research-eval-mvp-single-case.md 第 10 节：
- ``aggregate``：把 5 个 evaluator 的 MetricResult 聚合成最终结构（hard gate +
  process_eval + diagnosis + cost）。
- ``write_json`` / ``write_markdown``：输出 JSON 与 Markdown 报告。
- 每个结论可回溯到 claim_id / evidence_id / review gap。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.mvp_context import MvpEvalContext
from evals.schemas import MetricResult


def _metrics_by_name(metrics: list[MetricResult]) -> dict[str, MetricResult]:
    return {m.metric_name: m for m in metrics}


def _score(metrics: list[MetricResult], name: str, default: float | None = None) -> float | None:
    m = _metrics_by_name(metrics).get(name)
    return (m.score_value if m and m.score_value is not None else default)


def _detail(ctx: MvpEvalContext, intent: list[MetricResult], claims: list[MetricResult]) -> dict[str, Any]:
    """聚合 per-claim / per-evidence / gap 追溯信息。"""
    by_name = _metrics_by_name(claims)
    citation = by_name.get("citation_correctness")
    per_claim = (citation.details or {}).get("per_claim", []) if citation and citation.details else []
    intent_recall = _metrics_by_name(intent).get("intent_constraint_recall")
    missing_constraints = []
    if intent_recall and intent_recall.details:
        missing_constraints = intent_recall.details.get("missing_constraints", [])
    return {
        "per_claim": per_claim,
        "evidence_ids": [e.get("evidence_id") for e in ctx.evidence],
        "source_ids": [s.get("source_id") for s in ctx.sources],
        "blocking_gaps": ctx.review.get("blocking_gaps", []),
        "missing_constraints": missing_constraints,
    }


def aggregate(
    ctx: MvpEvalContext,
    intent: list[MetricResult],
    review: list[MetricResult],
    claims: list[MetricResult],
    consistency: list[MetricResult],
    verifier: list[MetricResult],
) -> dict[str, Any]:
    """规格第 10 节最终聚合。"""
    # required_point_coverage：来自 Intent recall（覆盖比例）
    required_point_coverage = _score(intent, "intent_constraint_recall", 0.0) or 0.0
    # gap 是否关闭影响最终覆盖率
    gap_closure = _score(review, "review_gap_closure_rate", 0.0) or 0.0
    effective_coverage = min(required_point_coverage, 1.0)

    citation_correctness = _score(claims, "citation_correctness", 0.0) or 0.0
    unsupported_critical = int(_score(claims, "unsupported_critical_claim_count", 0.0) or 0.0)

    # Hard Gate：critical 项不达标即 failed
    hard_gate_failed = (
        effective_coverage < 1.0
        or unsupported_critical > 0
        or citation_correctness < 1.0
    )
    hard_gate = "failed" if hard_gate_failed else "passed"
    failure_codes: list[str] = []
    if effective_coverage < 1.0:
        failure_codes.append("missing_required_points")
    if unsupported_critical > 0:
        failure_codes.append("unsupported_critical_claim")
    if citation_correctness < 1.0:
        failure_codes.append("citation_incorrect")

    # process_eval：各 evaluator 的关键指标
    def _proc(metrics: list[MetricResult]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for m in metrics:
            out[m.metric_name] = {
                "value": m.score_value,
                "passed": m.passed,
                "label": m.label_value,
                "reason": m.reason,
            }
        return out

    # diagnosis：由各 evaluator finding 汇总，对应规格第 2 节 6 个预置问题
    diagnosis: list[str] = []
    intent_missing = _metrics_by_name(intent).get("intent_constraint_recall")
    if intent_missing and intent_missing.details and intent_missing.details.get("missing_constraints"):
        diagnosis.append(f"Intent 漏掉安全约束：{intent_missing.details.get('missing_constraints')}")
    if (_score(review, "review_gap_recall", 0.0) or 0.0) >= 1.0 and (_score(review, "review_gap_closure_rate", 0.0) or 0.0) < 1.0:
        diagnosis.append("Reviewer 正确发现安全 Gap，但最终报告未使用新增 Evidence")
    if unsupported_critical > 0:
        diagnosis.append("最终报告存在 Unsupported Critical Claim")
    consistency_after = _score(consistency, "consistency_contradictions_after", 0.0)
    consistency_before = _score(consistency, "consistency_contradictions_before", 0.0)
    if (consistency_before or 0) > 0 and (consistency_after or 0) == 0:
        diagnosis.append("Consistency 前后矛盾已消除")
    verifier_recall = _score(verifier, "verifier_unsupported_detection_recall", 0.0) or 0.0
    correction = _score(verifier, "verifier_claim_correction_rate", 0.0) or 0.0
    if verifier_recall >= 1.0:
        diagnosis.append(f"ClaimVerifier 正确发现并标记 Unsupported Claim（修正率={correction:.2f}）")

    cost = {
        "input_tokens": ctx.run.get("input_tokens", 0),
        "output_tokens": ctx.run.get("output_tokens", 0),
        "reviewer_tokens": ctx.run.get("reviewer_tokens", 1800),
    }

    return {
        "case_id": ctx.case.get("case_id"),
        "context_complete": ctx.completeness.get("evaluable", False),
        "completeness": ctx.completeness,
        "result_eval": {
            "hard_gate": hard_gate,
            "failure_codes": failure_codes,
            "required_point_coverage": effective_coverage,
            "citation_correctness": citation_correctness,
            "unsupported_critical_claim_count": unsupported_critical,
        },
        "process_eval": {
            "intent": _proc(intent),
            "review": _proc(review),
            "claims": _proc(claims),
            "consistency": _proc(consistency),
            "claim_verifier": _proc(verifier),
        },
        "diagnosis": diagnosis,
        "cost": cost,
        "trace": _detail(ctx, intent, claims),
    }


def write_json(result: dict[str, Any], output_dir: str | Path) -> Path:
    """写 JSON 结果到 output_dir/result.json。"""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "result.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    return path


def render_report(result: dict[str, Any], ctx: MvpEvalContext) -> str:
    """规格第 10 节 Markdown 报告（8 段）。"""
    lines: list[str] = []
    lines.append("# Deep Research Eval 单题端到端 MVP 报告\n")
    lines.append(f"**Case ID**: {result.get('case_id')}\n")

    # 1. Case / Task Spec
    lines.append("## Case / Task Spec\n")
    case = ctx.case
    lines.append(f"- Query: {case.get('query')}")
    lines.append(f"- Task Type: {case.get('task_type')}  |  Language: {case.get('language')}  |  As-of: {case.get('as_of_date')}")
    rp = "、".join(f"{p.get('id')}(w={p.get('weight')})" for p in case.get("required_points", []) if isinstance(p, dict))
    lines.append(f"- Required Points: {rp}")
    lines.append(f"- Explicit Constraints: {case.get('explicit_constraints')}")
    lines.append(f"- Critical Facts: {case.get('critical_facts')}")
    lines.append(f"- Forbidden Claims: {case.get('forbidden_claims')}\n")

    # 2. EvalContext 完整性
    lines.append("## EvalContext 完整性\n")
    comp = result.get("completeness", {})
    lines.append(f"- evaluable: **{comp.get('evaluable')}**")
    for k in ["case_available", "intent_available", "review_available", "claims_available",
              "evidence_available", "consistency_pre_post_available", "verifier_pre_post_available"]:
        lines.append(f"  - {k}: {comp.get(k)}")
    if comp.get("missing"):
        lines.append(f"- missing: {comp.get('missing')}")
    lines.append("")

    # 3. Intent
    lines.append("## Intent\n")
    intent = result["process_eval"]["intent"]
    lines.append(f"- constraint_recall: {intent.get('intent_constraint_recall', {}).get('value')}")
    lines.append(f"- constraint_precision: {intent.get('intent_constraint_precision', {}).get('value')}")
    lines.append(f"- routing_accuracy: {intent.get('intent_routing_accuracy', {}).get('value')}")
    lines.append(f"- passed: {intent.get('intent_passed', {}).get('passed')}")
    lines.append(f"- reason: {intent.get('intent_passed', {}).get('reason')}\n")

    # 4. Review
    lines.append("## Review\n")
    review = result["process_eval"]["review"]
    for name in ["review_gap_precision", "review_gap_recall", "review_gap_closure_rate",
                 "review_new_evidence_count", "review_quality_delta", "reviewer_token_cost"]:
        m = review.get(name, {})
        lines.append(f"- {name}: {m.get('value')}  |  {m.get('reason')}")
    lines.append(f"- finding: {review.get('review_finding', {}).get('label')}\n")

    # 5. Claims/Citations/Evidence
    lines.append("## Claims / Citations / Evidence\n")
    claims = result["process_eval"]["claims"]
    lines.append(f"- total_claims: {claims.get('claim_total_claims', {}).get('value')}")
    for s in ["supported", "partially_supported", "unsupported", "contradicted", "not_verifiable"]:
        lines.append(f"- {s}: {claims.get(f'claim_{s}_claims', {}).get('value')}")
    lines.append(f"- citation_completeness: {claims.get('citation_completeness', {}).get('value')}")
    lines.append(f"- citation_correctness: {claims.get('citation_correctness', {}).get('value')}")
    lines.append(f"- unsupported_critical_claim_count: {claims.get('unsupported_critical_claim_count', {}).get('value')}")
    per_claim = result.get("trace", {}).get("per_claim", [])
    lines.append("\n| claim_id | verdict | mapped | evidence_id |")
    lines.append("|---|---|---|---|")
    for c in per_claim:
        lines.append(f"| {c.get('claim_id')} | {c.get('verdict')} | {c.get('citation_mapped')} | {c.get('citation_evidence_id')} |")
    lines.append("")

    # 6. Consistency 前后
    lines.append("## Consistency 前后\n")
    cons = result["process_eval"]["consistency"]
    for name in ["consistency_issues_reported", "consistency_issues_resolved",
                 "consistency_contradictions_before", "consistency_contradictions_after",
                 "consistency_claim_retention", "consistency_citation_retention",
                 "consistency_new_regressions"]:
        m = cons.get(name, {})
        lines.append(f"- {name}: {m.get('value')}  |  {m.get('reason')}")
    lines.append("")

    # 7. ClaimVerifier
    lines.append("## ClaimVerifier\n")
    ver = result["process_eval"]["claim_verifier"]
    for name in ["verifier_checked_claims", "verifier_unsupported_detection_precision",
                 "verifier_unsupported_detection_recall", "verifier_claim_correction_rate",
                 "verifier_false_warning_count", "verifier_coverage_regression"]:
        m = ver.get(name, {})
        lines.append(f"- {name}: {m.get('value')}  |  {m.get('reason')}")
    lines.append("")

    # 8. Hard Gate
    lines.append("## Hard Gate\n")
    re_val = result["result_eval"]
    lines.append(f"- hard_gate: **{re_val.get('hard_gate')}**")
    lines.append(f"- failure_codes: {re_val.get('failure_codes')}")
    lines.append(f"- required_point_coverage: {re_val.get('required_point_coverage')}")
    lines.append(f"- citation_correctness: {re_val.get('citation_correctness')}")
    lines.append(f"- unsupported_critical_claim_count: {re_val.get('unsupported_critical_claim_count')}\n")

    # 最终诊断
    lines.append("## 最终诊断\n")
    for i, d in enumerate(result.get("diagnosis", []), 1):
        lines.append(f"{i}. {d}")
    lines.append("")
    lines.append("## Cost\n")
    cost = result.get("cost", {})
    lines.append(f"- input_tokens: {cost.get('input_tokens')}  |  output_tokens: {cost.get('output_tokens')}  |  reviewer_tokens: {cost.get('reviewer_tokens')}")

    return "\n".join(lines)


def write_markdown(result: dict[str, Any], ctx: MvpEvalContext, output_dir: str | Path) -> Path:
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "report.md"
    md = render_report(result, ctx)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    return path
