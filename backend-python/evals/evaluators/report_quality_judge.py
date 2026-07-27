"""Eval MVP v2 — Report Quality Judge（§7.5 Analysis + §7.6 Presentation）。

覆盖 12 核心指标里的 analysis_depth / multi_source_synthesis /
uncertainty_calibration / instruction_following。
"""
from __future__ import annotations

import json

from evals.evaluators.llm_judge_base import LLMJudgeEvaluator


class ReportQualityJudgeEvaluator(LLMJudgeEvaluator):
    name = "report_quality_judge"
    version = "1.0.0"
    metric_group = "analysis"
    metrics = [
        "analysis_depth",
        "multi_source_synthesis",
        "uncertainty_calibration",
        "instruction_following",
    ]

    def user_prompt(self, ctx: EvalContext) -> str:
        return json.dumps(
            {
                "report_excerpt": (ctx.report or "")[:8000],
                "research_brief": ctx.dataset_item.get("query_snapshot") or "",
                "instruction": (
                    "analysis_depth: 分析深度；"
                    "multi_source_synthesis: 多源综合质量；"
                    "uncertainty_calibration: 不确定性是否标注得当；"
                    "instruction_following: 是否遵循题目/格式要求。"
                ),
            },
            ensure_ascii=False,
        )
