"""Eval MVP v2 — Source Quality Judge（§7.4）。

LLM 判定 ``source_quality`` 单指标。对应 v2 §7.4「Source Quality」分组语义：
权威来源占比、来源多样性、官方/权威域名识别、来源与声明匹配度。

基于 source_snapshot 列表（url/title/score）与报告，让 LLM 给 0-1 分。
"""
from __future__ import annotations

import json

from evals.evaluators.base import EvalContext
from evals.evaluators.llm_judge_base import LLMJudgeEvaluator


class SourceQualityJudgeEvaluator(LLMJudgeEvaluator):
    name = "source_quality_judge"
    version = "1.0.0"
    metric_group = "source"
    metrics = ["source_quality"]

    def user_prompt(self, ctx: EvalContext) -> str:
        sources = ctx.sources or []
        src_list = []
        for s in sources[:50]:
            src_list.append(
                {
                    "url": (s.get("url") or "")[:256],
                    "title": (s.get("title") or "")[:128],
                    "score": s.get("score"),
                }
            )
        return json.dumps(
            {
                "report_excerpt": (ctx.report or "")[:6000],
                "sources": src_list,
                "instruction": (
                    "source_quality: 综合来源权威性（官方/学术/权威媒体占比）、"
                    "来源多样性（不同域名/类型）、来源与报告声明的匹配度。"
                    "无来源或来源质量低给低分。"
                ),
            },
            ensure_ascii=False,
        )
