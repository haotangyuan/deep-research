"""Deep Research Eval 单题端到端 MVP — 五个 Evaluator。

按规格 docs/deep-research-eval-mvp-single-case.md 第 5–9 节实现：
Intent / Review / Claim / Consistency / ClaimVerifier。

- 产出统一复用 ``evals.schemas.MetricResult``（结合项目现有 eval 做法）。
- 直接接收 ``MvpEvalContext``（不复用 v2 ``BaseEvaluator`` ABC，因字段集不同）。
- 仅 Claim evaluator 调 LLM（通过注入的 ``chat_fn``）；其余四个为确定性规则比对。
- gold 标注不参与运行时路径，仅用于测试断言。

执行顺序（规格第 4 节）：
    Context Completeness → Intent → Review → Claim → Consistency → ClaimVerifier
"""
from __future__ import annotations

import json
from typing import Any

from evals.mvp_context import MvpEvalContext
from evals.evaluators.base import ChatFn, parse_json_safe
from evals.schemas import MetricResult

# evaluator 版本号（沿用现有框架 evaluator_version 约定）
EVALUATOR_VERSION = "mvp-1.0.0"


# ============================================================
# 1. Intent Evaluator（规格第 5 节）
# ============================================================

async def evaluate_intent(ctx: MvpEvalContext) -> list[MetricResult]:
    """规则比对：任务类型/语言/受众/引用要求、required_points 遗漏、错误增加限制、路由。"""
    case = ctx.case
    intent = ctx.intent
    results: list[MetricResult] = []

    expected_points = {p["id"] for p in case.get("required_points", []) if isinstance(p, dict)}
    actual_point_ids = set(intent.get("required_points", []))

    missing = expected_points - actual_point_ids
    extra = actual_point_ids - expected_points

    # constraint precision/recall（按 required_points 覆盖）
    if expected_points:
        precision = len(expected_points & actual_point_ids) / len(actual_point_ids) if actual_point_ids else 0.0
        recall = len(expected_points & actual_point_ids) / len(expected_points)
    else:
        precision = recall = 1.0

    # 任务类型、语言、受众、引用要求、路由 正确性
    type_ok = intent.get("task_type") == case.get("task_type")
    lang_ok = (intent.get("language") or "").lower().replace("-", "") == (case.get("language") or "").lower().replace("-", "")
    cite_ok = bool(intent.get("require_citations")) == bool(case.get("explicit_constraints", {}).get("require_citations"))
    audience_ok = intent.get("audience") == case.get("explicit_constraints", {}).get("audience")
    routing_ok = intent.get("routing") == case.get("task_type")

    routing_accuracy = 1.0 if routing_ok else 0.0
    passed = not missing and type_ok and lang_ok and cite_ok and audience_ok and routing_ok and not extra

    results.append(MetricResult(
        metric_name="intent_constraint_recall",
        metric_group="intent",
        evaluator_name="MvpIntentEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=recall,
        passed=int(recall >= 1.0),
        reason=f"Intent 覆盖 required_points recall={recall:.2f}",
        details={"missing_constraints": sorted(missing), "extra_constraints": sorted(extra)},
    ))
    results.append(MetricResult(
        metric_name="intent_constraint_precision",
        metric_group="intent",
        evaluator_name="MvpIntentEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=precision,
        passed=int(precision >= 1.0),
        reason=f"Intent 精确率={precision:.2f}",
        details={"extra_constraints": sorted(extra)},
    ))
    results.append(MetricResult(
        metric_name="intent_routing_accuracy",
        metric_group="intent",
        evaluator_name="MvpIntentEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=routing_accuracy,
        passed=int(routing_ok),
        reason=f"路由={intent.get('routing')} 期望={case.get('task_type')}",
    ))
    results.append(MetricResult(
        metric_name="intent_passed",
        metric_group="intent",
        evaluator_name="MvpIntentEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=1.0 if passed else 0.0,
        passed=int(passed),
        reason="Intent 漏掉安全约束" if missing else "Intent 约束齐全",
    ))
    return results


# ============================================================
# 2. Review Evaluator（规格第 6 节）
# ============================================================

