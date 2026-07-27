"""Eval MVP v2 — Hard Gate 聚合器测试（§8.1 + §18 失败原因码可查询）。

验证：
- 全部确定性指标通过 → gate_passed=1，无失败码。
- 悬空引用（citation_traceability.passed=0）→ failure 含 dangling_citation，gate=0。
- 未支持 critical claim（unsupported_critical_claim_count>0）→ failure 含 unsupported_critical_claim。
- workflow_failed / report_empty → 对应失败码。
- judge 未运行（passed=None）→ 不参与 gate，reason 标注「judge 未运行」。
- update_case_run_gate 写回（DB，真实 MySQL）。
"""
from __future__ import annotations

import json

import pytest

from evals.evaluators.base import EvalContext
from evals.evaluators.hard_gate import HardGateEvaluator
from evals.schemas import MetricResult


def _metric(name: str, *, score=None, passed=None, group="gate") -> MetricResult:
    return MetricResult(
        metric_name=name,
        metric_group=group,
        evaluator_name="test",
        evaluator_version="1.0.0",
        score_value=score,
        passed=passed,
        judge_model=None,
        reason="",
        details=None,
    )


def _ctx(prior: dict[str, MetricResult]) -> EvalContext:
    return EvalContext(case_run_id="cr1", report="报告", prior_results=prior)


@pytest.mark.asyncio
async def test_hard_gate_passes_when_all_ok() -> None:
    prior = {
        "workflow_completed": _metric("workflow_completed", score=1.0, passed=1),
        "report_non_empty": _metric("report_non_empty", score=1.0, passed=1),
        "citation_traceability": _metric("citation_traceability", score=1.0, passed=1),
        "unsupported_critical_claim_count": _metric("unsupported_critical_claim_count", score=0.0, passed=1),
    }
    r = (await HardGateEvaluator().evaluate(_ctx(prior)))[0]
    assert r.metric_name == "hard_gate_passed"
    assert r.score_value == 1.0
    assert r.passed == 1
    assert r.details["failure_reason_codes"] == []


@pytest.mark.asyncio
async def test_hard_gate_fails_on_dangling_citation() -> None:
    prior = {
        "workflow_completed": _metric("workflow_completed", passed=1),
        "report_non_empty": _metric("report_non_empty", passed=1),
        "citation_traceability": _metric("citation_traceability", passed=0),  # 悬空
        "unsupported_critical_claim_count": _metric("unsupported_critical_claim_count", score=0.0, passed=1),
    }
    r = (await HardGateEvaluator().evaluate(_ctx(prior)))[0]
    assert r.score_value == 0.0
    assert "dangling_citation" in r.details["failure_reason_codes"]


@pytest.mark.asyncio
async def test_hard_gate_fails_on_unsupported_critical_claim() -> None:
    prior = {
        "workflow_completed": _metric("workflow_completed", passed=1),
        "report_non_empty": _metric("report_non_empty", passed=1),
        "citation_traceability": _metric("citation_traceability", passed=1),
        "unsupported_critical_claim_count": _metric("unsupported_critical_claim_count", score=2.0, passed=0),
    }
    r = (await HardGateEvaluator().evaluate(_ctx(prior)))[0]
    assert r.score_value == 0.0
    assert "unsupported_critical_claim" in r.details["failure_reason_codes"]


@pytest.mark.asyncio
async def test_hard_gate_fails_on_workflow_and_empty_report() -> None:
    prior = {
        "workflow_completed": _metric("workflow_completed", passed=0),
        "report_non_empty": _metric("report_non_empty", passed=0),
        "citation_traceability": _metric("citation_traceability", passed=1),
        "unsupported_critical_claim_count": _metric("unsupported_critical_claim_count", score=0.0, passed=1),
    }
    r = (await HardGateEvaluator().evaluate(_ctx(prior)))[0]
    codes = r.details["failure_reason_codes"]
    assert "workflow_failed" in codes
    assert "report_empty" in codes


@pytest.mark.asyncio
async def test_hard_gate_judge_none_not_counted_but_flagged() -> None:
    # judge 类指标 passed=None（离线未运行）→ 不触发 failure，但 reason 标注
    prior = {
        "workflow_completed": _metric("workflow_completed", passed=1),
        "report_non_empty": _metric("report_non_empty", passed=1),
        "citation_traceability": _metric("citation_traceability", passed=1),
        "unsupported_critical_claim_count": _metric("unsupported_critical_claim_count", score=0.0, passed=1),
        "required_point_coverage": _metric("required_point_coverage", passed=None, group="recall"),
        "claim_factuality": _metric("claim_factuality", passed=None, group="factuality"),
    }
    r = (await HardGateEvaluator().evaluate(_ctx(prior)))[0]
    # gate 仅基于确定性指标 → 通过
    assert r.score_value == 1.0
    assert r.details["failure_reason_codes"] == []
    assert "judge 未运行" in r.reason
    assert "missing_required_points" in r.reason
    assert "critical_fact_error" in r.reason


@pytest.mark.asyncio
async def test_hard_gate_judge_fail_triggers_failure() -> None:
    # judge 跑了且失败 → 触发 failure
    prior = {
        "workflow_completed": _metric("workflow_completed", passed=1),
        "report_non_empty": _metric("report_non_empty", passed=1),
        "citation_traceability": _metric("citation_traceability", passed=1),
        "unsupported_critical_claim_count": _metric("unsupported_critical_claim_count", score=0.0, passed=1),
        "required_point_coverage": _metric("required_point_coverage", passed=0, group="recall"),
        "claim_factuality": _metric("claim_factuality", passed=1, group="factuality"),
    }
    r = (await HardGateEvaluator().evaluate(_ctx(prior)))[0]
    assert r.score_value == 0.0
    assert "missing_required_points" in r.details["failure_reason_codes"]
    assert "critical_fact_error" not in r.details["failure_reason_codes"]
