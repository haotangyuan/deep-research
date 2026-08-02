"""精简 Eval 过程事实源测试。

覆盖：
- _load_case_context 只读 round_review Artifact + research_llm_call 装配过程上下文；
- research_stage_usage 保留聚合投影用途，但不是 Eval 核心事实源；
- RoundDeltaEvaluator 从 ctx.review_attributes 产出真实 delta（非返回空）
- ReviewerEffectivenessEvaluator 从 run_row.reviewer_tokens / review_consensus 产出真实值

DB 测试走真实 MySQL；不 mock。LLM 不参与。
"""
from __future__ import annotations

import json
import uuid

import pytest
import pymysql
from sqlalchemy import select

from app.core.config import get_settings
from app.domain.models import (
    EvalCaseRun,
)
from app.infrastructure.db import SessionLocal
from app.infrastructure.eval_repository import EvalRepository
from evals.evaluators.round_delta import RoundDeltaEvaluator
from evals.evaluators.reviewer_effectiveness import ReviewerEffectivenessEvaluator
from evals.evaluators.base import EvalContext
from evals.runner import _load_case_context

settings = get_settings()


def _db_reachable() -> bool:
    from urllib.parse import urlparse

    raw = settings.db_url.removeprefix("jdbc:") if settings.db_url.startswith("jdbc:") else settings.db_url
    parsed = urlparse(raw)
    db_name = (parsed.path or "/").lstrip("/") or "db_deep_research"
    try:
        conn = pymysql.connect(
            host=parsed.hostname or "127.0.0.1",
            port=parsed.port or 3306,
            user=settings.db_username,
            password=settings.db_password,
            database=db_name,
            connect_timeout=2,
        )
        conn.close()
        return True
    except Exception:  # noqa: BLE001
        return False


DB_AVAILABLE = _db_reachable()
DB_REASON = "local MySQL not reachable"


@pytest.fixture(autouse=True)
async def _truncate_tables():
    if not DB_AVAILABLE:
        yield
        return
    from app.infrastructure.db import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        for t in (
            "research_stage_usage",
            "research_llm_call",
            "eval_score",
            "eval_case_run",
            "eval_experiment",
            "eval_dataset_item",
            "research_claim_manifest",
            "research_artifact",
            "research_run",
        ):
            await conn.execute(text("TRUNCATE TABLE " + t))
    yield

@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_load_case_context_assembles_artifacts_and_llm_call_facts() -> None:
    repo = EvalRepository()
    research_id = "research-load-" + uuid.uuid4().hex[:8]
    run_id = await repo.create_run(research_id, 1, "initial", {"workflow_commit_sha": "abc"}, None)
    # 两轮 Reviewer 事实统一落 round_review Artifact。
    for rno, consensus, votes in ((1, "split", 2), (2, "report", 0)):
        decision = {
            "nextAction": "continue" if rno == 1 else "report",
            "qualityScoreboard": {
                "coverage": 2 + rno,
                "evidence": 2 + rno,
                "freshness": 3,
                "sourceDiversity": 3,
                "consistency": 3,
            },
            "blockingGaps": [f"gap-{i}" for i in range(4 - rno)],
            "sectionScoreboard": (
                [{"section": "风险", "status": "needs_more_evidence"}] if rno == 2 else []
            ),
            "reviewSummary": {
                "continueVotes": votes,
                "reportVotes": 3 - votes,
                "totalVotes": 3,
                "consensus": consensus,
            },
        }
        await repo.upsert_artifact(
            run_id=run_id,
            research_id=research_id,
            artifact_type="round_review",
            stage_name="UltraDynamicReview",
            round_no=rno,
            content=json.dumps(decision, ensure_ascii=False),
            outcome="success",
        )
    # Token 直接读取 research_llm_call；stage_usage 只是 record_llm_call 的派生投影。
    for rno in (1, 2):
        await repo.record_llm_call(
            run_id=run_id,
            llm_call_id=f"review-call-{rno}-{uuid.uuid4().hex[:8]}",
            research_id=research_id,
            stage_name=(
                "UltraDynamicReviewer:coverage"
                if rno == 1
                else "UltraDynamicReviewer:freshness"
            ),
            round_no=rno,
            reviewer_lens="coverage" if rno == 1 else "freshness",
            input_tokens=100 * rno,
            output_tokens=50 * rno,
            outcome="success",
        )
    # 造 report_final + claim_manifest + dataset + experiment + case_run
    await repo.upsert_artifact(
        run_id=run_id,
        research_id=research_id,
        artifact_type="report_final",
        stage_name="ReportAgent.run",
        content="市场规模 5000 亿 [来源](https://a.com)。",
        outcome="success",
    )
    await repo.write_claim_manifest(
        run_id,
        research_id,
        None,
        [{"claim_id": "c1", "claim_text": "5000 亿", "importance": "critical", "citations": []}],
    )
    item_id = await repo.upsert_dataset_item(
        dataset_name="mvp_v1",
        dataset_version="1",
        query_snapshot="题" + uuid.uuid4().hex,
        task_type="market_analysis",
        required_points=["市场规模"],
    )
    exp_id = await repo.create_experiment(
        name="tier_cmp",
        dataset_name="mvp_v1",
        dataset_version="1",
        experiment_type="tier_comparison",
        evaluator_version="deterministic-1.0.0",
    )
    case_run_id = await repo.upsert_case_run(
        experiment_id=exp_id,
        dataset_item_id=item_id,
        variant_name="ULTRA",
    )
    # 给 case_run 填 run_id + estimated_cost + gate_passed
    async with SessionLocal() as session:
        await session.execute(
            EvalCaseRun.__table__.update()
            .where(EvalCaseRun.id == case_run_id)
            .values(run_id=run_id, estimated_cost=0.0123, gate_passed=1)
        )
        await session.commit()

    ctx = await _load_case_context(case_run_id)
    # review_attributes 来自 round_review Artifact。
    assert set(ctx.review_attributes) == {1, 2}
    r2 = ctx.review_attributes[2]
    assert r2["review.consensus"] == "report"
    assert r2["review.continue.votes"] == 0.0
    # report_quality 由最后一轮 round_review 派生，不读 span_attribute。
    assert ctx.report_quality["report.quality.status"] == "needs_disclosure"
    assert ctx.report_quality["report.weak.sections.count"] == 1
    # run_row 直链字段
    assert ctx.run["reviewer_tokens"] == (100 + 50) + (200 + 100)
    assert float(ctx.run["estimated_cost"]) == pytest.approx(0.0123)
    assert int(ctx.run["gate_passed"]) == 1
    # reviewer_lenses 去重 + 排序
    assert "coverage" in ctx.run["reviewer_lenses"]
    assert "freshness" in ctx.run["reviewer_lenses"]
    # review_consensus 取最后一轮
    assert ctx.run["review_consensus"] == "report"


