"""EvalRepository 落库测试。

遵循 CLAUDE.md「不 mock MySQL/Redis」：repository 的 DB 操作走真实 MySQL。
若本地 MySQL 不可达则跳过（CI 无 DB 时不算失败）。
纯逻辑（_sha256 等）无条件运行。
"""
from __future__ import annotations

import asyncio
import hashlib
import uuid

import pytest
import pymysql
from sqlalchemy import select

from app.core.config import get_settings
from app.core.timeutil import now_local
from app.domain.models import (
    ResearchArtifact,
    ResearchClaimManifest,
    ResearchLlmCall,
    ResearchRun,
    ResearchStageUsage,
)
from app.infrastructure.db import SessionLocal
from app.infrastructure.eval_repository import EvalRepository, _sha256

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
DB_REASON = "local MySQL not reachable — run `docker compose up -d mysql` first"


@pytest.fixture(autouse=True)
async def _truncate_eval_tables():
    """每个 DB 测试前清空 eval 表，避免跨用例脏数据。无 DB 时 no-op。"""
    if not DB_AVAILABLE:
        yield
        return
    from app.infrastructure.db import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        for t in [
            "research_claim_manifest",
            "research_stage_usage",
            "research_llm_call",
            "research_artifact",
            "research_run",
        ]:
            await conn.execute(text("TRUNCATE TABLE " + t))
    yield


def test_sha256_is_deterministic_and_empty_safe() -> None:
    assert _sha256("hello") == hashlib.sha256(b"hello").hexdigest()
    assert _sha256("") == _sha256(None)
    assert _sha256(None) == hashlib.sha256(b"").hexdigest()


def _new_research_id() -> str:
    return "test_" + uuid.uuid4().hex[:16]


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_run_lifecycle_create_close_attempt_no() -> None:
    repo = EvalRepository()
    research_id = _new_research_id()
    a1 = await repo.next_attempt_no(research_id)
    assert a1 == 1
    run_id = await repo.create_run(research_id, a1, "initial", {"workflow_commit_sha": "abc"}, None)
    assert len(run_id) == 32

    # 同 attempt_no replay → 不报错
    await repo.create_run(research_id, a1, "initial", {"workflow_commit_sha": "abc"}, None)

    a2 = await repo.next_attempt_no(research_id)
    assert a2 == 2

    await repo.close_run(run_id, "success", None, end_time=now_local(), active_ms=123, run_input=100, run_output=200)

    async with SessionLocal() as session:
        row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))
        assert row is not None
        assert row.outcome == "success"
        assert row.input_tokens == 100
        assert row.output_tokens == 200
        assert row.active_duration_ms == 123


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_artifact_upsert_idempotency() -> None:
    repo = EvalRepository()
    research_id = _new_research_id()
    run_id = await repo.create_run(research_id, 1, "initial", {}, None)
    payload = dict(
        run_id=run_id,
        research_id=research_id,
        artifact_type="research_brief",
        round_no=0,
        section_id=None,
        angle=None,
        content="brief text",
        stage_name="ScopeAgent",
        outcome="success",
        fallback_used=0,
    )
    aid1 = await repo.upsert_artifact(**payload)
    aid2 = await repo.upsert_artifact(**payload)
    assert aid1 == aid2

    async with SessionLocal() as session:
        rows = (await session.scalars(
            select(ResearchArtifact).where(
                ResearchArtifact.run_id == run_id, ResearchArtifact.artifact_type == "research_brief"
            )
        )).all()
        assert len(rows) == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_llm_call_dedup_and_stage_aggregation() -> None:
    repo = EvalRepository()
    research_id = _new_research_id()
    run_id = await repo.create_run(research_id, 1, "initial", {}, None)
    call_id = uuid.uuid4().hex
    common = dict(
        run_id=run_id,
        research_id=research_id,
        stage_name="SupervisorAgent",
        agent_name="supervisor-1",
        round_no=1,
        request_model="mimo",
        duration_ms=50,
        start_time=now_local(),
    )
    await repo.record_llm_call(llm_call_id=call_id, attempt_no=0, input_tokens=100, output_tokens=50, outcome="success", **common)
    # replay same llm_call_id → one row (dedup)，且 replay 不重复累加 stage_usage
    await repo.record_llm_call(llm_call_id=call_id, attempt_no=2, input_tokens=100, output_tokens=50, outcome="success", **common)
    # second distinct call (带一次 Layer-C 重试) → 聚合进同一 stage_usage 行
    await repo.record_llm_call(
        llm_call_id=uuid.uuid4().hex, attempt_no=1, input_tokens=80, output_tokens=40, outcome="success", **common
    )

    async with SessionLocal() as session:
        calls = (await session.scalars(select(ResearchLlmCall).where(ResearchLlmCall.run_id == run_id))).all()
        assert len(calls) == 2
        usage = (await session.scalars(select(ResearchStageUsage).where(ResearchStageUsage.run_id == run_id))).all()
        assert len(usage) == 1
        assert usage[0].request_count == 2
        assert usage[0].input_tokens == 180
        assert usage[0].output_tokens == 90
        # call2 带 1 次 Layer-C 重试；call1 与 replay（attempt_no=2 但被去重不计入）不贡献
        assert usage[0].retry_count == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_reconcile_tokens_delta_and_reason() -> None:
    repo = EvalRepository()
    research_id = _new_research_id()
    run_id = await repo.create_run(research_id, 1, "initial", {}, None)
    await repo.record_llm_call(
        llm_call_id=uuid.uuid4().hex,
        research_id=research_id,
        run_id=run_id,
        stage_name="SupervisorAgent",
        input_tokens=100,
        output_tokens=50,
        attempt_no=0,
        outcome="success",
        start_time=now_local(),
    )
    await repo.close_run(run_id, "success", None, run_input=100, run_output=50)
    rec = await repo.reconcile_tokens(run_id)
    assert rec["reason"] == "matched"
    assert rec["input_delta"] == 0

    await repo.close_run(run_id, "success", None, run_input=120, run_output=50)
    rec2 = await repo.reconcile_tokens(run_id)
    assert "input_delta" in rec2["reason"]
    assert rec2["input_delta"] == 20


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_claim_manifest_multi_citation_and_no_citation() -> None:
    repo = EvalRepository()
    research_id = _new_research_id()
    run_id = await repo.create_run(research_id, 1, "initial", {}, None)
    report_artifact_id = uuid.uuid4().hex
    claims = [
        {
            "claim_id": "c1",
            "claim_text": "claim one",
            "importance": "critical",
            "section_id": "intro",
            "citations": [
                {"citation_id": "cite-1a", "citation_url": "https://a", "excerpt": "ex a"},
                {"citation_id": "cite-1b", "citation_url": "https://b", "excerpt": "ex b"},
            ],
        },
        {
            "claim_id": "c2",
            "claim_text": "claim two no citation",
            "importance": "minor",
            "citations": [],
        },
    ]
    written = await repo.write_claim_manifest(run_id, research_id, report_artifact_id, claims)
    assert written == 3  # 2 + 1
    written2 = await repo.write_claim_manifest(run_id, research_id, report_artifact_id, claims)
    assert written2 == 3  # idempotent replay
    async with SessionLocal() as session:
        rows = (await session.scalars(
            select(ResearchClaimManifest).where(ResearchClaimManifest.run_id == run_id)
        )).all()
        assert len(rows) == 3
