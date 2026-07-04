from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from app.application.services import ResearchService
from app.domain.dto import ResearchMessageResp, WorkflowEventDTO, ChatMessageDTO


def _make_service() -> ResearchService:
    return ResearchService(model_service=SimpleNamespace())


def test_intervention_helpers_are_ultra_only() -> None:
    from app.application.interventions import (
        InterventionRequestData,
        build_intervention_applied_message,
        build_intervention_prompt_block,
        build_intervention_user_message,
        is_ultra_dynamic_budget,
        should_continue_ultra_dynamic_round,
    )

    payload = InterventionRequestData(
        focus_sections=["市场格局", "官方数据"],
        reinforce_modes=["official", "latest"],
        note="优先看最近两个季度的变化",
    )

    prompt = build_intervention_prompt_block(payload, round_no=2, remaining_rounds=3)
    assert "市场格局" in prompt
    assert "官方来源" in prompt
    assert "最近两个季度" in prompt

    user_message = build_intervention_user_message(payload)
    assert "官方来源" in user_message
    assert "latest" not in user_message

    applied_message = build_intervention_applied_message(
        {
            "appliedFocusSections": ["市场格局"],
            "appliedReinforceModes": ["official", "latest"],
            "note": "优先看最近两个季度的变化",
            "appliedRoundNo": 2,
        },
    )
    assert "官方来源" in applied_message
    assert "最新信息" in applied_message

    assert is_ultra_dynamic_budget("ULTRA") is True
    assert is_ultra_dynamic_budget("HIGH") is False
    assert is_ultra_dynamic_budget("MEDIUM") is False

    assert should_continue_ultra_dynamic_round("ULTRA", round_no=1, max_rounds=5, has_pending=True) is True
    assert should_continue_ultra_dynamic_round("ULTRA", round_no=5, max_rounds=5, has_pending=True) is False
    assert should_continue_ultra_dynamic_round("HIGH", round_no=1, max_rounds=5, has_pending=True) is False


@pytest.mark.asyncio
async def test_create_intervention_replaces_existing_pending(monkeypatch) -> None:
    from app.domain.dto import CreateInterventionReq
    from app.application.interventions import InterventionRecord, InterventionStatus

    service = _make_service()
    published_messages: list[tuple[str, str, str]] = []
    published_events: list[tuple[str, str, str, str | None]] = []

    research = SimpleNamespace(id="research-1", user_id=7, budget="ULTRA", status="IN_RESEARCH")

    async def load_session(_user_id: int, _research_id: str):
        return research

    async def create_or_replace(record: InterventionRecord, replace_pending: bool):
        assert replace_pending is True
        return (
            InterventionRecord(
                id=12,
                research_id=record.research_id,
                user_id=record.user_id,
                status=InterventionStatus.PENDING,
                focus_sections=record.focus_sections,
                reinforce_modes=record.reinforce_modes,
                note=record.note,
                replace_mode=record.replace_mode,
                create_time=record.create_time,
                update_time=record.update_time,
            ),
            True,
        )

    async def publish_message(research_id: str, role: str, content: str):
        published_messages.append((research_id, role, content))

    async def publish_event(research_id: str, event_type: str, title: str, content: str | None, _parent=None):
        published_events.append((research_id, event_type, title, content))
        return 1

    monkeypatch.setattr(service, "_load_owned_research_session", load_session)
    monkeypatch.setattr("app.application.services.create_or_replace_pending_intervention", create_or_replace)
    monkeypatch.setattr("app.application.services.event_publisher.publish_message", publish_message)
    monkeypatch.setattr("app.application.services.event_publisher.publish_event", publish_event)

    created = await service.create_intervention(
        7,
        "research-1",
        CreateInterventionReq(
            focus_sections=["行业对比"],
            reinforce_modes=["latest"],
            note="看最新进展",
            replace_pending=True,
        ),
    )

    assert created.status == InterventionStatus.PENDING
    assert created.focus_sections == ["行业对比"]
    assert any(role == "user" and "追加关注点" in content for _, role, content in published_messages)
    assert any(role == "assistant" and "当前轮不会中断" in content for _, role, content in published_messages)
    assert any(role == "user" and "最新信息" in content for _, role, content in published_messages)
    assert any(event_type == "INTERVENTION" for _, event_type, _, _ in published_events)
    assert all("reinforceModeLabels" not in (content or "") for _, _, _, content in published_events)


@pytest.mark.asyncio
async def test_create_intervention_rejects_non_ultra(monkeypatch) -> None:
    from app.domain.dto import CreateInterventionReq

    service = _make_service()
    research = SimpleNamespace(id="research-2", user_id=7, budget="HIGH", status="IN_RESEARCH")

    async def load_session(_user_id: int, _research_id: str):
        return research

    monkeypatch.setattr(service, "_load_owned_research_session", load_session)

    with pytest.raises(RuntimeError, match="仅支持 ULTRA"):
        await service.create_intervention(
            7,
            "research-2",
            CreateInterventionReq(
                focus_sections=["风险点"],
                reinforce_modes=["official"],
                note="",
                replace_pending=False,
            ),
        )


@pytest.mark.asyncio
async def test_research_message_payload_includes_pending_intervention(monkeypatch) -> None:
    from app.application.interventions import InterventionRecord, InterventionStatus

    service = _make_service()
    session_obj = SimpleNamespace(
        id="research-3",
        status="IN_RESEARCH",
        title="ULTRA research",
        model_id="model-1",
        budget="ULTRA",
        start_time=None,
        update_time=None,
        complete_time=None,
        total_input_tokens=10,
        total_output_tokens=20,
    )
    pending = InterventionRecord(
        id=21,
        research_id="research-3",
        user_id=7,
        status=InterventionStatus.PENDING,
        focus_sections=["政策变化"],
        reinforce_modes=["official"],
        note="补官方来源",
        create_time=datetime(2026, 7, 4, 11, 0, 0),
    )

    async def verify_ownership(_research_id: str, _user_id: int) -> bool:
        return True

    async def get_timeline(_research_id: str, _last_seq: int):
        return [
            SimpleNamespace(
                kind="message",
                message=ChatMessageDTO(
                    id=1,
                    research_id="research-3",
                    role="user",
                    content="hello",
                    sequence_no=1,
                    create_time=datetime(2026, 7, 4, 9, 0, 0),
                ),
                event=None,
            ),
            SimpleNamespace(
                kind="event",
                message=None,
                event=WorkflowEventDTO(
                    id=2,
                    research_id="research-3",
                    type="SUPERVISOR",
                    title="开始规划研究路线...",
                    content=None,
                    sequence_no=2,
                    create_time=datetime(2026, 7, 4, 9, 1, 0),
                ),
            ),
        ]

    async def load_pending(_research_id: str):
        return pending

    async def list_recent(_research_id: str, _limit: int = 5):
        return [pending]

    fake_cache = SimpleNamespace(verify_research_ownership=verify_ownership, get_timeline=get_timeline)
    async def load_session(_research_id: str):
        return session_obj

    monkeypatch.setattr("app.application.services.get_cache", lambda: fake_cache)
    monkeypatch.setattr(service, "_load_research_session", load_session)
    monkeypatch.setattr("app.application.services.load_pending_intervention_record", load_pending)
    monkeypatch.setattr("app.application.services.list_recent_intervention_records", list_recent)

    response = await service.get_research_messages(7, "research-3")

    assert isinstance(response, ResearchMessageResp)
    assert response.pending_intervention is not None
    assert response.pending_intervention.focus_sections == ["政策变化"]
    assert response.recent_interventions[0].status == "pending"
