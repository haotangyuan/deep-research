"""trace 标量本地落地（research_span_attribute）+ eval 读取测试。

覆盖：
- upsert_span_attributes 幂等（同 key 重写覆盖、不同 round_no 独立、数值/字符串/JSON 分流）
- _load_case_context 读 span_attribute + stage_usage 装配 EvalContext（review_attributes /
  report_quality / run_row.reviewer_tokens / reviewer_lenses / review_consensus /
  estimated_cost / gate_passed）
- RoundDeltaEvaluator 从 ctx.review_attributes 产出真实 delta（非返回空）
- ReviewerEffectivenessEvaluator 从 run_row.reviewer_tokens / review_consensus 产出真实值

DB 测试走真实 MySQL；不 mock。LLM 不参与。
"""
from __future__ import annotations

import uuid

import pytest
import pymysql
from sqlalchemy import select

from app.core.config import get_settings
from app.domain.models import (
    EvalCaseRun,
    EvalDatasetItem,
    ResearchSpanAttribute,
    ResearchStageUsage,
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
            "research_span_attribute",
            "research_stage_usage",
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
async def test_upsert_span_attributes_idempotent_and_typed() -> None:
    repo = EvalRepository()
    run_id = "run-spanattr-" + uuid.uuid4().hex[:8]
    research_id = "research-spanattr-" + uuid.uuid4().hex[:8]
    trace_id = "0" * 32
    attrs = {
        "review.continue.votes": 2,          # 数值
        "review.consensus": "split",         # 字符串
        "review.score.coverage": 4,
        "review.gaps": ["gap_a", "gap_b"],   # 结构化 → JSON
    }
    await repo.upsert_span_attributes(
        run_id=run_id,
        research_id=research_id,
        trace_id=trace_id,
        span_scope="UltraDynamicReview",
        round_no=1,
        attrs=attrs,
    )
    # replay：同 key 覆盖
    await repo.upsert_span_attributes(
        run_id=run_id,
        research_id=research_id,
        trace_id=trace_id,
        span_scope="UltraDynamicReview",
        round_no=1,
        attrs={"review.continue.votes": 3, "review.consensus": "report"},
    )
    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(ResearchSpanAttribute).where(
                    ResearchSpanAttribute.run_id == run_id,
                    ResearchSpanAttribute.span_scope == "UltraDynamicReview",
                    ResearchSpanAttribute.round_no == 1,
                )
            )
        ).all()
        # 同 round_no 内 4 个 key 各一行（gaps 用新覆盖值数未变）
        by_key = {r.attr_key: r for r in rows}
        assert by_key["review.continue.votes"].attr_value_num == 3.0  # 覆盖生效
        assert by_key["review.consensus"].attr_value_str == "report"
        assert by_key["review.score.coverage"].attr_value_num == 4.0
        assert by_key["review.gaps"].attr_value_json is not None
    # 不同 round_no 独立
    await repo.upsert_span_attributes(
        run_id=run_id,
        research_id=research_id,
        trace_id=trace_id,
        span_scope="UltraDynamicReview",
        round_no=2,
        attrs={"review.continue.votes": 0, "review.consensus": "continue"},
    )
    async with SessionLocal() as session:
        cnt = (
            await session.scalar(
                select(ResearchSpanAttribute).where(
                    ResearchSpanAttribute.run_id == run_id,
                    ResearchSpanAttribute.span_scope == "UltraDynamicReview",
                    ResearchSpanAttribute.round_no == 2,
                )
            )
        )
        assert cnt is not None


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_load_case_context_assembles_span_attributes_and_stage_usage() -> None:
    repo = EvalRepository()
    research_id = "research-load-" + uuid.uuid4().hex[:8]
    run_id = await repo.create_run(research_id, 1, "initial", {"workflow_commit_sha": "abc"}, None)
    # 落两轮 review 标量
    for rno, consensus, votes in ((1, "split", 2), (2, "report", 0)):
        await repo.upsert_span_attributes(
            run_id=run_id,
            research_id=research_id,
            trace_id="t" * 32,
            span_scope="UltraDynamicReview",
            round_no=rno,
            attrs={
                "review.consensus": consensus,
                "review.continue.votes": votes,
                "review.report.votes": 3 - votes,
                "review.total.votes": 3,
                "review.gaps.count": 4 - rno,
                "review.score.coverage": 2 + rno,
                "review.score.evidence": 2 + rno,
                "review.score.freshness": 3,
                "review.score.sourceDiversity": 3,
                "review.score.consistency": 3,
            },
        )
    # 落 report quality 标量
    await repo.upsert_span_attributes(
        run_id=run_id,
        research_id=research_id,
        trace_id="t" * 32,
        span_scope="UltraReportGate",
        round_no=0,
        attrs={"report.quality.status": "needs_disclosure", "report.weak.sections.count": 1},
    )
    # 直接插 stage_usage 行（走 ORM，模拟 reconcile 投影）
    from app.core.timeutil import now_local

    now = now_local()
    async with SessionLocal() as session:
        for rno in (1, 2):
            session.add(
                ResearchStageUsage(
                    run_id=run_id,
                    stage_name="UltraDynamicReview",
                    round_no=rno,
                    input_tokens=100 * rno,
                    output_tokens=50 * rno,
                    reviewer_lens="coverage" if rno == 1 else "freshness",
                    create_time=now,
                    update_time=now,
                )
            )
        await session.commit()
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
    # review_attributes：两轮，每轮含 votes/consensus/scores/gaps
    assert set(ctx.review_attributes) == {1, 2}
    r2 = ctx.review_attributes[2]
    assert r2["review.consensus"] == "report"
    assert r2["review.continue.votes"] == 0.0
    # report_quality
    assert ctx.report_quality["report.quality.status"] == "needs_disclosure"
    assert ctx.report_quality["report.weak.sections.count"] == 1.0
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
