from __future__ import annotations

import inspect
import time
from collections.abc import AsyncGenerator, Callable
from dataclasses import dataclass, field
from typing import Any

from agentscope.agent import Agent, ContextConfig
from agentscope.middleware import MiddlewareBase, TracingMiddleware
from agentscope.state import AgentState, Task

from app.core.config import get_settings


RUNTIME_SNAPSHOT_VERSION = 1


@dataclass
class RuntimeCallMetrics:
    replies: int = 0
    reasoning_steps: int = 0
    model_calls: int = 0
    tool_calls: int = 0
    tool_names: list[str] = field(default_factory=list)

    def copy(self) -> "RuntimeCallMetrics":
        return RuntimeCallMetrics(
            replies=self.replies,
            reasoning_steps=self.reasoning_steps,
            model_calls=self.model_calls,
            tool_calls=self.tool_calls,
            tool_names=list(self.tool_names),
        )

    def delta(self, before: "RuntimeCallMetrics") -> dict[str, Any]:
        return {
            "replyCount": self.replies - before.replies,
            "reasoningSteps": self.reasoning_steps - before.reasoning_steps,
            "modelCalls": self.model_calls - before.model_calls,
            "toolCalls": self.tool_calls - before.tool_calls,
            "toolNames": self.tool_names[len(before.tool_names) :],
        }


class ResearchRuntimeMiddleware(MiddlewareBase):
    def __init__(self, metrics: RuntimeCallMetrics, max_tool_calls: int) -> None:
        self.metrics = metrics
        self.max_tool_calls = max(1, max_tool_calls)
        self._reply_tool_calls = 0

    async def on_reply(self, agent: Agent, input_kwargs: dict, next_handler) -> AsyncGenerator:
        del agent
        self.metrics.replies += 1
        self._reply_tool_calls = 0
        async for item in next_handler(**input_kwargs):
            yield item

    async def on_reasoning(self, agent: Agent, input_kwargs: dict, next_handler) -> AsyncGenerator:
        del agent
        self.metrics.reasoning_steps += 1
        async for item in next_handler(**input_kwargs):
            yield item

    async def on_acting(self, agent: Agent, input_kwargs: dict, next_handler) -> AsyncGenerator:
        del agent
        if self._reply_tool_calls >= self.max_tool_calls:
            raise RuntimeError("AgentScope tool-call budget exceeded")
        self._reply_tool_calls += 1
        self.metrics.tool_calls += 1
        tool_call = input_kwargs.get("tool_call")
        tool_name = str(getattr(tool_call, "name", "") or "unknown")
        self.metrics.tool_names.append(tool_name)
        async for item in next_handler(**input_kwargs):
            yield item

    async def on_model_call(self, agent: Agent, input_kwargs: dict, next_handler):
        del agent
        self.metrics.model_calls += 1
        output = await next_handler(**input_kwargs)
        if not inspect.isasyncgen(output):
            return output

        async def stream():
            async for item in output:
                yield item

        return stream()


@dataclass
class AgentRuntimeEntry:
    agent: Agent
    state: AgentState
    metrics: RuntimeCallMetrics


class AgentScopeRuntimeSession:
    def __init__(self, research_id: str) -> None:
        self.research_id = research_id
        self.team_state = AgentState(session_id=research_id)
        self._entries: dict[str, AgentRuntimeEntry] = {}
        self._restored_states: dict[str, AgentState] = {}

    @staticmethod
    def context_config() -> ContextConfig:
        settings = get_settings()
        return ContextConfig(
            trigger_ratio=0.8,
            reserve_ratio=0.1,
            tool_result_limit=max(1000, settings.research_search_summary_raw_content_max_chars),
        )

    def get_or_create_agent(
        self,
        key: str,
        factory: Callable[[AgentState, list[MiddlewareBase]], Agent],
        max_tool_calls: int,
    ) -> AgentRuntimeEntry:
        entry = self._entries.get(key)
        if entry is not None:
            return entry
        state = self._restored_states.pop(key, AgentState(session_id=f"{self.research_id}:{key}"))
        metrics = RuntimeCallMetrics()
        middlewares: list[MiddlewareBase] = [
            ResearchRuntimeMiddleware(metrics, max_tool_calls),
        ]
        if get_settings().research_observability_enabled:
            middlewares.insert(0, TracingMiddleware())
        entry = AgentRuntimeEntry(factory(state, middlewares), state, metrics)
        self._entries[key] = entry
        return entry

    def replace_tasks(self, tasks: list[dict[str, Any]]) -> list[Task]:
        native_tasks = [
            Task(
                id=str(item["id"]),
                subject=str(item["subject"]),
                description=str(item["description"]),
                owner=item.get("owner"),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in tasks
        ]
        self.team_state.tasks_context.tasks = native_tasks
        return native_tasks

    def update_task(self, task_id: str, status: str, **metadata: Any) -> Task | None:
        for task in self.team_state.tasks_context.tasks:
            if task.id != task_id:
                continue
            task.state = "completed" if status in {"completed", "failed"} else status
            task.metadata.update(metadata)
            task.metadata["runtimeStatus"] = status
            return task
        return None

    def tasks(self) -> list[Task]:
        return list(self.team_state.tasks_context.tasks)

    def snapshot(self) -> dict[str, Any]:
        states = {
            key: self._checkpoint_state(entry.state)
            for key, entry in self._entries.items()
            if not key.startswith("SearchAgent:")
        }
        states.update(
            {
                key: self._checkpoint_state(state)
                for key, state in self._restored_states.items()
                if not key.startswith("SearchAgent:")
            },
        )
        return {
            "version": RUNTIME_SNAPSHOT_VERSION,
            "researchId": self.research_id,
            "teamState": self.team_state.model_dump(mode="json"),
            "agentStates": states,
        }

    @staticmethod
    def _checkpoint_state(state: AgentState) -> dict[str, Any]:
        data = state.model_dump(mode="json")
        data["context"] = []
        data["middle_context"] = {}
        return data

    def restore(self, snapshot: dict[str, Any] | None) -> None:
        if not snapshot or snapshot.get("version") != RUNTIME_SNAPSHOT_VERSION:
            return
        if snapshot.get("researchId") not in {None, self.research_id}:
            return
        team_state = snapshot.get("teamState")
        if isinstance(team_state, dict):
            self.team_state = AgentState.model_validate(team_state)
        states = snapshot.get("agentStates")
        if isinstance(states, dict):
            self._restored_states = {
                str(key): AgentState.model_validate(value)
                for key, value in states.items()
                if isinstance(value, dict)
            }

    def call_summary(
        self,
        key: str,
        before: RuntimeCallMetrics,
        stage: str,
        started_at: float,
        runtime_context: dict[str, Any],
    ) -> dict[str, Any]:
        entry = self._entries[key]
        summary = entry.metrics.delta(before)
        summary.update(
            {
                "kind": "agent_call",
                "framework": "agentscope-python",
                "stage": stage,
                "instance": key,
                "workerId": runtime_context.get("agent.worker.id"),
                "taskId": runtime_context.get("agent.task.id"),
                "status": "completed",
                "durationMs": round((time.perf_counter() - started_at) * 1000),
            },
        )
        return summary
