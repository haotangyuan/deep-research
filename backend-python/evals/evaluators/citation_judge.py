"""Eval MVP v2 — Citation/Factuality Judge（§7.3）。

LLM 判定 claim_factuality / citation_completeness / citation_correctness。
基于 claim-citation manifest 与报告，输出每指标分数。
"""
from __future__ import annotations

import json

from evals.evaluators.llm_judge_base import LLMJudgeEvaluator
from evals.evaluators.base import EvalContext


class CitationJudgeEvaluator(LLMJudgeEvaluator):
    name = "citation_judge"
    version = "1.0.0"
    metric_group = "factuality"
    metrics = [
        "claim_factuality",
        "citation_completeness",
        "citation_correctness",
    ]

    def user_prompt(self, ctx: EvalContext) -> str:
        manifest = ctx.claim_manifest or []
        # 把 manifest 压成 claim-citation 对摘要，避免爆 token
        pairs = []
        for c in manifest[:50]:
            cites = c.get("citations") or []
            urls = [cit.get("citation_url") for cit in cites if cit.get("citation_url")]
            pairs.append({"claim": (c.get("claim_text") or "")[:200], "urls": urls})
        return json.dumps(
            {
                "report_excerpt": (ctx.report or "")[:6000],
                "claim_citations": pairs,
                "instruction": (
                    "claim_factuality: 关键声明是否属实；"
                    "citation_completeness: 需引用处是否齐全；"
                    "citation_correctness: 引用是否真正支持对应声明。"
                ),
            },
            ensure_ascii=False,
        )
