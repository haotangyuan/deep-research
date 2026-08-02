"""Eval MVP v2 Commit 6e — Runner + 6 题 Dataset 测试。

- 6 题 dataset 结构（纯逻辑）。
- seed_dataset 幂等（DB）。
- evaluate_case_run 端到端：造 run + report_final + claim_manifest，跑确定性评估器，
  验证 eval_score 写入且能 list 出来。
- build_paired_diff_report（纯逻辑）。

DB 测试走真实 MySQL；LLM judges 不参与（无 chat_fn）。
"""
from __future__ import annotations

import json
import uuid

import pytest
import pymysql
from sqlalchemy import select

from app.core.config import get_settings
from app.core.timeutil import now_local
from app.domain.models import EvalCaseRun, EvalDatasetItem, EvalScore
from app.infrastructure.db import SessionLocal
from app.infrastructure.eval_repository import EvalRepository, eval_repository
from evals.runner import (
    build_paired_diff_report,
    default_evaluators,
    evaluate_case_run,
    load_dataset_json,
    select_mechanism_item_ids,
    seed_dataset,
)

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


def test_dataset_json_has_six_questions_across_task_types() -> None:
    data = load_dataset_json()
    assert data["dataset_name"] == "mvp_v1"
    assert len(data["items"]) == 6
    task_types = {i["task_type"] for i in data["items"]}
    # §11.2 六类全覆盖
    assert task_types == {
        "fact_lookup",
        "tech_comparison",
        "market_analysis",
        "academic_review",
        "trend_forecast",
        "evidence_conflict",
    }
    for item in data["items"]:
        assert item["query_snapshot"]
        assert item["required_points"]
        assert item["evaluation_contract"]["eligible_variants"] == ["MEDIUM", "HIGH", "ULTRA"]
        for criterion in item["required_points"]:
            assert criterion["criterion_id"]
            assert criterion["text"]
            assert criterion["weight"] >= 1
            assert isinstance(criterion["critical"], bool)
            assert criterion["acceptance"]


def test_formal_dataset_has_40_paired_items_and_valid_mechanism_subsets() -> None:
    data = load_dataset_json("formal_v1_40questions.json")
    items = data["items"]
    assert data["dataset_name"] == "deep_research_formal_v1"
    assert data["experiment_design"]["tier_comparison_repeats"] == 1
    assert data["experiment_design"]["mechanism_ablation_repeats"] == 1
    assert len(items) == 40
    assert sum(item["split_name"] == "calibration" for item in items) == 10
    assert sum(item["split_name"] == "test" for item in items) == 30

    expected_task_counts = {
        "fact_lookup": 6,
        "tech_comparison": 8,
        "market_analysis": 7,
        "academic_review": 7,
        "trend_forecast": 6,
        "evidence_conflict": 6,
    }
    assert {
        task_type: sum(item["task_type"] == task_type for item in items)
        for task_type in expected_task_counts
    } == expected_task_counts
    assert {
        difficulty: sum(
            item["evaluation_contract"]["strata"]["difficulty"] == difficulty for item in items
        )
        for difficulty in ("easy", "medium", "hard")
    } == {"easy": 8, "medium": 18, "hard": 14}

    item_ids = {item["item_id"] for item in items}
    assert len(item_ids) == 40
    for item in items:
        assert item["evaluation_contract"]["eligible_variants"] == ["MEDIUM", "HIGH", "ULTRA"]
        assert item["evaluation_contract"]["constraints"]["as_of_date"] == item["as_of_date"]
        assert len(item["required_points"]) >= 3
        assert len(item["reference_facts"]) >= 2
        assert item["forbidden_claims"]
        criterion_ids = [criterion["criterion_id"] for criterion in item["required_points"]]
        assert len(criterion_ids) == len(set(criterion_ids))
        for criterion in item["required_points"]:
            assert criterion["text"]
            assert criterion["weight"] >= 1
            assert isinstance(criterion["critical"], bool)
            assert criterion["acceptance"]

    expected_mechanism_sizes = {
        "high_report_ablation": 8,
        "reviewer_ablation": 10,
        "multi_round_ablation": 10,
        "section_team_ablation": 6,
        "claim_verifier_ablation": 8,
    }
    tag_by_suite = {
        "high_report_ablation": "synthesis_applicable",
        "reviewer_ablation": "reviewer_applicable",
        "multi_round_ablation": "multi_round_applicable",
        "section_team_ablation": "section_team_applicable",
        "claim_verifier_ablation": "claim_verifier_applicable",
    }
    by_id = {item["item_id"]: item for item in items}
    for suite_name, expected_size in expected_mechanism_sizes.items():
        selected = select_mechanism_item_ids(data, suite_name)
        assert len(selected) == expected_size
        assert set(selected) <= item_ids
        assert all(
            by_id[item_id]["evaluation_contract"]["mechanism_tags"][tag_by_suite[suite_name]]
            for item_id in selected
        )


