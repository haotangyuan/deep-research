"""Prompt registry —— 各 prompt family 的语义版本 + sha256 快照。

用于 ``research_run.prompt_version_json`` / ``prompt_hash_json``（见 v2 §6.11）。
没有版本信息无法归因质量回归。sha256 over 规范化全文（strip 行尾空白 + ``\\n`` join），
这样重排版/末尾空行不改变 hash。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from typing import Any

from app.application import prompts as prompt_module


# 各 family 的语义版本（改 prompt 文本时手动 +1）。
PROMPT_VERSIONS: dict[str, str] = {
    "scope": "1.0.0",
    "supervisor": "1.0.0",
    "researcher": "1.0.0",
    "reviewer": "1.0.0",
    "report": "1.0.0",
    "misc": "1.0.0",
}

# family → 代表性 prompt 常量名（snapshot 不必全量，但覆盖每个 agent family 的核心 system prompt）。
_FAMILY_PROMPTS: dict[str, list[str]] = {
    "scope": ["CLARIFY_WITH_USER_INSTRUCTIONS", "TRANSFORM_MESSAGES_INTO_RESEARCH_TOPIC_PROMPT"],
    "supervisor": ["RESEARCH_TASK_PLANNER_PROMPT"],
    "researcher": ["RESEARCH_AGENT_PROMPT", "COMPRESS_RESEARCH_SYSTEM_PROMPT", "SUMMARIZE_WEBPAGE_PROMPT"],
    "reviewer": [
        "ULTRA_DYNAMIC_REVIEW_PROMPT",
        "ULTRA_REVIEWER_LENS_PROMPT",
        "ULTRA_CLAIM_VERIFY_PROMPT",
    ],
    "report": [
        "REPORT_AGENT_PROMPT",
        "REPORT_DRAFT_ANGLE_PROMPT",
        "REPORT_JUDGE_PROMPT",
        "REPORT_SYNTHESIS_PROMPT",
        "HIGH_REPORT_SYNTHESIS_PROMPT",
    ],
    "misc": ["RESEARCH_AGENT_PROMPT"],
}


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in (text or "").splitlines())


def _sha256(text: str) -> str:
    return hashlib.sha256(_normalize(text).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class FamilySnapshot:
    version: str
    sha256: str
    text_len: int


@dataclass(frozen=True)
class VersionSnapshot:
    """run 创建时冻结的完整版本快照。"""

    workflow_commit_sha: str
    workflow_dirty: int
    prompt_versions: dict[str, FamilySnapshot]
    template_version: str | None
    template_sha256: str | None
    request_model: str | None
    response_model: str | None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # dataclass asdict 把 FamilySnapshot 也展平成 dict，保持即可
        return d

    def to_run_columns(self) -> dict[str, Any]:
        """落库到 research_run 的扁平列。"""
        versions = {family: snap.version for family, snap in self.prompt_versions.items()}
        hashes = {family: snap.sha256 for family, snap in self.prompt_versions.items()}
        return {
            "workflow_commit_sha": self.workflow_commit_sha,
            "workflow_dirty": self.workflow_dirty,
            "prompt_versions": versions,
            "prompt_hashes": hashes,
            "template_version": self.template_version,
            "template_sha256": self.template_sha256,
            "request_model": self.request_model,
            "response_model": self.response_model,
        }


@lru_cache(maxsize=1)
def snapshot() -> dict[str, FamilySnapshot]:
    """捕获各 prompt family 当前文本的版本 + sha256。进程内缓存。"""
    result: dict[str, FamilySnapshot] = {}
    for family, names in _FAMILY_PROMPTS.items():
        texts: list[str] = []
        for name in names:
            text = getattr(prompt_module, name, None)
            if isinstance(text, str):
                texts.append(text)
        combined = "\n\n".join(texts)
        result[family] = FamilySnapshot(
            version=PROMPT_VERSIONS.get(family, "0.0.0"),
            sha256=_sha256(combined),
            text_len=len(_normalize(combined)),
        )
    return result


def freeze_version_snapshot(
    *,
    workflow_commit_sha: str = "unknown",
    workflow_dirty: int = 0,
    template_version: str | None = None,
    template_sha256: str | None = None,
    request_model: str | None = None,
    response_model: str | None = None,
) -> VersionSnapshot:
    """在 run 创建时调一次，冻结当前代码 + prompt + template 版本。"""
    return VersionSnapshot(
        workflow_commit_sha=workflow_commit_sha,
        workflow_dirty=workflow_dirty,
        prompt_versions=snapshot(),
        template_version=template_version,
        template_sha256=template_sha256,
        request_model=request_model,
        response_model=response_model,
    )


def freeze_for_state(state: object | None) -> dict[str, Any]:
    """便捷入口：从 state 取 request_model + template，组装 VersionSnapshot → 扁平列。"""
    from app.core.build_info import capture_build_info
    from app.application.workflow_template import template_sha256 as compute_template_sha256

    build = capture_build_info()
    template = getattr(state, "workflow_template", None) if state else None
    template_ver = None
    template_hash = None
    if isinstance(template, dict):
        template_ver = str(template.get("version") or "")
        template_hash = compute_template_sha256(template) or None
    request_model = getattr(state, "trace_metadata_model", None) if state else None
    request_model_id = getattr(request_model, "model_id", None) if request_model else None
    snap = freeze_version_snapshot(
        workflow_commit_sha=build.workflow_commit_sha,
        workflow_dirty=build.workflow_dirty,
        template_version=template_ver or None,
        template_sha256=template_hash,
        request_model=request_model_id,
        response_model=None,
    )
    return snap.to_run_columns()
