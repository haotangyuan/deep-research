from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass

import httpx

from app.core.config import get_settings
from app.domain.state import TavilySearchResult


@dataclass
class CacheEntry:
    response: list[TavilySearchResult]
    expires_at: float


class TavilyClient:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, int, str, bool], CacheEntry] = {}
        self._inflight: dict[tuple[str, int, str, bool], asyncio.Future[list[TavilySearchResult]]] = {}
        self._lock = asyncio.Lock()

    async def search(
        self,
        query: str,
        max_results: int,
        topic: str | None,
        include_raw_content: bool,
    ) -> list[TavilySearchResult]:
        settings = get_settings()
        key = (normalize(query), max_results, normalize(topic or "general"), include_raw_content)
        if settings.tavily_cache_enabled:
            entry = self._cache.get(key)
            if entry and entry.expires_at > time.time():
                return entry.response
        async with self._lock:
            existing = self._inflight.get(key)
            if existing is not None:
                return await existing
            loop = asyncio.get_running_loop()
            future: asyncio.Future[list[TavilySearchResult]] = loop.create_future()
            self._inflight[key] = future
        try:
            response = await self._do_search(query, max_results, topic or "general", include_raw_content)
            if settings.tavily_cache_enabled:
                self._put_cache(key, response)
            future.set_result(response)
            return response
        except Exception as exc:
            future.set_exception(exc)
            return []
        finally:
            async with self._lock:
                self._inflight.pop(key, None)

    async def _do_search(
        self,
        query: str,
        max_results: int,
        topic: str,
        include_raw_content: bool,
    ) -> list[TavilySearchResult]:
        settings = get_settings()
        if not settings.tavily_api_key:
            return []
        payload = {
            "query": query,
            "max_results": max_results,
            "topic": topic,
            "include_raw_content": include_raw_content,
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    settings.tavily_base_url.rstrip("/") + "/search",
                    headers={"Authorization": f"Bearer {settings.tavily_api_key}"},
                    json=payload,
                )
            if response.status_code >= 400:
                return []
            data = response.json()
            return [
                TavilySearchResult(
                    url=item.get("url"),
                    title=item.get("title"),
                    content=item.get("content"),
                    raw_content=item.get("raw_content"),
                    score=item.get("score"),
                )
                for item in data.get("results", [])
            ]
        except Exception:
            return []

    def _put_cache(self, key: tuple[str, int, str, bool], response: list[TavilySearchResult]) -> None:
        settings = get_settings()
        self._cache[key] = CacheEntry(response, time.time() + max(1, settings.tavily_cache_ttl_minutes) * 60)
        max_entries = max(1, settings.tavily_cache_max_entries)
        if len(self._cache) <= max_entries:
            return
        now = time.time()
        for cache_key in list(self._cache):
            if self._cache[cache_key].expires_at <= now or len(self._cache) > max_entries:
                self._cache.pop(cache_key, None)


def normalize(value: str | None) -> str:
    return " ".join((value or "").strip().lower().split())


tavily_client = TavilyClient()
