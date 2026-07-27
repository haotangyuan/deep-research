"""Eval MVP v2 — Claim Extractor（离线生成 Claim-Citation Manifest）。

复用 ``app.application.claim_manifest.extract_claims_from_report``，把最终报告 Markdown
结构化为 manifest。v2 §6.4：MVP manifest 由 extractor 离线生成；报告 Agent 同步输出留给
后续。

作为 evaluator，它不产分数，而是产 ``claim_manifest``（metric_group=meta）与
``critical_claim_count``、``supported_claim_count`` 两个可聚合指标。
"""
from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult


class ClaimExtractorEvaluator(BaseEvaluator):
    name = "claim_extractor"
    version = "1.0.0"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        from app.application.claim_manifest import extract_claims_from_report

        # 若 runner 已注入 manifest（从 research_claim_manifest 表读），则直接复用；
        # 否则现场从 report 抽取（离线 replay 路径）。
        manifest = ctx.claim_manifest
        if not manifest:
            manifest = extract_claims_from_report(ctx.report)
            ctx.claim_manifest = manifest  # 供后续 evaluator 复用

        total_claims = len(manifest)
        critical_claims = sum(1 for c in manifest if c.get("importance") == "critical")
        supported_claims = sum(
            1
            for c in manifest
            if any(cit.get("citation_url") for cit in (c.get("citations") or []))
        )
        return [
            MetricResult(
                metric_name="critical_claim_count",
                metric_group="meta",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=float(critical_claims),
                reason=f"total_claims={total_claims}",
            ),
            MetricResult(
                metric_name="supported_claim_count",
                metric_group="factuality",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=float(supported_claims),
                passed=1 if supported_claims == total_claims else 0,
                reason=f"supported={supported_claims}/{total_claims}",
            ),
        ]
