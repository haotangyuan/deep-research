from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass

from sqlalchemy import select

from app.core.config import get_settings
from app.core.constants import EventType, WorkflowStatus
from app.infrastructure.db import SessionLocal
from app.infrastructure.events import event_publisher
from app.core.json_utils import extract_json, truncate
from app.infrastructure.llm import model_handler
from app.domain.models import ResearchSession
from app.infrastructure.observability import stage_span, tool_span
from app.application.prompts import (
    CLARIFY_WITH_USER_INSTRUCTIONS,
    COMPRESS_RESEARCH_HUMAN_MESSAGE,
    COMPRESS_RESEARCH_SYSTEM_PROMPT,
    REPORT_AGENT_PROMPT,
    RESEARCH_AGENT_PROMPT,
    RESEARCH_TASK_PLANNER_PROMPT,
    SUMMARIZE_WEBPAGE_PROMPT,
    TRANSFORM_MESSAGES_INTO_RESEARCH_TOPIC_PROMPT,
)
from app.domain.runtime import ResearchAgentRequest, ResearchMemory, ResearchMessage, ResearchToolCall, render_messages
from app.domain.state import DeepResearchState, TavilySearchResult
from app.infrastructure.tavily import tavily_client
from app.core.timeutil import today_str
from app.application.tools import RESEARCHER_STAGE_TOOLS, execute_simple_tool


class ScopeAgent:
    async def run(self, state: DeepResearchState) -> None:
        state.status = WorkflowStatus.IN_SCOPE
        user_input = state.chat_history[-1] if state.chat_history else ResearchMessage.user("")
        scope_event_id = await event_publisher.publish_event(
            state.research_id,
            EventType.SCOPE,
            "正在分析您的研究需求...",
            user_input.text,
        )
        state.current_scope_event_id = scope_event_id
        memory = ResearchMemory(100)
        memory.add_all(state.chat_history)
        await self._clarify_user_instructions(memory, state)
        if state.status == WorkflowStatus.FAILED:
            return
        clarify = state.clarify_with_user_schema or {}
        if clarify.get("needClarification"):
            return
        await self._write_research_brief(memory, state)

    async def _clarify_user_instructions(self, memory: ResearchMemory, state: DeepResearchState) -> None:
        prompt = CLARIFY_WITH_USER_INSTRUCTIONS.format(
            messages=render_messages(memory.messages()),
            hitl_feedback_section=self._hitl_feedback_section(state),
            date=today_str(),
        )
        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest.text_only(
                "ScopeAgent",
                "",
                [ResearchMessage.user(prompt)],
                state.trace_context(),
            ),
        )
        state.add_token_usage(response.token_usage)
        json_response = response.ai_message.text
        try:
            clarify = extract_json(json_response)
            if bool(clarify.get("needClarification")):
                question = str(clarify.get("question") or "")
                memory.add(ResearchMessage.assistant(question))
                state.status = WorkflowStatus.NEED_CLARIFICATION
                await event_publisher.publish_event(
                    state.research_id,
                    EventType.SCOPE,
                    "需要您提供更多信息",
                    question,
                    state.current_scope_event_id,
                )
                await event_publisher.publish_message(state.research_id, "assistant", question)
                # 发布结构化澄清表单（如果 LLM 有生成的话）
                clarification_form = clarify.get("clarificationForm")
                if clarification_form and isinstance(clarification_form, dict):
                    await event_publisher.publish_event(
                        state.research_id,
                        EventType.CLARIFY_FORM,
                        str(clarification_form.get("title") or "研究范围澄清"),
                        json.dumps(clarification_form, ensure_ascii=False),
                        state.current_scope_event_id,
                    )
            else:
                verification = str(clarify.get("verification") or "")
                memory.add(ResearchMessage.assistant(verification))
                await event_publisher.publish_event(
                    state.research_id,
                    EventType.SCOPE,
                    "研究需求已明确",
                    verification,
                    state.current_scope_event_id,
                )
            state.clarify_with_user_schema = clarify
        except Exception:
            state.status = WorkflowStatus.FAILED

    async def _write_research_brief(self, memory: ResearchMemory, state: DeepResearchState) -> None:
        prompt = TRANSFORM_MESSAGES_INTO_RESEARCH_TOPIC_PROMPT.format(
            messages=render_messages(memory.messages()),
            hitl_feedback_section=self._hitl_feedback_section(state),
            date=today_str(),
        )
        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest.text_only(
                "ScopeAgent",
                "",
                [ResearchMessage.user(prompt)],
                state.trace_context(),
            ),
        )
        state.add_token_usage(response.token_usage)
        try:
            question = extract_json(response.ai_message.text)
            research_brief = str(question.get("researchBrief") or "")
            memory.add(ResearchMessage.assistant(research_brief))
            await event_publisher.publish_event(
                state.research_id,
                EventType.SCOPE,
                "已制定研究计划",
                research_brief,
                state.current_scope_event_id,
            )
            state.research_question = question
            state.research_brief = research_brief
        except Exception:
            state.status = WorkflowStatus.FAILED

    @staticmethod
    def _hitl_feedback_section(state: DeepResearchState) -> str:
        feedback = (state.hitl_feedback or "").strip()
        if not feedback:
            return ""
        return (
            "<HumanRevision priority=\"highest\">\n"
            "用户在研究方向确认环节提出了修改意见。生成新的研究简报时，必须让这些修改意见覆盖历史消息、旧研究简报或旧确认消息中的冲突内容。\n"
            "如果修改意见指定了时间范围，必须严格使用该范围，不得扩展、近似或改写为相对时间表达。\n"
            f"{feedback}\n"
            "</HumanRevision>"
        )


