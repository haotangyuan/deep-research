from __future__ import annotations

import asyncio
from datetime import timedelta

from sqlalchemy import text

from app.application.agents import is_cancelled, report_agent, scope_agent, supervisor_agent
from app.infrastructure.cache import get_cache, sequence_util
from app.core.config import get_settings
from app.core.constants import EventType, WorkflowStatus
from app.infrastructure.db import SessionLocal
from app.infrastructure.events import event_publisher
from app.infrastructure.llm import model_handler
from app.infrastructure.observability import stage_span, workflow_span
from app.infrastructure.sse import sse_hub
from app.domain.state import DeepResearchState
from app.core.timeutil import now_local


class ResearchTaskQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[tuple[str, DeepResearchState]] | None = None
        self._workers: list[asyncio.Task] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        settings = get_settings()
        self._queue = asyncio.Queue(maxsize=settings.research_async_queue_capacity)
        self._workers = [
            asyncio.create_task(self._worker(), name=f"research-worker-{idx}")
            for idx in range(settings.research_async_max_pool_size)
        ]
        self._started = True

    async def stop(self) -> None:
        for worker in self._workers:
            worker.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        self._started = False

    async def submit(self, state: DeepResearchState) -> None:
        await self.start()
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
