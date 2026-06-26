from __future__ import annotations

import asyncio
from collections import defaultdict

from sse_starlette.sse import EventSourceResponse

from .cache import get_cache
from .common import ResearchError
from .dto import TimelineItem
from .serialization import dumps


class SseHub:
    def __init__(self) -> None:
        self._clients: defaultdict[str, dict[str, asyncio.Queue[dict | None]]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: int, research_id: str, client_id: str, last_event_id: str | None):
        cache = get_cache()
        if not await cache.verify_research_ownership(research_id, user_id):
            raise ResearchError("研究任务不存在或无权限访问")
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        async with self._lock:
            self._clients[research_id][client_id] = queue
        await self._replay_if_needed(research_id, queue, last_event_id)
        return EventSourceResponse(self._event_generator(research_id, client_id, queue), ping=None)

    async def _event_generator(
        self,
        research_id: str,
        client_id: str,
        queue: asyncio.Queue[dict | None],
    ):
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    yield {"comment": "heartbeat"}
                    continue
                if item is None:
                    break
                yield item
        finally:
            await self.remove(research_id, client_id)

    async def remove(self, research_id: str, client_id: str) -> None:
        async with self._lock:
            clients = self._clients.get(research_id)
            if not clients:
                return
            clients.pop(client_id, None)
            if not clients:
                self._clients.pop(research_id, None)

    async def send_timeline_item(self, research_id: str, item: TimelineItem | None) -> None:
        if item is None or item.sequence_no is None:
            return
        payload = {
            "id": str(item.sequence_no),
            "event": item.kind,
            "data": dumps(item.api_dump()),
        }
        await self._broadcast(research_id, payload)

    async def send_report_stream(self, research_id: str, partial_text: str | None) -> None:
        if not partial_text:
            return
        await self._broadcast(research_id, {"event": "report-stream", "data": partial_text})

    async def complete(self, research_id: str, final_status: str) -> None:
        async with self._lock:
            queues = list(self._clients.get(research_id, {}).values())
        for queue in queues:
            await queue.put({"data": f"[DONE] {final_status}"})
            await queue.put(None)

    async def _broadcast(self, research_id: str, payload: dict) -> None:
        async with self._lock:
            queues = list(self._clients.get(research_id, {}).values())
        for queue in queues:
            await queue.put(payload)

    async def _replay_if_needed(
        self,
        research_id: str,
        queue: asyncio.Queue[dict | None],
        last_event_id: str | None,
    ) -> None:
        if not last_event_id:
            return
        try:
            last_seq = int(last_event_id.strip())
        except ValueError:
            last_seq = 0
        items = await get_cache().get_timeline(research_id, last_seq)
        for item in items:
            await queue.put(
                {
                    "id": str(item.sequence_no),
                    "event": item.kind,
                    "data": dumps(item.api_dump()),
                },
            )


sse_hub = SseHub()
