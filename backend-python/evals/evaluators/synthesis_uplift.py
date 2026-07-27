r"""Eval MVP v2 — HIGH Synthesis Uplift 评估器（§8.3）。

对应 v2 §8.3「HIGH」指标：

- ``best_draft_quality``     : 双 draft 中较优者的质量代理分
- ``synthesis_uplift``       : synthesis 质量 - best_draft_quality
                                 （§8.3: ``synthesis_uplift = final_synthesis_quality - max(draft_quality)``）
- ``draft_complementarity``  : 双 draft 内容互补度（union claim / sum claim）

口径（MVP 简化）：
- 文档 §8.3 把 ``draft_quality`` / ``synthesis_quality`` 定义为 judge 给的分，
  但 ``_judge_draft`` 的 ``scores`` 当前**未落库**到 artifact metadata（只有文本落了）。
  因此本 evaluator 退化为以 ``claim + citation 密度`` 作质量代理：
    quality_proxy = (claim_count + citation_count) / max(chars, 1) * 1000
  （每千字 claim+citation 数，跨长度可比；claim/citation 载体定义同 section_loss）
- ``draft_complementarity`` = union(两 draft 的 claim) / sum(两 draft 的 claim)，
  >1 表示有互补（union 比 sum 大不可能，所以用 union / max(sum,1) 限定 [0,1]，
  实际用 unique_union / total_unique 表示互补）。
- 缺字段限制写入 ``reason``，§17 对账识别这是密度代理非 judge 分。

长期 draft judge 分落库后，应改为读 artifact metadata 的 quality_score，并升 version。
"""
from __future__ import annotations

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.evaluators.section_loss import _claims, _citations
from evals.schemas import MetricResult


def _quality_proxy(text: str) -> float:
    """质量代理：claim + citation 绝对计数（非密度）。

    用绝对数而非「每千字密度」：synthesis 融合两 draft 后内容更全，绝对 claim+citation
    数应 ≥ 任一单 draft。密度指标对长度敏感（短文本密度虚高），不适合跨长度比较 uplift。
    """
    if not text:
        return 0.0
    claims = _claims(text)
    cits = _citations(text)
    return float(len(claims) + len(cits))


class SynthesisUpliftEvaluator(BaseEvaluator):
    """HIGH 双 Draft / Synthesis 质量增量评估器。产 §8.3 三个指标。"""

    name = "synthesis_uplift"
    version = "1.0.0"
    metric_group = "mechanism"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        drafts = ctx.report_drafts or []
        synthesis = ctx.report_synthesis or ""
        results: list[MetricResult] = []

        # 非 HIGH 双 draft 路径（无 draft 或单 draft）→ 三指标 None
        if len(drafts) < 2:
            for name in ("best_draft_quality", "synthesis_uplift", "draft_complementarity"):
                results.append(
                    MetricResult(
                        metric_name=name,
                        metric_group=self.metric_group,
                        evaluator_name=self.name,
                        evaluator_version=self.version,
                        score_value=None,
                        passed=None,
                        judge_model=None,
                        reason=f"非 HIGH 双 draft 路径（draft_count={len(drafts)}），跳过",
                        details={"draft_count": len(drafts)},
                    )
                )
            return results

        qualities = [(d.get("angle") or "unknown", _quality_proxy(d.get("content") or "")) for d in drafts]
        best_angle, best_q = max(qualities, key=lambda x: x[1])
        synth_q = _quality_proxy(synthesis) if synthesis else 0.0
        uplift = round(synth_q - best_q, 4)

        results.append(
            MetricResult(
                metric_name="best_draft_quality",
                metric_group=self.metric_group,
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=best_q,
                passed=1 if best_q > 0 else 0,
                judge_model=None,
                reason=f"best draft={best_angle} quality_proxy={best_q}（claim+citation 密度代理，非 judge 分）",
                details={"angle": best_angle, "all_qualities": dict(qualities)},
            )
        )
        results.append(
            MetricResult(
                metric_name="synthesis_uplift",
                metric_group=self.metric_group,
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=uplift,
                passed=1 if uplift > 0 else 0,
                judge_model=None,
                reason=(
                    f"uplift={uplift}（synth_q={synth_q} - best_draft_q={best_q}）。"
                    "MVP draft judge 分未落库，用密度代理；正值表示 synthesis 比最优 draft 更密。"
                ),
                details={"synthesis_quality": synth_q, "best_draft_quality": best_q},
            )
        )

        # draft complementarity：两 draft claim 的并集 / 总唯一 claim
        all_claim_sets = [set(_claims(d.get("content") or "")) for d in drafts]
        union = set().union(*all_claim_sets) if all_claim_sets else set()
        total_unique = len(union)
        # 互补度 = union 中只被一个 draft 贡献的比例（互补性越高越值得融合）
        only_one = sum(
            1
            for c in union
            if sum(1 for cs in all_claim_sets if c in cs) == 1
        )
        complementarity = round(only_one / total_unique, 4) if total_unique else 0.0
        results.append(
            MetricResult(
                metric_name="draft_complementarity",
                metric_group=self.metric_group,
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=complementarity,
                passed=1 if complementarity >= 0.3 else 0,
                judge_model=None,
                reason=f"两 draft 互补度={complementarity}（only-in-one / union，越高越值得融合）",
                details={"union_claim_count": total_unique, "only_one_count": only_one},
            )
        )
        return results
