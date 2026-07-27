"""Eval MVP v2 Commit 6a — Eval 数据层 Repository 测试（dataset/experiment/case_run/score）。

遵循 CLAUDE.md「不 mock MySQL」：repository 的 DB 操作走真实 MySQL。
若本地 MySQL 不可达则跳过（CI 无 DB 时不算失败）。
"""
from __future__ import annotations

import uuid

import pytest
import pymysql
from sqlalchemy import select

from app.core.config import get_settings
from app.core.timeutil import now_local
from app.domain.models import (
    EvalCaseRun,
    EvalDatasetItem,
    EvalExperiment,
    EvalScore,
)
from app.infrastructure.db import SessionLocal
from app.infrastructure.eval_repository import EvalRepository

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
async def _truncate_eval_dataset_tables():
    if not DB_AVAILABLE:
        yield
        return
    from app.infrastructure.db import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        for t in ("eval_score", "eval_case_run", "eval_experiment", "eval_dataset_item"):
            await conn.execute(text("TRUNCATE TABLE " + t))
    yield


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_dataset_item_dedup_by_query_sha256() -> None:
    repo = EvalRepository()
    query = "事实检索题：2026 年某市场规模"
    id1 = await repo.upsert_dataset_item(
        dataset_name="mvp_v1",
        dataset_version="1",
        query_snapshot=query,
        task_type="fact_lookup",
        language="zh",
        required_points=["市场规模", "增长率"],
    )
    # 同 query 再次写入 → 返回已存在的 id（按 query_sha256 去重）
    id2 = await repo.upsert_dataset_item(
        dataset_name="mvp_v1",
        dataset_version="1",
        query_snapshot=query,
        task_type="fact_lookup",
    )
    assert id1 == id2

    async with SessionLocal() as session:
        rows = (await session.scalars(select(EvalDatasetItem))).all()
        assert len(rows) == 1


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_experiment_and_case_run_lifecycle() -> None:
    repo = EvalRepository()
    item_id = await repo.upsert_dataset_item(
        dataset_name="mvp_v1",
        dataset_version="1",
        query_snapshot="技术比较题：" + uuid.uuid4().hex,
        task_type="tech_comparison",
    )
    exp_id = await repo.create_experiment(
        name="tier_cmp_1",
        dataset_name="mvp_v1",
        dataset_version="1",
        experiment_type="tier_comparison",
        evaluator_version="eval-v1",
        judge_model="mimo",
    )
    # 三个档位各一条 case_run
    cr_medium = await repo.upsert_case_run(
        experiment_id=exp_id,
        dataset_item_id=item_id,
        variant_name="MEDIUM",
        repeat_no=0,
        research_id="r1",
        run_id="run1",
        gate_passed=1,
        input_tokens=81000,
        output_tokens=30000,
        duration_ms=12000,
        result={"report": "..."},
    )
    cr_high = await repo.upsert_case_run(
        experiment_id=exp_id,
        dataset_item_id=item_id,
        variant_name="HIGH",
        repeat_no=0,
        research_id="r2",
        run_id="run2",
        gate_passed=1,
        input_tokens=132000,
        output_tokens=38000,
    )
    # 同 variant+repeat replay → 返回同一 case_run_id
    cr_high_replay = await repo.upsert_case_run(
        experiment_id=exp_id,
        dataset_item_id=item_id,
        variant_name="HIGH",
        repeat_no=0,
        run_id="run2b",
        input_tokens=132000,
        output_tokens=38000,
        total_score=0.82,
    )
    assert cr_high == cr_high_replay
    assert cr_medium != cr_high

    await repo.complete_experiment(exp_id, status="completed")
    async with SessionLocal() as session:
        exp = await session.scalar(select(EvalExperiment).where(EvalExperiment.id == exp_id))
        assert exp.status == "completed"
        assert exp.complete_time is not None
        cr = await session.scalar(select(EvalCaseRun).where(EvalCaseRun.id == cr_high))
        assert float(cr.total_score) == 0.82  # replay 更新了 total_score（Decimal→float 比较）


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_score_upsert_evaluator_version_isolation() -> None:
    """同一 case_run 可被不同 evaluator_version 重评且不互相覆盖。"""
    repo = EvalRepository()
    item_id = await repo.upsert_dataset_item(
        dataset_name="mvp_v1",
        dataset_version="1",
        query_snapshot="市场分析题：" + uuid.uuid4().hex,
        task_type="market_analysis",
    )
    exp_id = await repo.create_experiment(
        name="ablation_1",
        dataset_name="mvp_v1",
        dataset_version="1",
        experiment_type="high_report_ablation",
        evaluator_version="eval-v1",
    )
    cr_id = await repo.upsert_case_run(
        experiment_id=exp_id,
        dataset_item_id=item_id,
        variant_name="HIGH",
    )
    # v1 打 citation_completeness = 0.9
    await repo.upsert_score(
        case_run_id=cr_id,
        metric_name="citation_completeness",
        evaluator_name="citation_judge",
        evaluator_version="eval-v1",
        metric_group="factuality",
        score_value=0.9,
        passed=1,
        reason="v1 判定",
    )
    # 同 evaluator 重评 → 更新（不新增行）
    await repo.upsert_score(
        case_run_id=cr_id,
        metric_name="citation_completeness",
        evaluator_name="citation_judge",
        evaluator_version="eval-v1",
        metric_group="factuality",
        score_value=0.85,
        passed=1,
        reason="v1 重判",
    )
    # 不同 evaluator_version → 新行
    await repo.upsert_score(
        case_run_id=cr_id,
        metric_name="citation_completeness",
        evaluator_name="citation_judge",
        evaluator_version="eval-v2",
        metric_group="factuality",
        score_value=0.88,
        passed=1,
        reason="v2 判定",
    )
    scores = await repo.list_scores(cr_id)
    assert len(scores) == 2
    versions = sorted(s["evaluator_version"] for s in scores)
    assert versions == ["eval-v1", "eval-v2"]
    v1 = [s for s in scores if s["evaluator_version"] == "eval-v1"][0]
    assert v1["score_value"] == 0.85  # 重评覆盖
