"""Eval MVP v2 — LLM Judge 评估器基类。

统一 prompt 模板：让 LLM 按 metric 列表输出 ``{"metric": score, ...}`` JSON。
子类只定义 system prompt 片段与 metric 列表。便于测试 monkeypatch chat_fn。
"""
from __future__ import annotations

import json
from typing import Any

from evals.evaluators.base import BaseEvaluator, EvalContext, parse_json_safe
from evals.schemas import MetricResult

JUDGE_SYSTEM_PROMPT = """你是研究报告评审。按指标给 0-1 分，并给 1-2 句 reason。
严格输出 JSON：{"metrics": {metric_name: score, ...}, "reasons": {metric_name: str}}。
不要输出 JSON 以外的内容。"""


class LLMJudgeEvaluator(BaseEvaluator):
    """子类设置 ``metrics``（list[str]）与 ``metric_group``，可选重写 user_prompt。"""

    metrics: list[str] = []
    metric_group: str = "analysis"

    def user_prompt(self, ctx: EvalContext) -> str:
        report = ctx.report or ""
        required = ctx.dataset_item.get("required_points_json") or "（未提供）"
        return json.dumps(
            {
                "report_excerpt": report[:8000],
                "required_points": required,
                "claim_manifest_size": len(ctx.claim_manifest),
            },
            ensure_ascii=False,
        )

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        if not self.metrics:
            return []
        raw = await self.chat(JUDGE_SYSTEM_PROMPT, self.user_prompt(ctx))
        parsed = parse_json_safe(raw) or {}
        scores: dict[str, Any] = parsed.get("metrics") or {}
        reasons: dict[str, str] = parsed.get("reasons") or {}
        results: list[MetricResult] = []
        for metric in self.metrics:
            val = scores.get(metric)
            score = None
            passed = None
            if isinstance(val, (int, float)):
                score = float(val)
                passed = 1 if score >= 0.6 else 0
            results.append(
                MetricResult(
                    metric_name=metric,
                    metric_group=self.metric_group,
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=score,
                    passed=passed,
                    judge_model=self.judge_model,
                    reason=reasons.get(metric),
                )
            )
        return results
