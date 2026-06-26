from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable, Any


class Role(str, Enum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class ToolChoiceMode(str, Enum):
    AUTO = "auto"
    REQUIRED = "required"


@dataclass(frozen=True)
class ResearchToolCall:
    id: str | None
    name: str
    arguments: str


@dataclass(frozen=True)
class ResearchMessage:
    role: Role
    text: str
    tool_calls: list[ResearchToolCall] = field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None

    @staticmethod
    def system(text: str) -> "ResearchMessage":
        return ResearchMessage(Role.SYSTEM, text or "")

    @staticmethod
    def user(text: str) -> "ResearchMessage":
        return ResearchMessage(Role.USER, text or "")

    @staticmethod
    def assistant(text: str, tool_calls: list[ResearchToolCall] | None = None) -> "ResearchMessage":
        return ResearchMessage(Role.ASSISTANT, text or "", tool_calls or [])

    @staticmethod
    def tool_result(tool_call: ResearchToolCall, result: str) -> "ResearchMessage":
        return ResearchMessage(Role.TOOL, result or "", [], tool_call.id, tool_call.name)


@dataclass(frozen=True)
class ResearchTokenUsage:
    input_token_count: int = 0
    output_token_count: int = 0


@dataclass(frozen=True)
class ResearchChatResponse:
    ai_message: ResearchMessage
    token_usage: ResearchTokenUsage = field(default_factory=ResearchTokenUsage)
    finish_reason: str | None = None


@dataclass(frozen=True)
class ResearchToolParameter:
    name: str
    description: str
    required: bool
    type: str = "string"


@dataclass(frozen=True)
class ResearchToolSpec:
    name: str
    description: str
    parameters: list[ResearchToolParameter] = field(default_factory=list)

    def json_schema(self) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        required: list[str] = []
        for param in self.parameters:
            properties[param.name] = {"type": param.type, "description": param.description}
            if param.required:
                required.append(param.name)
        schema: dict[str, Any] = {"type": "object", "properties": properties}
        if required:
            schema["required"] = required
        return schema


ToolExecutor = Callable[[ResearchToolCall], Awaitable[str]]


@dataclass(frozen=True)
class ResearchAgentRequest:
    stage_name: str
    system_prompt: str | None
    messages: list[ResearchMessage]
    tool_specifications: list[ResearchToolSpec] = field(default_factory=list)
    tool_executor: ToolExecutor | None = None
    max_iterations: int = 10
    runtime_context: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def text_only(
        stage_name: str,
        system_prompt: str | None,
        messages: list[ResearchMessage],
        runtime_context: dict[str, Any] | None = None,
    ) -> "ResearchAgentRequest":
        async def noop(_: ResearchToolCall) -> str:
            return ""

        return ResearchAgentRequest(
            stage_name=stage_name,
            system_prompt=system_prompt,
            messages=messages,
            tool_specifications=[],
            tool_executor=noop,
            max_iterations=1,
            runtime_context=runtime_context or {},
        )


class ResearchMemory:
    def __init__(self, max_messages: int) -> None:
        self.max_messages = max_messages
        self._messages: list[ResearchMessage] = []

    def add(self, message: ResearchMessage) -> None:
        self._messages.append(message)
        self._trim()

    def add_all(self, messages: list[ResearchMessage]) -> None:
        self._messages.extend(messages)
        self._trim()

    def messages(self) -> list[ResearchMessage]:
        return list(self._messages)

    def _trim(self) -> None:
        while len(self._messages) > self.max_messages:
            self._messages.pop(0)


def render_messages(messages: list[ResearchMessage]) -> str:
    return "\n".join(f"{message.role.value}: {message.text}" for message in messages)


def arguments_json(arguments: dict[str, Any]) -> str:
    return json.dumps(arguments or {}, ensure_ascii=False)
