"""Build info —— 捕获运行时代码版本快照。

用于 ``research_run.workflow_commit_sha`` / ``workflow_dirty``，使每个 run 可复现地
绑定到生成它的代码版本（见 v2 §6.11）。绝不静默返回空：失败时记 warning 并
返回 ``"unknown"`` / ``0``。
"""
from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache

from app.core.config import PROJECT_ROOT

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuildInfo:
    workflow_commit_sha: str
    workflow_dirty: int

    def to_dict(self) -> dict:
        return asdict(self)


def _run_git(args: list[str], timeout: float = 2.0) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("build_info git %s failed: %s", " ".join(args), exc)
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


@lru_cache(maxsize=1)
def capture_build_info() -> BuildInfo:
    """进程内缓存（版本在进程生命期内不变）。优先环境注入，否则本地 git。"""
    sha = os.environ.get("GIT_COMMIT_SHA") or os.environ.get("APP_VERSION")
    if not sha:
        sha = _run_git(["rev-parse", "HEAD"]) or "unknown"
    dirty_flag = os.environ.get("GIT_DIRTY")
    if dirty_flag is not None:
        dirty = 1 if dirty_flag.lower() in {"1", "true", "yes"} else 0
    else:
        status = _run_git(["status", "--porcelain"])
        dirty = 1 if status else 0
    if sha == "unknown":
        logger.warning("build_info: git sha unavailable, using 'unknown'")
    return BuildInfo(workflow_commit_sha=sha, workflow_dirty=dirty)
