from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta

from sqlalchemy import select, text

from app.application.agents import is_cancelled, report_agent, scope_agent, supervisor_agent
from app.application.interventions import (
    dynamic_round_limit,
    expire_pending_interventions,
    has_pending_intervention,
    is_ultra_dynamic_budget,
)
from app.application.ultra_dynamic import build_report_quality_context, render_report_quality_markdown
from app.core.config import get_settings
from app.core.constants import EventType, WorkflowMode, WorkflowStatus
from app.core.prompt_registry import freeze_for_state
from app.core.timeutil import now_local
from app.domain.models import ChatMessage, Model, ResearchSession
from app.domain.runtime import ResearchMessage
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel
from app.infrastructure.cache import get_cache, sequence_util
from app.infrastructure.db import SessionLocal
from app.infrastructure.events import event_publisher
from app.infrastructure.eval_repository import eval_repository, safe_record
from app.infrastructure.llm import model_handler
from app.infrastructure.observability import stage_span, summarize, workflow_span
from app.infrastructure.sse import sse_hub
from app.application.eval_snapshot import enqueue_snapshot


INTERRUPTED_RUNNING_STATUSES = {
    WorkflowStatus.START,
    WorkflowStatus.IN_SCOPE,
    WorkflowStatus.IN_RESEARCH,
    WorkflowStatus.IN_REPORT,
}

CONFIRMED_DIRECTION_MESSAGE = "确认研究方向，开始执行研究"
REVISE_DIRECTION_PREFIX = "修改意见:"
REVISE_DIRECTION_FALLBACK = "请重新调整研究方向"


# Eval MVP v2：resume_status → trigger_type 映射（见 v2 §6.1）
_TRIGGER_MAP = {
    WorkflowStatus.QUEUE: "initial",
    WorkflowStatus.START: "initial",
    WorkflowStatus.FAILED: "retry",
    WorkflowStatus.CANCELLED: "retry",
    WorkflowStatus.AWAITING_DIRECTION_CONFIRM: "hitl_resume",
    WorkflowStatus.NEED_CLARIFICATION: "clarify_resume",
    WorkflowStatus.IN_RESEARCH: "checkpoint_resume",
    WorkflowStatus.IN_REPORT: "checkpoint_resume",
}


def _derive_outcome(status: str | None, report_quality_context: dict | None) -> str:
    """终态 status → run outcome（对齐 pipeline.py:651 的 degraded 判定）。"""
    if status == WorkflowStatus.COMPLETED:
        if report_quality_context and report_quality_context.get("status") != "ready":
            return "degraded"
        return "success"
    if status == WorkflowStatus.FAILED:
        return "failed"
    if status == WorkflowStatus.CANCELLED:
        return "cancelled"
    if status in (WorkflowStatus.AWAITING_DIRECTION_CONFIRM, WorkflowStatus.NEED_CLARIFICATION):
        return "hitl_wait"
    return "success"


def _capture_trace_id() -> str | None:
    """取当前 OTel span 的 trace_id（必须在 workflow_span 内调用）。"""
    try:
        import opentelemetry.trace as otel_trace

        span = otel_trace.get_current_span()
        ctx = span.get_span_context() if span is not None else None
        if ctx is not None and getattr(ctx, "trace_id", 0):
            return f"{ctx.trace_id:032x}"
    except Exception:  # noqa: BLE001 — 观测未初始化时返回 None
        return None
    return None


