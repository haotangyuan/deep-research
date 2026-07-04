from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select, update

from app.core.common import ResearchError
from app.core.config import get_settings
from app.core.constants import WorkflowMode
from app.core.timeutil import now_local
from app.domain.models import ResearchIntervention
from app.infrastructure.db import SessionLocal


class InterventionStatus:
    PENDING = "pending"
    APPLIED = "applied"
    PARTIALLY_APPLIED = "partially_applied"
    EXPIRED = "expired"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass
class InterventionRequestData:
    focus_sections: list[str] = field(default_factory=list)
    reinforce_modes: list[str] = field(default_factory=list)
    note: str | None = None


@dataclass
class InterventionRecord:
    id: int | None = None
    research_id: str = ""
    user_id: int = 0
    status: str = InterventionStatus.PENDING
    focus_sections: list[str] = field(default_factory=list)
    reinforce_modes: list[str] = field(default_factory=list)
    note: str | None = None
    replace_mode: str | None = None
    requested_round_no: int | None = None
    target_round_no: int | None = None
    applied_round_no: int | None = None
    superseded_by_id: int | None = None
    apply_summary: dict | None = None
    reject_code: str | None = None
    reject_reason: str | None = None
    create_time: datetime | None = None
    update_time: datetime | None = None
    applied_time: datetime | None = None
    expired_time: datetime | None = None


ALLOWED_REINFORCE_MODES = {"official", "data", "comparison", "latest"}
REINFORCE_MODE_LABELS = {
    "official": "官方来源",
    "data": "数据证据",
    "comparison": "对比观点",
    "latest": "最新信息",
}
ACTIVE_INTERVENTION_STATUSES = {"QUEUE", "START", "IN_SCOPE", "AWAITING_DIRECTION_CONFIRM", "IN_RESEARCH", "IN_REPORT"}


def is_ultra_dynamic_budget(budget_name: str | None) -> bool:
    return (budget_name or "").upper() == "ULTRA"


def workflow_mode_for_budget(budget_name: str | None) -> str:
    return WorkflowMode.ULTRA_DYNAMIC if is_ultra_dynamic_budget(budget_name) else WorkflowMode.FIXED


def should_continue_ultra_dynamic_round(
    budget_name: str | None,
    round_no: int,
    max_rounds: int,
    has_pending: bool,
) -> bool:
    return is_ultra_dynamic_budget(budget_name) and has_pending and round_no < max(1, max_rounds)


def normalize_intervention_request(payload: InterventionRequestData) -> InterventionRequestData:
    focus_sections = []
    seen_sections: set[str] = set()
    for section in payload.focus_sections:
        value = " ".join((section or "").strip().split())
        if value and value not in seen_sections:
            seen_sections.add(value)
            focus_sections.append(value)

    reinforce_modes = []
    seen_modes: set[str] = set()
    for mode in payload.reinforce_modes:
        value = (mode or "").strip().lower()
        if value in ALLOWED_REINFORCE_MODES and value not in seen_modes:
            seen_modes.add(value)
            reinforce_modes.append(value)

    note = (payload.note or "").strip() or None
    return InterventionRequestData(
        focus_sections=focus_sections[:3],
        reinforce_modes=reinforce_modes[:2],
        note=note[:500] if note else None,
    )


def reinforce_mode_label(mode: str) -> str:
    value = (mode or "").strip().lower()
    return REINFORCE_MODE_LABELS.get(value, mode)


def reinforce_mode_labels(modes: list[str]) -> list[str]:
    return [reinforce_mode_label(mode) for mode in modes if str(mode).strip()]


