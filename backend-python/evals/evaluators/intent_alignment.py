"""ScopeAgent 意图与澄清决策评价。

结果与过程联合判断：
- Dataset 冻结 expected_intent；
- research_brief Artifact 提供实际 research_type / clarification；
- 若 Scope 在 Brief 生成前就进入等待态，则从 research_run.outcome=hitl_wait
  识别实际发生了澄清，仍可判断澄清决策是否正确。
"""
from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult


class IntentAlignmentEvaluator(BaseEvaluator):
    name = "intent_alignment"
    version = "1.0.0"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        contract = ctx.dataset_item.get("evaluation_contract_json") or {}
        expected = contract.get("expected_intent") or {}
        expected_type = expected.get("research_type")
        expected_clarify = expected.get("should_clarify")

        actual_type = ctx.intent_metadata.get("research_type")
        clarification = ctx.intent_metadata.get("clarification") or {}
        actual_clarify = clarification.get("needClarification")
        if actual_clarify is None and str((ctx.run or {}).get("outcome") or "").lower() == "hitl_wait":
            actual_clarify = True

        type_score = (
            float(actual_type == expected_type)
            if expected_type is not None and actual_type is not None
            else None
        )
        clarify_score = (
            float(bool(actual_clarify) == bool(expected_clarify))
            if expected_clarify is not None and actual_clarify is not None
            else None
        )
        available_scores = [score for score in (type_score, clarify_score) if score is not None]
        overall = min(available_scores) if available_scores else None

        return [
            MetricResult(
                metric_name="intent_type_accuracy",
                metric_group="intent",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=type_score,
                passed=int(type_score == 1.0) if type_score is not None else None,
                label_value=str(actual_type) if actual_type is not None else None,
                reason=f"expected={expected_type} actual={actual_type}",
            ),
            MetricResult(
                metric_name="clarification_decision_accuracy",
                metric_group="intent",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=clarify_score,
                passed=int(clarify_score == 1.0) if clarify_score is not None else None,
                label_value=str(actual_clarify).lower() if actual_clarify is not None else None,
                reason=f"expected_should_clarify={expected_clarify} actual={actual_clarify}",
            ),
            MetricResult(
                metric_name="intent_alignment",
                metric_group="intent",
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=overall,
                passed=int(overall == 1.0) if overall is not None else None,
                reason=(
                    f"type_accuracy={type_score} "
                    f"clarification_decision_accuracy={clarify_score}"
                ),
                details={
                    "expected_intent": expected,
                    "actual_research_type": actual_type,
                    "actual_should_clarify": actual_clarify,
                },
            ),
        ]
