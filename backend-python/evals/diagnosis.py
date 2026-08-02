"""Eval 指标 → 根因 → Agent 模块 → 优化建议的可审计诊断层。

本模块不是新的 Evaluator，也不重新评价报告。它只消费已经产生的事实和指标，
通过显式规则完成：

1. 单 Case 根因定位；
2. Agent 功能状态映射；
3. 同题档位增益/成本决策；
4. 决策型 Markdown 报告。

每个诊断都保留触发它的指标证据，避免生成无法追溯的自然语言结论。
"""
from __future__ import annotations

from collections import Counter
from typing import Any

RULESET_VERSION = "1.0.0"
TIER_ORDER = {"MEDIUM": 0, "HIGH": 1, "ULTRA": 2}

CONTENT_QUALITY_METRICS = (
    "required_point_coverage",
    "critical_fact_recall",
    "claim_factuality",
    "analysis_depth",
    "multi_source_synthesis",
    "uncertainty_calibration",
    "instruction_following",
)
EVIDENCE_QUALITY_METRICS = (
    "citation_traceability",
    "citation_completeness",
    "citation_correctness",
    "source_quality",
)


def _score_map(scores: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """同一次 evaluate_case_run 返回值每个 metric 唯一；保留完整证据字段。"""
    return {
        str(score.get("metric_name")): score
        for score in scores
        if score.get("metric_name")
    }


def _value(scores: dict[str, dict[str, Any]], metric: str) -> float | None:
    score = scores.get(metric) or {}
    value = score.get("score_value")
    return float(value) if isinstance(value, (int, float)) else None


def _passed(scores: dict[str, dict[str, Any]], metric: str) -> int | None:
    score = scores.get(metric) or {}
    value = score.get("passed")
    if value in (0, 1, False, True):
        return int(value)
    numeric = _value(scores, metric)
    return int(numeric) if numeric in (0.0, 1.0) else None


def _label(scores: dict[str, dict[str, Any]], metric: str) -> str | None:
    value = (scores.get(metric) or {}).get("label_value")
    return str(value) if value is not None else None


def _mean_available(scores: dict[str, dict[str, Any]], metrics: tuple[str, ...]) -> float | None:
    values = [_value(scores, metric) for metric in metrics]
    available = [value for value in values if value is not None]
    if not available:
        return None
    return round(sum(available) / len(available), 4)


def _failure_codes(scores: dict[str, dict[str, Any]]) -> list[str]:
    hard_gate = scores.get("hard_gate_passed") or {}
    details = hard_gate.get("details") or {}
    codes = details.get("failure_reason_codes") or []
    if isinstance(codes, list):
        return [str(code) for code in codes]
    return []


def _evidence(metric: str, value: Any, reason: str | None = None) -> dict[str, Any]:
    item = {"metric": metric, "value": value}
    if reason:
        item["reason"] = reason
    return item


def _root_cause(
    *,
    code: str,
    title: str,
    layer: str,
    modules: list[str],
    severity: str,
    confidence: float,
    evidence: list[dict[str, Any]],
    recommendation: str,
    priority: int,
) -> dict[str, Any]:
    return {
        "code": code,
        "title": title,
        "layer": layer,
        "agent_modules": modules,
        "severity": severity,
        "confidence": confidence,
        "evidence": evidence,
        "recommendation": recommendation,
        "_priority": priority,
    }


def diagnose_case(record: dict[str, Any]) -> dict[str, Any]:
    """对单个 Case 做规则化根因诊断。"""
    scores = _score_map(list(record.get("scores") or []))
    failure_codes = _failure_codes(scores)
    workflow_completed = _passed(scores, "workflow_completed")
    report_non_empty = _passed(scores, "report_non_empty")
    hard_gate = _passed(scores, "hard_gate_passed")
    intent_alignment = _value(scores, "intent_alignment")
    intent_type = _value(scores, "intent_type_accuracy")
    clarification_accuracy = _value(scores, "clarification_decision_accuracy")
    factuality = _value(scores, "claim_factuality")
    traceability = _value(scores, "citation_traceability")
    required_coverage = _value(scores, "required_point_coverage")
    claim_retention = _value(scores, "claim_retention_after_revision")
    merge_loss = _value(scores, "merge_information_loss")
    quality_delta = _value(scores, "quality_delta_per_round")
    reviewer_tokens = _value(scores, "reviewer_token_cost") or 0.0
    reviewer_consensus = _label(scores, "reviewer_consensus_predictiveness")
    synthesis_uplift = _value(scores, "synthesis_uplift")

    content_quality = _mean_available(scores, CONTENT_QUALITY_METRICS)
    evidence_quality = _mean_available(scores, EVIDENCE_QUALITY_METRICS)
    dimensions = [value for value in (content_quality, evidence_quality) if value is not None]
    overall_quality = round(sum(dimensions) / len(dimensions), 4) if dimensions else None

    roots: list[dict[str, Any]] = []

    if clarification_accuracy == 0:
        roots.append(
            _root_cause(
                code="scope_clarification_error",
                title="ScopeAgent 产生了不必要或错误的澄清",
                layer="intent",
                modules=["ScopeAgent"],
                severity="blocking",
                confidence=0.99,
                evidence=[
                    _evidence("clarification_decision_accuracy", clarification_accuracy),
                    _evidence("workflow_completed", workflow_completed),
                    _evidence("run.outcome", record.get("outcome")),
                ],
                recommendation=(
                    "把 Dataset 的 should_clarify 契约加入 Scope 提示词和回归测试；"
                    "对信息已充分的问题禁止生成澄清，并记录触发澄清的具体缺口。"
                ),
                priority=100,
            )
        )
    elif intent_type == 0:
        roots.append(
            _root_cause(
                code="scope_routing_error",
                title="ScopeAgent 研究类型路由错误",
                layer="intent",
                modules=["ScopeAgent", "WorkflowTemplateSelector"],
                severity="blocking",
                confidence=0.98,
                evidence=[_evidence("intent_type_accuracy", intent_type)],
                recommendation=(
                    "校准研究类型分类样本和路由枚举；对低置信度结果使用候选类型复核，"
                    "并增加 task_type→research_type 契约测试。"
                ),
                priority=98,
            )
        )

    if workflow_completed == 0 and not any(root["layer"] == "intent" for root in roots):
        roots.append(
            _root_cause(
                code="workflow_execution_failure",
                title="AgentPipeline 未完成任务",
                layer="execution",
                modules=["AgentPipeline"],
                severity="blocking",
                confidence=0.9,
                evidence=[
                    _evidence("workflow_completed", workflow_completed),
                    _evidence("run.outcome", record.get("outcome")),
                    _evidence("run.status", record.get("status")),
                ],
                recommendation=(
                    "按 research_run 的最后成功 Stage 和 error_type 定位失败节点，"
                    "为超时、重试耗尽和等待态分别建立恢复策略。"
                ),
                priority=95,
            )
        )

    if report_non_empty == 0 and workflow_completed != 0:
        roots.append(
            _root_cause(
                code="report_generation_failure",
                title="工作流结束但没有生成最终报告",
                layer="report",
                modules=["ReportAgent", "AgentPipeline"],
                severity="blocking",
                confidence=0.98,
                evidence=[_evidence("report_non_empty", report_non_empty)],
                recommendation=(
                    "检查 report_final Artifact 写入、报告阶段回退路径和终态切换顺序；"
                    "没有 report_final 时不得将运行标记为成功。"
                ),
                priority=94,
            )
        )

    citation_failures = {
        code for code in failure_codes if code in {"dangling_citation", "unsupported_critical_claim"}
    }
    if citation_failures:
        linkage_failure = (
            factuality is not None
            and factuality >= 0.8
            and (traceability is None or traceability < 0.5)
        )
        roots.append(
            _root_cause(
                code=(
                    "citation_claim_linkage_failure"
                    if linkage_failure
                    else "critical_claim_evidence_insufficient"
                ),
                title=(
                    "报告内容基本正确，但引用与 Claim Manifest 的关联链路丢失"
                    if linkage_failure
                    else "关键 Claim 缺少足够证据支持"
                ),
                layer="evidence",
                modules=(
                    ["ReportAgent", "ClaimVerifier", "ClaimManifestPersistence"]
                    if linkage_failure
                    else ["ResearcherAgent", "SearchAgent", "ClaimVerifier"]
                ),
                severity="blocking",
                confidence=0.96 if linkage_failure else 0.88,
                evidence=[
                    _evidence("hard_gate.failure_codes", sorted(citation_failures)),
                    _evidence("claim_factuality", factuality),
                    _evidence("citation_traceability", traceability),
                ],
                recommendation=(
                    "为每个关键 Claim 强制保存 citation_url、evidence_id 和报告引用标记的三方映射；"
                    "在 ReportAgent 输出后运行一致性校验，存在悬空引用时先修复再完成报告。"
                    if linkage_failure
                    else
                    "让 ResearcherAgent 针对未支持的关键 Claim 定向补证；"
                    "ClaimVerifier 不通过时阻止报告定稿，并把缺口反馈给下一轮计划。"
                ),
                priority=90,
            )
        )

    if "missing_required_points" in failure_codes and report_non_empty != 0:
        roots.append(
            _root_cause(
                code="required_point_coverage_gap",
                title="最终报告遗漏 Dataset 必答点",
                layer="coverage",
                modules=(
                    ["SupervisorAgent", "ResearcherAgent", "ReportAgent"]
                    if intent_alignment == 1
                    else ["ScopeAgent", "SupervisorAgent", "ReportAgent"]
                ),
                severity="blocking",
                confidence=0.9,
                evidence=[
                    _evidence("required_point_coverage", required_coverage),
                    _evidence("intent_alignment", intent_alignment),
                ],
                recommendation=(
                    "把 required_points 映射到 research_plan、evidence_item 和报告 section，"
                    "在报告定稿前逐项检查是否已有证据且已写入正文。"
                ),
                priority=88,
            )
        )

    if "critical_fact_error" in failure_codes and report_non_empty != 0:
        roots.append(
            _root_cause(
                code="critical_fact_error",
                title="最终报告存在关键事实错误",
                layer="quality",
                modules=["ResearcherAgent", "ClaimVerifier", "ReportAgent"],
                severity="blocking",
                confidence=0.9,
                evidence=[_evidence("claim_factuality", factuality)],
                recommendation=(
                    "对关键事实强制使用权威来源交叉验证；ClaimVerifier 输出矛盾或不支持时，"
                    "必须回到证据补充或删除该结论。"
                ),
                priority=89,
            )
        )

    if claim_retention is not None and claim_retention < 0.8:
        roots.append(
            _root_cause(
                code="section_revision_claim_loss",
                title="章节修订过程中丢失了较多 Claim",
                layer="mechanism",
                modules=["ReportSectionAgent", "ReportConsistencyAgent"],
                severity="warning",
                confidence=0.86,
                evidence=[_evidence("claim_retention_after_revision", claim_retention)],
                recommendation=(
                    "修订提示词增加“保留已支持 Claim”约束；修订后按 claim_id 做差异检查，"
                    "只有明确解决冲突或删除不支持内容时才允许 Claim 消失。"
                ),
                priority=65,
            )
        )

    if merge_loss is not None and merge_loss > 0.15:
        roots.append(
            _root_cause(
                code="report_merge_information_loss",
                title="章节合并阶段存在明显信息损失",
                layer="mechanism",
                modules=["ReportConsistencyAgent", "ReportAgent"],
                severity="warning",
                confidence=0.84,
                evidence=[_evidence("merge_information_loss", merge_loss)],
                recommendation=(
                    "合并前建立章节 Claim/Citation 清单，合并后逐项校验保留率；"
                    "把去重和删除事实拆开，禁止因文本压缩丢失独有证据。"
                ),
                priority=62,
            )
        )

    if reviewer_tokens > 0 and quality_delta is None:
        roots.append(
            _root_cause(
                code="reviewer_uplift_not_measurable",
                title="Reviewer 已消耗 Token，但缺少可比较的前后质量增益",
                layer="eval_observability",
                modules=["UltraDynamicReviewer", "RoundArtifactRecorder"],
                severity="warning",
                confidence=1.0,
                evidence=[
                    _evidence("reviewer_token_cost", reviewer_tokens),
                    _evidence("quality_delta_per_round", quality_delta),
                    _evidence("reviewer_consensus", reviewer_consensus),
                ],
                recommendation=(
                    "冻结 Reviewer 前后的同口径报告/证据快照，并用同一 Judge 分别评分；"
                    "只有得到 quality_delta_per_round 和 marginal_quality_per_1k_tokens，"
                    "才能判断 Reviewer 是否值得保留。"
                ),
                priority=60,
            )
        )
    elif reviewer_tokens > 0 and quality_delta is not None and quality_delta <= 0:
        roots.append(
            _root_cause(
                code="reviewer_no_quality_uplift",
                title="Reviewer 消耗了 Token，但没有带来正向质量增益",
                layer="mechanism",
                modules=["UltraDynamicReviewer"],
                severity="warning",
                confidence=0.92,
                evidence=[
                    _evidence("reviewer_token_cost", reviewer_tokens),
                    _evidence("quality_delta_per_round", quality_delta),
                ],
                recommendation=(
                    "收紧 Reviewer 继续研究阈值，减少无效 Lens；"
                    "仅当明确 Gap 能映射到下一轮 Work Item 和新增 Evidence 时继续。"
                ),
                priority=68,
            )
        )

    if synthesis_uplift is not None and synthesis_uplift <= 0:
        roots.append(
            _root_cause(
                code="synthesis_no_uplift",
                title="多 Draft Synthesis 没有超过最佳单 Draft",
                layer="mechanism",
                modules=["ReportAgent:Synthesis"],
                severity="warning",
                confidence=0.85,
                evidence=[_evidence("synthesis_uplift", synthesis_uplift)],
                recommendation=(
                    "减少重复 Draft；只有在 draft_complementarity 足够高时才执行 Synthesis，"
                    "否则直接采用最佳 Draft。"
                ),
                priority=58,
            )
        )

    roots.sort(key=lambda item: (-int(item["_priority"]), item["code"]))
    for root in roots:
        root.pop("_priority", None)

    if workflow_completed == 1:
        result_status = "degraded" if str(record.get("outcome") or "").lower() == "degraded" else "completed"
    else:
        result_status = "failed"

    if roots:
        primary = roots[0]
        main_finding = primary["title"]
        recommendation = primary["recommendation"]
        modules = primary["agent_modules"]
    elif hard_gate == 1:
        main_finding = "任务和质量 Gate 均通过，未发现阻断级根因"
        recommendation = "保持当前配置，并在更多同类型题目上验证稳定性和成本。"
        modules = []
    else:
        main_finding = "存在未被当前规则解释的 Gate 失败"
        recommendation = "检查 Hard Gate failure_reason_codes，并补充根因映射规则。"
        modules = []

    agent_function_status = {
        "scope": (
            "effective"
            if intent_alignment == 1
            else "ineffective"
            if intent_alignment == 0
            else "not_evaluable"
        ),
        "report_content": (
            "effective"
            if content_quality is not None and content_quality >= 0.8
            else "degraded"
            if content_quality is not None
            else "not_evaluable"
        ),
        "citation_pipeline": (
            "effective"
            if traceability is not None and traceability >= 0.95
            else "ineffective"
            if traceability is not None
            else "not_evaluable"
        ),
        "reviewer": (
            "not_applicable"
            if reviewer_tokens <= 0
            else "unproven"
            if quality_delta is None
            else "effective"
            if quality_delta > 0
            else "ineffective"
        ),
    }

    tokens = int(record.get("input_tokens") or 0) + int(record.get("output_tokens") or 0)
    return {
        "item_id": str(record.get("item_id") or ""),
        "item_label": str(record.get("item_label") or record.get("item_id") or ""),
        "variant": str(record.get("variant") or ""),
        "research_id": record.get("research_id"),
        "run_id": record.get("run_id"),
        "result_status": result_status,
        "outcome": record.get("outcome"),
        "total_tokens": tokens,
        "total_tokens_k": round(tokens / 1000.0, 3),
        "hard_gate_passed": hard_gate,
        "failure_reason_codes": failure_codes,
        "quality": {
            "content_quality": content_quality,
            "evidence_quality": evidence_quality,
            "overall_quality": overall_quality,
            "usable_quality": overall_quality if hard_gate == 1 else 0.0,
        },
        "agent_function_status": agent_function_status,
        "root_causes": roots,
        "primary_agent_modules": modules,
        "main_finding": main_finding,
        "optimization_recommendation": recommendation,
    }


def _tier_comparisons(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_item: dict[str, list[dict[str, Any]]] = {}
    for case in cases:
        by_item.setdefault(case["item_id"], []).append(case)
    comparisons: list[dict[str, Any]] = []
    for item_id, item_cases in by_item.items():
        ordered = sorted(item_cases, key=lambda item: TIER_ORDER.get(item["variant"], 99))
        for lower, higher in zip(ordered[:-1], ordered[1:]):
            token_delta = round(higher["total_tokens_k"] - lower["total_tokens_k"], 3)
            lower_quality = lower["quality"].get("overall_quality")
            higher_quality = higher["quality"].get("overall_quality")
            quality_delta = (
                round(float(higher_quality) - float(lower_quality), 4)
                if lower_quality is not None and higher_quality is not None
                else None
            )
            gate_delta = (
                int(higher["hard_gate_passed"]) - int(lower["hard_gate_passed"])
                if higher["hard_gate_passed"] is not None and lower["hard_gate_passed"] is not None
                else None
            )
            lower_gate = lower["hard_gate_passed"]
            higher_gate = higher["hard_gate_passed"]
            if higher["result_status"] == "failed":
                decision = "不建议升级：高档位任务未完成"
            elif lower_gate == 0 and higher_gate == 1:
                decision = "升级带来可用性提升；需结合新增 Token 判断是否只对该任务类型启用"
            elif lower_gate == 0 and higher_gate == 0:
                if quality_delta is not None and quality_delta > 0.05:
                    decision = "质量有所提升但仍不可用；先修复共同 Gate 根因，再讨论升级"
                else:
                    decision = "不建议升级：增加成本但未改变 Hard Gate 结果"
            elif lower_gate == 1 and higher_gate == 1:
                if token_delta > 0 and (quality_delta is None or quality_delta <= 0.02):
                    decision = "不建议默认升级：质量基本持平但成本增加"
                elif quality_delta is not None and quality_delta > 0:
                    decision = "可考虑升级：质量提升且保持通过，需验证边际成本"
                else:
                    decision = "保持低档位：高档位未体现正向质量增益"
            else:
                decision = "样本不可直接比较，需要检查缺失指标"
            marginal = (
                round(quality_delta / token_delta, 6)
                if quality_delta is not None and token_delta > 0
                else None
            )
            comparisons.append(
                {
                    "item_id": item_id,
                    "item_label": lower["item_label"],
                    "comparison": f"{lower['variant']}→{higher['variant']}",
                    "token_delta_k": token_delta,
                    "quality_delta": quality_delta,
                    "hard_gate_delta": gate_delta,
                    "marginal_quality_per_1k_tokens": marginal,
                    "decision": decision,
                }
            )
    return comparisons


def diagnose_experiment(
    live_results: list[dict[str, Any]],
    eval_results: list[dict[str, Any]],
    *,
    item_metadata: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """把真实运行结果和 evaluator 输出连接成 Experiment 诊断。"""
    item_metadata = item_metadata or {}
    live_by_key = {
        (str(item.get("item_id")), str(item.get("variant"))): item
        for item in live_results
    }
    cases: list[dict[str, Any]] = []
    for result in eval_results:
        item_id = str(result.get("item_id") or "")
        variant = str(result.get("variant") or "")
        live = dict(live_by_key.get((item_id, variant)) or {})
        metadata = item_metadata.get(item_id) or {}
        live.update(
            {
                "item_id": item_id,
                "variant": variant,
                "scores": result.get("scores") or [],
                "item_label": metadata.get("sample_reason") or item_id,
            }
        )
        cases.append(diagnose_case(live))
    cases.sort(key=lambda item: (item["item_id"], TIER_ORDER.get(item["variant"], 99)))
    comparisons = _tier_comparisons(cases)

    cause_counts = Counter(
        cause["code"]
        for case in cases
        for cause in case["root_causes"]
        if cause["severity"] == "blocking"
    )
    module_counts = Counter(
        module
        for case in cases
        for cause in case["root_causes"]
        for module in cause["agent_modules"]
    )
    recommendations: list[str] = []
    seen: set[str] = set()
    for case in cases:
        for cause in case["root_causes"]:
            recommendation = cause["recommendation"]
            if recommendation not in seen:
                seen.add(recommendation)
                recommendations.append(recommendation)

    return {
        "ruleset_version": RULESET_VERSION,
        "summary": {
            "case_count": len(cases),
            "workflow_completed_count": sum(case["result_status"] != "failed" for case in cases),
            "hard_gate_pass_count": sum(case["hard_gate_passed"] == 1 for case in cases),
            "top_blocking_root_causes": [
                {"code": code, "case_count": count}
                for code, count in cause_counts.most_common()
            ],
            "agent_module_priority": [
                {"module": module, "diagnosis_count": count}
                for module, count in module_counts.most_common()
            ],
            "optimization_backlog": recommendations,
        },
        "cases": cases,
        "tier_comparisons": comparisons,
    }


def _escape(value: Any) -> str:
    return str(value if value is not None else "-").replace("|", "\\|").replace("\n", " ")


def render_diagnosis_markdown(diagnosis: dict[str, Any]) -> str:
    """生成可直接用于 Agent 迭代的决策型报告。"""
    summary = diagnosis.get("summary") or {}
    cases = diagnosis.get("cases") or []
    comparisons = diagnosis.get("tier_comparisons") or []
    lines = [
        "# Eval 自动根因诊断与 Agent 迭代建议",
        "",
        f"- 诊断规则版本：`{diagnosis.get('ruleset_version')}`",
        f"- Case：{summary.get('case_count', 0)}",
        f"- 工作流完成：{summary.get('workflow_completed_count', 0)}",
        f"- Hard Gate 通过：{summary.get('hard_gate_pass_count', 0)}",
        "",
        "## 决策摘要",
        "",
        "| 题目 | 档位 | 结果 | Token(k) | Hard Gate | 主要根因/发现 | Agent 模块 | 优化建议 |",
        "|---|---|---|---:|---:|---|---|---|",
    ]
    for case in cases:
        gate = (
            "通过"
            if case.get("hard_gate_passed") == 1
            else "失败"
            if case.get("hard_gate_passed") == 0
            else "不可评估"
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape(case.get("item_label")),
                    _escape(case.get("variant")),
                    _escape(case.get("result_status")),
                    f"{float(case.get('total_tokens_k') or 0):.3f}",
                    gate,
                    _escape(case.get("main_finding")),
                    _escape(", ".join(case.get("primary_agent_modules") or []) or "-"),
                    _escape(case.get("optimization_recommendation")),
                ]
            )
            + " |"
        )

    lines += ["", "## 单 Case 根因证据", ""]
    for case in cases:
        lines += [
            f"### {_escape(case.get('item_label'))} / {_escape(case.get('variant'))}",
            "",
            (
                f"- 功能状态：Scope=`{case['agent_function_status']['scope']}`，"
                f"ReportContent=`{case['agent_function_status']['report_content']}`，"
                f"CitationPipeline=`{case['agent_function_status']['citation_pipeline']}`，"
                f"Reviewer=`{case['agent_function_status']['reviewer']}`"
            ),
            (
                f"- 质量：content={case['quality'].get('content_quality')}，"
                f"evidence={case['quality'].get('evidence_quality')}，"
                f"overall={case['quality'].get('overall_quality')}"
            ),
        ]
        if not case.get("root_causes"):
            lines.append("- 未发现阻断级或过程级根因。")
        for cause in case.get("root_causes") or []:
            evidence_text = "; ".join(
                f"{item.get('metric')}={item.get('value')}"
                for item in cause.get("evidence") or []
            )
            lines += [
                (
                    f"- `{cause['code']}`（{cause['severity']}，"
                    f"confidence={cause['confidence']:.2f}）：{cause['title']}"
                ),
                f"  - Agent：{', '.join(cause['agent_modules'])}",
                f"  - 指标证据：{evidence_text}",
                f"  - 优化建议：{cause['recommendation']}",
            ]
        lines.append("")

    lines += [
        "## 同题档位决策",
        "",
        "| 题目 | 比较 | Token 增量(k) | 质量增量 | Gate 增量 | 边际质量/1k Token | 决策 |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for item in comparisons:
        lines.append(
            "| "
            + " | ".join(
                [
                    _escape(item.get("item_label")),
                    _escape(item.get("comparison")),
                    f"{float(item.get('token_delta_k') or 0):+.3f}",
                    (
                        f"{float(item['quality_delta']):+.4f}"
                        if item.get("quality_delta") is not None
                        else "-"
                    ),
                    (
                        f"{int(item['hard_gate_delta']):+d}"
                        if item.get("hard_gate_delta") is not None
                        else "-"
                    ),
                    (
                        f"{float(item['marginal_quality_per_1k_tokens']):+.6f}"
                        if item.get("marginal_quality_per_1k_tokens") is not None
                        else "-"
                    ),
                    _escape(item.get("decision")),
                ]
            )
            + " |"
        )

    lines += ["", "## Agent 模块优化优先级", ""]
    priorities = summary.get("agent_module_priority") or []
    if priorities:
        for index, item in enumerate(priorities, start=1):
            lines.append(
                f"{index}. `{item['module']}`：关联 {item['diagnosis_count']} 条根因诊断。"
            )
    else:
        lines.append("未发现需要优先修复的 Agent 模块。")
    lines += [
        "",
        "> 说明：本报告是规则化归因。它不会把相关性伪装成因果性；"
        "每条结论均保留触发指标，机制是否真正有效仍需同题消融或前后快照实验验证。",
        "",
    ]
    return "\n".join(lines)