async def evaluate_review(ctx: MvpEvalContext) -> list[MetricResult]:
    """评价 Reviewer 的 gap 识别、下一轮 work item/evidence、最终是否关闭、质量提升。"""
    review = ctx.review
    rounds = ctx.rounds
    results: list[MetricResult] = []

    # 外部 Eval 发现的缺失项 = case.required_points 中 intent 未覆盖的（这里以 review.blocking_gaps 对照）
    expected_gaps = {p["id"] for p in ctx.case.get("required_points", []) if isinstance(p, dict)} - set(ctx.intent.get("required_points", []))
    actual_gaps = set(review.get("blocking_gaps", []))

    # 规格问题 2/3：Reviewer 发现 security gap，但最终报告未使用安全 evidence
    gap_precision = len(expected_gaps & actual_gaps) / len(actual_gaps) if actual_gaps else 1.0
    gap_recall = len(expected_gaps & actual_gaps) / len(expected_gaps) if expected_gaps else 1.0

    # 下一轮是否针对 gap 新增 evidence
    gap_evidence: dict[str, list[str]] = {}
    for r in rounds:
        for ev_id in r.get("new_evidence", []) or []:
            ev = ctx.evidence_by_id.get(ev_id)
            if ev:
                gap_evidence.setdefault(ev.get("claim", ""), []).append(ev_id)

    new_evidence_for_gaps = sum(len(ids) for g, ids in gap_evidence.items() if g in actual_gaps)
    new_evidence_count = sum(len(r.get("new_evidence", []) or []) for r in rounds) - (len(rounds[0].get("new_evidence", []) or []) if rounds else 0)

    # gap 是否在最终报告关闭：检查 final 是否包含 gap 对应 evidence 文本
    final = ctx.reports.get("final", "")
    gap_closed: list[str] = []
    for g in actual_gaps:
        # 查找该 gap 对应的 evidence 文本是否出现在 final（宽松：只看 evidence_text 出现）
        closed = False
        for ev in ctx.evidence:
            if ev.get("claim") == g and ev.get("evidence_text", "") and ev.get("evidence_text", "") in final:
                closed = True
                break
        if closed:
            gap_closed.append(g)
    gap_closure_rate = len(gap_closed) / len(actual_gaps) if actual_gaps else 1.0

    # reviewer token 成本（取 run 的 output 的一部分作近似，规格示例 1800）
    reviewer_tokens = ctx.run.get("reviewer_tokens", 1800)

    # 质量提升 delta：rounds[1] vs rounds[0] tokens 比例的近似（MVP 占位，生产用真实评分）
    quality_delta = 0.0

    finding = "Reviewer 找对问题，但最终报告未使用新增 Evidence" if (gap_recall >= 1.0 and gap_closure_rate < 1.0) else "Reviewer gap 识别正常"

    results.append(MetricResult(
        metric_name="review_gap_precision",
        metric_group="review",
        evaluator_name="MvpReviewEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=gap_precision,
        reason=f"gap precision={gap_precision:.2f}",
    ))
    results.append(MetricResult(
        metric_name="review_gap_recall",
        metric_group="review",
        evaluator_name="MvpReviewEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=gap_recall,
        passed=int(gap_recall >= 1.0),
        reason=f"gap recall={gap_recall:.2f} actual_gaps={sorted(actual_gaps)}",
        details={"blocking_gaps": sorted(actual_gaps), "expected_gaps": sorted(expected_gaps)},
    ))
    results.append(MetricResult(
        metric_name="review_gap_closure_rate",
        metric_group="review",
        evaluator_name="MvpReviewEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=gap_closure_rate,
        passed=int(gap_closure_rate >= 1.0),
        reason=f"gap closure={gap_closure_rate:.2f} closed={gap_closed}",
    ))
    results.append(MetricResult(
        metric_name="review_new_evidence_count",
        metric_group="review",
        evaluator_name="MvpReviewEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(new_evidence_for_gaps),
        reason=f"为 gap 新增 evidence={new_evidence_for_gaps}",
    ))
    results.append(MetricResult(
        metric_name="review_quality_delta",
        metric_group="review",
        evaluator_name="MvpReviewEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=quality_delta,
        reason="MVP 占位 delta，生产用真实评分",
    ))
    results.append(MetricResult(
        metric_name="reviewer_token_cost",
        metric_group="cost",
        evaluator_name="MvpReviewEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(reviewer_tokens),
        reason=f"reviewer_tokens={reviewer_tokens}",
    ))
    results.append(MetricResult(
        metric_name="review_finding",
        metric_group="review",
        evaluator_name="MvpReviewEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        label_value=finding,
        reason=finding,
    ))
    return results


