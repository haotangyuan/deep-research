"""Eval MVP v2 — Round Delta 评估器（§9.2）。

跨轮增量价值：quality_delta_per_round / marginal_quality_per_1k_tokens / gap_closure_rate。
每轮 quality/gaps/tokens 来自 research_span_attribute（trace 标量本地落地），
由 runner 装配进 ``ctx.review_attributes``（{round_no: {attr_key: value}}）。
"""
from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult

# 各维度 score 前缀，用于从 review_attributes 派生每轮短板质量
_SCORE_DIMS = ("coverage", "evidence", "freshness", "sourceDiversity", "consistency")


class RoundDeltaEvaluator(BaseEvaluator):
    name = "round_delta"
    version = "1.0.0"

    @staticmethod
    def _round_quality(attrs: dict[str, object]) -> float | None:
        """取该轮各维度 review.score.{dim} 的短板 min 作为质量分。"""
        scores = [
            float(attrs[f"review.score.{dim}"])
            for dim in _SCORE_DIMS
            if isinstance(attrs.get(f"review.score.{dim}"), (int, float))
        ]
        return min(scores) if scores else None

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        # review_attributes: {round_no: {attr_key: value}}，按 round_no 升序
        rounds = sorted(ctx.review_attributes.items()) if ctx.review_attributes else []
        results: list[MetricResult] = []
        if len(rounds) >= 2:
            prev_no, prev_attrs = rounds[-2]
            cur_no, cur_attrs = rounds[-1]
            prev_q = self._round_quality(prev_attrs)
            cur_q = self._round_quality(cur_attrs)
            # 任一轮缺维度分则无法算 delta，记 None + reason
            if prev_q is None or cur_q is None:
                results.append(
                    MetricResult(
                        metric_name="quality_delta_per_round",
                        metric_group="mechanism",
                        evaluator_name=self.name,
                        evaluator_version=self.version,
                        score_value=None,
                        reason=f"missing score dims prev_round={prev_no} cur_round={cur_no}",
                    )
                )
                return results
            quality_delta = cur_q - prev_q
            results.append(
                MetricResult(
                    metric_name="quality_delta_per_round",
                    metric_group="mechanism",
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=quality_delta,
                    reason=f"prev_round={prev_no} q={prev_q} cur_round={cur_no} q={cur_q}",
                )
            )
            cur_tokens = int(cur_attrs.get("review.tokens") or 0)
            marginal = (quality_delta / cur_tokens * 1000) if cur_tokens else 0.0
            results.append(
                MetricResult(
                    metric_name="marginal_quality_per_1k_tokens",
                    metric_group="mechanism",
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=marginal,
                    reason=f"delta={quality_delta} tokens={cur_tokens}",
                )
            )
            # gap_closure_rate：上轮 gaps 与本轮 gaps 之差近似闭合量
            prev_gaps = int(prev_attrs.get("review.gaps.count") or 0)
            cur_gaps = int(cur_attrs.get("review.gaps.count") or 0)
            closed = max(0, prev_gaps - cur_gaps)
            closure = (closed / prev_gaps) if prev_gaps else 0.0
            results.append(
                MetricResult(
                    metric_name="gap_closure_rate",
                    metric_group="mechanism",
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=closure,
                    reason=f"closed={closed}/{prev_gaps} prev_round={prev_no} cur_round={cur_no}",
                )
            )
        return results
