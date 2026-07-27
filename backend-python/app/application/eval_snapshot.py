"""Eval MVP v2 Commit 6b — Candidate Snapshot Worker。

研究主流程完成后**异步**冻结 Eval Candidate Snapshot。Snapshot 是一个指向
本次 run 全部可评估产物（query/brief/report/source/evidence/version）的不可变索引：

- 不重复写入已经被 Commit 2 写过的 artifacts（user_query/research_brief/source_snapshot/
  evidence_item/round_review/report_final），而是把它们的存在性与 sha256 汇总成一个
  ``eval_candidate_snapshot`` artifact，供 Dataset Curator 选入版本化 Dataset。
- 失败绝不阻塞用户研究（``safe_record`` 包裹，且 pipeline 调用方再包一层 try/except）。
- 不反向修改 ``state``（v2 §0.3 红线 2 / §14）。

幂等键：``(run_id, artifact_type="eval_candidate_snapshot", content_sha256)`` ——
同 run 重跑 snapshot 只会更新索引行。
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.core.timeutil import now_local
from app.infrastructure.db import SessionLocal
from app.infrastructure.eval_repository import eval_repository, safe_record
from app.domain.models import ResearchArtifact
from sqlalchemy import func, select

logger = logging.getLogger(__name__)

SNAPSHOT_ARTIFACT_TYPE = "eval_candidate_snapshot"


async def _collect_artifact_index(run_id: str) -> dict[str, Any]:
    """汇总 run 下所有 artifact 的 type→计数 与各 type 的 sha256 集合（去重）。

    排除 ``eval_candidate_snapshot`` 自身（否则 snapshot 会索引自己，导致每次 freeze
    都因自引用而改变 content_sha256 → 失去幂等性）。
    """
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(
                    ResearchArtifact.artifact_type,
                    func.count(ResearchArtifact.id),
                )
                .where(ResearchArtifact.run_id == run_id)
                .where(ResearchArtifact.artifact_type != SNAPSHOT_ARTIFACT_TYPE)
                .group_by(ResearchArtifact.artifact_type)
            )
        ).all()
        by_type_counts = {r[0]: int(r[1]) for r in rows if r[0]}
        sha_rows = (
            await session.execute(
                select(
                    ResearchArtifact.artifact_type,
                    ResearchArtifact.content_sha256,
                )
                .where(ResearchArtifact.run_id == run_id)
                .where(ResearchArtifact.artifact_type != SNAPSHOT_ARTIFACT_TYPE)
            )
        ).all()
        sha_samples: dict[str, list[str]] = {}
        for art_type, sha in sha_rows:
            if not art_type or not sha:
                continue
            sha_samples.setdefault(art_type, [])
            if len(sha_samples[art_type]) < 3 and sha not in sha_samples[art_type]:
                sha_samples[art_type].append(sha)
    return {"counts": by_type_counts, "sha_samples": sha_samples}


async def freeze_candidate_snapshot(state: Any) -> str | None:
    """冻结一次 run 的 Candidate Snapshot。

    在 pipeline ``_close_run`` 之后、仅 success/degraded outcome 时调用。
    返回 snapshot artifact_id（失败返回 None，异常被 ``safe_record`` 吞）。

    Snapshot 内容（落为 ``eval_candidate_snapshot`` artifact 的 content_json）：
      - run_id / research_id / research_id / outcome / version_snapshot
      - artifact_index: {type: count, sha_samples}
      - total tokens（从 run 行读，不从 state.total_* 读，避免 fork 子状态污染）
    """
    run_id = getattr(state, "run_id", None)
    research_id = getattr(state, "research_id", None)
    if not run_id:
        return None
    try:
        index = await _collect_artifact_index(run_id)
        snapshot_payload = {
            "run_id": run_id,
            "research_id": research_id,
            "attempt_no": getattr(state, "run_attempt_no", None),
            "trigger_type": getattr(state, "run_trigger_type", None),
            "workflow_mode": getattr(state, "workflow_mode", None),
            "budget_name": getattr(state, "budget_name", None),
            "version_snapshot": getattr(state, "run_version_snapshot", None),
            "artifact_index": index,
        }
        content = json.dumps(snapshot_payload, ensure_ascii=False, default=str)
        artifact_id = await eval_repository.upsert_artifact(
            run_id=run_id,
            research_id=research_id or "",
            artifact_type=SNAPSHOT_ARTIFACT_TYPE,
            stage_name="EvalSnapshot",
            content=content,
            outcome="success",
            # frozen_at 放 metadata（不进 content_sha256），保证同 run replay 幂等。
            metadata={
                "artifact_type_counts": index.get("counts", {}),
                "frozen_at": now_local().isoformat(),
            },
        )
        return artifact_id
    except Exception:  # noqa: BLE001
        logger.exception(
            "candidate snapshot freeze failed research_id=%s run_id=%s",
            research_id,
            run_id,
        )
        return None


async def enqueue_snapshot(state: Any) -> None:
    """pipeline finally 入口：异步冻结 snapshot，吞异常不阻塞。

    仅在 success/degraded outcome 时冻结（failed/cancelled 的 run 无可评估终态报告）。
    """
    try:
        from app.application.pipeline import _derive_outcome  # 局部 import 避免循环依赖

        outcome = _derive_outcome(getattr(state, "status", None), getattr(state, "report_quality_context", None))
        if outcome not in ("success", "degraded"):
            return
        if not getattr(state, "run_id", None):
            return
        await safe_record(
            lambda: freeze_candidate_snapshot(state),
            context=f"candidate_snapshot research_id={getattr(state, 'research_id', None)}",
        )
    except Exception:  # noqa: BLE001
        logger.exception(
            "enqueue snapshot failed research_id=%s",
            getattr(state, "research_id", None),
        )
