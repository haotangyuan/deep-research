"""Eval MVP v2 — EvalScore trace_id/report_artifact_id 跳转列测试（§18）。

验证：
- EvalScore ORM 有 trace_id / report_artifact_id 列。
- evaluate_case_run 写 score 时回填 trace_id + report_artifact_id（来自 run.trace_id + report_final artifact.id）。
- list_scores 返回 trace_id / report_artifact_id，可从 score 直跳 trace/artifact。

DB 测试走真实 MySQL；不 mock。
"""
from __future__ import annotations

import uuid

import pymysql
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.domain.models import EvalCaseRun, EvalScore, ResearchArtifact, ResearchRun
from app.infrastructure.db import SessionLocal
from app.infrastructure.eval_repository import EvalRepository, eval_repository
from evals.runner import evaluate_case_run

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
async def _truncate_eval_tables():
    if not DB_AVAILABLE:
        yield
        return
    from app.infrastructure.db import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        for t in (
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
async def test_score_carries_trace_id_and_report_artifact_id() -> None:
    repo = EvalRepository()
    research_id = "research-trace-" + uuid.uuid4().hex[:8]
    # 建一个带 trace_id 的 run
    run_id = await repo.create_run(
        research_id,
        1,
        "initial",
        {"workflow_commit_sha": "abc"},
        None,
    )
    # 直接 UPDATE 设 trace_id（create_run 未接收 trace_id 参数，走 state 注入路径在 pipeline 里）
    async with SessionLocal() as session:
        await session.execute(
            ResearchRun.__table__.update().where(ResearchRun.id == run_id).values(trace_id="0123456789abcdef0123456789abcdef")
        )
        await session.commit()

    # 建 report_final artifact，记其 id
    await repo.upsert_artifact(
        run_id=run_id,
        research_id=research_id,
        artifact_type="report_final",
        stage_name="ReportAgent.run",
        content="市场规模 5000 亿 [来源](https://a.com)。",
        outcome="success",
    )
    async with SessionLocal() as session:
        art = await session.scalar(
            select(ResearchArtifact).where(ResearchArtifact.run_id == run_id, ResearchArtifact.artifact_type == "report_final")
        )
        report_artifact_id = art.id

    await repo.write_claim_manifest(
        run_id,
        research_id,
        report_artifact_id,
        [
            {
                "claim_id": "c1",
                "claim_text": "市场规模 5000 亿",
                "importance": "critical",
                "citations": [{"citation_id": "cite1", "citation_url": "https://a.com", "excerpt": "数据"}],
            }
        ],
    )

    # dataset + experiment + case_run 关联 run_id
    item_id = await repo.upsert_dataset_item(
        dataset_name="mvp_v1",
        dataset_version="1",
        query_snapshot="市场分析题：" + uuid.uuid4().hex,
        task_type="market_analysis",
        required_points=["市场规模"],
    )
    exp_id = await repo.create_experiment(
        name="trace_cmp",
        dataset_name="mvp_v1",
        dataset_version="1",
        experiment_type="tier_comparison",
        evaluator_version="deterministic-1.0.0",
    )
    case_run_id = await repo.upsert_case_run(
        experiment_id=exp_id,
        dataset_item_id=item_id,
        variant_name="MEDIUM",
    )
    async with SessionLocal() as session:
        await session.execute(
            EvalCaseRun.__table__.update().where(EvalCaseRun.id == case_run_id).values(run_id=run_id)
        )
        await session.commit()

    # 跑评估（无 chat_fn，确定性 + gate）
    await evaluate_case_run(case_run_id)

    # 验证 eval_score 行带 trace_id + report_artifact_id
    scores = await eval_repository.list_scores(case_run_id)
    assert scores, "应有 score 写入"
    for s in scores:
        assert s["trace_id"] == "0123456789abcdef0123456789abcdef"
        assert s["report_artifact_id"] == report_artifact_id

    # 直跳验证：能从 trace_id 反查到 run，从 report_artifact_id 反查到 artifact
    async with SessionLocal() as session:
        score_row = await session.scalar(select(EvalScore).where(EvalScore.case_run_id == case_run_id).limit(1))
        # score.trace_id → research_run
        run = await session.scalar(select(ResearchRun).where(ResearchRun.trace_id == score_row.trace_id))
        assert run is not None and run.id == run_id
        # score.report_artifact_id → research_artifact
        art2 = await session.scalar(
            select(ResearchArtifact).where(ResearchArtifact.id == score_row.report_artifact_id)
        )
        assert art2 is not None and art2.artifact_type == "report_final"
