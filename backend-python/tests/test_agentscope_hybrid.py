from __future__ import annotations

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import agentscope
import pytest
from agentscope.middleware import TracingMiddleware

from app.application.research_team import AgentScopeResearchTeam
from app.application.pipeline import ResearchTaskQueue
from app.domain.dto import WorkflowEventDTO
from app.infrastructure.agentscope_runtime import (
    AgentScopeRuntimeSession,
    ResearchRuntimeMiddleware,
    RuntimeCallMetrics,
)


def test_agentscope_version_is_locked() -> None:
    assert agentscope.__version__ == "2.0.3"


def test_runtime_snapshot_restores_tasks_and_isolated_states() -> None:
    session = AgentScopeRuntimeSession("research-1")

    def factory(state, _middlewares):
        return SimpleNamespace(state=state)

    first = session.get_or_create_agent("worker-1", factory, 4)
    second = session.get_or_create_agent("worker-2", factory, 4)
    assert first.state is not second.state
    first.state.summary = "worker one"
    assert second.state.summary == ""

    session.replace_tasks(
        [
            {
                "id": "task-1",
                "subject": "Topic",
                "description": "Research topic",
                "owner": "worker-1",
                "metadata": {"index": 0},
            },
        ],
    )
    session.update_task("task-1", "failed", reason="test")

    snapshot = session.snapshot()
    assert snapshot["agentStates"]["worker-1"]["context"] == []
    restored = AgentScopeRuntimeSession("research-1")
    restored.restore(snapshot)
    task = restored.tasks()[0]
    assert task.state == "completed"
    assert task.metadata["runtimeStatus"] == "failed"
    assert task.metadata["reason"] == "test"


@pytest.mark.asyncio
async def test_runtime_middleware_enforces_per_reply_tool_budget() -> None:
    metrics = RuntimeCallMetrics()
    middleware = ResearchRuntimeMiddleware(metrics, max_tool_calls=1)

    async def reply_handler(**_kwargs):
        yield "reply"

    assert [item async for item in middleware.on_reply(agent=None, input_kwargs={}, next_handler=reply_handler)] == ["reply"]

    async def acting_handler(**_kwargs):
        yield "tool-result"

    tool_call = SimpleNamespace(name="search")
    assert [
        item
        async for item in middleware.on_acting(agent=None, input_kwargs={"tool_call": tool_call}, next_handler=acting_handler)
    ] == ["tool-result"]
    with pytest.raises(RuntimeError, match="budget exceeded"):
        _ = [
            item
            async for item in middleware.on_acting(agent=None, input_kwargs={"tool_call": tool_call}, next_handler=acting_handler)
        ]

    assert [item async for item in middleware.on_reply(agent=None, input_kwargs={}, next_handler=reply_handler)] == ["reply"]
    assert [
        item
        async for item in middleware.on_acting(agent=None, input_kwargs={"tool_call": tool_call}, next_handler=acting_handler)
    ] == ["tool-result"]


@pytest.mark.asyncio
async def test_research_team_limits_concurrency_and_preserves_order(monkeypatch) -> None:
    team = AgentScopeResearchTeam()
    updates: list[tuple[str, str]] = []
    published: list[tuple[str, str]] = []
    active = 0
    peak = 0

    monkeypatch.setattr(
        "app.application.research_team.model_handler.update_task",
        lambda _research_id, task_id, status, **_metadata: updates.append((task_id, status)),
    )

    async def publish_event(_research_id, _event_type, title, content, _parent=None):
        published.append((title, content))

    monkeypatch.setattr(
        "app.application.research_team.event_publisher.publish_event",
        publish_event,
    )

    tasks = [
        SimpleNamespace(index=index, task_id=f"t{index}", worker_id=f"w{index}", title=f"T{index}")
        for index in range(4)
    ]

    async def runner(task):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.01 * (4 - task.index))
        active -= 1
        return task.index

    async def failure_handler(task, _exc):
        return -task.index

    results = await team.execute("research-1", tasks, 2, runner, failure_handler, None)
    assert results == [0, 1, 2, 3]
    assert peak == 2
    assert updates.count(("t0", "in_progress")) == 1
    assert updates.count(("t3", "completed")) == 1
    assert len(published) == 10
    assert published[0][0] == "AgentScope 研究团队已启动"
    assert published[-1][0] == "AgentScope 研究团队已完成"
    lifecycle = json.loads(published[0][1])
    assert lifecycle["kind"] == "team_lifecycle"
    assert lifecycle["taskCount"] == 4
    assert lifecycle["maxConcurrency"] == 2


def test_runtime_metadata_is_added_without_changing_event_content() -> None:
    event = WorkflowEventDTO(
        id=1,
        research_id="research-1",
        type="AGENT_RUNTIME",
        title="runtime",
        content='{"kind":"team_task","taskId":"t1","status":"completed"}',
        create_time=datetime(2026, 7, 3, 12, 0, 0),
    )
    payload = event.api_dump()
    assert payload["content"] == event.content
    assert payload["runtimeMetadata"]["taskId"] == "t1"
    assert payload["runtimeMetadata"]["status"] == "completed"


def test_runtime_enables_agentscope_tracing_when_observability_is_enabled(monkeypatch) -> None:
    captured_middlewares = []
    settings = SimpleNamespace(research_observability_enabled=True)
    monkeypatch.setattr("app.infrastructure.agentscope_runtime.get_settings", lambda: settings)

    def factory(state, middlewares):
        captured_middlewares.extend(middlewares)
        return SimpleNamespace(state=state)

    AgentScopeRuntimeSession("research-tracing").get_or_create_agent("ScopeAgent", factory, 2)
    assert isinstance(captured_middlewares[0], TracingMiddleware)
    assert isinstance(captured_middlewares[1], ResearchRuntimeMiddleware)


@pytest.mark.asyncio
async def test_research_queue_cancels_only_the_active_pipeline_task(monkeypatch) -> None:
    queue = ResearchTaskQueue()
    started = asyncio.Event()
    cancelled = asyncio.Event()
    settings = SimpleNamespace(research_async_queue_capacity=2, research_async_max_pool_size=1)
    monkeypatch.setattr("app.application.pipeline.get_settings", lambda: settings)

    async def run_forever(_state) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr("app.application.pipeline.agent_pipeline._run_now", run_forever)
    await queue.submit(SimpleNamespace(research_id="cancel-me"))
    await asyncio.wait_for(started.wait(), timeout=1)
    assert queue.cancel("cancel-me") is not None
    await asyncio.wait_for(cancelled.wait(), timeout=1)
    assert queue.cancel("not-active") is None
    await queue.stop()