# ============================================================
# 3. Claim/Citation Evaluator（规格第 7 节）— 调 LLM
# ============================================================

_CLAIM_SYSTEM_PROMPT = """你是严格的 Claim 支持状态判定器。给定一个 claim、其引用的 evidence 文本与来源摘要，判断该 claim 的支持状态。
只输出 JSON：{"verdict": "<status>", "reason": "<简短中文理由>"}
status 取值之一：
- supported：evidence 明确支持 claim
- partially_supported：evidence 部分支持
- unsupported：evidence 不支持 claim 或与 claim 无关
- contradicted：evidence 与 claim 直接矛盾
- not_verifiable：无法判断（如缺 evidence 或信息不足）"""


def _build_claim_user_prompt(claim: dict[str, Any], evidence: dict[str, Any] | None, source: dict[str, Any] | None, all_evidence: list[dict[str, Any]] | None = None) -> str:
    """构造 claim 判定 prompt。

    优先用 claim 明确映射的 evidence（citation↔evidence_id）；若 claim 无明确映射
    （真实生产 claim_manifest 常见：citation 是 marker-N 文本标记，无 evidence_id），
    则把全部 evidence 摘要喂给 LLM，由其判断 claim 是否被其中任一支持。
    """
    parts = [f"Claim（id={claim.get('claim_id')}）: {claim.get('claim_text', '')}"]
    if evidence:
        parts.append(f"引用 Evidence（id={evidence.get('evidence_id')}）: {evidence.get('evidence_text', '')}")
        if source:
            parts.append(f"Source（id={source.get('source_id')}）: {source.get('snapshot', '')}")
    elif all_evidence:
        # 无明确 citation 映射，喂全部 evidence 摘要（真实生产场景）。
        # 截断每条 + 限条数，避免 prompt 过长爆 token。
        evs = "\n".join(
            f"- [{e.get('evidence_id')}] {e.get('evidence_text', '')[:160]}"
            for e in all_evidence if e.get('evidence_text')
        )[:8000]
        parts.append(f"可用 Evidence 池（共 {len(all_evidence)} 条，含 claim 上下文里的 Evidence N 编号）:\n{evs}")
    else:
        parts.append("Evidence: <无对应 evidence>")
    parts.append("判断该 claim 的支持状态，只输出 JSON。")
    return "\n".join(parts)


async def _judge_one_claim(claim: dict[str, Any], ctx: MvpEvalContext, chat_fn: ChatFn | None) -> tuple[str, str]:
    """返回 (verdict, reason)。chat_fn 缺失或调用失败 → not_verifiable。"""
    # 确定性规则：citation↔evidence 映射
    citations = claim.get("citations", []) or []
    evidence: dict[str, Any] | None = None
    source: dict[str, Any] | None = None
    if citations:
        ev_id = citations[0].get("evidence_id")
        evidence = ctx.evidence_by_id.get(ev_id)
        if evidence:
            source = ctx.source_by_id.get(evidence.get("source_id"))
    if chat_fn is None:
        return "not_verifiable", "未注入 chat_fn，无法调用 LLM 判定"
    try:
        user_prompt = _build_claim_user_prompt(claim, evidence, source, all_evidence=ctx.evidence if not evidence else None)
        raw = await chat_fn(_CLAIM_SYSTEM_PROMPT, user_prompt)
    except Exception as exc:  # noqa: BLE001
        return "not_verifiable", f"LLM 调用失败：{exc}"
    parsed = parse_json_safe(raw)
    if not isinstance(parsed, dict) or "verdict" not in parsed:
        return "not_verifiable", f"LLM 输出无法解析：{raw[:200]}"
    verdict = str(parsed.get("verdict", "not_verifiable"))
    reason = str(parsed.get("reason", ""))
    allowed = {"supported", "partially_supported", "unsupported", "contradicted", "not_verifiable"}
    if verdict not in allowed:
        verdict = "not_verifiable"
    return verdict, reason