async def _open_run(state: DeepResearchState, trigger_type: str) -> None:
    """run 开场：捕获 trace_id、取 attempt_no、create_run、写 user_query artifact。

    全程 try/except 吞异常（v2 §0.3 红线 2），失败仅日志，不阻塞研究。
    """
    research_id = state.research_id
    try:
        state.run_trace_id = _capture_trace_id()
        state.run_trigger_type = trigger_type
        attempt_no = await eval_repository.next_attempt_no(research_id)
        version_snapshot = freeze_for_state(state)
        run_id = await eval_repository.create_run(
            research_id, attempt_no, trigger_type, version_snapshot, state
        )
        state.run_id = run_id
        state.run_attempt_no = attempt_no
        state.run_version_snapshot = version_snapshot
        state.run_start_input_tokens = state.total_input_tokens
        state.run_start_output_tokens = state.total_output_tokens
        state.run_start_perf_ts = time.perf_counter()
        # user_query artifact
        user_text = state.chat_history[-1].text if state.chat_history else ""
        await safe_record(
            lambda: eval_repository.upsert_artifact(
                run_id=run_id,
                research_id=research_id,
                artifact_type="user_query",
                stage_name="Pipeline",
                round_no=0,
                content=user_text,
                outcome="success",
                fallback_used=0,
            ),
            context=f"user_query research_id={research_id}",
        )
    except Exception:  # noqa: BLE001
        logger.exception("open_run failed research_id=%s", research_id)


async def _close_run(state: DeepResearchState) -> None:
    """run 收尾：close_run + reconcile_tokens。仅在 finally 调用，吞异常。"""
    if not state.run_id:
        return
    try:
        outcome = _derive_outcome(state.status, state.report_quality_context)
        active_ms = (
            int((time.perf_counter() - state.run_start_perf_ts) * 1000)
            if state.run_start_perf_ts
            else None
        )
        run_input = state.total_input_tokens - state.run_start_input_tokens
        run_output = state.total_output_tokens - state.run_start_output_tokens
        await eval_repository.close_run(
            state.run_id,
            outcome,
            state,
            end_time=now_local(),
            active_ms=active_ms,
            wall_ms=active_ms,
            run_input=run_input,
            run_output=run_output,
        )
    except Exception:  # noqa: BLE001
        logger.exception("close_run failed research_id=%s run_id=%s", state.research_id, state.run_id)
    try:
        await eval_repository.reconcile_tokens(state.run_id)
    except Exception:  # noqa: BLE001
        logger.exception("reconcile_tokens failed run_id=%s", state.run_id)


def should_rebuild_scope_from_latest_user(latest_user_text: str) -> bool:
    return latest_user_text.startswith(REVISE_DIRECTION_PREFIX) or latest_user_text == REVISE_DIRECTION_FALLBACK


logger = logging.getLogger(__name__)


def _dev_error_content(exc: Exception) -> str | None:
    return summarize(f"{exc.__class__.__name__}: {exc}")


def _checkpoint_status(state: DeepResearchState) -> str:
    if state.status in {WorkflowStatus.IN_REPORT, WorkflowStatus.IN_RESEARCH}:
        return state.status
    if state.supervisor_notes:
        return WorkflowStatus.IN_REPORT
    if state.research_brief:
        return WorkflowStatus.IN_RESEARCH
    return state.status


class ResearchTaskQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, DeepResearchState]] | None = None
        self._workers: list[asyncio.Task] = []
        self._active_tasks: dict[str, asyncio.Task[None]] = {}
        self._active_count = 0
        self._started = False
        self._recovered = False

    async def start(self, recover: bool = True) -> None:
        if self._started:
            if recover and not self._recovered:
                await self._recover_interrupted_tasks()
            return
        settings = get_settings()
        self._queue = asyncio.Queue(maxsize=settings.research_async_queue_capacity)
        self._workers = [
            asyncio.create_task(self._worker(), name=f"research-worker-{idx}")
            for idx in range(settings.research_async_max_pool_size)
        ]
        self._started = True
        if recover and not self._recovered:
            await self._recover_interrupted_tasks()

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._active_tasks.clear()
        self._started = False
        self._recovered = False

    def cancel(self, research_id: str) -> asyncio.Task[None] | None:
        task = self._active_tasks.get(research_id)
        if task is None or task.done():
            return None
        task.cancel()
        return task

    async def submit(self, state: DeepResearchState) -> None:
        await self.start(recover=False)
        assert self._queue is not None
        if self._queue.full():
            raise RuntimeError("系统繁忙，请稍后重试")
        queue_notice = self._queue_notice()
        self._queue.put_nowait((state.research_id, state))
        if queue_notice:
            await event_publisher.publish_temp_event(
                state.research_id,
                EventType.QUEUE,
                queue_notice,
            )

    def _queue_notice(self) -> str | None:
        if self._queue is None:
            return None
        settings = get_settings()
        queue_size = self._queue.qsize()
        worker_count = max(1, settings.research_async_max_pool_size)
        if self._active_count < worker_count and queue_size == 0:
            return None
        position = queue_size + 1
        batch = (position + settings.research_async_max_pool_size - 1) // settings.research_async_max_pool_size
        wait_minutes = batch * settings.research_async_task_timeout_minutes
        estimated = (now_local() + timedelta(minutes=wait_minutes)).strftime("%H:%M")
        return f"排队中：前方 {queue_size} 个任务，预计 {estimated} 开始执行"


    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            research_id, state = await self._queue.get()
            try:
                self._active_count += 1
                task = asyncio.create_task(agent_pipeline._run_now(state), name=f"research-run-{research_id}")
                self._active_tasks[research_id] = task
                try:
                    await task
                except asyncio.CancelledError:
                    if asyncio.current_task() and asyncio.current_task().cancelling():
                        raise
            finally:
                self._active_tasks.pop(research_id, None)
                self._active_count = max(0, self._active_count - 1)
                self._queue.task_done()

    async def _recover_interrupted_tasks(self) -> None:
        self._recovered = True
        await self._fail_interrupted_running_tasks()
        queued_states = await self._load_queued_states()
        assert self._queue is not None
        for state in queued_states:
            if self._queue.full():
                await self._mark_recovery_failed(
                    state.research_id,
                    "服务重启后恢复失败",
                    "排队任务数量超过当前队列容量，请重新提交研究。",
                )
                continue
            await event_publisher.publish_event(
                state.research_id,
                EventType.QUEUE,
                "服务重启后已恢复排队任务",
                None,
            )
            self._queue.put_nowait((state.research_id, state))

    async def _fail_interrupted_running_tasks(self) -> None:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ResearchSession.id).where(ResearchSession.status.in_(INTERRUPTED_RUNNING_STATUSES)),
            )
            research_ids = [str(value) for value in result.scalars()]
            if not research_ids:
                return
            await session.execute(
                text(
                    """
                    UPDATE research_session
                    SET status = 'FAILED', complete_time = NOW(), update_time = NOW()
                    WHERE status IN ('START', 'IN_SCOPE', 'IN_RESEARCH', 'IN_REPORT')
                    """,
                ),
            )
            await session.commit()
        for research_id in research_ids:
            await event_publisher.publish_event(
                research_id,
                EventType.ERROR,
                "服务重启导致任务中断",
                "任务执行上下文已丢失，请重新提交研究。",
            )

    async def _load_queued_states(self) -> list[DeepResearchState]:
        async with SessionLocal() as session:
            result = await session.execute(
                select(ResearchSession)
                .where(ResearchSession.status == WorkflowStatus.QUEUE)
                .order_by(ResearchSession.update_time.asc(), ResearchSession.create_time.asc()),
            )
            sessions = list(result.scalars())
        states: list[DeepResearchState] = []
        for session_obj in sessions:
            try:
                states.append(await self._rebuild_queued_state(session_obj))
            except Exception as exc:
                await self._mark_recovery_failed(
                    session_obj.id,
                    "服务重启后恢复失败",
                    str(exc) or "无法重建排队任务，请重新提交研究。",
                )
        return states

    async def _rebuild_queued_state(self, session_obj: ResearchSession) -> DeepResearchState:
        if not session_obj.model_id:
            raise RuntimeError("模型信息缺失，无法恢复排队任务")
        budget_name = (session_obj.budget or "HIGH").upper()
        budget_level = get_settings().budget_levels().get(budget_name) or get_settings().budget_levels()["HIGH"]
        async with SessionLocal() as session:
            model = await session.get(Model, session_obj.model_id)
            if model is None:
                raise RuntimeError("模型不存在，无法恢复排队任务")
            model_handler.add_model(session_obj.id, model)
            result = await session.execute(
                select(ChatMessage)
                .where(ChatMessage.research_id == session_obj.id)
                .order_by(ChatMessage.sequence_no.asc()),
            )
            chat_history = [
                ResearchMessage.user(item.content)
                if item.role == "user"
                else ResearchMessage.assistant(item.content)
                for item in result.scalars()
            ]

        state = await self._state_from_checkpoint(session_obj)
        latest_user_text = self._latest_user_text(chat_history)
        if state is None or should_rebuild_scope_from_latest_user(latest_user_text):
            state = self._new_state_from_history(session_obj, chat_history, budget_name, budget_level)
            if latest_user_text.startswith(REVISE_DIRECTION_PREFIX):
                state.hitl_feedback = latest_user_text.removeprefix(REVISE_DIRECTION_PREFIX).strip() or None
        else:
            state.trace_metadata_model = self._trace_metadata(session_obj, budget_name)
            state.budget = BudgetSnapshot(
                max_conduct_count=budget_level.max_conduct_count,
                max_search_count=budget_level.max_search_count,
                max_concurrent_units=budget_level.max_concurrent_units,
            )
            state.budget_name = budget_name
            state.workflow_mode = WorkflowMode.ULTRA_DYNAMIC if is_ultra_dynamic_budget(budget_name) else WorkflowMode.FIXED
            state.dynamic_max_rounds = dynamic_round_limit() if is_ultra_dynamic_budget(budget_name) else 1
            state.total_input_tokens = int(session_obj.total_input_tokens or state.total_input_tokens or 0)
            state.total_output_tokens = int(session_obj.total_output_tokens or state.total_output_tokens or 0)
            if latest_user_text == CONFIRMED_DIRECTION_MESSAGE:
                state.skip_scope_phase = True
            else:
                state.chat_history = chat_history
        state.status = WorkflowStatus.QUEUE
        return state

    async def _state_from_checkpoint(
        self,
        session_obj: ResearchSession,
    ) -> DeepResearchState | None:
        checkpoint = await get_cache().load_checkpoint(session_obj.id)
        if not checkpoint:
            return None
        return DeepResearchState.model_validate(checkpoint)

    def _new_state_from_history(
        self,
        session_obj: ResearchSession,
        chat_history: list[ResearchMessage],
        budget_name: str,
        budget_level,
    ) -> DeepResearchState:
        return DeepResearchState(
            research_id=session_obj.id,
            chat_history=chat_history,
            status=WorkflowStatus.QUEUE,
            workflow_mode=WorkflowMode.ULTRA_DYNAMIC if is_ultra_dynamic_budget(budget_name) else WorkflowMode.FIXED,
            dynamic_max_rounds=dynamic_round_limit() if is_ultra_dynamic_budget(budget_name) else 1,
            trace_metadata_model=self._trace_metadata(session_obj, budget_name),
            budget=BudgetSnapshot(
                max_conduct_count=budget_level.max_conduct_count,
                max_search_count=budget_level.max_search_count,
                max_concurrent_units=budget_level.max_concurrent_units,
            ),
            budget_name=budget_name,
            supervisor_notes=[],
            researcher_notes=[],
            search_results={},
            search_notes=[],
            hitl_mode="DIRECTION_ONLY",
            total_input_tokens=int(session_obj.total_input_tokens or 0),
            total_output_tokens=int(session_obj.total_output_tokens or 0),
        )

    async def _mark_recovery_failed(self, research_id: str, title: str, content: str) -> None:
        async with SessionLocal() as session:
            await session.execute(
                text(
                    """
                    UPDATE research_session
                    SET status = 'FAILED', complete_time = NOW(), update_time = NOW()
                    WHERE id = :id
                    """,
                ),
                {"id": research_id},
            )
            await session.commit()
        await event_publisher.publish_event(research_id, EventType.ERROR, title, content)

    @staticmethod
    def _latest_user_text(chat_history: list[ResearchMessage]) -> str:
        for message in reversed(chat_history):
            if message.role.value == "user":
                return message.text.strip()
        return ""

    @staticmethod
    def _trace_metadata(session_obj: ResearchSession, budget_name: str) -> TraceMetadataModel:
        return TraceMetadataModel(
            research_id=session_obj.id,
            user_id=int(session_obj.user_id),
            model_id=session_obj.model_id or "",
            budget_level=budget_name,
            agent_framework=get_settings().research_agent_framework,
        )


