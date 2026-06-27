from __future__ import annotations

import asyncio
from typing import Any

from agentscope.agent import Agent, ReActConfig
from agentscope.credential import OpenAICredential
from agentscope.event import ModelCallEndEvent, TextBlockDeltaEvent
from agentscope.formatter import OpenAIChatFormatter
from agentscope.message import AssistantMsg, Msg, SystemMsg, TextBlock, ToolCallBlock, ToolResultState, UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import ToolBase, ToolChunk, Toolkit

from app.core.config import get_settings
from app.domain.models import Model
from app.infrastructure.observability import model_span
from app.domain.runtime import (
    ResearchAgentRequest,
    ResearchChatResponse,
    ResearchMessage,
    ResearchTokenUsage,
    ResearchToolCall,
    ResearchToolSpec,
    Role,
    arguments_json,
    render_messages,
)


class ResearchDynamicTool(ToolBase):
    def __init__(self, spec: ResearchToolSpec, executor) -> None:
        self.name = spec.name
        self.description = spec.description
        self.input_schema = spec.json_schema()
        self.is_concurrency_safe = False
        self.is_read_only = False
        self.is_external_tool = False
        self.is_state_injected = False
        self.is_mcp = False
        self.mcp_name = None
        self._executor = executor

    async def check_permissions(self, *_args: Any, **_kwargs: Any) -> PermissionDecision:
        return PermissionDecision(behavior=PermissionBehavior.ALLOW, message="allowed")

    async def __call__(self, **kwargs: Any) -> ToolChunk:
        result = await self._executor(ResearchToolCall(id=None, name=self.name, arguments=arguments_json(kwargs)))
        return ToolChunk(content=[TextBlock(text=result or "")], state=ToolResultState.SUCCESS)


class AgentScopeChatClient:
    def __init__(self, model_record: Model) -> None:
        settings = get_settings()
        if not model_record or not model_record.id:
            raise ValueError("模型不应为空")
        credential = OpenAICredential(api_key=model_record.api_key or "", base_url=model_record.base_url)
        self.model_name = model_record.model
        self.framework = "agentscope-python"
        self.timeout = settings.llm_timeout
        self.model = OpenAIChatModel(
            credential=credential,
            model=model_record.model,
            parameters=OpenAIChatModel.Parameters(max_tokens=16384),
            stream=True,
            max_retries=0,
            formatter=OpenAIChatFormatter(),
            client_kwargs={"timeout": settings.llm_timeout},
        )

    async def run_agent(self, request: ResearchAgentRequest) -> ResearchChatResponse:
        request_summary = render_messages(request.messages)
        async with model_span(
            self.model_name,
            self.framework,
            request_summary,
            len(request.tool_specifications),
        ) as span:
            response = await asyncio.wait_for(
                self._run_agent(request),
                timeout=self._agent_timeout(request),
            )
            span.set_attribute("gen_ai.usage.available", True)
            span.set_attribute("gen_ai.usage.input_tokens", response.token_usage.input_token_count)
            span.set_attribute("gen_ai.usage.output_tokens", response.token_usage.output_token_count)
            span.set_attribute(
                "gen_ai.usage.total_tokens",
                response.token_usage.input_token_count + response.token_usage.output_token_count,
            )
            span.set_attribute("gen_ai.response.finish_reason", response.finish_reason or "")
            return response

    async def _run_agent(self, request: ResearchAgentRequest) -> ResearchChatResponse:
        toolkit = self._toolkit(request)
        system_prompt = self._merged_system_prompt(request)
        agent = Agent(
            name=request.stage_name,
            system_prompt=system_prompt,
            model=self.model,
            toolkit=toolkit,
            react_config=ReActConfig(max_iters=max(1, request.max_iterations)),
        )
        inputs = self._input_messages(request)
        final_msg: Msg | None = None
        text_parts: list[str] = []
        input_tokens = 0
        output_tokens = 0
        async for event_or_msg in agent.reply_stream(inputs=inputs):
            if isinstance(event_or_msg, ModelCallEndEvent):
                input_tokens += int(event_or_msg.input_tokens or 0)
                output_tokens += int(event_or_msg.output_tokens or 0)
            elif isinstance(event_or_msg, TextBlockDeltaEvent):
                text_parts.append(event_or_msg.delta or "")
            elif isinstance(event_or_msg, Msg):
                final_msg = event_or_msg
        if final_msg is None:
            final_msg = AssistantMsg(name=request.stage_name, content="".join(text_parts))
        ai_message = self._to_research_message(final_msg)
        if not ai_message.text and text_parts:
            ai_message = ResearchMessage.assistant("".join(text_parts), ai_message.tool_calls)
        return ResearchChatResponse(
            ai_message=ai_message,
            token_usage=ResearchTokenUsage(input_tokens, output_tokens),
            finish_reason=None,
        )

    def _agent_timeout(self, request: ResearchAgentRequest) -> float:
        override = request.runtime_context.get("llm.timeout.seconds")
        if override:
            try:
                seconds = float(override)
                if seconds > 0:
                    return seconds
            except (TypeError, ValueError):
                pass
        return float(self.timeout * max(1, request.max_iterations))

    def _toolkit(self, request: ResearchAgentRequest) -> Toolkit | None:
        if not request.tool_specifications:
            return None
        if request.tool_executor is None:
            return None
        return Toolkit(
            tools=[
                ResearchDynamicTool(spec, request.tool_executor)
                for spec in request.tool_specifications
            ],
        )

    @staticmethod
    def _merged_system_prompt(request: ResearchAgentRequest) -> str:
        prompts: list[str] = []
        if request.system_prompt:
            prompts.append(request.system_prompt)
        for message in request.messages:
            if message.role == Role.SYSTEM and message.text:
                prompts.append(message.text)
        return "\n\n".join(prompts)

    @staticmethod
    def _input_messages(request: ResearchAgentRequest) -> list[Msg]:
        converted: list[Msg] = []
        for message in request.messages:
            if message.role == Role.SYSTEM:
                continue
            if message.role == Role.USER:
                converted.append(UserMsg(name="user", content=message.text or ""))
            elif message.role == Role.ASSISTANT:
                converted.append(AssistantMsg(name=request.stage_name, content=message.text or ""))
            elif message.role == Role.TOOL:
                converted.append(AssistantMsg(name=request.stage_name, content=message.text or ""))
        return converted

    @staticmethod
    def _to_research_message(message: Msg) -> ResearchMessage:
        text = message.get_text_content() or ""
        tool_calls: list[ResearchToolCall] = []
        for block in message.get_content_blocks("tool_call"):
            if isinstance(block, ToolCallBlock):
                tool_calls.append(ResearchToolCall(id=block.id, name=block.name, arguments=block.input or "{}"))
        return ResearchMessage.assistant(text, tool_calls)


class ModelHandler:
    def __init__(self) -> None:
        self._clients: dict[str, AgentScopeChatClient] = {}

    def add_model(self, research_id: str, model_record: Model) -> None:
        self._clients[research_id] = AgentScopeChatClient(model_record)

    def get_chat_client(self, research_id: str) -> AgentScopeChatClient:
        client = self._clients.get(research_id)
        if client is None:
            raise RuntimeError("模型不应为空")
        return client

    def remove_model(self, research_id: str) -> None:
        self._clients.pop(research_id, None)


model_handler = ModelHandler()
