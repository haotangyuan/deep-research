"""LLM 阶段归因维度派生。

从 ``stage_name`` + ``runtime_context`` 派生 ``research_llm_call`` 的归因列：
``report_phase`` / ``reviewer_lens`` / ``round_no`` / ``section_id``。

刻意不进 ``api``/``main.py``（见 CLAUDE.md 红线 6）。纯函数，无副作用。
"""
from __future__ import annotations

from typing import Any

from app.domain.runtime import ResearchAgentRequest


# report_phase 派生：按 stage_name 前缀匹配。
# 与 v2 §6.6 stage_name 枚举对齐。
_REPORT_PHASE_RULES: tuple[tuple[str, str], ...] = (
    ("ReportAgent:merge", "merge"),
    ("ReportMerge", "merge"),
    ("ReportAgent:high-synthesis", "synthesis"),
    ("ReportSynthesizer", "synthesis"),
    ("ReportSynthesis", "synthesis"),
    ("ReportSectionDraft", "section_draft"),
    ("ReportSectionAgent", "section_draft"),
    ("ReportSectionReviser", "section_revision"),
    ("ReportSectionRevise", "section_revision"),
    ("ReportJudge", "judge"),
    ("ClaimVerifier", "claim_verify"),
    ("ReportAgent", "single"),
)


def derive_report_phase(stage_name: str | None) -> str | None:
    if not stage_name:
        return None
    for prefix, phase in _REPORT_PHASE_RULES:
        if stage_name.startswith(prefix):
            return phase
    return None


def parse_reviewer_lens(stage_name: str | None, ctx: dict[str, Any] | None) -> str | None:
    """显式 ``reviewer.lens`` 优先；否则 ``UltraDynamicReviewer:{lens}`` 后缀。"""
    if ctx:
        lens = ctx.get("reviewer.lens")
        if lens:
            return str(lens)
    if stage_name and stage_name.startswith("UltraDynamicReviewer:"):
        return stage_name.split(":", 1)[1] or None
    return None


def resolve_run_id(ctx: dict[str, Any] | None) -> str | None:
    """从 runtime_context 解析 run_id；None 则跳过记录（非本 run 的 ad-hoc 调用）。"""
    if not ctx:
        return None
    rid = ctx.get("run.id")
    return str(rid) if rid else None


def derive_round_no(ctx: dict[str, Any] | None) -> int | None:
    if not ctx:
        return None
    val = ctx.get("research.round.no")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def derive_section_id(ctx: dict[str, Any] | None) -> str | None:
    """优先 ``report.section.id``，回退 ``report.agent.id``（report_team.py 旧键）。"""
    if not ctx:
        return None
    return ctx.get("report.section.id") or ctx.get("report.agent.id")


def derive_agent_name(ctx: dict[str, Any] | None, stage_name: str | None) -> str | None:
    if ctx:
        for key in ("agent.worker.id", "agent.instance"):
            val = ctx.get(key)
            if val:
                return str(val)
    return stage_name


def attribution_from_request(request: ResearchAgentRequest) -> dict[str, Any]:
    """从 ResearchAgentRequest 一次性派生全部归因列。"""
    ctx = request.runtime_context
    stage = request.stage_name
    return {
        "stage_name": stage,
        "agent_name": derive_agent_name(ctx, stage),
        "round_no": derive_round_no(ctx),
        "report_phase": derive_report_phase(stage),
        "reviewer_lens": parse_reviewer_lens(stage, ctx),
        "section_id": derive_section_id(ctx),
    }