@pytest.fixture(autouse=True)
async def _truncate_eval_tables():
    if not DB_AVAILABLE:
        yield
        return
    from app.infrastructure.db import engine
    from sqlalchemy import text

    async with engine.begin() as conn:
        for t in ("eval_score", "eval_case_run", "eval_experiment", "eval_dataset_item", "research_claim_manifest", "research_artifact", "research_run"):
            await conn.execute(text("TRUNCATE TABLE " + t))
    yield


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_seed_dataset_idempotent() -> None:
    ids1 = await seed_dataset()
    assert len(ids1) == 6
    # replay → 同 id（按 query_sha256 去重）
    ids2 = await seed_dataset()
    assert sorted(ids1) == sorted(ids2)
    async with SessionLocal() as session:
        rows = (await session.scalars(select(EvalDatasetItem))).all()
        assert len(rows) == 6


@pytest.mark.asyncio
@pytest.mark.skipif(not DB_AVAILABLE, reason=DB_REASON)
async def test_evaluate_case_run_writes_scores_end_to_end() -> None:
    repo = EvalRepository()
    research_id = "research-runner-" + uuid.uuid4().hex[:8]
    run_id = await repo.create_run(research_id, 1, "initial", {"workflow_commit_sha": "abc"}, None)
    # 造 report_final artifact + claim_manifest
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
        [
            {
                "claim_id": "c1",
                "claim_text": "市场规模 5000 亿",
                "importance": "critical",
                "citations": [{"citation_id": "cite1", "citation_url": "https://a.com", "excerpt": "数据"}],
            }
        ],
    )
    # dataset_item + experiment + case_run
    item_id = await repo.upsert_dataset_item(
        dataset_name="mvp_v1",
        dataset_version="1",
        query_snapshot="市场分析题：" + uuid.uuid4().hex,
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
    # 关联 run_id 到 case_run（先 upsert 再 update run_id）
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

    # 跑确定性评估器（无 chat_fn）
    results = await evaluate_case_run(case_run_id)
    metric_names = {r.metric_name for r in results}
    assert "workflow_completed" in metric_names
    assert "citation_traceability" in metric_names
    assert "effective_citation_count" in metric_names

    # 验证 eval_score 真写库
    scores = await eval_repository.list_scores(case_run_id)
    written_metrics = {s["metric_name"] for s in scores}
    assert "workflow_completed" in written_metrics
    # evaluator_version 隔离：同 metric 不同 version 不覆盖（此处单 version）
    assert all(s["evaluator_version"] for s in scores)


def test_build_paired_diff_report_produces_markdown() -> None:
    summary = {
        "MEDIUM": {
            "cr1": {"workflow_completed": 1.0, "effective_citation_count": 2.0},
            "cr2": {"workflow_completed": 1.0, "effective_citation_count": 3.0},
        },
        "ULTRA": {
            "cr1": {"workflow_completed": 1.0, "effective_citation_count": 5.0},
            "cr2": {"workflow_completed": 1.0, "effective_citation_count": 6.0},
        },
    }
    report = build_paired_diff_report(summary)
    assert "# Eval 配对差异报告" in report
    assert "MEDIUM" in report and "ULTRA" in report
    assert "决策输出" in report


def test_default_evaluators_offline_vs_with_chat() -> None:
    offline = default_evaluators()
    assert "citation_judge" not in {e.name for e in offline}

    async def fake_chat(sys_p, user_p):
        return "{}"

    with_chat = default_evaluators(chat_fn=fake_chat, judge_model="mimo")
    names = {e.name for e in with_chat}
    assert "citation_judge" in names
    assert "coverage_judge" in names
    assert "report_quality_judge" in names
