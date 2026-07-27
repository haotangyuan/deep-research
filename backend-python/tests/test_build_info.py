"""build_info 单测。

CLAUDE.md「不 mock」原则适用于 MySQL/Redis/Tavily/LLM；build_info 走 subprocess git，
属纯逻辑，可直接断言。git 不可用时降级为 ``"unknown"`` + warning。
"""
from __future__ import annotations

import os
from unittest import mock

from app.core import build_info


def test_capture_build_info_returns_commit_sha_and_dirty_flag() -> None:
    # 清掉 lru_cache，确保拿到当前仓库状态
    build_info.capture_build_info.cache_clear()
    info = build_info.capture_build_info()
    assert isinstance(info.workflow_commit_sha, str) and len(info.workflow_commit_sha) >= 7
    assert info.workflow_dirty in (0, 1)
    assert "workflow_commit_sha" in info.to_dict()


def test_env_overrides_git() -> None:
    build_info.capture_build_info.cache_clear()
    with mock.patch.dict(os.environ, {"GIT_COMMIT_SHA": "envsha123", "GIT_DIRTY": "1"}):
        info = build_info.capture_build_info()
    assert info.workflow_commit_sha == "envsha123"
    assert info.workflow_dirty == 1
    build_info.capture_build_info.cache_clear()


def test_git_failure_falls_back_to_unknown() -> None:
    build_info.capture_build_info.cache_clear()
    # 清掉 env，让 _run_git 返回 None（模拟 git 不可用）
    env = {k: v for k, v in os.environ.items() if k not in {"GIT_COMMIT_SHA", "APP_VERSION", "GIT_DIRTY"}}
    with mock.patch.dict(os.environ, env, clear=True), mock.patch(
        "app.core.build_info._run_git", return_value=None
    ):
        info = build_info.capture_build_info()
    assert info.workflow_commit_sha == "unknown"
    assert info.workflow_dirty == 0
    build_info.capture_build_info.cache_clear()
