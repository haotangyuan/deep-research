"""Eval MVP v2 — Reviewer Effectiveness 评估器（§9.1）。

诊断 Reviewer 的 Gap 判断有效性。MVP 用 manifest + round_review artifacts 推导：
  - reviewer_token_cost（run 行 reviewer lens 聚合 tokens）
  - review_consensus_predictiveness（continue/report 投票 vs 实际 outcome）

reviewer_gap_precision/recall 需要 Reviewer Gap 标注 + 外部 Eval Gap 比对，
留作校准期（v2 §17 Phase 6）。
"""
from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult


class ReviewerEffectivenessEvaluator(BaseEvaluator):
    name = "reviewer_effectiveness"
    version = "1.0.0"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        run = ctx.run or {}
        # Reviewer token 由 runner 直接从 research_llm_call 聚合。
        reviewer_tokens = int(run.get("reviewer_tokens") or 0)
        consensus = run.get("review_consensus")  # "continue" | "report" | None
        outcome = str(run.get("outcome") or "").lower()
        # 简化预测有效性：consensus=report 且 outcome=success → reviewer 判 report 后确实收敛
        pred_ok = 1 if (consensus == "report" and outcome in ("success", "degraded")) else 0
        return [
            MetricResult(
                metric_name="reviewer_token_cost",
                metric_group="mechanism",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=float(reviewer_tokens),
                reason=f"lenses={len(ctx.reviewer_lenses)}",
            ),
            MetricResult(
                metric_name="reviewer_consensus_predictiveness",
                metric_group="mechanism",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=float(pred_ok),
                label_value=str(consensus),
                reason=f"consensus={consensus} outcome={outcome}",
            ),
        ]