class SupervisorAgent:
    def __init__(self, researcher_agent: "ResearcherAgent") -> None:
        self.researcher_agent = researcher_agent

    async def run(self, state: DeepResearchState) -> None:
        state.status = WorkflowStatus.IN_RESEARCH
        supervisor_event_id = await event_publisher.publish_event(
            state.research_id,
            EventType.SUPERVISOR,
            "开始规划研究路线...",
            state.research_brief,
        )
        state.current_supervisor_event_id = supervisor_event_id
        tasks = await self._plan_research_tasks(state)
        results = await self._execute_research_tasks(tasks, state)
        if await is_cancelled(state.research_id):
            state.status = WorkflowStatus.CANCELLED
            return
        await self._summarize_supervisor_results(results, state)

    async def _plan_research_tasks(self, state: DeepResearchState) -> list["ResearchTask"]:
        system_prompt = RESEARCH_TASK_PLANNER_PROMPT.format(
            date=today_str(),
            max_concurrent_research_units=state.budget.max_concurrent_units,
            max_researcher_iterations=state.budget.max_conduct_count,
        )
        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest.text_only(
                "SupervisorAgent",
                None,
                [ResearchMessage.system(system_prompt), ResearchMessage.user(state.research_brief or "")],
                state.trace_context(),
            ),
        )
        state.add_token_usage(response.token_usage)
        tasks = self._parse_research_tasks(response.ai_message.text, state)
        formatted = self._format_task_list(tasks)
        await event_publisher.publish_event(
            state.research_id,
            EventType.SUPERVISOR,
            "已拆解研究任务",
            formatted,
            state.current_supervisor_event_id,
        )
        state.supervisor_notes.append("## 研究任务拆解\n\n" + formatted)
        return tasks

    def _parse_research_tasks(self, response_text: str, state: DeepResearchState) -> list["ResearchTask"]:
        max_count = max(1, state.budget.max_conduct_count)
        try:
            root = extract_json(response_text)
            nodes = root.get("researchTasks")
            if not isinstance(nodes, list):
                return self._fallback_research_tasks(state)
            tasks: list[ResearchTask] = []
            for node in nodes:
                if len(tasks) >= max_count:
                    break
                if not isinstance(node, dict):
                    continue
                topic = str(node.get("researchTopic") or "").strip()
                if not topic:
                    continue
                title = str(node.get("title") or "").strip() or f"研究任务 {len(tasks) + 1}"
                tasks.append(ResearchTask(len(tasks), title, topic))
            return tasks or self._fallback_research_tasks(state)
        except Exception:
            return self._fallback_research_tasks(state)

    def _fallback_research_tasks(self, state: DeepResearchState) -> list["ResearchTask"]:
        return [ResearchTask(0, "综合研究", state.research_brief or "")]

    async def _execute_research_tasks(self, tasks: list["ResearchTask"], state: DeepResearchState) -> list["ResearchResult"]:
        parallelism = max(1, min(len(tasks), state.budget.max_concurrent_units))
        semaphore = asyncio.Semaphore(parallelism)

        async def run_task(task: ResearchTask) -> ResearchResult:
            async with semaphore:
                return await self._execute_research_task(task, state)

        results = await asyncio.gather(*(run_task(task) for task in tasks))
        return sorted(results, key=lambda item: item.index)

    async def _execute_research_task(self, task: "ResearchTask", state: DeepResearchState) -> "ResearchResult":
        if not self._reserve_conduct_slot(state):
            return ResearchResult(task.index, task.title, task.research_topic, "已达到研究任务配额限制", None)
        plan_event_id = await event_publisher.publish_event(
            state.research_id,
            EventType.SUPERVISOR,
            "正在研究: " + task.title,
            task.research_topic,
            state.current_supervisor_event_id,
        )
        branch_state = state.fork_for_research(task.research_topic, plan_event_id)
        async with tool_span("conductResearch", "SupervisorAgent", state, "execute_tool conductResearch"):
            result = await self.researcher_agent.run(branch_state)
        return ResearchResult(task.index, task.title, task.research_topic, result, branch_state)

    async def _summarize_supervisor_results(self, results: list["ResearchResult"], state: DeepResearchState) -> None:
        for result in results:
            state.merge_token_usage_from(result.branch_state)
            state.supervisor_notes.append(self._format_research_result(result))
        state.supervisor_iterations += len(results) + 1
        await event_publisher.publish_event(
            state.research_id,
            EventType.SUPERVISOR,
            f"研究资料收集完成",
            f"共完成 {len(results)} 个研究任务，准备生成最终报告",
            state.current_supervisor_event_id,
        )

    def _reserve_conduct_slot(self, state: DeepResearchState) -> bool:
        if state.conduct_count >= state.budget.max_conduct_count:
            return False
        state.conduct_count += 1
        return True

    @staticmethod
    def _format_task_list(tasks: list["ResearchTask"]) -> str:
        return "\n\n".join(f"{task.index + 1}. {task.title}\n{task.research_topic}" for task in tasks).strip()

    @staticmethod
    def _format_research_result(result: "ResearchResult") -> str:
        return f"""## {result.title}

<research_topic>
{result.research_topic}
</research_topic>

<research_findings>
{result.findings or ""}
</research_findings>
"""


