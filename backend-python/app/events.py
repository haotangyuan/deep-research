from __future__ import annotations

from .cache import get_cache
from .dto import TimelineItem
from .sse import sse_hub


class EventPublisher:
    async def publish_message(self, research_id: str, role: str, content: str) -> TimelineItem:
        item = await get_cache().save_message(research_id, role, content)
        await sse_hub.send_timeline_item(research_id, item)
        return item

    async def publish_event(
        self,
        research_id: str,
        event_type: str,
        title: str,
        content: str | None,
        parent_event_id: int | None = None,
    ) -> int | None:
        safe_title = title[:200] + "..." if title and len(title) > 200 else title
        item = await get_cache().save_event(research_id, event_type, safe_title or "", content, parent_event_id)
        await sse_hub.send_timeline_item(research_id, item)
        return item.event.id if item.event else None

    async def publish_temp_event(self, research_id: str, event_type: str, title: str) -> None:
        item = await get_cache().save_temp_event(research_id, event_type, title)
        await sse_hub.send_timeline_item(research_id, item)

    async def publish_report_stream(self, research_id: str, partial_text: str) -> None:
        await sse_hub.send_report_stream(research_id, partial_text)


event_publisher = EventPublisher()
