"""pytest 共享配置。

eval repository 测试复用全局 async engine（app/infrastructure/db.SessionLocal）。
pytest-asyncio 默认每个 async 用例一个 event loop，全局 engine 连接池跨 loop
会失效。每个 DB 用例后 dispose engine 池，让下一用例在新 loop 上重建连接。
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
async def _dispose_engine_between_async_tests():
    """async 用例结束后 dispose 全局 engine 连接池，避免跨 loop 复用死连接。"""
    yield
    try:
        from app.infrastructure.db import engine

        await engine.dispose()
    except Exception:  # noqa: BLE001
        pass
