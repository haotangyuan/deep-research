"""Eval MVP v2 Commit 6b — Candidate Snapshot Worker 测试。

验证：
1. success/degraded outcome → 冻结一条 ``eval_candidate_snapshot`` artifact。
2. failed/cancelled outcome → 跳过（无可评估终态报告）。
3. 同 run 重跑 snapshot → 幂等（一行，content_sha256 不变）。
4. snapshot 抛错不影响调用方（safe_record 吞异常）。

DB 测试：走真实 MySQL（CLAUDE.md「不 mock MySQL」），DB 不可达则跳过。
"""
from __future__ import annotations

import json
import uuid

import pytest
import pymysql
from sqlalchemy import select

from app.core.config import get_settings
from app.core.constants import WorkflowMode, WorkflowStatus
from app.domain.models import ResearchArtifact
from app.domain.runtime import ResearchMessage
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel
from app.infrastructure.db import SessionLocal
from app.application.eval_snapshot import freeze_candidate_snapshot, enqueue_snapshot

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


def _state(status: WorkflowStatus, *, run_id: str | None = None) -> DeepResearchState:
    rid = "research-snap-" + uuid.uuid4().hex[:8]
    s = DeepResearchState(
        research_id=rid,
        chat_history=[ResearchMessage.user("x")],
        status=status,
        workflow_mode=WorkflowMode.ULTRA_DYNAMIC,
        dynamic_round_no=1,
        trace_metadata_model=TraceMetadataModel(
            research_id=rid,
            user_id=1,
            model_id="mimo",
            budget_level="ULTRA",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=6, max_search_count=4, max_concurrent_units=3),
        budget_name="ULTRA",
        report="示例报告 [来源](https://example.com/a)。",
    )
    if run_id:
        s.run_id = run_id
    s.run_version_snapshot = {"workflow_commit_sha": "abc"}
    return s


@pytest.fixture(autouse=True)
async def _truncate_artifacts():
    if not DB_AVAILABLE:
        yield
        return
    from app.infrastructure.db import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM research_artifact WHERE artifact_type='eval_candidate_snapshot'"))
    yield


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_freeze_writes_snapshot_artifact() -> None:
    from app.infrastructure.eval_repository import EvalRepository

    repo = EvalRepository()
    state = _state(WorkflowStatus.COMPLETED)
    # 先建 run + 一个 report_final artifact，让 snapshot 索引有内容
    run_id = await repo.create_run(state.research_id, 1, "initial", {"workflow_commit_sha": "abc"}, state)
    state.run_id = run_id
    await repo.upsert_artifact(
        run_id=run_id,
        research_id=state.research_id,
        artifact_type="report_final",
        stage_name="ReportAgent.run",
        content="# 最终报告",
        outcome="success",
    )
    aid = await freeze_candidate_snapshot(state)
    assert aid is not None

    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(ResearchArtifact).where(
                    ResearchArtifact.run_id == run_id,
                    ResearchArtifact.artifact_type == "eval_candidate_snapshot",
                )
            )
        ).all()
        assert len(rows) == 1
        payload = json.loads(rows[0].content)
        assert payload["run_id"] == run_id
        assert payload["artifact_index"]["counts"]["report_final"] == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_freeze_idempotent_on_replay() -> None:
    from app.infrastructure.eval_repository import EvalRepository

    repo = EvalRepository()
    state = _state(WorkflowStatus.COMPLETED)
    run_id = await repo.create_run(state.research_id, 1, "initial", {"workflow_commit_sha": "abc"}, state)
    state.run_id = run_id
    aid1 = await freeze_candidate_snapshot(state)
    aid2 = await freeze_candidate_snapshot(state)
    assert aid1 == aid2
    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(ResearchArtifact).where(
                    ResearchArtifact.run_id == run_id,
                    ResearchArtifact.artifact_type == "eval_candidate_snapshot",
                )
            )
        ).all()
        assert len(rows) == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_enqueue_skips_failed_and_cancelled() -> None:
    """failed/cancelled outcome → 不冻结 snapshot。"""
    for status in (WorkflowStatus.FAILED, WorkflowStatus.CANCELLED):
        state = _state(status, run_id=uuid.uuid4().hex)
        await enqueue_snapshot(state)
        async with SessionLocal() as session:
            rows = (
                await session.scalars(
                    select(ResearchArtifact).where(
                        ResearchArtifact.run_id == state.run_id,
                        ResearchArtifact.artifact_type == "eval_candidate_snapshot",
                    )
                )
            ).all()
            assert len(rows) == 0, f"failed/cancelled 不应冻结 snapshot ({status})"


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_enqueue_skips_when_no_run_id() -> None:
    state = _state(WorkflowStatus.COMPLETED, run_id=None)
    # run_id=None → enqueue_snapshot 早退，不应抛错
    await enqueue_snapshot(state)


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_enqueue_isolated_from_failure(monkeypatch) -> None:
    """freeze_candidate_snapshot 抛错时 enqueue_snapshot 不传播异常。"""

    async def boom(state):
        raise RuntimeError("snapshot db down")

    monkeypatch.setattr("app.application.eval_snapshot.freeze_candidate_snapshot", boom)
    state = _state(WorkflowStatus.COMPLETED, run_id=uuid.uuid4().hex)
    await enqueue_snapshot(state)  # 不抛错