class ResearcherAgent:
    def __init__(self, search_agent: "SearchAgent") -> None:
        self.search_agent = search_agent

    async def run(self, state: DeepResearchState) -> str:
        research_event_id = await event_publisher.publish_event(
            state.research_id,
            EventType.RESEARCH,
            "深入研究: " + (state.research_topic or ""),
            None,
            state.current_research_event_id,
        )
        state.current_research_event_id = research_event_id
        memory = ResearchMemory(100)
        memory.add(ResearchMessage.system(RESEARCH_AGENT_PROMPT.format(date=today_str())))
        memory.add(ResearchMessage.user(state.research_topic or ""))
        await self._plan(memory, state)
        return await self._compress_research(memory, state)

    async def _plan(self, memory: ResearchMemory, state: DeepResearchState) -> None:
        max_search_count = state.budget.max_search_count
        max_iterations = max_search_count * 2
        search_semaphore = asyncio.Semaphore(max(1, max_search_count))

        async def execute_tool(tool_call: ResearchToolCall) -> str:
            return await self._execute_tool(tool_call, state, search_semaphore)

        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest(
                stage_name="ResearcherAgent",
                system_prompt=None,
                messages=memory.messages(),
                tool_specifications=RESEARCHER_STAGE_TOOLS,
                tool_executor=execute_tool,
                max_iterations=max_iterations,
                runtime_context=state.trace_context(),
            ),
        )
        state.add_token_usage(response.token_usage)
        memory.add(response.ai_message)

    async def _execute_tool(
        self,
        tool_call: ResearchToolCall,
        state: DeepResearchState,
        search_semaphore: asyncio.Semaphore,
    ) -> str:
        if tool_call.name == "tavilySearch":
            if not self._reserve_search_slot(state):
                async with tool_span(tool_call.name, "ResearcherAgent", state):
                    result = "已达到搜索配额限制，请根据已有信息完成研究"
            else:
                result = await self._execute_search_tool(tool_call, state, search_semaphore)
        else:
            async with tool_span(tool_call.name, "ResearcherAgent", state):
                result = await execute_simple_tool(tool_call.name, json.loads(tool_call.arguments or "{}"))
        if tool_call.name == "thinkTool":
            await event_publisher.publish_event(
                state.research_id,
                EventType.RESEARCH,
                "分析中...",
                result,
                state.current_research_event_id,
            )
        state.researcher_notes.append(f"[{tool_call.name}] {result}")
        state.researcher_iterations += 1
        return result

    async def _execute_search_tool(
        self,
        tool_call: ResearchToolCall,
        state: DeepResearchState,
        search_semaphore: asyncio.Semaphore,
    ) -> str:
        args = json.loads(tool_call.arguments or "{}")
        query = str(args.get("query") or "")
        max_results = int(args.get("maxResults") or 3)
        settings = get_settings()
        max_results = max(1, min(max_results, max(1, settings.research_search_max_results_per_query)))
        topic = str(args.get("topic") or "general")
        search_state = state.fork_for_search(query, max_results, topic)
        async with search_semaphore:
            async with tool_span(tool_call.name, "ResearcherAgent", state):
                result = await self.search_agent.run(search_state)
        state.merge_token_usage_from(search_state)
        return result

    async def _compress_research(self, memory: ResearchMemory, state: DeepResearchState) -> str:
        system_prompt = COMPRESS_RESEARCH_SYSTEM_PROMPT.format(date=today_str())
        messages = [ResearchMessage.system(system_prompt)]
        messages.extend(memory.messages()[2:])
        messages.append(
            ResearchMessage.user(
                COMPRESS_RESEARCH_HUMAN_MESSAGE.format(research_topic=state.research_topic or ""),
            ),
        )
        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest.text_only("ResearcherAgent", None, messages, state.trace_context()),
        )
        state.add_token_usage(response.token_usage)
        compressed = response.ai_message.text
        state.compressed_research = compressed
        preview = compressed[: min(200, len(compressed))] + "..."
        await event_publisher.publish_event(
            state.research_id,
            EventType.RESEARCH,
            "已完成该主题研究",
            preview,
            state.current_research_event_id,
        )
        return compressed

    def _reserve_search_slot(self, state: DeepResearchState) -> bool:
        if state.search_count >= state.budget.max_search_count:
            return False
        state.search_count += 1
        return True