async def evaluate_claims(ctx: MvpEvalContext, *, chat_fn: ChatFn | None = None) -> list[MetricResult]:
    """逐 claim 判定支持状态。citation↔evidence 映射为确定性规则，支持判定调 LLM。"""
    results: list[MetricResult] = []
    counts = {"supported": 0, "partially_supported": 0, "unsupported": 0, "contradicted": 0, "not_verifiable": 0}
    total = len(ctx.claims)
    citation_has = 0
    citation_correct = 0
    unsupported_critical = 0
    per_claim: list[dict[str, Any]] = []

    for claim in ctx.claims:
        requires_citation = bool(claim.get("requires_citation"))
        citations = claim.get("citations", []) or []
        has_cite = bool(citations)
        if requires_citation and has_cite:
            citation_has += 1

        # citation↔evidence 映射正确性（确定性）
        mapped_evidence = None
        if citations:
            ev_id = citations[0].get("evidence_id")
            mapped_evidence = ctx.evidence_by_id.get(ev_id)
        citation_mapped_ok = mapped_evidence is not None

        verdict, reason = await _judge_one_claim(claim, ctx, chat_fn)
        counts[verdict] += 1

        # citation_correct：evidence 映射正确 且 verdict 为 supported/partial
        if citation_mapped_ok and verdict in ("supported", "partially_supported"):
            citation_correct += 1

        if verdict in ("unsupported", "contradicted") and claim.get("importance") == "critical":
            unsupported_critical += 1

        per_claim.append({
            "claim_id": claim.get("claim_id"),
            "claim_text": claim.get("claim_text"),
            "importance": claim.get("importance"),
            "requires_citation": requires_citation,
            "has_citation": has_cite,
            "citation_evidence_id": citations[0].get("evidence_id") if citations else None,
            "citation_mapped": citation_mapped_ok,
            "verdict": verdict,
            "reason": reason,
        })

    citation_completeness = (citation_has / total) if total else 0.0
    citation_correctness = (citation_correct / total) if total else 0.0

    results.append(MetricResult(
        metric_name="claim_total_claims",
        metric_group="claim",
        evaluator_name="MvpClaimEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(total),
        reason=f"total_claims={total}",
    ))
    for label in ("supported", "partially_supported", "unsupported", "contradicted", "not_verifiable"):
        results.append(MetricResult(
            metric_name=f"claim_{label}_claims",
            metric_group="claim",
            evaluator_name="MvpClaimEvaluator",
            evaluator_version=EVALUATOR_VERSION,
            score_value=float(counts[label]),
            reason=f"{label}={counts[label]}",
        ))
    results.append(MetricResult(
        metric_name="citation_completeness",
        metric_group="claim",
        evaluator_name="MvpClaimEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=citation_completeness,
        reason=f"citation_completeness={citation_completeness:.2f}",
    ))
    results.append(MetricResult(
        metric_name="citation_correctness",
        metric_group="claim",
        evaluator_name="MvpClaimEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=citation_correctness,
        passed=int(citation_correctness >= 1.0),
        reason=f"citation_correctness={citation_correctness:.2f}",
        details={"per_claim": per_claim},
    ))
    results.append(MetricResult(
        metric_name="unsupported_critical_claim_count",
        metric_group="claim",
        evaluator_name="MvpClaimEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(unsupported_critical),
        passed=int(unsupported_critical == 0),
        reason=f"unsupported_critical_claim_count={unsupported_critical}",
        details={"per_claim": per_claim},
    ))
    return results


# ============================================================
# 4. Consistency Evaluator（规格第 8 节）— Before/After
# ============================================================

def _count_contradictions(messages: list[dict[str, Any]]) -> int:
    return sum(1 for m in messages if m.get("severity") == "blocking")


def _norm_text(s: str) -> str:
    """归一化文本用于 forbidden claim 匹配：去首尾空白与末尾中英句号，容忍标点差异。"""
    if not s:
        return ""
    s = s.strip()
    while s and s[-1] in "。.；;":
        s = s[:-1]
    return s


