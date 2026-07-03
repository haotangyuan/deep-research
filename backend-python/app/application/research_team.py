from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

from app.core.constants import EventType
from app.infrastructure.events import event_publisher
from app.infrastructure.llm import model_handler


TTask = TypeVar("TTask")
TResult = TypeVar("TResult")


class AgentScopeResearchTeam:
    def prepare(self, research_id: str, tasks: list[Any]) -> None:
        model_handler.replace_tasks(
            research_id,
            [
                {
                    "id": task.task_id,
                    "subject": task.title,
                    "description": task.research_topic,
                    "owner": task.worker_id,
                    "metadata": {
                        "index": task.index,
                        "workerId": task.worker_id,
                        "framework": "agentscope-python",
                    },
                }
                for task in tasks
            ],
        )

    async def execute(
        self,
        research_id: str,
        tasks: list[TTask],
        max_concurrency: int,
        runner: Callable[[TTask], Awaitable[TResult]],
        failure_handler: Callable[[TTask, Exception], Awaitable[TResult]],
        parent_event_id: int | None,
    ) -> list[TResult]:
        concurrency = max(1, min(len(tasks), max_concurrency))
        semaphore = asyncio.Semaphore(concurrency)
        await self._publish_team_event(
            research_id,
            "in_progress",
            len(tasks),
            concurrency,
            parent_event_id,
        )

        async def run_task(task: Any) -> tuple[int, TResult]:
            async with semaphore:
                model_handler.update_task(
                    research_id,
                    task.task_id,
                    "in_progress",
                    started=True,
                )
                await self._publish_task_event(research_id, task, "in_progress", parent_event_id)
                try:
                    result = await runner(task)
                    model_handler.update_task(
                        research_id,
                        task.task_id,
                        "completed",
                        completed=True,
                    )
                    await self._publish_task_event(research_id, task, "completed", parent_event_id)
                    return task.index, result
                except Exception as exc:
                    model_handler.update_task(
                        research_id,
                        task.task_id,
                        "failed",
                        errorType=exc.__class__.__name__,
                    )
                    await self._publish_task_event(research_id, task, "failed", parent_event_id)
                    return task.index, await failure_handler(task, exc)

        results = await asyncio.gather(*(run_task(task) for task in tasks))
        await self._publish_team_event(
            research_id,
            "completed",
            len(tasks),
            concurrency,
            parent_event_id,
        )
        return [result for _, result in sorted(results, key=lambda item: item[0])]

    @staticmethod
    async def _publish_team_event(
        research_id: str,
        status: str,
        task_count: int,
        max_concurrency: int,
        parent_event_id: int | None,
    ) -> None:
        metadata = {
            "kind": "team_lifecycle",
            "framework": "agentscope-python",
            "stage": "SupervisorAgent",
            "team": "AgentScopeResearchTeam",
            "taskCount": task_count,
            "maxConcurrency": max_concurrency,
            "status": status,
        }
        title = "AgentScope 研究团队已启动" if status == "in_progress" else "AgentScope 研究团队已完成"
        content = (
            f"SupervisorAgent 已调度 {task_count} 个研究任务，最大并发 {max_concurrency}。"
            if status == "in_progress"
            else f"AgentScope 研究团队已完成 {task_count} 个研究任务。"
        )
        await event_publisher.publish_event(
            research_id,
            EventType.AGENT_RUNTIME,
            title,
            json.dumps({**metadata, "summary": content}, ensure_ascii=False),
            parent_event_id,
        )

    @staticmethod
    async def _publish_task_event(
        research_id: str,
        task: Any,
        status: str,
        parent_event_id: int | None,
    ) -> None:
        metadata = {
            "kind": "team_task",
            "framework": "agentscope-python",
            "stage": "SupervisorAgent",
            "taskId": task.task_id,
            "workerId": task.worker_id,
            "taskIndex": task.index,
            "taskTitle": task.title,
            "status": status,
        }
        await event_publisher.publish_event(
            research_id,
            EventType.AGENT_RUNTIME,
            f"{task.title}: {status}",
            json.dumps(metadata, ensure_ascii=False),
            parent_event_id,
        )


research_team = AgentScopeResearchTeam()