class AgentPipeline:
    async def run(self, state: DeepResearchState) -> None:
        await research_task_queue.submit(state)

    async def _run_now(self, state: DeepResearchState) -> None:
        research_id = state.research_id
        resume_status = state.status
        trigger_type = _TRIGGER_MAP.get(resume_status, "initial")
        try:
            if await is_cancelled(research_id):
                state.status = WorkflowStatus.CANCELLED
                return
            with workflow_span(state):
                # Eval MVP v2：run 开场（trace_id 必须在 workflow_span 内捕获）
                await _open_run(state, trigger_type)
                state.status = WorkflowStatus.START
                await update_research_session(research_id, WorkflowStatus.START, state)

                if state.skip_scope_phase:
                    state.status = WorkflowStatus.IN_SCOPE
                    await update_research_session(research_id, WorkflowStatus.IN_SCOPE, state)
                    await save_workflow_checkpoint(state)
                    if resume_status == WorkflowStatus.IN_REPORT and state.supervisor_notes:
                        await self._execute_report_only(state)
                    elif resume_status == WorkflowStatus.IN_RESEARCH and state.supervisor_notes:
                        await self._execute_report_only(state)
                    else:
                        await self._execute_phase_2_and_3(state)
                    if state.status == WorkflowStatus.COMPLETED:
                        await get_cache().remove_checkpoint(research_id)
                    return

                async with stage_span("ScopeAgent", state):
                    await scope_agent.run(state)

                if state.status == WorkflowStatus.FAILED:
                    await event_publisher.publish_event(research_id, EventType.ERROR, "范围分析失败", None)
                    await update_research_session(research_id, WorkflowStatus.FAILED, state)
                    return
                if state.status == WorkflowStatus.NEED_CLARIFICATION:
                    await update_research_session(research_id, WorkflowStatus.NEED_CLARIFICATION, state)
                    return
                if state.status != WorkflowStatus.IN_SCOPE:
                    state.status = WorkflowStatus.FAILED
                    await event_publisher.publish_event(
                        research_id,
                        EventType.ERROR,
                        "范围分析状态异常",
                        "status=" + str(state.status),
                    )
                    await update_research_session(research_id, WorkflowStatus.FAILED, state)
                    return
                await update_research_session(research_id, WorkflowStatus.IN_SCOPE, state)

                if state.hitl_mode == "DIRECTION_ONLY":
                    await save_workflow_checkpoint(state)
                    state.status = WorkflowStatus.AWAITING_DIRECTION_CONFIRM
                    await update_research_session(research_id, WorkflowStatus.AWAITING_DIRECTION_CONFIRM, state)
                    await event_publisher.publish_event(
                        research_id,
                        EventType.DIRECTION_CONFIRM,
                        "研究方向已确定，请确认",
                        state.research_brief,
                        state.current_scope_event_id,
                    )
                    await event_publisher.publish_message(
                        research_id,
                        "assistant",
                        "### 研究方向确认\n\n"
                        + (state.research_brief or "")
                        + "\n\n---\n\n请确认研究方向是否准确，或提出修改意见。",
                    )
                    return

                await self._execute_phase_2_and_3(state)
        except asyncio.CancelledError:
            if await is_cancelled(research_id):
                state.status = WorkflowStatus.CANCELLED
            raise
        except Exception as exc:
            logger.exception(
                "research pipeline failed research_id=%s status=%s model_id=%s budget=%s",
                research_id,
                state.status,
                state.trace_metadata_model.model_id,
                state.budget_name,
            )
            state.status = _checkpoint_status(state)
            await save_workflow_checkpoint(state)
            state.status = WorkflowStatus.FAILED
            await event_publisher.publish_event(
                research_id,
                EventType.ERROR,
                "系统错误，请稍后重试",
                _dev_error_content(exc),
            )
            await update_research_session(research_id, WorkflowStatus.FAILED, state)
        finally:
            # Eval MVP v2：run 收尾（close_run + reconcile_tokens），吞异常不阻塞
            await _close_run(state)
            # Eval MVP v2 Commit 6b：异步冻结 Candidate Snapshot（仅 success/degraded）
            await enqueue_snapshot(state)
            try:
                sequence_util.reset(research_id)
                await sse_hub.complete(research_id, state.status)
                model_handler.remove_model(research_id)
            except Exception:
                pass

    async def _execute_phase_2_and_3(self, state: DeepResearchState) -> None:
        if state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC:
            await self._execute_ultra_dynamic_phase_and_3(state)
            return

        research_id = state.research_id
        if await is_cancelled(research_id):
            state.status = WorkflowStatus.CANCELLED
            await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
            return

        state.status = WorkflowStatus.IN_RESEARCH
        await update_research_session(research_id, WorkflowStatus.IN_RESEARCH, state)
        await save_workflow_checkpoint(state)
        async with stage_span("SupervisorAgent", state):
            await supervisor_agent.run(state)

        if state.status == WorkflowStatus.FAILED:
            await event_publisher.publish_event(research_id, EventType.ERROR, "研究规划失败", None)
            await update_research_session(research_id, WorkflowStatus.FAILED, state)
            return
        if state.status == WorkflowStatus.CANCELLED:
            await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
            return
        if state.status != WorkflowStatus.IN_RESEARCH:
            state.status = WorkflowStatus.FAILED
            await event_publisher.publish_event(
                research_id,
                EventType.ERROR,
                "研究规划状态异常",
                "status=" + str(state.status),
            )
            await update_research_session(research_id, WorkflowStatus.FAILED, state)
            return
        await update_research_session(research_id, WorkflowStatus.IN_RESEARCH, state)
        await save_workflow_checkpoint(state)

        if await is_cancelled(research_id):
            state.status = WorkflowStatus.CANCELLED
            await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
            return

        await self._execute_report_only(state)

    async def _execute_ultra_dynamic_phase_and_3(self, state: DeepResearchState) -> None:
        research_id = state.research_id
        # 意图识别 + 模板选择（借鉴点 E）：scope 后按 researchType 选模板
        if not state.workflow_template:
            from app.application.workflow_template import select_template

            template = select_template(state.research_type, state.research_type_confidence)
            state.workflow_template = template
            await event_publisher.publish_event(
                research_id,
                EventType.AGENT_RUNTIME,
                f"编排模板: {template.get('type', 'general')}（最大 {state.dynamic_max_rounds} 轮）",
                json.dumps({"kind": "workflow_template", "template": template}, ensure_ascii=False),
                state.current_supervisor_event_id,
            )
        from app.application.workflow_template import template_budget

        # Re-apply persisted template limits after checkpoint/resume. The
        # service-level budget only contains the tier defaults.
        state.dynamic_max_rounds = int(state.workflow_template.get("maxRounds", state.dynamic_max_rounds))
        state.budget = state.budget.model_copy(update=template_budget(state.workflow_template))
        while True:
            if await is_cancelled(research_id):
                state.status = WorkflowStatus.CANCELLED
                await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
                return

            state.status = WorkflowStatus.IN_RESEARCH
            state.dynamic_round_no += 1
            # Per-round and run-level budgets are deliberately independent.
            # Reset only the round counter; total_conduct_count remains the
            # cost guardrail across all ULTRA rounds.
            state.conduct_count = 0
            await update_research_session(research_id, WorkflowStatus.IN_RESEARCH, state)
            await save_workflow_checkpoint(state)
            async with stage_span("SupervisorAgent", state):
                await supervisor_agent.run(state)

            if state.status == WorkflowStatus.FAILED:
                await event_publisher.publish_event(research_id, EventType.ERROR, "研究规划失败", None)
                await update_research_session(research_id, WorkflowStatus.FAILED, state)
                return
            if state.status == WorkflowStatus.CANCELLED:
                await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
                return
            if state.status != WorkflowStatus.IN_RESEARCH:
                state.status = WorkflowStatus.FAILED
                await event_publisher.publish_event(
                    research_id,
                    EventType.ERROR,
                    "研究规划状态异常",
                    "status=" + str(state.status),
                )
                await update_research_session(research_id, WorkflowStatus.FAILED, state)
                return
            await update_research_session(research_id, WorkflowStatus.IN_RESEARCH, state)
            await save_workflow_checkpoint(state)

            pending = await has_pending_intervention(research_id)
            continue_for_decision = bool((state.latest_dynamic_decision or {}).get("nextAction") == "continue")
            if state.total_conduct_count >= state.budget.total_conduct_limit:
                if pending:
                    await expire_pending_interventions(research_id, "研究任务预算已耗尽，未能继续追加下一轮规划。", "budget_exhausted")
                    await event_publisher.publish_event(
                        research_id,
                        EventType.INTERVENTION,
                        "待生效调整已过期",
                        "研究任务预算已耗尽，未能继续追加下一轮规划。",
                    )
                    await event_publisher.publish_message(
                        research_id,
                        "assistant",
                        "待生效的下一轮调整未能执行：当前 ULTRA 研究任务预算已耗尽。",
                    )
                if continue_for_decision:
                    state.report_quality_context = build_report_quality_context(
                        state.latest_dynamic_decision,
                        "研究任务预算已耗尽，无法继续补强缺口。",
                    )
                break

            should_continue = pending or continue_for_decision
            if not should_continue:
                break

            if state.dynamic_round_no >= max(1, state.dynamic_max_rounds):
                if pending:
                    await expire_pending_interventions(research_id, "已达到 ULTRA 动态最大轮次，未能继续追加下一轮规划。", "max_rounds")
                    await event_publisher.publish_event(
                        research_id,
                        EventType.INTERVENTION,
                        "待生效调整已过期",
                        "已达到 ULTRA 动态最大轮次，未能继续追加下一轮规划。",
                    )
                    await event_publisher.publish_message(
                        research_id,
                        "assistant",
                        "待生效的下一轮调整未能执行：本次 ULTRA 动态工作流已达到最大轮次。",
                    )
                if continue_for_decision:
                    state.report_quality_context = build_report_quality_context(
                        state.latest_dynamic_decision,
                        "已达到 ULTRA 动态最大轮次，无法继续补强缺口。",
                    )
                break

            if continue_for_decision:
                await event_publisher.publish_message(
                    research_id,
                    "assistant",
                    f"系统将在第 {state.dynamic_round_no + 1} 轮继续补强当前证据缺口。",
                )

        await self._execute_report_only(state)

    async def _execute_report_only(self, state: DeepResearchState) -> None:
        research_id = state.research_id
        if await is_cancelled(research_id):
            state.status = WorkflowStatus.CANCELLED
            await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
            return

        if state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC:
            await self._apply_ultra_report_gate(state)

        state.status = WorkflowStatus.IN_REPORT
        await update_research_session(research_id, WorkflowStatus.IN_REPORT, state)
        await save_workflow_checkpoint(state)
        async with stage_span("ReportAgent", state):
            await report_agent.run(state)

        if state.status == WorkflowStatus.FAILED:
            await event_publisher.publish_event(research_id, EventType.ERROR, "报告生成失败", None)
            await update_research_session(research_id, WorkflowStatus.FAILED, state)
            return
        if state.status == WorkflowStatus.CANCELLED:
            await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
            return
        if state.status != WorkflowStatus.IN_REPORT:
            state.status = WorkflowStatus.FAILED
            await event_publisher.publish_event(
                research_id,
                EventType.ERROR,
                "报告生成状态异常",
                "status=" + str(state.status),
            )
            await update_research_session(research_id, WorkflowStatus.FAILED, state)
            return

        state.status = WorkflowStatus.COMPLETED
        await update_research_session(research_id, WorkflowStatus.COMPLETED, state)

    async def _apply_ultra_report_gate(self, state: DeepResearchState) -> None:
        async with stage_span("UltraReportGate", state) as span:
            context = state.report_quality_context or build_report_quality_context(state.latest_dynamic_decision)
            state.report_quality_context = context
            span.set_attribute("report.quality.status", str(context.get("status") or ""))
            span.set_attribute("report.weak.sections.count", len(context.get("weakSections") or []))
            span.set_attribute("report.blocking.gaps.count", len(context.get("blockingGaps") or []))
            # trace 标量本地落地（observability 导出 Langfuse 的同时落 research_span_attribute，
            # 供 eval 读取 report quality 摘要；set_attribute 不删，Langfuse 导出不受影响）。
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                weak_sections = context.get("weakSections") or []
                blocking_gaps = context.get("blockingGaps") or []
                gate_attrs = {
                    "report.quality.status": str(context.get("status") or ""),
                    "report.weak.sections.count": len(weak_sections),
                    "report.blocking.gaps.count": len(blocking_gaps),
                }
                if weak_sections:
                    gate_attrs["report.weak.sections"] = weak_sections
                if blocking_gaps:
                    gate_attrs["report.blocking.gaps"] = blocking_gaps
                await safe_record(
                    lambda: eval_repository.upsert_span_attributes(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        trace_id=state.run_trace_id,
                        span_scope="UltraReportGate",
                        round_no=0,
                        attrs=gate_attrs,
                    ),
                    context=f"span_attribute report_gate research_id={state.research_id}",
                )
            title = "报告前验证通过" if context.get("status") == "ready" else "报告前验证未完全通过"
            await event_publisher.publish_event(
                state.research_id,
                EventType.SUPERVISOR,
                title,
                render_report_quality_markdown(context),
                state.current_supervisor_event_id,
            )
            if context.get("status") != "ready":
                await event_publisher.publish_message(
                    state.research_id,
                    "assistant",
                    "报告前验证发现仍有证据缺口，最终报告会明确标注不确定性与未覆盖部分。",
                )


async def update_research_session(research_id: str, status: str, state: DeepResearchState) -> None:
    set_start = status == WorkflowStatus.START
    set_complete = status in {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    }
    sql = """
        UPDATE research_session
        SET status = :status,
            update_time = NOW(),
            total_input_tokens = :input_tokens,
            total_output_tokens = :output_tokens
    """
    if set_start:
        sql += ", start_time = COALESCE(start_time, NOW()), complete_time = NULL"
    if set_complete:
        sql += ", complete_time = NOW()"
    sql += " WHERE id = :id"
    async with SessionLocal() as session:
        await session.execute(
            text(sql),
            {
                "id": research_id,
                "status": status,
                "input_tokens": state.total_input_tokens,
                "output_tokens": state.total_output_tokens,
            },
        )
        await session.commit()


research_task_queue = ResearchTaskQueue()
agent_pipeline = AgentPipeline()


async def save_workflow_checkpoint(state: DeepResearchState) -> None:
    snapshot = model_handler.snapshot(state.research_id)
    if snapshot is not None:
        state.agent_runtime_snapshot = snapshot
    await get_cache().save_checkpoint(state.research_id, state.model_dump(mode="json"))
