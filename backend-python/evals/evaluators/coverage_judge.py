"""Eval MVP v2 — Coverage Judge（§7.2 Information Recall）。

LLM 判定 required_point_coverage / critical_fact_recall。
依赖 dataset_item 的 required_points / reference_facts。
"""
from __future__ import annotations

import json

from evals.evaluators.llm_judge_base import LLMJudgeEvaluator


class CoverageJudgeEvaluator(LLMJudgeEvaluator):
    name = "coverage_judge"
    version = "1.0.0"
    metric_group = "recall"
    metrics = [
        "required_point_coverage",
        "critical_fact_recall",
    ]

    def user_prompt(self, ctx: EvalContext) -> str:
        return json.dumps(
            {
                "report_excerpt": (ctx.report or "")[:8000],
                "required_points": ctx.dataset_item.get("required_points_json") or [],
                "reference_facts": ctx.dataset_item.get("reference_facts_json") or [],
                "instruction": (
                    "required_point_coverage: 报告覆盖必须点的比例；"
                    "critical_fact_recall: 关键参考事实是否被准确复述。"
                ),
            },
            ensure_ascii=False,
        )