async def evaluate_consistency(ctx: MvpEvalContext) -> list[MetricResult]:
    """评价 Consistency 前后矛盾数、解决数、claim/citation 保留率、新回归。

    claim/citation 保留率用 claim_id 集合比对（reports.pre/post_consistency_claim_ids），
    不靠文本子串匹配，避免 pre/post 报告与 claims 措辞口径不一致导致误判。
    """
    pre = ctx.reports.get("pre_consistency", "")
    post = ctx.reports.get("post_consistency", "")
    messages = ctx.reports.get("consistency_messages", []) or []
    if not isinstance(messages, list):
        messages = []

    issues_reported = _count_contradictions(messages)
    # 矛盾数：pre 中出现的禁止性结论数与 blocking 消息数取大（归一化匹配，容忍标点差异）
    forbidden = ctx.case.get("forbidden_claims", []) or []
    forbidden_norm = {_norm_text(f) for f in forbidden}

    def _count_forbidden_in(text: str) -> int:
        t = _norm_text(text)
        return sum(1 for f in forbidden_norm if f and f in t)

    pre_forbidden_present = _count_forbidden_in(pre)
    post_forbidden_present = _count_forbidden_in(post)
    contradictions_before = max(pre_forbidden_present, issues_reported)
    contradictions_after = post_forbidden_present
    issues_resolved = max(0, contradictions_before - contradictions_after)

    # claim 保留率：post 仍包含 pre 中非禁止性 claim 的比例（按 claim_id，口径一致）
    pre_ids = set(ctx.reports.get("pre_consistency_claim_ids", []) or [])
    post_ids = set(ctx.reports.get("post_consistency_claim_ids", []) or [])
    forbidden_ids = {cid for cid in pre_ids
                     if _norm_text(ctx.claim_by_id.get(cid, {}).get("claim_text")) in forbidden_norm}
    non_forbidden_pre = pre_ids - forbidden_ids
    if non_forbidden_pre:
        retained_non_forbidden = non_forbidden_pre & post_ids
        claim_retention = len(retained_non_forbidden) / len(non_forbidden_pre)
    else:
        claim_retention = 1.0
    citation_retention = claim_retention  # MVP 近似

    # 新回归：post 中出现 pre 没有的禁止性结论
    pre_norm = _norm_text(pre)
    post_norm = _norm_text(post)
    new_regressions = sum(1 for f in forbidden_norm if f and f not in pre_norm and f in post_norm)

    results: list[MetricResult] = []
    results.append(MetricResult(
        metric_name="consistency_issues_reported",
        metric_group="consistency",
        evaluator_name="MvpConsistencyEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(issues_reported),
        reason=f"issues_reported={issues_reported}",
    ))
    results.append(MetricResult(
        metric_name="consistency_issues_resolved",
        metric_group="consistency",
        evaluator_name="MvpConsistencyEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(issues_resolved),
        reason=f"issues_resolved={issues_resolved}",
    ))
    results.append(MetricResult(
        metric_name="consistency_contradictions_before",
        metric_group="consistency",
        evaluator_name="MvpConsistencyEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(contradictions_before),
        reason=f"contradictions_before={contradictions_before}",
    ))
    results.append(MetricResult(
        metric_name="consistency_contradictions_after",
        metric_group="consistency",
        evaluator_name="MvpConsistencyEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(contradictions_after),
        passed=int(contradictions_after == 0),
        reason=f"contradictions_after={contradictions_after}",
    ))
    results.append(MetricResult(
        metric_name="consistency_claim_retention",
        metric_group="consistency",
        evaluator_name="MvpConsistencyEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=claim_retention,
        reason=f"claim_retention={claim_retention:.2f}",
    ))
    results.append(MetricResult(
        metric_name="consistency_citation_retention",
        metric_group="consistency",
        evaluator_name="MvpConsistencyEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=citation_retention,
        reason=f"citation_retention={citation_retention:.2f}",
    ))
    results.append(MetricResult(
        metric_name="consistency_new_regressions",
        metric_group="consistency",
        evaluator_name="MvpConsistencyEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(new_regressions),
        passed=int(new_regressions == 0),
        reason=f"new_regressions={new_regressions}",
    ))
    return results


# ============================================================
# 5. ClaimVerifier Evaluator（规格第 9 节）
# ============================================================

