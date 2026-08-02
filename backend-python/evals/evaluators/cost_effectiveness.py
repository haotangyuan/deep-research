"""Eval MVP v2 — Cost Effectiveness 评估器（§12）。

cost_per_pass / incremental_cost_per_success / marginal_quality_per_1k_tokens。
需 runner 注入成本与 gate passed 计数。无 LLM，纯计算。
"""
from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult


class CostEffectivenessEvaluator(BaseEvaluator):
    name = "cost_effectiveness"
    version = "1.1.0"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        run = ctx.run or {}
        raw_cost = run.get("estimated_cost")
        cost = float(raw_cost) if isinstance(raw_cost, (int, float)) else None
        raw_gate = run.get("gate_passed")
        gate_passed = int(raw_gate) if raw_gate in (0, 1) else None
        tokens = int(run.get("input_tokens") or 0) + int(run.get("output_tokens") or 0)
        results: list[MetricResult] = []
        # 单 case 仅在 Gate 已经完成且货币成本可得时计算；缺值不能伪装成 0。
        cost_per_pass = cost if gate_passed == 1 and cost is not None else None
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
        # 货币单价未配置时保留 None；正式档位比较至少仍有 total_tokens 这一事实成本。
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
        tokens_k = tokens / 1000.0
        results.append(
            MetricResult(
                metric_name="total_tokens_k",
                metric_group="cost",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=tokens_k,
                reason=(
                    f"input_tokens={int(run.get('input_tokens') or 0)} "
                    f"output_tokens={int(run.get('output_tokens') or 0)}"
                ),
            )
        )
        results.append(
            MetricResult(
                metric_name="tokens_per_pass_k",
                metric_group="cost",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=tokens_k if gate_passed == 1 else None,
                reason=f"tokens={tokens} gate_passed={gate_passed}",
            )
        )
        return results