class SearchAgent:
    def __init__(self) -> None:
        self._summary_cache: dict[tuple[str, int], tuple[dict, float]] = {}
        self._inflight: dict[tuple[str, int], asyncio.Future[dict]] = {}
        self._lock = asyncio.Lock()

    async def run(self, state: DeepResearchState) -> str:
        search_event_id = await event_publisher.publish_event(
            state.research_id,
            EventType.SEARCH,
            "正在搜索: " + (state.query or ""),
            None,
            state.current_research_event_id,
        )
        state.current_search_event_id = search_event_id
        await self._plan(state)
        await self._action(state)
        return await self._summarize(state)

    async def _plan(self, state: DeepResearchState) -> None:
        results = await tavily_client.search(
            state.query or "",
            state.max_results or 3,
            state.topic or "general",
            True,
        )
        unique: dict[str, TavilySearchResult] = {}
        for result in results:
            if result.url and result.url not in unique:
                unique[result.url] = result
        state.search_results = unique
        search_event_content = self._format_search_event_content(list(unique.values()))
        await event_publisher.publish_event(
            state.research_id,
            EventType.SEARCH,
            f"找到 {len(unique)} 个相关结果",
            search_event_content,
            state.current_search_event_id,
        )

    @staticmethod
    def _format_search_event_content(results: list[TavilySearchResult]) -> str | None:
        if not results:
            return None
        lines: list[str] = []
        for index, result in enumerate(results, start=1):
            title = (result.title or "Untitled source").replace("\n", " ").strip()
            url = (result.url or "").strip()
            snippet = truncate((result.content or result.raw_content or "").replace("\n", " ").strip(), 180)
            lines.append(f"{index}. {title}\nURL: {url}\n{snippet}".strip())
        return "\n\n".join(lines)

    async def _action(self, state: DeepResearchState) -> None:
        if not state.search_results:
            return
        results = list(state.search_results.values())
        parallelism = max(1, min(len(results), 4))
        semaphore = asyncio.Semaphore(parallelism)

        async def summarize_one(result: TavilySearchResult) -> str:
            async with semaphore:
                try:
                    return await asyncio.wait_for(
                        self._summarize_result(state, result),
                        timeout=max(5, get_settings().research_search_summary_timeout_seconds + 5),
                    )
                except Exception:
                    return self._format_content(result, result.content)

        notes = await asyncio.gather(*(summarize_one(result) for result in results))
        state.search_notes.extend(notes)

    async def _summarize_result(self, state: DeepResearchState, result: TavilySearchResult) -> str:
        content = result.raw_content or result.content or ""
        if len(content) <= 500:
            return self._format_content(result, content)
        summary = await self._summarize_webpage_with_cache(state, result.url or "", content)
        return self._format_summary(result, summary)

    async def _summarize_webpage_with_cache(self, state: DeepResearchState, url: str, content: str) -> dict:
        settings = get_settings()
        if not settings.research_search_summary_cache_enabled:
            return await self._summarize_webpage(state, content)
        key = (url.strip().lower(), hash(content))
        cached = self._summary_cache.get(key)
        if cached and cached[1] > time.time():
            return cached[0]
        async with self._lock:
            existing = self._inflight.get(key)
            if existing:
                return await existing
            future: asyncio.Future[dict] = asyncio.get_running_loop().create_future()
            self._inflight[key] = future
        try:
            summary = await self._summarize_webpage(state, content)
            self._summary_cache[key] = (
                summary,
                time.time() + max(1, settings.research_search_summary_cache_ttl_minutes) * 60,
            )
            self._prune_summary_cache()
            future.set_result(summary)
            return summary
        except Exception as exc:
            future.set_exception(exc)
            raise
        finally:
            async with self._lock:
                self._inflight.pop(key, None)

    async def _summarize_webpage(self, state: DeepResearchState, content: str) -> dict:
        settings = get_settings()
        bounded = truncate(content, max(1000, settings.research_search_summary_raw_content_max_chars))
        prompt = SUMMARIZE_WEBPAGE_PROMPT.format(webpage_content=bounded, date=today_str())
        context = dict(state.trace_context())
        context["llm.timeout.seconds"] = max(5, settings.research_search_summary_timeout_seconds)
        try:
            response = await model_handler.get_chat_client(state.research_id).run_agent(
                ResearchAgentRequest.text_only("SearchAgent", "", [ResearchMessage.user(prompt)], context),
            )
            state.add_token_usage(response.token_usage)
            return extract_json(response.ai_message.text)
        except Exception:
            return {
                "summary": truncate(content, max(300, settings.research_search_summary_fallback_content_max_chars)),
                "key_excerpts": "",
            }

    def _prune_summary_cache(self) -> None:
        max_entries = max(1, get_settings().research_search_summary_cache_max_entries)
        now = time.time()
        for key in list(self._summary_cache):
            if self._summary_cache[key][1] <= now or len(self._summary_cache) > max_entries:
                self._summary_cache.pop(key, None)

    @staticmethod
    def _format_summary(result: TavilySearchResult, summary: dict) -> str:
        return (
            f"[{result.title or ''}]\n"
            f"URL: {result.url or ''}\n"
            f"<summary>{summary.get('summary') or ''}</summary>\n"
            f"<key_excerpts>{summary.get('key_excerpts') or summary.get('keyExcerpts') or ''}</key_excerpts>"
        )

    @staticmethod
    def _format_content(result: TavilySearchResult, content: str | None) -> str:
        return f"[{result.title or ''}]\nURL: {result.url or ''}\n{content or ''}"

    async def _summarize(self, state: DeepResearchState) -> str:
        if not state.search_notes:
            return "No search results found for: " + (state.query or "")
        await event_publisher.publish_event(
            state.research_id,
            EventType.SEARCH,
            "已分析并整理搜索结果",
            None,
            state.current_search_event_id,
        )
        output = [f"Search results for query: '{state.query}'\n"]
        for idx, result in enumerate(state.search_notes, start=1):
            output.append(f"\n--- SOURCE {idx} ---\n")
            output.append(result)
            output.append("\n" + "-" * 80 + "\n")
        return "".join(output)


