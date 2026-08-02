"""Eval MVP v2 — 确定性 Evaluator（Hard Gate + 引用可追溯性）。

不调用 LLM，纯规则。覆盖 v2 §7.1 Hard Gate 的机器可判部分与 §7.3 引用指标的可计算项：
  - workflow_completed / report_non_empty
  - citation_parse_rate
  - citation_traceability
  - effective_citation_count
  - unsupported_critical_claim_count（基于 manifest：critical claim 但无 citation_url）

LLM 才能判的（claim_factuality 真伪、citation_correctness 正确性）留给 citation_judge。
"""
from __future__ import annotations

import re
from typing import Any

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult

_NUMERIC_CITATION = re.compile(r"\[(\d+)\]")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _report_status(ctx: EvalContext) -> str:
    return str((ctx.run or {}).get("outcome") or "").lower()


class DeterministicEvaluator(BaseEvaluator):
    name = "deterministic"
    version = "1.0.0"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        report = ctx.report or ""
        cr = ctx.case_run_id
        results: list[MetricResult] = []

        # --- Hard Gate（§7.1）---
        outcome = _report_status(ctx)
        workflow_completed = outcome in ("success", "degraded")
        results.append(
            MetricResult(
                metric_name="workflow_completed",
                metric_group="gate",
                evaluator_name=self.name,
                evaluator_version=self.version,
                passed=1 if workflow_completed else 0,
                label_value="1" if workflow_completed else "0",
                reason=f"outcome={outcome}",
            )
        )
        report_non_empty = len(report.strip()) > 0
        results.append(
            MetricResult(
                metric_name="report_non_empty",
                metric_group="gate",
                evaluator_name=self.name,
                evaluator_version=self.version,
                passed=1 if report_non_empty else 0,
                label_value="1" if report_non_empty else "0",
            )
        )

        # --- 引用解析 ---
        md_urls = {m.group(2) for m in _MD_LINK.finditer(report)}
        num_markers = {m.group(1) for m in _NUMERIC_CITATION.finditer(report)}
        total_citation_markers = len(md_urls) + len(num_markers)
        # parse_rate = 1 表示所有 [n] 标记都能解析到 URL（MVP：要求每个 [n] 都有对应 md 链接）
        # 简化口径：无 [n] 标记 → 1（无悬空）；有 [n] 但无 url → 0
        if num_markers and not md_urls:
            parse_rate = 0.0
        else:
            parse_rate = 1.0
        results.append(
            MetricResult(
                metric_name="citation_parse_rate",
                metric_group="factuality",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=parse_rate,
                passed=1 if parse_rate >= 1.0 else 0,
                reason=f"md_urls={len(md_urls)} numeric_markers={len(num_markers)}",
            )
        )

        # effective_citation_count = 去重 URL 数 + 0.5×悬空 numeric 标记（半分）
        dangling_numeric = num_markers - md_urls  # 有 [n] 但无对应 url
        effective = float(len(md_urls) + 0.5 * len(dangling_numeric))
        results.append(
            MetricResult(
                metric_name="effective_citation_count",
                metric_group="factuality",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=effective,
                reason=f"md_urls={len(md_urls)} numeric={len(num_markers)}",
            )
        )

        # citation_traceability：manifest 中 claim-citation 对里 citation_url 非空比例
        manifest = ctx.claim_manifest or []
        total_claims = len(manifest)
        cited = sum(
            1
            for c in manifest
            if any((cit.get("citation_url") for cit in (c.get("citations") or [])))
        )
        # 无 manifest 不是“100% 可追溯”，而是不可评估；否则空报告会把档位均值虚高。
        trace_rate = (cited / total_claims) if total_claims else None
        results.append(
            MetricResult(
                metric_name="citation_traceability",
                metric_group="factuality",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=trace_rate,
                passed=(1 if trace_rate >= 0.95 else 0) if trace_rate is not None else None,
                reason=(
                    f"cited={cited}/{total_claims}"
                    if total_claims
                    else "claim_manifest 为空，citation_traceability 不可评估"
                ),
            )
        )

        # unsupported_critical_claim_count：critical claim 但无任何 citation_url
        unsupported_critical = sum(
            1
            for c in manifest
            if c.get("importance") == "critical"
            and not any((cit.get("citation_url") for cit in (c.get("citations") or [])))
        )
        results.append(
            MetricResult(
                metric_name="unsupported_critical_claim_count",
                metric_group="factuality",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=float(unsupported_critical),
                passed=1 if unsupported_critical == 0 else 0,
                reason=f"critical claims without citation_url",
            )
        )

        return results
