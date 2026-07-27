"""Eval MVP v2 Commit 6d — Evaluators 测试。

- deterministic：纯规则，覆盖 gate / citation 指标（无 LLM）。
- claim_extractor：从 report 抽 manifest 并回写 ctx。
- LLM judges：monkeypatch chat_fn 返回固定 JSON，验证 metric 映射。
- cost/round/reviewer：纯计算。

不连 DB、不调真 LLM（与 CLAUDE.md「不 mock MySQL」无关——evaluator 是纯逻辑层）。
"""
from __future__ import annotations

import json

import pytest

from evals.evaluators.base import EvalContext
from evals.evaluators.claim_extractor import ClaimExtractorEvaluator
from evals.evaluators.cost_effectiveness import CostEffectivenessEvaluator
from evals.evaluators.citation_judge import CitationJudgeEvaluator
from evals.evaluators.coverage_judge import CoverageJudgeEvaluator
from evals.evaluators.deterministic import DeterministicEvaluator
from evals.evaluators.report_quality_judge import ReportQualityJudgeEvaluator
from evals.evaluators.reviewer_effectiveness import ReviewerEffectivenessEvaluator
from evals.evaluators.round_delta import RoundDeltaEvaluator


def _ctx(report: str, **kw) -> EvalContext:
    return EvalContext(case_run_id="cr1", report=report, **kw)


@pytest.mark.asyncio
async def test_deterministic_gate_and_citation_metrics() -> None:
    ev = DeterministicEvaluator()
    report = "市场规模 5000 亿 [来源](https://a.com)。风险 [2]。"
    ctx = _ctx(report, run={"outcome": "success"})
    results = await ev.evaluate(ctx)
    by_name = {r.metric_name: r for r in results}
    assert by_name["workflow_completed"].passed == 1
    assert by_name["report_non_empty"].passed == 1
    # 有 [2] 标记但无 url，且无 md 链接对应 → parse_rate 视实现：这里同时有 md link，
    # parse_rate=1（简化口径：有 md 链接即视为可解析）
    assert by_name["citation_parse_rate"].score_value == 1.0
    # effective_citation_count = 1 md url + 0.5 * dangling numeric
    assert by_name["effective_citation_count"].score_value == 1.5
    # 无 manifest → traceability=1.0（无 claim 不算违规）
    assert by_name["citation_traceability"].passed == 1


@pytest.mark.asyncio
async def test_deterministic_unsupported_critical_claim_flagged() -> None:
    ev = DeterministicEvaluator()
    ctx = _ctx(
        "报告",
        run={"outcome": "degraded"},
        claim_manifest=[
            {"claim_id": "c1", "importance": "critical", "citations": [{"citation_url": "https://a.com"}]},
            {"claim_id": "c2", "importance": "critical", "citations": [{"citation_marker": "[3]"}]},
        ],
    )
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    # c2 无 citation_url → unsupported
    assert results["unsupported_critical_claim_count"].score_value == 1.0
    assert results["unsupported_critical_claim_count"].passed == 0
    # traceability = 1/2 = 0.5 → 不达 0.95
    assert results["citation_traceability"].score_value == 0.5
    assert results["citation_traceability"].passed == 0


@pytest.mark.asyncio
async def test_claim_extractor_extracts_and_backfills_manifest() -> None:
    ev = ClaimExtractorEvaluator()
    ctx = _ctx("市场规模 2026 年达 5000 亿 [来源](https://a.com)。")
    assert ctx.claim_manifest == []
    results = await ev.evaluate(ctx)
    # 现场抽取并回写 ctx
    assert len(ctx.claim_manifest) >= 1
    by_name = {r.metric_name: r for r in results}
    assert by_name["supported_claim_count"].score_value == 1.0


@pytest.mark.asyncio
async def test_citation_judge_maps_llm_json_to_metrics() -> None:
    async def fake_chat(sys_p, user_p):
        return json.dumps(
            {
                "metrics": {"claim_factuality": 0.9, "citation_completeness": 0.8, "citation_correctness": 0.7},
                "reasons": {"claim_factuality": "属实"},
            }
        )

    ev = CitationJudgeEvaluator(chat_fn=fake_chat, judge_model="mimo")
    ctx = _ctx("报告 [来源](https://a.com)。", claim_manifest=[{"claim_text": "x", "citations": [{"citation_url": "https://a.com"}]}])
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    assert results["claim_factuality"].score_value == 0.9
    assert results["claim_factuality"].passed == 1
    assert results["citation_completeness"].score_value == 0.8
    assert results["citation_correctness"].score_value == 0.7
    assert results["claim_factuality"].reason == "属实"
    assert results["claim_factuality"].judge_model == "mimo"
    assert results["claim_factuality"].evaluator_version == "1.0.0"