@pytest.mark.asyncio
async def test_round_delta_reads_review_attributes() -> None:
    """无 DB：直接构造 EvalContext.review_attributes，验证 round_delta 产出真实 delta。"""
    ctx = EvalContext(
        case_run_id="cr1",
        report="",
        review_attributes={
            1: {
                "review.score.coverage": 3.0,
                "review.score.evidence": 4.0,
                "review.score.freshness": 3.0,
                "review.score.sourceDiversity": 3.0,
                "review.score.consistency": 3.0,  # 短板 min = 3
                "review.gaps.count": 4.0,
                "review.tokens": 300,
            },
            2: {
                "review.score.coverage": 5.0,
                "review.score.evidence": 4.0,
                "review.score.freshness": 4.0,
                "review.score.sourceDiversity": 5.0,
                "review.score.consistency": 4.0,  # 短板 min = 4
                "review.gaps.count": 1.0,
                "review.tokens": 500,
            },
        },
    )
    results = await RoundDeltaEvaluator().evaluate(ctx)
    by_name = {r.metric_name: r for r in results}
    delta = by_name["quality_delta_per_round"]
    assert delta.score_value == 1.0  # 4 - 3
    marginal = by_name["marginal_quality_per_1k_tokens"]
    assert marginal.score_value == 1.0 / 500 * 1000  # 2.0
    closure = by_name["gap_closure_rate"]
    assert closure.score_value == 0.75  # (4-1)/4


@pytest.mark.asyncio
async def test_round_delta_returns_empty_when_single_round() -> None:
    ctx = EvalContext(case_run_id="cr1", report="", review_attributes={1: {"review.score.coverage": 3.0}})
    results = await RoundDeltaEvaluator().evaluate(ctx)
    assert results == []


@pytest.mark.asyncio
async def test_reviewer_effectiveness_reads_run_row() -> None:
    """无 DB：run_row.reviewer_tokens/review_consensus 填了真实值，evaluator 出真实分。"""
    ctx = EvalContext(
        case_run_id="cr1",
        report="",
        run={
            "reviewer_tokens": 1500,
            "review_consensus": "report",
            "outcome": "success",
        },
        reviewer_lenses=["coverage", "freshness"],
    )
    results = await ReviewerEffectivenessEvaluator().evaluate(ctx)
    by_name = {r.metric_name: r for r in results}
    assert by_name["reviewer_token_cost"].score_value == 1500.0
    # consensus=report 且 outcome=success → predictiveness=1
    assert by_name["reviewer_consensus_predictiveness"].score_value == 1.0
