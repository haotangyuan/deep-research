"""Eval MVP v2 — Cost Effectiveness 评估器（§12）。

cost_per_pass / incremental_cost_per_success / marginal_quality_per_1k_tokens。
需 runner 注入成本与 gate passed 计数。无 LLM，纯计算。
"""
from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult


class CostEffectivenessEvaluator(BaseEvaluator):
    name = "cost_effectiveness"
    version = "1.0.0"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        run = ctx.run or {}
        cost = float(run.get("estimated_cost") or 0)
        gate_passed = int(run.get("gate_passed") or 0)
        tokens = int(run.get("input_tokens") or 0) + int(run.get("output_tokens") or 0)
        results: list[MetricResult] = []
        # cost_per_pass = 总成本 / gate passed cases（单 case 视角：gate 通过则成本，否则 0）
        cost_per_pass = cost if gate_passed else 0.0
        results.append(
            MetricResult(
                metric_name="cost_per_pass",
                metric_group="cost",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=cost_per_pass,
                reason=f"cost={cost} gate_passed={gate_passed}",
            )
        )
        # pair 比较的 incremental_cost_per_success 由 runner 聚合，evaluator 只回单 case 成本
        results.append(
            MetricResult(
                metric_name="total_cost",
                metric_group="cost",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=cost,
                reason=f"tokens={tokens}",
            )
        )
        return results