class ReportAgent:
    async def run(self, state: DeepResearchState) -> str:
        state.status = WorkflowStatus.IN_REPORT
        await event_publisher.publish_event(
            state.research_id,
            EventType.REPORT,
            "正在生成研究报告...",
            None,
        )
        prompt = REPORT_AGENT_PROMPT.format(
            research_brief=state.research_brief or "",
            date=today_str(),
            findings=self._bounded_findings(state.supervisor_notes),
        )
        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest.text_only(
                "ReportAgent",
                "",
                [ResearchMessage.user(prompt)],
                state.trace_context(),
            ),
        )
        state.add_token_usage(response.token_usage)
        state.report = response.ai_message.text
        await event_publisher.publish_event(state.research_id, EventType.REPORT, "研究报告已完成", None)
        await event_publisher.publish_message(state.research_id, "assistant", state.report)
        return state.report

    @staticmethod
    def _bounded_findings(supervisor_notes: list[str]) -> str:
        findings = "\n".join(supervisor_notes)
        max_chars = max(1000, get_settings().research_report_findings_max_chars)
        if len(findings) <= max_chars:
            return findings
        return truncate(findings, max_chars) + "\n\n[部分研究材料因长度限制已截断，以上保留最相关的前序材料。]"


async def is_cancelled(research_id: str) -> bool:
    try:
        async with SessionLocal() as session:
            session_obj = await session.get(ResearchSession, research_id)
            return bool(session_obj and session_obj.status == WorkflowStatus.CANCELLED)
    except Exception:
        return False


@dataclass(frozen=True)
class ResearchTask:
    index: int
    title: str
    research_topic: str


@dataclass(frozen=True)
class ResearchResult:
    index: int
    title: str
    research_topic: str
    findings: str | None
    branch_state: DeepResearchState | None


search_agent = SearchAgent()
researcher_agent = ResearcherAgent(search_agent)
scope_agent = ScopeAgent()
supervisor_agent = SupervisorAgent(researcher_agent)
report_agent = ReportAgent()
