from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from .timeutil import format_datetime


def to_camel(value: str) -> str:
    parts = value.split("_")
    return parts[0] + "".join(part.capitalize() for part in parts[1:])


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)

    def api_dump(self) -> dict[str, Any]:
        return self.model_dump(by_alias=True, exclude_none=True)


class RegisterReq(CamelModel):
    username: str
    password: str


class LoginReq(CamelModel):
    username: str
    password: str


class LoginResp(CamelModel):
    token: str


class UserInfoResp(CamelModel):
    avatar_url: str | None = None


class AddModelReq(CamelModel):
    name: str | None = None
    model: str
    base_url: str
    api_key: str


class ModelResp(CamelModel):
    id: str
    type: str
    name: str
    model: str
    base_url: str


class SendMessageReq(CamelModel):
    content: str
    model_id: str | None = None
    budget: Literal["MEDIUM", "HIGH", "ULTRA"] | str | None = None
    hitl_mode: Literal["NONE", "DIRECTION_ONLY"] | str | None = None


class ConfirmDirectionReq(CamelModel):
    action: Literal["APPROVE", "REVISE"] | str
    feedback: str | None = None


class CreateResearchResp(CamelModel):
    research_ids: list[str]


class SendMessageResp(CamelModel):
    id: str
    content: str


class ResearchStatusResp(CamelModel):
    id: str
    status: str
    title: str | None = None
    model_id: str | None = None
    budget: str | None = None
    start_time: datetime | None = None
    complete_time: datetime | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None

    def api_dump(self) -> dict[str, Any]:
        data = super().api_dump()
        data["startTime"] = format_datetime(self.start_time)
        data["completeTime"] = format_datetime(self.complete_time)
        return {k: v for k, v in data.items() if v is not None}


class ChatMessageDTO(CamelModel):
    id: int
    research_id: str
    role: str
    content: str
    sequence_no: int | None = None
    create_time: datetime | None = None

    def api_dump(self) -> dict[str, Any]:
        data = super().api_dump()
        data["createTime"] = format_datetime(self.create_time)
        return {k: v for k, v in data.items() if v is not None}


class WorkflowEventDTO(CamelModel):
    id: int | None = None
    research_id: str
    type: str
    title: str
    content: str | None = None
    parent_event_id: int | None = None
    sequence_no: int | None = None
    create_time: datetime | None = None

    def api_dump(self) -> dict[str, Any]:
        data = super().api_dump()
        data["createTime"] = format_datetime(self.create_time)
        return {k: v for k, v in data.items() if v is not None}


class TimelineItem(CamelModel):
    kind: str
    research_id: str
    sequence_no: int
    message: ChatMessageDTO | None = None
    event: WorkflowEventDTO | None = None

    def api_dump(self) -> dict[str, Any]:
        data = {
            "kind": self.kind,
            "researchId": self.research_id,
            "sequenceNo": self.sequence_no,
        }
        if self.message is not None:
            data["message"] = self.message.api_dump()
        if self.event is not None:
            data["event"] = self.event.api_dump()
        return data


class ResearchMessageResp(CamelModel):
    id: str
    status: str
    messages: list[ChatMessageDTO]
    events: list[WorkflowEventDTO]
    start_time: datetime | None = None
    update_time: datetime | None = None
    complete_time: datetime | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None

    def api_dump(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status,
            "messages": [item.api_dump() for item in self.messages],
            "events": [item.api_dump() for item in self.events],
            "startTime": format_datetime(self.start_time),
            "updateTime": format_datetime(self.update_time),
            "completeTime": format_datetime(self.complete_time),
            "totalInputTokens": self.total_input_tokens,
            "totalOutputTokens": self.total_output_tokens,
        }