def build_intervention_prompt_block(payload: InterventionRequestData, round_no: int, remaining_rounds: int) -> str:
    normalized = normalize_intervention_request(payload)
    lines = [
        "<UserIntervention priority=\"highest\">",
        f"当前为 ULTRA 动态工作流第 {round_no} 轮规划。",
        f"剩余可用动态轮次：{max(0, remaining_rounds)}。",
    ]
    if normalized.focus_sections:
        lines.append("下一轮重点 section：" + "、".join(normalized.focus_sections))
    if normalized.reinforce_modes:
        lines.append("下一轮补强方向：" + "、".join(reinforce_mode_labels(normalized.reinforce_modes)))
    if normalized.note:
        lines.append("用户备注：" + normalized.note)
    lines.append("要求：当前轮不回滚，只在本轮规划和后续研究任务中优先体现这些偏置。")
    lines.append("</UserIntervention>")
    return "\n".join(lines)


def build_intervention_user_message(payload: InterventionRequestData) -> str:
    normalized = normalize_intervention_request(payload)
    parts = ["追加关注点："]
    if normalized.focus_sections:
        parts.append("下一轮优先补充「" + "、".join(normalized.focus_sections) + "」")
    if normalized.reinforce_modes:
        parts.append("补强方向偏向「" + "、".join(reinforce_mode_labels(normalized.reinforce_modes)) + "」")
    if normalized.note:
        parts.append("备注：" + normalized.note)
    return "；".join(parts)


def build_intervention_ack_message(payload: InterventionRequestData, replaced: bool = False) -> str:
    prefix = "已用新的下一轮调整替换上一条待生效调整。" if replaced else "已记录你的下一轮调整。"
    return prefix + " 当前轮不会中断；系统会在下一轮 ULTRA 规划开始前应用这条偏置。"


def build_intervention_round_start_message(payload: InterventionRequestData, round_no: int) -> str:
    normalized = normalize_intervention_request(payload)
    summary = []
    if normalized.focus_sections:
        summary.append("重点 section「" + "、".join(normalized.focus_sections) + "」")
    if normalized.reinforce_modes:
        summary.append("补强方向「" + "、".join(reinforce_mode_labels(normalized.reinforce_modes)) + "」")
    if normalized.note:
        summary.append("备注：" + normalized.note)
    detail = "，".join(summary) if summary else "已加载你的下一轮偏置"
    return f"第 {round_no} 轮开始前，系统正在按你的追加关注点重新规划：{detail}。"


def build_intervention_apply_summary(record: InterventionRecord, round_no: int, remaining_rounds: int) -> dict:
    return {
        "appliedFocusSections": record.focus_sections,
        "appliedReinforceModes": record.reinforce_modes,
        "note": record.note,
        "appliedRoundNo": round_no,
        "remainingRoundsAfterApply": max(0, remaining_rounds),
    }


def build_intervention_applied_message(summary: dict) -> str:
    parts = []
    focus_sections = list(summary.get("appliedFocusSections") or [])
    reinforce_modes = list(summary.get("appliedReinforceModes") or [])
    note = summary.get("note")
    round_no = summary.get("appliedRoundNo")
    if focus_sections:
        parts.append("重点 section「" + "、".join(focus_sections) + "」")
    if reinforce_modes:
        parts.append("补强方向「" + "、".join(reinforce_mode_labels(reinforce_modes)) + "」")
    if note:
        parts.append("备注：" + str(note))
    detail = "；".join(parts) if parts else "系统已采纳你的下一轮偏置。"
    return f"已在第 {round_no} 轮规划中采纳你的调整：{detail}"


def intervention_record_from_model(model: ResearchIntervention) -> InterventionRecord:
    return InterventionRecord(
        id=model.id,
        research_id=model.research_id,
        user_id=model.user_id,
        status=model.status,
        focus_sections=json.loads(model.focus_sections_json or "[]"),
        reinforce_modes=json.loads(model.reinforce_modes_json or "[]"),
        note=model.note,
        replace_mode=model.replace_mode,
        requested_round_no=model.requested_round_no,
        target_round_no=model.target_round_no,
        applied_round_no=model.applied_round_no,
        superseded_by_id=model.superseded_by_id,
        apply_summary=json.loads(model.apply_summary_json) if model.apply_summary_json else None,
        reject_code=model.reject_code,
        reject_reason=model.reject_reason,
        create_time=model.create_time,
        update_time=model.update_time,
        applied_time=model.applied_time,
        expired_time=model.expired_time,
    )


