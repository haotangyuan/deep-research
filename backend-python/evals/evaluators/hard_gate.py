r"""Eval MVP v2 — Hard Gate 聚合器（§8.1 共同 Hard Gate + §18 失败原因码可查询）。

Hard Gate 不是普通 evaluator：它依赖其他 evaluator 已产出的指标，做**组合判定**，
写回 ``eval_case_run.gate_passed`` + ``failure_reasons_json``（§6.9 列）。

失败原因码语义来自 v2 §17.2 验收：「悬空引用、不支持 Claim、漏答、关键事实错误」，
加 workflow/report 两个基础失败：

- ``workflow_failed``       ← workflow_completed.passed == 0
- ``report_empty``          ← report_non_empty.passed == 0
- ``dangling_citation``     ← citation_traceability.passed == 0（有 claim 但无 url）
- ``unsupported_critical_claim`` ← unsupported_critical_claim_count.score_value > 0
- ``missing_required_points``    ← required_point_coverage.passed == 0（需 judge；离线 None 跳过）
- ``critical_fact_error``       ← claim_factuality.passed == 0（需 judge；离线 None 跳过）

Gate 规则（§8.1）：workflow 完成 + 报告非空 + 无悬空引用 + 无未支持 critical claim
+ required_point_coverage 通过 + claim_factuality 通过。
任一基础/事实失败 → gate_passed=0。
judge 类指标在离线（无 chat_fn）时为 None，不参与 gate 判定（gate 只判确定性可得的部分），
但 ``reason`` 里会标注「judge 未运行，gate 仅基于确定性指标」。
"""
from __future__ import annotations

from typing import Any

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult

# gate 触发的失败原因码映射
_FAILURE_RULES: list[tuple[str, str]] = [
    ("workflow_failed", "workflow_completed"),
    ("report_empty", "report_non_empty"),
    ("dangling_citation", "citation_traceability"),
]

# 阈值类：score_value > 0 触发失败
_COUNT_FAILURES: list[tuple[str, str]] = [
    ("unsupported_critical_claim", "unsupported_critical_claim_count"),
]

# judge 类（passed 可能为 None，None 不参与判定）
_JUDGE_FAILURES: list[tuple[str, str]] = [
    ("missing_required_points", "required_point_coverage"),
    ("critical_fact_error", "claim_factuality"),
]


class HardGateEvaluator(BaseEvaluator):
    """Hard Gate 聚合器。读 ``ctx`` 上其他 evaluator 已产出的 MetricResult（通过 ``prior_results``），
    做 gate 判定，产 ``hard_gate_passed`` 指标 + ``failure_reason_codes`` 标签。
    """

    name = "hard_gate"
    version = "1.0.0"
    metric_group = "gate"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        prior: dict[str, MetricResult] = ctx.prior_results  # type: ignore[attr-defined]
        failures: list[str] = []
        judge_ran: dict[str, bool] = {}

        for code, metric_name in _FAILURE_RULES:
            r = prior.get(metric_name)
            if r is not None and r.passed == 0:
                failures.append(code)

        for code, metric_name in _COUNT_FAILURES:
            r = prior.get(metric_name)
            if r is not None and isinstance(r.score_value, (int, float)) and r.score_value > 0:
                failures.append(code)

        for code, metric_name in _JUDGE_FAILURES:
            r = prior.get(metric_name)
            if r is None:
                judge_ran[code] = False
                continue
            # judge 未运行时 passed=None（离线无 chat_fn）→ 不参与判定，记 missing
            if r.passed is None:
                judge_ran[code] = False
                continue
            judge_ran[code] = True
            if r.passed == 0:
                failures.append(code)

        gate_passed = 0 if failures else 1
        judge_missing = [c for c, ran in judge_ran.items() if not ran]
        if judge_missing:
            reason = (
                f"gate_passed={gate_passed}（仅基于确定性指标；judge 未运行: {','.join(judge_missing)}，"
                "离线判定可能偏宽，全量判定需注入 chat_fn）"
            )
        else:
            reason = f"gate_passed={gate_passed}, failure_codes={failures or '[]'}"

        return [
            MetricResult(
                metric_name="hard_gate_passed",
                metric_group=self.metric_group,
                evaluator_name=self.name,
                evaluator_version=self.version,
                score_value=float(gate_passed),
                passed=gate_passed,
                judge_model=None,
                reason=reason,
                details={"failure_reason_codes": failures, "judge_missing": judge_missing},
            ),
        ]
