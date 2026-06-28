from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import select, text

from app.application.agents import is_cancelled, report_agent, scope_agent, supervisor_agent
from app.infrastructure.cache import get_cache, sequence_util
from app.core.config import get_settings
from app.core.constants import EventType, WorkflowStatus
from app.infrastructure.db import SessionLocal
from app.infrastructure.events import event_publisher
from app.infrastructure.llm import model_handler
from app.infrastructure.observability import stage_span, workflow_span
from app.infrastructure.sse import sse_hub
from app.domain.models import ChatMessage, Model, ResearchSession
from app.domain.runtime import ResearchMessage
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel
from app.core.timeutil import now_local


INTERRUPTED_RUNNING_STATUSES = {
    WorkflowStatus.START,
    WorkflowStatus.IN_SCOPE,
    WorkflowStatus.IN_RESEARCH,
    WorkflowStatus.IN_REPORT,
}

CONFIRMED_DIRECTION_MESSAGE = "确认研究方向，开始执行研究"
REVISE_DIRECTION_PREFIX = "修改意见:"
REVISE_DIRECTION_FALLBACK = "请重新调整研究方向"


def should_rebuild_scope_from_latest_user(latest_user_text: str) -> bool:
    return latest_user_text.startswith(REVISE_DIRECTION_PREFIX) or latest_user_text == REVISE_DIRECTION_FALLBACK


class ResearchTaskQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, DeepResearchState]] | None = None
        self._workers: list[asyncio.Task] = []
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
        self._started = False
        self._recovered = False

    async def submit(self, state: DeepResearchState) -> None:
        await self.start(recover=False)
        assert self._queue is not None
        if self._queue.full():
            raise RuntimeError("系统繁忙，请稍后重试")
        estimated = self._calculate_estimated_time()
        self._queue.put_nowait((state.research_id, state))
        await event_publisher.publish_temp_event(
            state.research_id,
            EventType.QUEUE,
            "排队中：预计 " + estimated + " 开始执行",
        )

    def _calculate_estimated_time(self) -> str:
        if self._queue is None:
            return now_local().strftime("%H:%M")
        settings = get_settings()
        queue_size = self._queue.qsize()
        position = queue_size + 1
        batch = (position + settings.research_async_max_pool_size - 1) // settings.research_async_max_pool_size
        wait_minutes = batch * settings.research_async_task_timeout_minutes
        return (now_local() + timedelta(minutes=wait_minutes)).strftime("%H:%M")


    async def _worker(self) -> None:
        assert self._queue is not None
        while True:
            _, state = await self._queue.get()
            try:
                await agent_pipeline._run_now(state)
            finally:
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
        try:
            with workflow_span(state):
                state.status = WorkflowStatus.START
                await update_research_session(research_id, WorkflowStatus.START, state)

                if state.skip_scope_phase:
                    state.status = WorkflowStatus.IN_SCOPE
                    await update_research_session(research_id, WorkflowStatus.IN_SCOPE, state)
                    await self._execute_phase_2_and_3(state)
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
                    await get_cache().save_checkpoint(research_id, state.model_dump(mode="json"))
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
        except Exception:
            state.status = WorkflowStatus.FAILED
            await event_publisher.publish_event(research_id, EventType.ERROR, "系统错误，请稍后重试", None)
            await update_research_session(research_id, WorkflowStatus.FAILED, state)
        finally:
            try:
                sequence_util.reset(research_id)
                await sse_hub.complete(research_id, state.status)
                model_handler.remove_model(research_id)
            except Exception:
                pass

    async def _execute_phase_2_and_3(self, state: DeepResearchState) -> None:
        research_id = state.research_id
        if await is_cancelled(research_id):
            state.status = WorkflowStatus.CANCELLED
            await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
            return

        state.status = WorkflowStatus.IN_RESEARCH
        await update_research_session(research_id, WorkflowStatus.IN_RESEARCH, state)
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

        if await is_cancelled(research_id):
            state.status = WorkflowStatus.CANCELLED
            await update_research_session(research_id, WorkflowStatus.CANCELLED, state)
            return

        state.status = WorkflowStatus.IN_REPORT
        await update_research_session(research_id, WorkflowStatus.IN_REPORT, state)
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


async def update_research_session(research_id: str, status: str, state: DeepResearchState) -> None:
    set_start = status == WorkflowStatus.START
    set_complete = status in {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.NEED_CLARIFICATION,
        WorkflowStatus.AWAITING_DIRECTION_CONFIRM,
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
        sql += ", start_time = NOW()"
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