async def load_pending_intervention_record(research_id: str) -> InterventionRecord | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(ResearchIntervention)
            .where(
                ResearchIntervention.research_id == research_id,
                ResearchIntervention.status == InterventionStatus.PENDING,
            )
            .order_by(ResearchIntervention.create_time.desc(), ResearchIntervention.id.desc())
            .limit(1),
        )
        model = result.scalar_one_or_none()
        return intervention_record_from_model(model) if model is not None else None


async def has_pending_intervention(research_id: str) -> bool:
    return await load_pending_intervention_record(research_id) is not None


async def list_recent_intervention_records(research_id: str, limit: int = 5) -> list[InterventionRecord]:
    async with SessionLocal() as session:
        result = await session.execute(
            select(ResearchIntervention)
            .where(ResearchIntervention.research_id == research_id)
            .order_by(ResearchIntervention.create_time.desc(), ResearchIntervention.id.desc())
            .limit(max(1, limit)),
        )
        return [intervention_record_from_model(item) for item in result.scalars()]


async def create_or_replace_pending_intervention(
    record: InterventionRecord,
    replace_pending: bool,
) -> tuple[InterventionRecord, bool]:
    created_at = record.create_time or now_local()
    updated_at = record.update_time or created_at
    async with SessionLocal() as session:
        pending_result = await session.execute(
            select(ResearchIntervention)
            .where(
                ResearchIntervention.research_id == record.research_id,
                ResearchIntervention.status == InterventionStatus.PENDING,
            )
            .order_by(ResearchIntervention.create_time.desc(), ResearchIntervention.id.desc())
            .with_for_update(),
        )
        pending_models = list(pending_result.scalars())
        if pending_models and not replace_pending:
            raise ResearchError("已有一条待生效的下一轮调整，请确认后再替换")

        model = ResearchIntervention(
            research_id=record.research_id,
            user_id=record.user_id,
            status=record.status,
            focus_sections_json=json.dumps(record.focus_sections, ensure_ascii=False),
            reinforce_modes_json=json.dumps(record.reinforce_modes, ensure_ascii=False),
            note=record.note,
            replace_mode=record.replace_mode,
            requested_round_no=record.requested_round_no,
            target_round_no=record.target_round_no,
            create_time=created_at,
            update_time=updated_at,
        )
        session.add(model)
        await session.flush()
        pending_ids = [int(item.id) for item in pending_models if item.id is not None]
        if pending_ids:
            await session.execute(
                update(ResearchIntervention)
                .where(ResearchIntervention.id.in_(pending_ids))
                .values(
                    status=InterventionStatus.SUPERSEDED,
                    superseded_by_id=model.id,
                    update_time=updated_at,
                ),
            )
        await session.commit()
        await session.refresh(model)
        return intervention_record_from_model(model), bool(pending_ids)


async def mark_intervention_applied(record_id: int, round_no: int, summary: dict, partial: bool = False) -> None:
    now = now_local()
    async with SessionLocal() as session:
        await session.execute(
            update(ResearchIntervention)
            .where(ResearchIntervention.id == record_id)
            .values(
                status=InterventionStatus.PARTIALLY_APPLIED if partial else InterventionStatus.APPLIED,
                applied_round_no=round_no,
                apply_summary_json=json.dumps(summary, ensure_ascii=False),
                applied_time=now,
                update_time=now,
            ),
        )
        await session.commit()


async def expire_pending_interventions(research_id: str, reason: str, reject_code: str = "expired") -> None:
    now = now_local()
    async with SessionLocal() as session:
        await session.execute(
            update(ResearchIntervention)
            .where(
                ResearchIntervention.research_id == research_id,
                ResearchIntervention.status == InterventionStatus.PENDING,
            )
            .values(
                status=InterventionStatus.EXPIRED,
                reject_code=reject_code,
                reject_reason=reason,
                expired_time=now,
                update_time=now,
            ),
        )
        await session.commit()


def dynamic_round_limit() -> int:
    return max(1, get_settings().research_ultra_dynamic_max_rounds)
