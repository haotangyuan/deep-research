from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import redis.asyncio as redis
from sqlalchemy import func, select, text

from app.core.config import get_settings
from app.infrastructure.db import SessionLocal
from app.domain.dto import ChatMessageDTO, TimelineItem, WorkflowEventDTO
from app.domain.models import ChatMessage, ResearchSession, WorkflowEvent
from app.core.serialization import dumps, loads
from app.core.timeutil import now_local


KIND_MESSAGE = "message"
KIND_EVENT = "event"
TIMELINE_TTL_SECONDS = 30 * 60
CHECKPOINT_TTL_SECONDS = 30 * 60


class SequenceUtil:
    def __init__(self) -> None:
        self._values: dict[str, int] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def next(self, research_id: str) -> int:
        async with self._locks[research_id]:
            if research_id not in self._values:
                async with SessionLocal() as session:
                    result = await session.execute(
                        text(
                            """
                            SELECT COALESCE(MAX(sequence_no), 0) FROM (
                                SELECT sequence_no FROM chat_message WHERE research_id = :research_id
                                UNION ALL
                                SELECT sequence_no FROM workflow_event WHERE research_id = :research_id
                            ) t
                            """,
                        ),
                        {"research_id": research_id},
                    )
                    self._values[research_id] = int(result.scalar() or 0)
            self._values[research_id] += 1
            return self._values[research_id]

    def reset(self, research_id: str) -> None:
        self._values.pop(research_id, None)


sequence_util = SequenceUtil()


