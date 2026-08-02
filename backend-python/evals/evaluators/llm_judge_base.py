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
        user_prompt = self.user_prompt(ctx)
        scores: dict[str, Any] = {}
        reasons: dict[str, str] = {}
        raw = ""
        # Judge 偶尔返回可解析 JSON 但漏掉某个 metric。最多补问一次，避免把协议
        # 失败误当成报告得分缺失；第二次仍不完整时保留 None，绝不默认通过。
        for attempt in range(2):
            retry_note = ""
            if attempt:
                missing = [metric for metric in self.metrics if not isinstance(scores.get(metric), (int, float))]
                retry_note = (
                    "\n上一次输出不完整。请重新输出完整 JSON，必须包含这些缺失指标："
                    + ", ".join(missing)
                    + f"\n上一次输出：{raw[:1000]}"
                )
            raw = await self.chat(JUDGE_SYSTEM_PROMPT, user_prompt + retry_note)
            parsed = parse_json_safe(raw) or {}
            parsed_scores = parsed.get("metrics") or {}
            parsed_reasons = parsed.get("reasons") or {}
            if isinstance(parsed_scores, dict):
                scores.update(parsed_scores)
            if isinstance(parsed_reasons, dict):
                reasons.update(parsed_reasons)
            if all(isinstance(scores.get(metric), (int, float)) for metric in self.metrics):
                break
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
                    evaluator_version=f"{self.version}-retry1",
                    score_value=score,
                    passed=passed,
                    judge_model=self.judge_model,
                    reason=reasons.get(metric),
                )
            )
        return results
