"""Eval MVP v2 — Synthesis Uplift + 配对差值真实计算测试（§8.3 + §18/§19）。

验证：
- 非 HIGH 双 draft 路径 → 三指标 None。
- 双 draft + synthesis → best_draft_quality/synthesis_uplift/draft_complementarity 真实算。
- synthesis 比 best draft 密 → uplift > 0。
- 两 draft 互补 → complementarity > 0。
- build_paired_diff_report 真实算跨 variant 均值 + 相邻档位差值 + 决策输出。
"""
from __future__ import annotations

import pytest

from evals.evaluators.base import EvalContext
from evals.evaluators.synthesis_uplift import SynthesisUpliftEvaluator, _quality_proxy
from evals.runner import build_paired_diff_report


def _ctx(**kw) -> EvalContext:
    return EvalContext(case_run_id="cr1", report="报告", **kw)


@pytest.mark.asyncio
async def test_no_dual_draft_returns_none() -> None:
    ev = SynthesisUpliftEvaluator()
    results = {r.metric_name: r for r in await ev.evaluate(_ctx())}
    assert set(results) == {"best_draft_quality", "synthesis_uplift", "draft_complementarity"}
    assert all(r.score_value is None for r in results.values())


@pytest.mark.asyncio
async def test_synthesis_uplift_positive() -> None:
    ev = SynthesisUpliftEvaluator()
    # 两个稀疏 draft + 密集 synthesis
    ctx = _ctx(
        report_drafts=[
            {"angle": "comparative", "content": "市场规模 5000 亿 [来源](https://a.com)。"},
            {"angle": "data-driven", "content": "玩家占 60% [1]。"},
        ],
        report_synthesis="市场规模 5000 亿 [来源](https://a.com)。玩家占 60% [1]。风险率 30% [2]。",
    )
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    # synthesis 比 best draft 密 → uplift > 0
    assert results["synthesis_uplift"].score_value > 0
    assert results["synthesis_uplift"].passed == 1
    assert results["best_draft_quality"].score_value > 0
    # 互补：两 draft 的 claim 不重叠 → complementarity = 1.0
    assert results["draft_complementarity"].score_value == 1.0


@pytest.mark.asyncio
async def test_synthesis_uplift_negative_when_synthesis_sparser() -> None:
    ev = SynthesisUpliftEvaluator()
    ctx = _ctx(
        report_drafts=[
            {"angle": "comparative", "content": "市场规模 5000 亿 [来源](https://a.com)。玩家占 60% [1]。"},
            {"angle": "data-driven", "content": "风险率 30% [2]。"},
        ],
        report_synthesis="综合结论。",
    )
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    # synthesis 比 best draft 稀 → uplift < 0
    assert results["synthesis_uplift"].score_value < 0
    assert results["synthesis_uplift"].passed == 0


def test_quality_proxy_counts_claims_and_citations() -> None:
    rich = "市场规模 5000 亿 [来源](https://a.com)。玩家占 60% [1]。"  # 2 claim + 2 citation
    empty = "综合结论。"  # 0
    assert _quality_proxy(rich) == 4.0
    assert _quality_proxy(empty) == 0.0


def test_build_paired_diff_report_computes_means_and_deltas() -> None:
    summary = {
        "MEDIUM": {
            "cr1": {"effective_citation_count": 2.0, "total_cost": 0.10},
            "cr2": {"effective_citation_count": 4.0, "total_cost": 0.10},
        },
        "HIGH": {
            "cr1": {"effective_citation_count": 5.0, "total_cost": 0.20},
            "cr2": {"effective_citation_count": 7.0, "total_cost": 0.20},
        },
    }
    report = build_paired_diff_report(summary)
    # 均值表
    assert "## 各 Variant 指标均值" in report
    assert "MEDIUM" in report and "HIGH" in report
    # 相邻差值：HIGH - MEDIUM 均值 = (6 - 3) = +3 for citation, (0.20-0.10)=+0.10 for cost
    assert "## 相邻档位差值（uplift）" in report
    assert "MEDIUM→HIGH" in report
    assert "+3.0000" in report  # citation delta
    assert "+0.1000" in report  # cost delta
    # 决策输出
    assert "## 决策输出（§19）" in report
    assert "边际质量/成本" in report


def test_build_paired_diff_report_single_variant() -> None:
    summary = {"MEDIUM": {"cr1": {"effective_citation_count": 2.0}}}
    report = build_paired_diff_report(summary)
    assert "仅一个 variant" in report


def test_build_paired_diff_report_ignores_unpaired_runs_for_delta() -> None:
    summary = {
        "MEDIUM": {
            "item1::0": {"required_point_coverage": 0.2},
            "item2::0": {"required_point_coverage": 1.0},
        },
        "HIGH": {
            "item1::0": {"required_point_coverage": 0.5},
        },
    }
    report = build_paired_diff_report(summary)
    # 只比较共同的 item1::0：0.5 - 0.2 = 0.3。
    # 如果错误地用两个 Variant 的总体均值相减，会得到 -0.1。
    assert "+0.3000" in report
    assert "-0.1000" not in report


def test_build_paired_diff_report_empty() -> None:
    report = build_paired_diff_report({})
    assert "无数据" in report
