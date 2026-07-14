from __future__ import annotations

import asyncio
import hashlib
import json
import time
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
from app.core.constants import EventType
from app.domain.models import Model
from app.infrastructure.agentscope_runtime import AgentScopeRuntimeSession
from app.infrastructure.events import event_publisher
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


_MODEL_ACCOUNT_SEMAPHORES: dict[str, asyncio.Semaphore] = {}
_MODEL_ACCOUNT_LIMITS: dict[str, int] = {}


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
    _TRANSIENT_RETRY_PHRASES = (
        "concurrency limit exceeded",
        "rate limit",
        "too many requests",
        "temporarily unavailable",
        "service unavailable",
        "server overloaded",
    )

    def __init__(self, research_id: str, model_record: Model) -> None:
        settings = get_settings()
        if not model_record or not model_record.id:
            raise ValueError("模型不应为空")
        credential = OpenAICredential(api_key=model_record.api_key or "", base_url=model_record.base_url)
        self.research_id = research_id
        self.model_name = model_record.model
        self.framework = "agentscope-python"
        self.timeout = settings.llm_timeout
        self.retry_max_attempts = max(1, settings.llm_retry_max_attempts)
        self.retry_initial_delay = max(0.0, settings.llm_retry_initial_delay_seconds)
        self.retry_max_delay = max(self.retry_initial_delay, settings.llm_retry_max_delay_seconds)
        self._model_account_key = self._account_key(model_record)
        self._model_account_semaphore = self._account_semaphore(
            self._model_account_key,
            max(1, settings.llm_max_concurrency),
        )
        self.runtime = AgentScopeRuntimeSession(research_id)
        self.model = OpenAIChatModel(
            credential=credential,
            model=model_record.model,
            parameters=OpenAIChatModel.Parameters(max_tokens=16384),
            stream=True,
            max_retries=2,
            retry_delay=1.0,
            formatter=OpenAIChatFormatter(),
            client_kwargs={"timeout": settings.llm_timeout},
        )

    async def run_agent(self, request: ResearchAgentRequest) -> ResearchChatResponse:
        request_summary = render_messages(request.messages)
        started_at = time.perf_counter()
        runtime_key, entry = self._runtime_entry(request)
        before = entry.metrics.copy()
        async with model_span(
            self.model_name,
            self.framework,
            request_summary,
            len(request.tool_specifications),
            request.stage_name,
        ) as span:
            try:
                response = await self._run_agent_with_transient_retries(request, entry.agent)
            except Exception:
                summary = self.runtime.call_summary(
                    runtime_key,
                    before,
                    request.stage_name,
                    started_at,
                    request.runtime_context,
                )
                await self._publish_runtime_summary(summary | {"status": "failed"})
                raise
            span.set_attribute("gen_ai.usage.available", True)
            span.set_attribute("gen_ai.usage.input_tokens", response.token_usage.input_token_count)
            span.set_attribute("gen_ai.usage.output_tokens", response.token_usage.output_token_count)
            span.set_attribute(
                "gen_ai.usage.total_tokens",
                response.token_usage.input_token_count + response.token_usage.output_token_count,
            )
            span.set_attribute("gen_ai.response.finish_reason", response.finish_reason or "")
            await self._publish_runtime_summary(
                self.runtime.call_summary(
                    runtime_key,
                    before,
                    request.stage_name,
                    started_at,
                    request.runtime_context,
                ),
            )
            return response

    async def _run_agent_with_transient_retries(self, request: ResearchAgentRequest, agent: Agent) -> ResearchChatResponse:
        max_attempts = max(1, self._runtime_int(request, "llm.retry.max_attempts", self.retry_max_attempts))
        initial_delay = max(0.0, self._runtime_float(request, "llm.retry.initial_delay.seconds", self.retry_initial_delay))
        max_delay = max(initial_delay, self._runtime_float(request, "llm.retry.max_delay.seconds", self.retry_max_delay))
        attempt = 0
        while True:
            try:
                async with self._model_account_semaphore:
                    return await asyncio.wait_for(
                        self._run_agent(request, agent),
                        timeout=self._agent_timeout(request),
                    )
            except Exception as exc:
                attempt += 1
                if attempt >= max_attempts or not self._is_transient_llm_error(exc):
                    raise
                await asyncio.sleep(min(max_delay, initial_delay * (2 ** (attempt - 1))))

    async def _run_agent(self, request: ResearchAgentRequest, agent: Agent) -> ResearchChatResponse:
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

    def _runtime_entry(self, request: ResearchAgentRequest):
        system_prompt = self._merged_system_prompt(request)
        instance = str(
            request.runtime_context.get("agent.instance")
            or request.runtime_context.get("agent.worker.id")
            or "main"
        )
        tool_names = ",".join(spec.name for spec in request.tool_specifications)
        signature = hashlib.sha1(f"{system_prompt}|{tool_names}".encode()).hexdigest()[:10]
        runtime_key = f"{request.stage_name}:{instance}:{signature}"
        toolkit = self._toolkit(request)

        def factory(state, middlewares):
            return Agent(
                name=f"{request.stage_name}-{instance}",
                system_prompt=system_prompt,
                model=self.model,
                toolkit=toolkit,
                middlewares=middlewares,
                state=state,
                context_config=self.runtime.context_config(),
                react_config=ReActConfig(max_iters=max(1, request.max_iterations)),
            )

        max_tool_calls = max(1, request.max_iterations * max(1, len(request.tool_specifications)))
        return runtime_key, self.runtime.get_or_create_agent(runtime_key, factory, max_tool_calls)

    async def _publish_runtime_summary(self, summary: dict[str, Any]) -> None:
        await event_publisher.publish_event(
            self.research_id,
            EventType.AGENT_RUNTIME,
            f"{summary.get('stage') or 'Agent'} runtime {summary.get('status') or 'completed'}",
            json.dumps(summary, ensure_ascii=False),
        )

    def snapshot(self) -> dict[str, Any]:
        return self.runtime.snapshot()

    def restore(self, snapshot: dict[str, Any] | None) -> None:
        self.runtime.restore(snapshot)

    def replace_tasks(self, tasks: list[dict[str, Any]]):
        return self.runtime.replace_tasks(tasks)

    def update_task(self, task_id: str, status: str, **metadata: Any):
        return self.runtime.update_task(task_id, status, **metadata)

    def tasks(self):
        return self.runtime.tasks()

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

    @classmethod
    def _is_transient_llm_error(cls, exc: Exception) -> bool:
        message = f"{exc.__class__.__name__}: {exc}".lower()
        return any(phrase in message for phrase in cls._TRANSIENT_RETRY_PHRASES)

    @staticmethod
    def _runtime_int(request: ResearchAgentRequest, key: str, default: int) -> int:
        try:
            return int(request.runtime_context.get(key, default))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _runtime_float(request: ResearchAgentRequest, key: str, default: float) -> float:
        try:
            return float(request.runtime_context.get(key, default))
        except (TypeError, ValueError):
            return default

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

    @classmethod
    def _account_semaphore(cls, key: str, limit: int) -> asyncio.Semaphore:
        current = _MODEL_ACCOUNT_SEMAPHORES.get(key)
        if current is None or _MODEL_ACCOUNT_LIMITS.get(key) != limit:
            current = asyncio.Semaphore(limit)
            _MODEL_ACCOUNT_SEMAPHORES[key] = current
            _MODEL_ACCOUNT_LIMITS[key] = limit
        return current

    @staticmethod
    def _account_key(model_record: Model) -> str:
        digest = hashlib.sha1((model_record.api_key or "").encode("utf-8")).hexdigest()[:12]
        return "|".join(
            [
                str(model_record.base_url or ""),
                str(model_record.model or ""),
                digest,
            ],
        )

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
        self._clients[research_id] = AgentScopeChatClient(research_id, model_record)

    def get_chat_client(self, research_id: str) -> AgentScopeChatClient:
        client = self._clients.get(research_id)
        if client is None:
            raise RuntimeError("模型不应为空")
        return client

    def remove_model(self, research_id: str) -> None:
        self._clients.pop(research_id, None)

    def snapshot(self, research_id: str) -> dict[str, Any] | None:
        client = self._clients.get(research_id)
        return client.snapshot() if client is not None else None

    def restore(self, research_id: str, snapshot: dict[str, Any] | None) -> None:
        self.get_chat_client(research_id).restore(snapshot)

    def replace_tasks(self, research_id: str, tasks: list[dict[str, Any]]):
        return self.get_chat_client(research_id).replace_tasks(tasks)

    def update_task(self, research_id: str, task_id: str, status: str, **metadata: Any):
        return self.get_chat_client(research_id).update_task(task_id, status, **metadata)

    def tasks(self, research_id: str):
        return self.get_chat_client(research_id).tasks()


model_handler = ModelHandler()