@pytest.mark.asyncio
async def test_coverage_judge_requires_dataset_points() -> None:
    async def fake_chat(sys_p, user_p):
        assert "required_points" in user_p  # 校验 prompt 带了 dataset 上下文
        return json.dumps({"metrics": {"required_point_coverage": 0.7, "critical_fact_recall": 0.6}, "reasons": {}})

    ev = CoverageJudgeEvaluator(chat_fn=fake_chat)
    ctx = _ctx("报告", dataset_item={"required_points_json": ["市场规模", "增长率"]})
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    assert results["required_point_coverage"].score_value == 0.7
    assert results["required_point_coverage"].metric_group == "recall"


@pytest.mark.asyncio
async def test_report_quality_judge_four_metrics() -> None:
    async def fake_chat(sys_p, user_p):
        return json.dumps(
            {
                "metrics": {
                    "analysis_depth": 0.8,
                    "multi_source_synthesis": 0.7,
                    "uncertainty_calibration": 0.6,
                    "instruction_following": 0.9,
                },
                "reasons": {},
            }
        )

    ev = ReportQualityJudgeEvaluator(chat_fn=fake_chat)
    results = {r.metric_name: r for r in await ev.evaluate(_ctx("报告"))}
    assert {r.metric_name for r in results.values()} == {
        "analysis_depth",
        "multi_source_synthesis",
        "uncertainty_calibration",
        "instruction_following",
    }
    assert all(r.evaluator_name == "report_quality_judge" for r in results.values())


@pytest.mark.asyncio
async def test_llm_judge_handles_malformed_output_gracefully() -> None:
    async def fake_chat(sys_p, user_p):
        return "not json at all"

    ev = CitationJudgeEvaluator(chat_fn=fake_chat)
    results = await ev.evaluate(_ctx("报告"))
    # 所有 metric score=None（解析失败），不抛错
    assert all(r.score_value is None for r in results)


@pytest.mark.asyncio
async def test_cost_effectiveness_per_pass() -> None:
    ev = CostEffectivenessEvaluator()
    ctx = _ctx("报告", run={"estimated_cost": 0.12, "gate_passed": 1, "input_tokens": 100, "output_tokens": 50})
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    assert results["cost_per_pass"].score_value == 0.12
    assert results["total_cost"].score_value == 0.12


@pytest.mark.asyncio
async def test_round_delta_two_rounds() -> None:
    ev = RoundDeltaEvaluator()
    # review_attributes: {round_no: {attr_key: value}}；quality 取各维度 score 的短板 min
    # 轮1 短板=0.5、gaps=4、tokens=100；轮2 短板=0.7、gaps=2、tokens=80
    ctx = _ctx(
        "报告",
        review_attributes={
            1: {
                "review.score.coverage": 0.5, "review.score.evidence": 0.6,
                "review.score.freshness": 0.5, "review.score.sourceDiversity": 0.5,
                "review.score.consistency": 0.5, "review.gaps.count": 4, "review.tokens": 100,
            },
            2: {
                "review.score.coverage": 0.7, "review.score.evidence": 0.8,
                "review.score.freshness": 0.7, "review.score.sourceDiversity": 0.7,
                "review.score.consistency": 0.7, "review.gaps.count": 2, "review.tokens": 80,
            },
        },
    )
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    assert results["quality_delta_per_round"].score_value == pytest.approx(0.2)
    assert results["gap_closure_rate"].score_value == 0.5
    # marginal = 0.2/80*1000 = 2.5
    assert results["marginal_quality_per_1k_tokens"].score_value == pytest.approx(2.5)


@pytest.mark.asyncio
async def test_reviewer_effectiveness_predictiveness() -> None:
    ev = ReviewerEffectivenessEvaluator()
    # consensus=report 且 outcome=success → predictiveness=1
    ctx = _ctx("报告", run={"outcome": "success", "review_consensus": "report", "reviewer_tokens": 5000}, reviewer_lenses=["a", "b", "c"])
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    assert results["reviewer_consensus_predictiveness"].score_value == 1.0
    assert results["reviewer_token_cost"].score_value == 5000.0
