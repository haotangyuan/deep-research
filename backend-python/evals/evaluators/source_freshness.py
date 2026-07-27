r"""Eval MVP v2 — Source Freshness 评估器（确定性）。

对应 v2 §7.4「Source Quality」分组下的 ``source_freshness`` 指标。

口径（MVP 简化，文档 §7.4 只列指标名，无独立定义段）：

- 理想口径：来源的 ``published_at`` / ``fetched_at`` 相对 ``as_of_date`` 的新鲜度。
- MVP 现实约束：``research_artifact(type=source_snapshot)`` 当前只落 ``metadata={url,title,score}``
  （context_writer.py:110），**没有** ``published_at`` / ``fetched_at`` / ``http_status``。
  因此本 evaluator 退化为「来源有效度近似」：
    1. 来源数 >= 阈值（默认 3）→ 否则 freshness 受样本不足拖累；
    2. 有效来源（score>0.5 或域名非空）占比；
    3. 域名去重率（避免同一域名重复刷量）。
- 缺字段限制写入 ``reason``，便于 §17 对账时识别「这是近似值，非真 freshness」。

长期 source_snapshot 补 ``published_at`` 后，本 evaluator 应改为按 ``as_of_date`` 算真实时效，
并升级 ``evaluator_version``。
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult

_MIN_SOURCES = 3
_VALID_SCORE_THRESHOLD = 0.5


def _domain(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:  # noqa: BLE001
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


class SourceFreshnessEvaluator(BaseEvaluator):
    """来源新鲜度（确定性近似）。产 ``source_freshness`` 单指标。"""

    name = "source_freshness"
    version = "1.0.0"
    metric_group = "source"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        sources = ctx.sources or []
        n = len(sources)
        if n == 0:
            return [
                MetricResult(
                    metric_name="source_freshness",
                    metric_group=self.metric_group,
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=0.0,
                    passed=0,
                    judge_model=None,
                    reason="无来源快照，source_freshness=0",
                    details={"source_count": 0},
                )
            ]

        valid = 0
        domains: list[str] = []
        for s in sources:
            url = (s.get("url") or "").strip()
            score = s.get("score")
            domain = _domain(url)
            if domain:
                domains.append(domain)
            is_valid = (isinstance(score, (int, float)) and score > _VALID_SCORE_THRESHOLD) or bool(domain)
            if is_valid:
                valid += 1

        valid_ratio = valid / n
        unique_domains = len(set(domains))
        domain_diversity = unique_domains / n if n else 0.0

        # 综合分：有效来源占比为主，域名多样性为辅；样本不足扣分
        score = round(0.7 * valid_ratio + 0.3 * domain_diversity, 4)
        if n < _MIN_SOURCES:
            score = round(score * (n / _MIN_SOURCES), 4)

        passed = 1 if score >= 0.6 else 0
        reason = (
            f"source_freshness≈{score}（近似：valid_ratio={valid_ratio:.2f}, "
            f"domain_diversity={domain_diversity:.2f}）。"
            "MVP source_snapshot 未落 published_at/fetched_at，此为有效度近似，非真时效。"
        )
        return [
            MetricResult(
                metric_name="source_freshness",
                metric_group=self.metric_group,
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=score,
                passed=passed,
                judge_model=None,
                reason=reason,
                details={
                    "source_count": n,
                    "valid_source_count": valid,
                    "valid_ratio": round(valid_ratio, 4),
                    "unique_domain_count": unique_domains,
                    "domain_diversity": round(domain_diversity, 4),
                },
            )
        ]
