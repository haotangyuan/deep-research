"""Eval MVP v2 落库 Repository。

所有方法均按 key 幂等（ON DUPLICATE KEY UPDATE / 方言适配）。
记录失败由调用方 `_safe_record` 吞，本层正常 raise。

token 单一事实源 = ``research_llm_call`` 行；``research_stage_usage`` 仅作投影/汇总，
**绝不**从 ``state.total_*`` 或 OTel span 属性读（见 v2 §0.3 红线 3）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.timeutil import now_local
from app.domain.models import (
    EvalCaseRun,
    EvalDatasetItem,
    EvalExperiment,
    EvalScore,
    ResearchArtifact,
    ResearchClaimManifest,
    ResearchLlmCall,
    ResearchRun,
    ResearchSpanAttribute,
    ResearchStageUsage,
)
from app.infrastructure.db import SessionLocal

logger = logging.getLogger(__name__)

MAX_RETRY_ON_ATTEMPT_CONFLICT = 3


def _sha256(text: str | None) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def _new_id() -> str:
    return uuid.uuid4().hex


def _json_dumps(value: object | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


class EvalRepository:
    """落库写入门面。所有方法 async、幂等。"""

    async def next_attempt_no(self, research_id: str) -> int:
        """``COALESCE(MAX(attempt_no),0)+1``。仅取号，不建行。

        真正建行 + 冲突重试在 ``create_run`` 内完成。这里只读不写，
        避免预插入一行与 create_run 返回的 run_id 不一致。
        """
        async with SessionLocal() as session:
            current = await session.scalar(
                select(func.coalesce(func.max(ResearchRun.attempt_no), 0)).where(
                    ResearchRun.research_id == research_id
                )
            )
            return int(current or 0) + 1

    async def create_run(
        self,
        research_id: str,
        attempt_no: int,
        trigger_type: str,
        version_snapshot: dict | None,
        state: object | None,
    ) -> str:
        """建行并返回 run_id。``UNIQUE(research_id, attempt_no)`` 冲突时
        重新取号重试（max 3），仍冲突则复用既有行（replay 幂等）。
        """
        snap_cols = self._version_snapshot_columns(version_snapshot, state)
        last_err: Exception | None = None
        run_id = _new_id()
        for _ in range(MAX_RETRY_ON_ATTEMPT_CONFLICT):
            run_id = _new_id()
            async with SessionLocal() as session:
                stmt = (
                    mysql_insert(ResearchRun)
                    .values(
                        id=run_id,
                        research_id=research_id,
                        attempt_no=attempt_no,
                        trigger_type=trigger_type,
                        start_time=now_local(),
                        create_time=now_local(),
                        **snap_cols,
                    )
                    .on_duplicate_key_update(
                        start_time=now_local(),
                        trigger_type=trigger_type,
                        **snap_cols,
                    )
                )
                try:
                    await session.execute(stmt)
                    await session.commit()
                    # ON DUPLICATE KEY UPDATE 走的是既有行，本次 run_id 可能未落库 → 取真实 id
                    existing = await session.scalar(
                        select(ResearchRun).where(
                            ResearchRun.research_id == research_id,
                            ResearchRun.attempt_no == attempt_no,
                        )
                    )
                    return existing.id if existing else run_id
                except Exception as exc:  # noqa: BLE001 — UNIQUE 冲突等
                    await session.rollback()
                    last_err = exc
                    attempt_no = await self.next_attempt_no(research_id)
                    continue
        logger.warning("create_run retries exhausted research_id=%s err=%s", research_id, last_err)
        async with SessionLocal() as session:
            row = await session.scalar(
                select(ResearchRun).where(
                    ResearchRun.research_id == research_id,
                    ResearchRun.attempt_no == attempt_no,
                )
            )
            return row.id if row else run_id

    @staticmethod
    def _version_snapshot_columns(
        version_snapshot: dict | None, state: object | None
    ) -> dict:
        snap = version_snapshot or {}
        columns: dict = {
            "workflow_commit_sha": snap.get("workflow_commit_sha"),
            "workflow_dirty": snap.get("workflow_dirty"),
            "prompt_version_json": _json_dumps(snap.get("prompt_versions")),
            "prompt_hash_json": _json_dumps(snap.get("prompt_hashes")),
            "template_version": snap.get("template_version"),
            "template_sha256": snap.get("template_sha256"),
            "request_model": snap.get("request_model"),
            "response_model": snap.get("response_model"),
        }
        if state is not None:
            for attr in ("status", "workflow_mode", "budget_name", "budget_level"):
                if hasattr(state, attr):
                    value = getattr(state, attr)
                    if attr == "budget_name":
                        columns["budget_level"] = value
                    else:
                        columns[attr] = value
            # trace_id：_open_run 已捕获存进 state.run_trace_id，此处落库（§6.1/§18 跳转链路）
            if hasattr(state, "run_trace_id"):
                columns["trace_id"] = getattr(state, "run_trace_id")
        return {k: v for k, v in columns.items() if v is not None}

    async def close_run(
        self,
        run_id: str,
        outcome: str,
        state: object | None,
        *,
        end_time: datetime | None = None,
        active_ms: int | None = None,
        wall_ms: int | None = None,
        run_input: int = 0,
        run_output: int = 0,
    ) -> None:
        async with SessionLocal() as session:
            row = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))
            if row is None:
                return
            row.outcome = outcome
            row.end_time = end_time or now_local()
            if active_ms is not None:
                row.active_duration_ms = active_ms
            if wall_ms is not None:
                row.wall_duration_ms = wall_ms
            row.input_tokens = run_input
            row.output_tokens = run_output
            if state is not None:
                row.status = getattr(state, "status", None) or row.status
                row.search_count = getattr(state, "search_count", None) or row.search_count
                row.conduct_count = getattr(state, "total_conduct_count", None) or row.conduct_count
                row.round_count = getattr(state, "dynamic_round_no", None) or row.round_count
            await session.commit()

    async def upsert_artifact(
        self,
        run_id: str,
        research_id: str,
        artifact_type: str,
        *,
        stage_name: str | None = None,
        agent_name: str | None = None,
        round_no: int | None = None,
        section_id: str | None = None,
        angle: str | None = None,
        content: str | None = None,
        content_ref: str | None = None,
        content_sha256: str | None = None,
        request_model: str | None = None,
        response_model: str | None = None,
        prompt_version: str | None = None,
        prompt_sha256: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        duration_ms: int | None = None,
        outcome: str | None = None,
        fallback_used: int | None = None,
        metadata: dict | None = None,
    ) -> str:
        sha = content_sha256 or _sha256(content)
        # 幂等键里的 nullable 文本列归一化为空串，避免 MySQL UNIQUE 多 NULL
        # 不参与 ON DUPLICATE KEY UPDATE 去重的问题（NULL 在唯一索引里不匹配）。
        sec_key = section_id or ""
        ang_key = angle or ""
        # round_no 同理：None 归一化为 0，否则 MySQL UNIQUE 允许多 NULL → replay 插重复行。
        # 真实 round 0（首轮/初始）与「无 round 概念」的 artifact（user_query/snapshot 等）
        # 语义上同属「第 0 轮」，归一为 0 不产生语义冲突。
        round_key = round_no if round_no is not None else 0
        artifact_id = _new_id()
        now = now_local()
        async with SessionLocal() as session:
            stmt = mysql_insert(ResearchArtifact).values(
                id=artifact_id,
                run_id=run_id,
                research_id=research_id,
                artifact_type=artifact_type,
                stage_name=stage_name,
                agent_name=agent_name,
                round_no=round_key,
                section_id=sec_key,
                angle=ang_key,
                content=content,
                content_ref=content_ref,
                content_sha256=sha,
                request_model=request_model,
                response_model=response_model,
                prompt_version=prompt_version,
                prompt_sha256=prompt_sha256,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                outcome=outcome,
                fallback_used=fallback_used,
                metadata_json=_json_dumps(metadata) if metadata else None,
                create_time=now,
                update_time=now,
            )
            update_cols = {
                "content": content,
                "content_ref": content_ref,
                "content_sha256": sha,
                "metadata_json": _json_dumps(metadata) if metadata else None,
                "outcome": outcome,
                "fallback_used": fallback_used,
                "request_model": request_model,
                "response_model": response_model,
                "prompt_version": prompt_version,
                "prompt_sha256": prompt_sha256,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "duration_ms": duration_ms,
                "update_time": now,
            }
            stmt = stmt.on_duplicate_key_update(**update_cols)
            await session.execute(stmt)
            await session.commit()
        # ON DUPLICATE KEY UPDATE 走的是既有行，本次 artifact_id 可能未落库 → 取真实 id。
        async with SessionLocal() as session:
            stmt = select(ResearchArtifact).where(
                ResearchArtifact.run_id == run_id,
                ResearchArtifact.artifact_type == artifact_type,
                ResearchArtifact.content_sha256 == sha,
                ResearchArtifact.section_id == sec_key,
                ResearchArtifact.angle == ang_key,
                ResearchArtifact.round_no == round_key,
            )
            existing = await session.scalar(stmt)
            return existing.id if existing else artifact_id

    async def upsert_span_attributes(
        self,
        *,
        run_id: str,
        research_id: str,
        span_scope: str,
        attrs: dict[str, object],
        trace_id: str | None = None,
        round_no: int | None = None,
    ) -> None:
        """trace 标量本地落地（observability 导出 Langfuse 的同时落本表）。

        幂等键 (run_id, span_scope, round_no, attr_key)；replay 时覆盖。
        与 upsert_artifact 严格分工：artifact 存产出全文，本表只存标量，
        同一份标量不两处重复落库（去重原则）。失败由调用方 safe_record 吞。
        """
        round_key = round_no if round_no is not None else 0
        now = now_local()
        rows: list[dict[str, object]] = []
        for attr_key, value in (attrs or {}).items():
            if value is None:
                continue
            num_val: float | None = None
            str_val: str | None = None
            json_val: str | None = None
            if isinstance(value, bool):
                # bool 是 int 子类，单独处理为数值 0/1
                num_val = float(int(value))
            elif isinstance(value, (int, float)):
                num_val = float(value)
            elif isinstance(value, str):
                str_val = value
            else:
                json_val = _json_dumps(value)
            rows.append(
                {
                    "id": _new_id(),
                    "run_id": run_id,
                    "research_id": research_id,
                    "trace_id": trace_id,
                    "span_scope": span_scope,
                    "round_no": round_key,
                    "attr_key": attr_key,
                    "attr_value_num": num_val,
                    "attr_value_str": str_val,
                    "attr_value_json": json_val,
                    "create_time": now,
                }
            )
        if not rows:
            return
        async with SessionLocal() as session:
            for row in rows:
                stmt = mysql_insert(ResearchSpanAttribute).values(**row)
                stmt = stmt.on_duplicate_key_update(
                    trace_id=row["trace_id"],
                    attr_value_num=row["attr_value_num"],
                    attr_value_str=row["attr_value_str"],
                    attr_value_json=row["attr_value_json"],
                )
                await session.execute(stmt)
            await session.commit()

    async def record_llm_call(
        self,
        *,
        run_id: str,
        llm_call_id: str,
        research_id: str | None = None,
        stage_name: str | None = None,
        agent_name: str | None = None,
        round_no: int | None = None,
        report_phase: str | None = None,
        reviewer_lens: str | None = None,
        section_id: str | None = None,
        request_model: str | None = None,
        response_model: str | None = None,
        attempt_no: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        duration_ms: int | None = None,
        outcome: str = "success",
        error_type: str | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ) -> None:
        now = end_time or now_local()
        # 先判存：replay 同一 llm_call_id 不重复累加 stage_usage 投影。
        # aiomysql 的 ON DUPLICATE rowcount 对 insert/update 都返回 1，无法区分，
        # 故用显式存在性检查（记录场景可接受微小竞态）。
        async with SessionLocal() as session:
            existed = await session.scalar(
                select(ResearchLlmCall.id).where(
                    ResearchLlmCall.run_id == run_id,
                    ResearchLlmCall.id == llm_call_id,
                )
            )
            stmt = mysql_insert(ResearchLlmCall).values(
                id=llm_call_id,
                run_id=run_id,
                research_id=research_id or "",
                stage_name=stage_name,
                agent_name=agent_name,
                round_no=round_no,
                report_phase=report_phase,
                reviewer_lens=reviewer_lens,
                section_id=section_id,
                request_model=request_model,
                response_model=response_model,
                attempt_no=attempt_no,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                outcome=outcome,
                error_type=error_type,
                start_time=start_time,
                end_time=now,
            )
            stmt = stmt.on_duplicate_key_update(
                outcome=outcome,
                error_type=error_type,
                attempt_no=attempt_no,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                end_time=now,
            )
            await session.execute(stmt)
            await session.commit()
        # 仅新插入时累加 stage_usage 投影。
        if not existed:
            await self._upsert_stage_usage(
                run_id=run_id,
                stage_name=stage_name,
                agent_name=agent_name,
                round_no=round_no,
                report_phase=report_phase,
                reviewer_lens=reviewer_lens,
                section_id=section_id,
                attempt_no=attempt_no,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                outcome=outcome,
            )

    async def _upsert_stage_usage(
        self,
        *,
        run_id: str,
        stage_name: str | None,
        agent_name: str | None,
        round_no: int | None,
        report_phase: str | None,
        reviewer_lens: str | None,
        section_id: str | None,
        attempt_no: int,
        input_tokens: int,
        output_tokens: int,
        duration_ms: int | None,
        outcome: str,
    ) -> None:
        # 幂等键里的 nullable 文本列归一化为空串，避免 MySQL UNIQUE 多 NULL
        # 不参与 ON DUPLICATE KEY UPDATE 去重的问题（NULL 在唯一索引里不匹配）。
        now = now_local()
        retry_inc = 1 if attempt_no and attempt_no > 0 else 0
        async with SessionLocal() as session:
            stmt = mysql_insert(ResearchStageUsage).values(
                run_id=run_id,
                stage_name=stage_name or "",
                agent_name=agent_name or "",
                round_no=round_no,
                report_phase=report_phase or "",
                reviewer_lens=reviewer_lens or "",
                section_id=section_id or "",
                request_count=1,
                retry_count=retry_inc,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                duration_ms=duration_ms,
                outcome=outcome,
                create_time=now,
                update_time=now,
            )
            stmt = stmt.on_duplicate_key_update(
                request_count=ResearchStageUsage.request_count + 1,
                retry_count=ResearchStageUsage.retry_count + retry_inc,
                input_tokens=ResearchStageUsage.input_tokens + input_tokens,
                output_tokens=ResearchStageUsage.output_tokens + output_tokens,
                duration_ms=(ResearchStageUsage.duration_ms or 0) + (duration_ms or 0),
                outcome=outcome,
                update_time=now,
            )
            await session.execute(stmt)
            await session.commit()

    async def reconcile_tokens(self, run_id: str) -> dict:
        async with SessionLocal() as session:
            stage = await session.execute(
                select(
                    func.coalesce(func.sum(ResearchStageUsage.input_tokens), 0),
                    func.coalesce(func.sum(ResearchStageUsage.output_tokens), 0),
                ).where(ResearchStageUsage.run_id == run_id)
            )
            stage_in, stage_out = stage.one()
            run = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))
        if run is None:
            rec = {
                "stage_input": int(stage_in or 0),
                "stage_output": int(stage_out or 0),
                "run_input": 0,
                "run_output": 0,
                "input_delta": int(stage_in or 0),
                "output_delta": int(stage_out or 0),
                "reason": "run_missing",
            }
        else:
            run_in = int(run.input_tokens or 0)
            run_out = int(run.output_tokens or 0)
            in_delta = run_in - int(stage_in or 0)
            out_delta = run_out - int(stage_out or 0)
            if in_delta == 0 and out_delta == 0:
                reason = "matched"
            elif int(stage_in or 0) == 0 and int(stage_out or 0) == 0:
                reason = "stage_missing"
            else:
                reason = f"input_delta={in_delta},output_delta={out_delta}"
            rec = {
                "stage_input": int(stage_in or 0),
                "stage_output": int(stage_out or 0),
                "run_input": run_in,
                "run_output": run_out,
                "input_delta": in_delta,
                "output_delta": out_delta,
                "reason": reason,
            }
        try:
            await self.upsert_artifact(
                run_id=run_id,
                research_id="",
                artifact_type="token_reconciliation",
                round_no=None,
                section_id=None,
                angle=None,
                content=_json_dumps(rec),
                content_sha256=_sha256(_json_dumps(rec)),
                outcome=rec["reason"],
                metadata={"reconciled_at": now_local().isoformat()},
            )
        except Exception:  # noqa: BLE001 — 对账落库失败不影响主流程
            logger.exception("reconcile_tokens artifact persist failed run_id=%s", run_id)
        return rec

    async def write_claim_manifest(
        self,
        run_id: str,
        research_id: str,
        report_artifact_id: str | None,
        claims: Iterable[dict],
    ) -> int:
        written = 0
        for claim in claims:
            claim_id = claim.get("claim_id")
            claim_text = claim.get("claim_text") or claim.get("text")
            citations = claim.get("citations") or []
            if not citations:
                # 无引用的 claim 落一行；用 sentinel 占位 citation_id，
                # 否则 MySQL UNIQUE 允许多 NULL → replay 会插重复行。
                citations = [{"citation_id": "__none__"}]
            for citation in citations:
                manifest_id = _new_id()
                now = now_local()
                async with SessionLocal() as session:
                    stmt = mysql_insert(ResearchClaimManifest).values(
                        id=manifest_id,
                        run_id=run_id,
                        research_id=research_id,
                        report_artifact_id=report_artifact_id,
                        claim_id=claim_id,
                        claim_text=claim_text,
                        section_id=claim.get("section_id"),
                        importance=claim.get("importance"),
                        citation_id=citation.get("citation_id"),
                        citation_url=citation.get("citation_url") or citation.get("url"),
                        citation_excerpt=citation.get("excerpt"),
                        evidence_id=citation.get("evidence_id"),
                        verifiable=citation.get("verifiable"),
                        metadata_json=_json_dumps(citation.get("metadata")) if citation.get("metadata") else None,
                        create_time=now,
                    )
                    stmt = stmt.on_duplicate_key_update(
                        claim_text=claim_text,
                        section_id=claim.get("section_id"),
                        importance=claim.get("importance"),
                        citation_url=citation.get("citation_url") or citation.get("url"),
                        citation_excerpt=citation.get("excerpt"),
                        evidence_id=citation.get("evidence_id"),
                        verifiable=citation.get("verifiable"),
                    )
                    await session.execute(stmt)
                    await session.commit()
                written += 1
        return written

    # ------------------------------------------------------------------
    # Eval 数据层（Commit 6）：dataset_item / experiment / case_run / score
    # ------------------------------------------------------------------

    async def upsert_dataset_item(
        self,
        *,
        dataset_name: str,
        dataset_version: str,
        query_snapshot: str,
        item_id: str | None = None,
        source_research_id: str | None = None,
        source_run_id: str | None = None,
        task_type: str | None = None,
        language: str | None = None,
        as_of_date: str | None = None,
        required_points: list | dict | None = None,
        reference_facts: list | dict | None = None,
        forbidden_claims: list | dict | None = None,
        source_policy: dict | None = None,
        original_budget_level: str | None = None,
        privacy_status: str = "candidate",
        annotation_status: str = "ready",
        sample_reason: str | None = None,
        split_name: str | None = None,
    ) -> str:
        """幂等写入 dataset_item；按 ``query_sha256`` 去重（同一题目不重复入集）。"""
        query_sha256 = _sha256(query_snapshot)
        now = now_local()
        item_id = item_id or _new_id()
        async with SessionLocal() as session:
            existing = await session.scalar(
                select(EvalDatasetItem).where(EvalDatasetItem.query_sha256 == query_sha256)
            )
            if existing is not None:
                return existing.id
            session.add(
                EvalDatasetItem(
                    id=item_id,
                    dataset_name=dataset_name,
                    dataset_version=dataset_version,
                    source_research_id=source_research_id,
                    source_run_id=source_run_id,
                    query_snapshot=query_snapshot,
                    query_sha256=query_sha256,
                    task_type=task_type,
                    language=language,
                    as_of_date=as_of_date,
                    required_points_json=_json_dumps(required_points),
                    reference_facts_json=_json_dumps(reference_facts),
                    forbidden_claims_json=_json_dumps(forbidden_claims),
                    source_policy_json=_json_dumps(source_policy),
                    original_budget_level=original_budget_level,
                    privacy_status=privacy_status,
                    annotation_status=annotation_status,
                    sample_reason=sample_reason,
                    split_name=split_name,
                    create_time=now,
                )
            )
            await session.commit()
        return item_id

    async def create_experiment(
        self,
        *,
        name: str,
        dataset_name: str,
        dataset_version: str,
        experiment_type: str,
        baseline_experiment_id: str | None = None,
        workflow_version: str | None = None,
        evaluator_version: str | None = None,
        judge_model: str | None = None,
        config: dict | None = None,
        status: str = "planned",
    ) -> str:
        experiment_id = _new_id()
        now = now_local()
        async with SessionLocal() as session:
            session.add(
                EvalExperiment(
                    id=experiment_id,
                    name=name,
                    dataset_name=dataset_name,
                    dataset_version=dataset_version,
                    experiment_type=experiment_type,
                    baseline_experiment_id=baseline_experiment_id,
                    workflow_version=workflow_version,
                    evaluator_version=evaluator_version,
                    judge_model=judge_model,
                    config_json=_json_dumps(config),
                    status=status,
                    create_time=now,
                )
            )
            await session.commit()
        return experiment_id

    async def complete_experiment(self, experiment_id: str, status: str = "completed") -> None:
        async with SessionLocal() as session:
            await session.execute(
                EvalExperiment.__table__.update()
                .where(EvalExperiment.id == experiment_id)
                .values(status=status, complete_time=now_local())
            )
            await session.commit()

    async def upsert_case_run(
        self,
        *,
        experiment_id: str,
        dataset_item_id: str,
        variant_name: str,
        repeat_no: int = 0,
        **fields,
    ) -> str:
        """幂等写入 case_run；唯一键 (experiment_id, dataset_item_id, variant_name, repeat_no)。"""
        case_run_id = _new_id()
        now = now_local()
        async with SessionLocal() as session:
            existing = await session.scalar(
                select(EvalCaseRun).where(
                    EvalCaseRun.experiment_id == experiment_id,
                    EvalCaseRun.dataset_item_id == dataset_item_id,
                    EvalCaseRun.variant_name == variant_name,
                    EvalCaseRun.repeat_no == repeat_no,
                )
            )
            if existing is not None:
                # 更新可变字段
                updates = {k: v for k, v in fields.items() if v is not None}
                if updates:
                    await session.execute(
                        EvalCaseRun.__table__.update()
                        .where(EvalCaseRun.id == existing.id)
                        .values(**updates)
                    )
                    await session.commit()
                return existing.id
            session.add(
                EvalCaseRun(
                    id=case_run_id,
                    experiment_id=experiment_id,
                    dataset_item_id=dataset_item_id,
                    research_id=fields.get("research_id"),
                    run_id=fields.get("run_id"),
                    variant_name=variant_name,
                    repeat_no=repeat_no,
                    gate_passed=fields.get("gate_passed"),
                    failure_reasons_json=_json_dumps(fields.get("failure_reasons")),
                    total_score=fields.get("total_score"),
                    input_tokens=fields.get("input_tokens"),
                    output_tokens=fields.get("output_tokens"),
                    duration_ms=fields.get("duration_ms"),
                    estimated_cost=fields.get("estimated_cost"),
                    result_json=_json_dumps(fields.get("result")),
                    create_time=now,
                )
            )
            await session.commit()
        return case_run_id

    async def upsert_score(
        self,
        *,
        case_run_id: str,
        metric_name: str,
        evaluator_name: str,
        evaluator_version: str,
        metric_group: str | None = None,
        score_value: float | None = None,
        label_value: str | None = None,
        passed: int | None = None,
        judge_model: str | None = None,
        reason: str | None = None,
        details: dict | None = None,
        trace_id: str | None = None,
        report_artifact_id: str | None = None,
    ) -> None:
        """幂等写分数；唯一键 (case_run_id, metric_name, evaluator_version)。

        同一报告可被不同 evaluator_version 重评且结果不互相覆盖。
        trace_id/report_artifact_id 提供 score→trace/artifact 直链（§18 跳转）。
        """
        now = now_local()
        async with SessionLocal() as session:
            stmt = mysql_insert(EvalScore).values(
                case_run_id=case_run_id,
                metric_name=metric_name,
                metric_group=metric_group,
                score_value=score_value,
                label_value=label_value,
                passed=passed,
                evaluator_name=evaluator_name,
                evaluator_version=evaluator_version,
                judge_model=judge_model,
                reason=reason,
                details_json=_json_dumps(details),
                trace_id=trace_id,
                report_artifact_id=report_artifact_id,
                create_time=now,
            )
            stmt = stmt.on_duplicate_key_update(
                metric_group=metric_group,
                score_value=score_value,
                label_value=label_value,
                passed=passed,
                judge_model=judge_model,
                reason=reason,
                details_json=_json_dumps(details),
                trace_id=trace_id,
                report_artifact_id=report_artifact_id,
            )
            await session.execute(stmt)
            await session.commit()

    async def list_scores(self, case_run_id: str) -> list[dict]:
        async with SessionLocal() as session:
            rows = (
                await session.scalars(
                    select(EvalScore).where(EvalScore.case_run_id == case_run_id)
                )
            ).all()
            return [
                {
                    "metric_name": r.metric_name,
                    "metric_group": r.metric_group,
                    "score_value": float(r.score_value) if r.score_value is not None else None,
                    "label_value": r.label_value,
                    "passed": r.passed,
                    "evaluator_name": r.evaluator_name,
                    "evaluator_version": r.evaluator_version,
                    "reason": r.reason,
                    "trace_id": r.trace_id,  # §18 跳转
                    "report_artifact_id": r.report_artifact_id,
                }
                for r in rows
            ]

    async def update_case_run_gate(
        self,
        case_run_id: str,
        *,
        gate_passed: int,
        failure_reasons: list[str] | None = None,
        total_score: float | None = None,
    ) -> None:
        """评估后回填 case_run 的 gate 结果（§8.1 Hard Gate + §18 失败原因码可查询）。

        gate_passed/failure_reasons_json 列由 Commit 6a 建表时已存在，本方法提供写入入口。
        """
        values: dict = {"gate_passed": gate_passed, "failure_reasons_json": _json_dumps(failure_reasons)}
        if total_score is not None:
            values["total_score"] = total_score
        async with SessionLocal() as session:
            await session.execute(
                EvalCaseRun.__table__.update().where(EvalCaseRun.id == case_run_id).values(**values)
            )
            await session.commit()

# 模块级单例，供 pipeline / llm 注入
eval_repository = EvalRepository()


async def safe_record(coro_factory, *, context: str = "") -> None:
    """执行一条落库 coroutine，吞掉异常仅记日志（v2 §0.3 红线 2）。

    记录失败绝不阻塞用户研究。``coro_factory`` 是返回 coroutine 的零参可调用，
    以便 try/except 能包住 await 而不是包住 coroutine 对象构造。
    """
    try:
        await coro_factory()
    except Exception:  # noqa: BLE001
        logger.exception("eval record failed %s", context)


async def ensure_eval_tables(engine: AsyncEngine | None = None) -> None:
    """测试辅助：在给定 engine 上建 eval 表。生产走 ensure_tables。"""
    from app.domain.models import Base

    target = engine
    if target is None:
        from app.infrastructure.db import engine as default_engine

        target = default_engine
    async with target.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