class CacheUtil:
    def __init__(self, redis_client: redis.Redis) -> None:
        self.redis = redis_client

    @staticmethod
    def timeline_key(research_id: str) -> str:
        return f"research:{research_id}:timeline"

    @staticmethod
    def user_researches_key(user_id: int) -> str:
        return f"user:{user_id}:researches"

    @staticmethod
    def checkpoint_key(research_id: str) -> str:
        return f"research:{research_id}:checkpoint"

    async def save_message(self, research_id: str, role: str, content: str) -> TimelineItem:
        seq = await sequence_util.next(research_id)
        async with SessionLocal() as session:
            message = ChatMessage(
                research_id=research_id,
                role=role,
                content=content,
                sequence_no=seq,
                create_time=now_local(),
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            item = TimelineItem(
                kind=KIND_MESSAGE,
                research_id=research_id,
                sequence_no=seq,
                message=ChatMessageDTO.model_validate(message),
            )
        await self.write_to_redis(research_id, [item])
        return item

    async def save_event(
        self,
        research_id: str,
        event_type: str,
        title: str,
        content: str | None,
        parent_event_id: int | None = None,
    ) -> TimelineItem:
        seq = await sequence_util.next(research_id)
        async with SessionLocal() as session:
            event = WorkflowEvent(
                research_id=research_id,
                type=event_type,
                title=title,
                content=content,
                parent_event_id=parent_event_id,
                sequence_no=seq,
                create_time=now_local(),
            )
            session.add(event)
            await session.commit()
            await session.refresh(event)
            form_data = None
            if event_type == "CLARIFY_FORM" and content:
                try:
                    form_data = loads(content)
                except Exception:
                    pass
            item = TimelineItem(
                kind=KIND_EVENT,
                research_id=research_id,
                sequence_no=seq,
                event=WorkflowEventDTO.model_validate({**event.__dict__, "form_data": form_data}),
            )
        await self.write_to_redis(research_id, [item])
        return item

    async def save_temp_event(self, research_id: str, event_type: str, title: str) -> TimelineItem:
        item = TimelineItem(
            kind=KIND_EVENT,
            research_id=research_id,
            sequence_no=-1,
            event=WorkflowEventDTO(
                research_id=research_id,
                type=event_type,
                title=title,
                sequence_no=-1,
                create_time=now_local(),
            ),
        )
        await self.write_to_redis(research_id, [item])
        return item

    async def get_timeline(self, research_id: str, last_seq: int) -> list[TimelineItem]:
        redis_items = await self.read_from_redis(research_id, last_seq + 1, 2_147_483_647)
        if redis_items:
            return redis_items
        all_items = await self.load_from_db(research_id)
        await self.write_to_redis(research_id, all_items)
        if last_seq == 0:
            return all_items
        return [item for item in all_items if item.sequence_no > last_seq]

    async def write_to_redis(self, research_id: str, items: list[TimelineItem]) -> None:
        if not items:
            return
        key = self.timeline_key(research_id)
        mapping = {dumps(item.api_dump()): item.sequence_no for item in items}
        if mapping:
            await self.redis.zadd(key, mapping)
            await self.redis.expire(key, TIMELINE_TTL_SECONDS)

    async def read_from_redis(self, research_id: str, min_seq: int, max_seq: int) -> list[TimelineItem]:
        key = self.timeline_key(research_id)
        values = await self.redis.zrangebyscore(key, min_seq, max_seq)
        if not values:
            return []
        await self.redis.expire(key, TIMELINE_TTL_SECONDS)
        items: list[TimelineItem] = []
        for raw in values:
            try:
                text_value = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                items.append(TimelineItem.model_validate(loads(text_value)))
            except Exception:
                continue
        return sorted(items, key=lambda item: item.sequence_no)

    async def load_from_db(self, research_id: str) -> list[TimelineItem]:
        async with SessionLocal() as session:
            messages_result = await session.execute(
                select(ChatMessage).where(ChatMessage.research_id == research_id),
            )
            events_result = await session.execute(
                select(WorkflowEvent).where(WorkflowEvent.research_id == research_id),
            )
            items: list[TimelineItem] = []
            for message in messages_result.scalars():
                items.append(
                    TimelineItem(
                        kind=KIND_MESSAGE,
                        research_id=research_id,
                        sequence_no=message.sequence_no,
                        message=ChatMessageDTO.model_validate(message),
                    ),
                )
            for event in events_result.scalars():
                form_data = None
                if event.type == "CLARIFY_FORM" and event.content:
                    try:
                        form_data = loads(event.content)
                    except Exception:
                        pass
                items.append(
                    TimelineItem(
                        kind=KIND_EVENT,
                        research_id=research_id,
                        sequence_no=event.sequence_no,
                        event=WorkflowEventDTO.model_validate({**event.__dict__, "form_data": form_data}),
                    ),
                )
        return sorted(items, key=lambda item: item.sequence_no)

    async def verify_research_ownership(self, research_id: str, user_id: int) -> bool:
        key = self.user_researches_key(user_id)
        if await self.redis.sismember(key, research_id):
            return True
        async with SessionLocal() as session:
            result = await session.execute(
                select(func.count())
                .select_from(ResearchSession)
                .where(ResearchSession.id == research_id, ResearchSession.user_id == user_id),
            )
            found = int(result.scalar() or 0) > 0
        if found:
            await self.redis.sadd(key, research_id)
        return found

    async def cache_research_ownership(self, research_id: str, user_id: int) -> None:
        await self.redis.sadd(self.user_researches_key(user_id), research_id)

    async def save_checkpoint(self, research_id: str, state_json: dict[str, Any]) -> None:
        await self.redis.set(self.checkpoint_key(research_id), dumps(state_json), ex=CHECKPOINT_TTL_SECONDS)

    async def load_checkpoint(self, research_id: str) -> dict[str, Any] | None:
        value = await self.redis.get(self.checkpoint_key(research_id))
        if not value:
            return None
        text_value = value.decode("utf-8") if isinstance(value, bytes) else value
        return loads(text_value)

    async def remove_checkpoint(self, research_id: str) -> None:
        await self.redis.delete(self.checkpoint_key(research_id))


redis_client: redis.Redis | None = None
cache_util: CacheUtil | None = None


def init_cache() -> CacheUtil:
    global redis_client, cache_util
    settings = get_settings()
    redis_client = redis.from_url(settings.redis_url(), decode_responses=False)
    cache_util = CacheUtil(redis_client)
    return cache_util


def get_cache() -> CacheUtil:
    if cache_util is None:
        return init_cache()
    return cache_util


async def close_cache() -> None:
    global redis_client, cache_util
    if redis_client is not None:
        await redis_client.aclose()
    redis_client = None
    cache_util = None
