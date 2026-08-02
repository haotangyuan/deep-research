"""Eval MVP v2 — Score 到 Run/Artifact 的规范化关联测试。

验证：
- EvalScore 不重复保存 trace_id / report_artifact_id。
- score -> case_run -> run 能定位 trace。
- case_run.run_id -> report_final artifact 能定位被评报告。

DB 测试走真实 MySQL；不 mock。
"""
from __future__ import annotations

import uuid

import pymysql
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.domain.models import EvalCaseRun, ResearchArtifact, ResearchRun
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
async def test_score_uses_normalized_case_run_to_trace_and_artifact_chain() -> None:
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

    scores = await eval_repository.list_scores(case_run_id)
    assert scores, "应有 score 写入"
    for s in scores:
        assert "trace_id" not in s
        assert "report_artifact_id" not in s

    # 规范化关联：score -> case_run -> run/trace；run_id -> report_final artifact。
    async with SessionLocal() as session:
        case_run = await session.scalar(select(EvalCaseRun).where(EvalCaseRun.id == case_run_id))
        run = await session.scalar(select(ResearchRun).where(ResearchRun.id == case_run.run_id))
        assert run is not None and run.id == run_id
        assert run.trace_id == "0123456789abcdef0123456789abcdef"
        art2 = await session.scalar(
            select(ResearchArtifact).where(
                ResearchArtifact.run_id == case_run.run_id,
                ResearchArtifact.artifact_type == "report_final",
            )
        )
        assert art2 is not None and art2.id == report_artifact_id