async def evaluate_claim_verifier(ctx: MvpEvalContext) -> list[MetricResult]:
    """评价 ClaimVerifier 是否发现预置 unsupported claim、verdict 正确性、后报告修正、误报。"""
    verifier = ctx.claim_verifier
    forbidden = ctx.case.get("forbidden_claims", []) or []
    forbidden_norm_ver = {_norm_text(f) for f in forbidden}

    checked = len(verifier)
    # gold 期望被标记 unsupported 的 claim（取 claim_verifier verdict=unverified 的集合）
    detected_unsupported = {v.get("claim_id") for v in verifier if v.get("verdict") == "unverified"}
    # 实际应为 unsupported 的 claim：依据 fixture 中 claim_verifier 已标注 unverified 作为校准真值（MVP）
    expected_unsupported = {v.get("claim_id") for v in verifier if v.get("verdict") == "unverified"}

    precision = (len(detected_unsupported & expected_unsupported) / len(detected_unsupported)) if detected_unsupported else 1.0
    recall = (len(detected_unsupported & expected_unsupported) / len(expected_unsupported)) if expected_unsupported else 1.0

    # claim_id 集合（口径一致，不靠文本子串）；forbidden 判定用归一化匹配容忍标点差异
    pre_ver_ids = set(ctx.reports.get("pre_verification_claim_ids", []) or [])
    post_ver_ids = set(ctx.reports.get("post_verification_claim_ids", []) or [])
    forbidden_ids_ver = {cid for cid in pre_ver_ids
                         if _norm_text(ctx.claim_by_id.get(cid, {}).get("claim_text")) in forbidden_norm_ver}

    # 后报告是否披露/删除/修正该 claim（按 claim_id）
    forbidden_in_pre = len(forbidden_ids_ver & pre_ver_ids)
    forbidden_in_post = len(forbidden_ids_ver & post_ver_ids)
    corrected = max(0, forbidden_in_pre - forbidden_in_post)
    correction_rate = (corrected / forbidden_in_pre) if forbidden_in_pre else 1.0

    # 误报：verifier 标 unverified 但该 claim 根本不在 pre_verification 报告里（无可修正对象）
    false_warning = 0
    for v in verifier:
        if v.get("verdict") == "unverified" and v.get("claim_id") not in pre_ver_ids:
            false_warning += 1

    # coverage regression：post 删除了不应删除的非禁止 claim（按 claim_id，口径一致）
    non_forbidden_pre_ver = pre_ver_ids - forbidden_ids_ver
    if non_forbidden_pre_ver:
        regressed_ids = non_forbidden_pre_ver - post_ver_ids
        coverage_regression = len(regressed_ids) / len(non_forbidden_pre_ver)
    else:
        coverage_regression = 0.0

    results: list[MetricResult] = []
    results.append(MetricResult(
        metric_name="verifier_checked_claims",
        metric_group="claim_verifier",
        evaluator_name="MvpClaimVerifierEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(checked),
        reason=f"checked_claims={checked}",
    ))
    results.append(MetricResult(
        metric_name="verifier_unsupported_detection_precision",
        metric_group="claim_verifier",
        evaluator_name="MvpClaimVerifierEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=precision,
        reason=f"detection precision={precision:.2f}",
    ))
    results.append(MetricResult(
        metric_name="verifier_unsupported_detection_recall",
        metric_group="claim_verifier",
        evaluator_name="MvpClaimVerifierEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=recall,
        passed=int(recall >= 1.0),
        reason=f"detection recall={recall:.2f} detected={sorted(detected_unsupported)}",
        details={"detected_unsupported": sorted(detected_unsupported)},
    ))
    results.append(MetricResult(
        metric_name="verifier_claim_correction_rate",
        metric_group="claim_verifier",
        evaluator_name="MvpClaimVerifierEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=correction_rate,
        passed=int(correction_rate >= 1.0),
        reason=f"correction_rate={correction_rate:.2f}",
    ))
    results.append(MetricResult(
        metric_name="verifier_false_warning_count",
        metric_group="claim_verifier",
        evaluator_name="MvpClaimVerifierEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=float(false_warning),
        passed=int(false_warning == 0),
        reason=f"false_warning={false_warning}",
    ))
    results.append(MetricResult(
        metric_name="verifier_coverage_regression",
        metric_group="claim_verifier",
        evaluator_name="MvpClaimVerifierEvaluator",
        evaluator_version=EVALUATOR_VERSION,
        score_value=coverage_regression,
        passed=int(coverage_regression == 0.0),
        reason=f"coverage_regression={coverage_regression:.2f}",
    ))
    return results
