from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from sqlalchemy import select

from app.core.config import get_settings
from app.core.constants import EventType, WorkflowMode, WorkflowStatus
from app.application.interventions import (
    InterventionRecord,
    InterventionRequestData,
    build_intervention_apply_summary,
    build_intervention_applied_message,
    build_intervention_prompt_block,
    build_intervention_round_start_message,
    load_pending_intervention_record,
    mark_intervention_applied,
    normalize_intervention_request,
)
from app.infrastructure.db import SessionLocal
from app.infrastructure.events import event_publisher
from app.core.json_utils import extract_json, truncate
from app.infrastructure.llm import model_handler
from app.domain.models import ResearchSession
from app.infrastructure.observability import stage_span, summarize, tool_span
from app.application.prompts import (
    CLARIFY_WITH_USER_INSTRUCTIONS,
    COMPRESS_RESEARCH_HUMAN_MESSAGE,
    COMPRESS_RESEARCH_SYSTEM_PROMPT,
    REPORT_AGENT_PROMPT,
    RESEARCH_AGENT_PROMPT,
    RESEARCH_TASK_PLANNER_PROMPT,
    SUMMARIZE_WEBPAGE_PROMPT,
    TRANSFORM_MESSAGES_INTO_RESEARCH_TOPIC_PROMPT,
    ULTRA_CLAIM_VERIFY_PROMPT,
    REPORT_DRAFT_ANGLE_PROMPT,
    HIGH_REPORT_SYNTHESIS_PROMPT,
    REPORT_JUDGE_PROMPT,
    REPORT_SYNTHESIS_PROMPT,
)
from app.application.ultra_dynamic import (
    UltraDynamicRoundCoordinator,
    render_dynamic_decision_markdown,
    render_dynamic_focus_prompt_block,
    render_report_quality_markdown,
)
from app.domain.runtime import ResearchAgentRequest, ResearchMemory, ResearchMessage, ResearchToolCall, render_messages
from app.domain.context import BranchEvidencePackage, EvidenceItem
from app.domain.state import DeepResearchState, ResearcherSource, TavilySearchResult
from app.infrastructure.tavily import tavily_client
from app.core.timeutil import today_str
from app.application.context_writer import branch_index_from_task_id, write_branch_package_context, write_search_context
from app.application.report_context import ReportContextBuilder, has_selected_context, render_report_context
from app.application.report_team import report_section_team
from app.application.tools import RESEARCHER_STAGE_TOOLS, execute_simple_tool
from app.application.research_team import research_team
from app.application.workflow_template import (
    claim_verification_enabled,
    draft_angles,
    report_judge_enabled,
    report_section_team_enabled,
)
from app.infrastructure.context_store import ResearchContextStore


logger = logging.getLogger(__name__)
ultra_dynamic_round_coordinator = UltraDynamicRoundCoordinator()


def _safe_error_summary(exc: Exception) -> str:
    raw = f"{exc.__class__.__name__}: {exc}".strip()
    return summarize(raw) or exc.__class__.__name__


def _valid_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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
            # 意图识别：解析研究类型（借鉴点 E，零额外 LLM 调用）
            research_type = str(question.get("researchType") or "general").strip().lower()
            try:
                type_confidence = float(question.get("typeConfidence") or 0.0)
            except (TypeError, ValueError):
                type_confidence = 0.0
            from app.application.workflow_template import RESEARCH_TYPES

            state.research_type = research_type if research_type in RESEARCH_TYPES else "general"
            state.research_type_confidence = type_confidence
            state.research_type_reason = truncate(str(question.get("typeReason") or ""), 500) or None
            candidates: list[dict[str, Any]] = []
            for item in list(question.get("typeCandidates") or []):
                if not isinstance(item, dict):
                    continue
                candidate_type = str(item.get("type") or "").strip().lower()
                if candidate_type not in RESEARCH_TYPES:
                    continue
                try:
                    candidate_confidence = float(item.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    candidate_confidence = 0.0
                candidates.append(
                    {
                        "type": candidate_type,
                        "confidence": max(0.0, min(1.0, candidate_confidence)),
                        "reason": truncate(str(item.get("reason") or ""), 240),
                    },
                )
            state.research_type_candidates = candidates[:3]
            # Eval 事实源：Brief 与其结构化意图放在同一个 Artifact，避免 Eval
            # 再从 workflow_event 或 span 拼装重复数据。
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="research_brief",
                        stage_name="ScopeAgent",
                        round_no=0,
                        content=research_brief,
                        outcome="success",
                        fallback_used=0,
                        metadata={
                            "research_type": state.research_type,
                            "type_confidence": state.research_type_confidence,
                            "type_reason": state.research_type_reason,
                            "type_candidates": state.research_type_candidates,
                            "clarification": state.clarify_with_user_schema or {},
                        },
                    ),
                    context=f"research_brief research_id={state.research_id}",
                )
            await event_publisher.publish_event(
                state.research_id,
                EventType.AGENT_RUNTIME,
                f"意图识别: {state.research_type}（置信度 {type_confidence:.2f}）",
                json.dumps(
                    {
                        "kind": "intent_recognition",
                        "researchType": state.research_type,
                        "confidence": type_confidence,
                        "reason": state.research_type_reason,
                        "candidates": state.research_type_candidates,
                    },
                    ensure_ascii=False,
                ),
                state.current_scope_event_id,
            )
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
        await self._activate_intervention_for_round(state)
        if state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC:
            await ultra_dynamic_round_coordinator.start_round(state)
        title = "开始规划研究路线..."
        if state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC:
            title = f"开始规划第 {max(1, state.dynamic_round_no)} 轮研究路线..."
        supervisor_event_id = await event_publisher.publish_event(
            state.research_id,
            EventType.SUPERVISOR,
            title,
            state.research_brief,
        )
        state.current_supervisor_event_id = supervisor_event_id
        tasks = await self._plan_research_tasks(state)
        if state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC:
            await ultra_dynamic_round_coordinator.persist_planned_tasks(state, tasks)
        research_team.prepare(state.research_id, tasks)
        results = await self._execute_research_tasks(tasks, state)
        if await is_cancelled(state.research_id):
            state.status = WorkflowStatus.CANCELLED
            return
        await self._summarize_supervisor_results(tasks, results, state)

    async def _plan_research_tasks(self, state: DeepResearchState) -> list["ResearchTask"]:
        system_prompt = RESEARCH_TASK_PLANNER_PROMPT.format(
            date=today_str(),
            max_concurrent_research_units=state.budget.max_concurrent_units,
            max_researcher_iterations=state.budget.max_conduct_count,
        )
        planner_input = state.research_brief or ""
        if state.dynamic_next_focus:
            planner_input = (
                planner_input
                + "\n\n"
                + render_dynamic_focus_prompt_block(
                    state.dynamic_next_focus,
                    round_no=max(1, state.dynamic_round_no),
                    remaining_rounds=max(0, state.dynamic_max_rounds - state.dynamic_round_no),
                )
            )
        if state.active_intervention:
            planner_input = (
                planner_input
                + "\n\n"
                + build_intervention_prompt_block(
                    InterventionRequestData(
                        focus_sections=list(state.active_intervention.get("focusSections") or []),
                        reinforce_modes=list(state.active_intervention.get("reinforceModes") or []),
                        note=state.active_intervention.get("note"),
                    ),
                    round_no=max(1, state.dynamic_round_no),
                    remaining_rounds=max(0, state.dynamic_max_rounds - state.dynamic_round_no),
                )
            )
        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest.text_only(
                "SupervisorAgent",
                None,
                [ResearchMessage.system(system_prompt), ResearchMessage.user(planner_input)],
                state.trace_context(),
            ),
        )
        state.add_token_usage(response.token_usage)
        tasks = self._parse_research_tasks(response.ai_message.text, state)
        # Eval 事实源：每轮 Plan 统一落 research_artifact，Eval 无需依赖
        # research_work_item/research_planning_round 这两张业务过程表。
        if state.run_id:
            from app.infrastructure.eval_repository import eval_repository, safe_record

            plan_content = json.dumps(
                {
                    "round_no": max(1, state.dynamic_round_no),
                    "tasks": [
                        {
                            "task_key": task.task_id,
                            "title": task.title,
                            "research_topic": task.research_topic,
                            "priority": "high" if task.index == 0 else "normal",
                        }
                        for task in tasks
                    ],
                },
                ensure_ascii=False,
            )
            await safe_record(
                lambda: eval_repository.upsert_artifact(
                    run_id=state.run_id,
                    research_id=state.research_id,
                    artifact_type="research_plan",
                    stage_name="SupervisorAgent",
                    round_no=max(1, state.dynamic_round_no),
                    content=plan_content,
                    outcome="success",
                    fallback_used=0,
                    metadata={"task_count": len(tasks)},
                ),
                context=(
                    f"research_plan research_id={state.research_id} "
                    f"round={max(1, state.dynamic_round_no)}"
                ),
            )
        formatted = self._format_task_list(tasks)
        await event_publisher.publish_event(
            state.research_id,
            EventType.SUPERVISOR,
            "已拆解研究任务",
            formatted,
            state.current_supervisor_event_id,
        )
        if state.active_intervention and state.active_intervention.get("id"):
            summary = build_intervention_apply_summary(
                InterventionRecord(
                    id=int(state.active_intervention["id"]),
                    research_id=state.research_id,
                    user_id=state.trace_metadata_model.user_id,
                    focus_sections=list(state.active_intervention.get("focusSections") or []),
                    reinforce_modes=list(state.active_intervention.get("reinforceModes") or []),
                    note=state.active_intervention.get("note"),
                ),
                round_no=max(1, state.dynamic_round_no),
                remaining_rounds=max(0, state.dynamic_max_rounds - state.dynamic_round_no),
            )
            await mark_intervention_applied(int(state.active_intervention["id"]), max(1, state.dynamic_round_no), summary)
            await event_publisher.publish_event(
                state.research_id,
                EventType.INTERVENTION,
                f"第 {max(1, state.dynamic_round_no)} 轮已采纳用户调整",
                json.dumps(summary, ensure_ascii=False),
                state.current_supervisor_event_id,
            )
            await event_publisher.publish_message(
                state.research_id,
                "assistant",
                build_intervention_applied_message(summary),
            )
            state.active_intervention = None
        state.supervisor_notes.append("## 研究任务拆解\n\n" + formatted)
        return tasks

    def _parse_research_tasks(self, response_text: str, state: DeepResearchState) -> list["ResearchTask"]:
        max_count = max(
            0,
            min(state.budget.max_conduct_count, state.remaining_total_conduct_slots),
        )
        if max_count <= 0:
            return []
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
                index = len(tasks)
                round_no = max(1, state.dynamic_round_no)
                tasks.append(
                    ResearchTask(
                        index,
                        title,
                        topic,
                        f"{state.research_id}-round-{round_no}-task-{index}",
                        f"researcher-r{round_no}-{index + 1}",
                    ),
                )
            return tasks or self._fallback_research_tasks(state)
        except Exception:
            return self._fallback_research_tasks(state)

    def _fallback_research_tasks(self, state: DeepResearchState) -> list["ResearchTask"]:
        round_no = max(1, state.dynamic_round_no)
        return [
            ResearchTask(
                0,
                "综合研究",
                state.research_brief or "",
                f"{state.research_id}-round-{round_no}-task-0",
                f"researcher-r{round_no}-1",
            ),
        ]

    async def _activate_intervention_for_round(self, state: DeepResearchState) -> None:
        state.active_intervention = None
        if state.workflow_mode != WorkflowMode.ULTRA_DYNAMIC:
            return
        pending = await load_pending_intervention_record(state.research_id)
        if pending is None:
            return
        payload = normalize_intervention_request(
            InterventionRequestData(
                focus_sections=pending.focus_sections,
                reinforce_modes=pending.reinforce_modes,
                note=pending.note,
            ),
        )
        state.active_intervention = {
            "id": pending.id,
            "focusSections": payload.focus_sections,
            "reinforceModes": payload.reinforce_modes,
            "note": payload.note,
        }
        await event_publisher.publish_event(
            state.research_id,
            EventType.INTERVENTION,
            f"第 {max(1, state.dynamic_round_no)} 轮准备应用用户调整",
            build_intervention_prompt_block(
                payload,
                round_no=max(1, state.dynamic_round_no),
                remaining_rounds=max(0, state.dynamic_max_rounds - state.dynamic_round_no),
            ),
            state.current_supervisor_event_id,
        )
        await event_publisher.publish_message(
            state.research_id,
            "assistant",
            build_intervention_round_start_message(payload, max(1, state.dynamic_round_no)),
        )

    async def _execute_research_tasks(self, tasks: list["ResearchTask"], state: DeepResearchState) -> list["ResearchResult"]:
        return await research_team.execute(
            state.research_id,
            tasks,
            state.budget.max_concurrent_units,
            lambda task: self._execute_research_task(task, state),
            lambda task, exc: self._research_task_failure_result(task, state, exc),
            state.current_supervisor_event_id,
        )

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
        branch_state = state.fork_for_research(
            task.research_topic,
            plan_event_id,
            task.worker_id,
            task.task_id,
        )
        async with tool_span("conductResearch", "SupervisorAgent", state, "execute_tool conductResearch"):
            result = await self.researcher_agent.run(branch_state)
        return ResearchResult(task.index, task.title, task.research_topic, result, branch_state)

    async def _research_task_failure_result(
        self,
        task: "ResearchTask",
        state: DeepResearchState,
        exc: Exception,
    ) -> "ResearchResult":
        logger.exception(
            "research branch failed research_id=%s task_index=%s task_title=%s model_id=%s budget=%s",
            state.research_id,
            task.index,
            task.title,
            state.trace_metadata_model.model_id,
            state.budget_name,
        )
        error_summary = summarize(f"{exc.__class__.__name__}: {exc}")
        await event_publisher.publish_event(
            state.research_id,
            EventType.ERROR,
            "研究分支失败: " + task.title,
            error_summary,
            state.current_supervisor_event_id,
        )
        detail = error_summary or "内部异常详情已写入后端日志。"
        findings = (
            "该研究分支执行失败，系统已保留其他分支结果并继续汇总。\n\n"
            f"错误摘要：{detail}"
        )
        return ResearchResult(task.index, task.title, task.research_topic, findings, None)

    async def _summarize_supervisor_results(
        self,
        tasks: list["ResearchTask"],
        results: list["ResearchResult"],
        state: DeepResearchState,
    ) -> None:
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
        if state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC:
            decision = await ultra_dynamic_round_coordinator.finalize_round(state, tasks, results)
            state.supervisor_notes.append("## 动态决策复盘\n\n" + render_dynamic_decision_markdown(decision))

    def _reserve_conduct_slot(self, state: DeepResearchState) -> bool:
        if state.conduct_count >= state.budget.max_conduct_count:
            return False
        if state.total_conduct_count >= state.budget.total_conduct_limit:
            return False
        state.conduct_count += 1
        state.total_conduct_count += 1
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
        for url, item in search_state.search_results.items():
            state.search_results.setdefault(url, item)
        state.search_notes.extend(search_state.search_notes)
        try:
            await write_search_context(
                store=ResearchContextStore(),
                research_id=state.research_id,
                branch_index=branch_index_from_task_id(state.agent_task_id),
                round_no=state.dynamic_round_no,
                search_results=list(search_state.search_results.values()),
                state=state,
            )
        except Exception:
            logger.exception("write search context failed research_id=%s query=%s", state.research_id, query)
        return result

    async def _compress_research(self, memory: ResearchMemory, state: DeepResearchState) -> str:
        system_prompt = COMPRESS_RESEARCH_SYSTEM_PROMPT.replace("{date}", today_str())
        messages = [ResearchMessage.system(system_prompt)]
        messages.extend(memory.messages()[2:])
        messages.append(
            ResearchMessage.user(
                COMPRESS_RESEARCH_HUMAN_MESSAGE.format(research_topic=state.research_topic or ""),
            ),
        )
        try:
            response = await model_handler.get_chat_client(state.research_id).run_agent(
                ResearchAgentRequest.text_only("ResearchCompressorAgent", None, messages, state.trace_context()),
            )
            state.add_token_usage(response.token_usage)
            branch_index = branch_index_from_task_id(state.agent_task_id)
            findings, sources, package = self._parse_evidence_package(response.ai_message.text, state, branch_index)
            state.branch_evidence_package = package
        except Exception as exc:
            logger.exception(
                "research compression failed research_id=%s topic=%s model_id=%s budget=%s",
                state.research_id,
                state.research_topic,
                state.trace_metadata_model.model_id,
                state.budget_name,
            )
            await event_publisher.publish_event(
                state.research_id,
                EventType.ERROR,
                "研究材料压缩失败，使用原始材料",
                summarize(f"{exc.__class__.__name__}: {exc}"),
                state.current_research_event_id,
            )
            findings = self._fallback_compressed_research(state, exc)
            sources = self._fallback_researcher_sources(state)
            state.branch_evidence_package = BranchEvidencePackage(
                branch_index=branch_index_from_task_id(state.agent_task_id),
                task_key=state.agent_task_id,
                task_title=state.research_topic or "",
                research_topic=state.research_topic or "",
                branch_summary=truncate(findings, 1200),
                evidence_items=[],
                source_paths=[],
                gaps=[f"evidence extraction failed: {_safe_error_summary(exc)}"],
                conflicts=[],
            )
        state.compressed_research = findings
        state.researcher_sources = sources
        if state.branch_evidence_package is not None:
            try:
                await write_branch_package_context(
                    store=ResearchContextStore(),
                    research_id=state.research_id,
                    round_no=state.dynamic_round_no,
                    package=state.branch_evidence_package,
                    state=state,
                )
            except Exception:
                logger.exception("write branch evidence context failed research_id=%s", state.research_id)
        preview = findings[: min(200, len(findings))] + "..."
        await event_publisher.publish_event(
            state.research_id,
            EventType.RESEARCH,
            "已完成该主题研究",
            preview,
            state.current_research_event_id,
        )
        return findings

    def _parse_evidence_package(
        self,
        text: str,
        state: DeepResearchState,
        branch_index: int,
    ) -> tuple[str, list[ResearcherSource], BranchEvidencePackage]:
        data = extract_json(text)
        if not isinstance(data, dict):
            findings, sources = self._parse_compressed_research(text, state)
            package = BranchEvidencePackage(
                branch_index=branch_index,
                task_key=state.agent_task_id,
                task_title=state.research_topic or "",
                research_topic=state.research_topic or "",
                branch_summary=truncate(findings, 1200),
                evidence_items=[],
                source_paths=[],
                gaps=[],
                conflicts=[],
            )
            return findings, sources, package

        findings = str(data.get("findings") or data.get("branchSummary") or "")
        _, sources = self._parse_compressed_research(
            json.dumps({"findings": findings, "sources": data.get("sources") or []}, ensure_ascii=False),
            state,
        )
        evidence_items: list[EvidenceItem] = []
        for item in data.get("evidenceItems") or []:
            if not isinstance(item, dict):
                continue
            evidence_items.append(
                EvidenceItem(
                    claim=str(item.get("claim") or ""),
                    evidence_text=str(item.get("evidenceText") or item.get("evidence_text") or ""),
                    source_url=item.get("sourceUrl") or item.get("source_url"),
                    source_title=item.get("sourceTitle") or item.get("source_title"),
                    source_type=str(item.get("sourceType") or item.get("source_type") or "other"),
                    strength=str(item.get("strength") or "medium"),
                    section_hint=item.get("sectionHint") or item.get("section_hint"),
                    confidence=float(item.get("confidence") or 0.5),
                )
            )
        package = BranchEvidencePackage(
            branch_index=branch_index,
            task_key=state.agent_task_id,
            task_title=state.research_topic or "",
            research_topic=state.research_topic or "",
            branch_summary=str(data.get("branchSummary") or findings),
            evidence_items=evidence_items,
            source_paths=[],
            gaps=[str(item) for item in data.get("gaps") or []],
            conflicts=[str(item) for item in data.get("conflicts") or []],
        )
        return findings, sources, package

    def _parse_compressed_research(self, text: str, state: DeepResearchState) -> tuple[str, list[ResearcherSource]]:
        """解析 Researcher 结构化 JSON 输出，返回 (findings, sources)。解析失败时 fallback。"""
        data = extract_json(text)
        if not isinstance(data, dict):
            return text, self._fallback_researcher_sources(state)
        findings = str(data.get("findings") or text)
        raw_sources = data.get("sources") or []
        sources: list[ResearcherSource] = []
        seen_urls: set[str] = set()
        for item in raw_sources if isinstance(raw_sources, list) else []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url or not _valid_http_url(url) or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(
                ResearcherSource(
                    url=url,
                    title=item.get("title"),
                    type=str(item.get("type") or "other"),
                    strength=str(item.get("strength") or "medium"),
                    snippet=item.get("snippet"),
                    section_hint=item.get("sectionHint") or item.get("section_hint"),
                )
            )
        return findings, sources

    def _fallback_researcher_sources(self, state: DeepResearchState) -> list[ResearcherSource]:
        """降级：从 branch_state.search_results 提取结构化来源（URL 启发式分类）。"""
        from app.application.ultra_dynamic import classify_source_type

        sources: list[ResearcherSource] = []
        seen: set[str] = set()
        for item in state.search_results.values():
            url = (item.url or "").strip()
            if not url or not _valid_http_url(url) or url in seen:
                continue
            seen.add(url)
            sources.append(
                ResearcherSource(
                    url=url,
                    title=item.title,
                    type=classify_source_type(url),
                    strength="medium",
                    snippet=truncate(item.content or item.raw_content or "", 200) or None,
                    section_hint=state.research_topic,
                )
            )
        return sources

    @staticmethod
    def _fallback_compressed_research(state: DeepResearchState, exc: Exception) -> str:
        settings = get_settings()
        max_chars = max(2000, min(8000, settings.research_report_findings_max_chars // 2))
        parts = [
            "## 研究主题",
            state.research_topic or "未记录研究主题",
            "## 降级说明",
            "研究材料压缩阶段失败，系统已保留原始搜索结果和工具调用记录用于后续汇总。",
            f"错误摘要：{_safe_error_summary(exc)}",
        ]
        if state.search_notes:
            parts.extend(["## 搜索材料", "\n\n".join(state.search_notes)])
        if state.researcher_notes:
            parts.extend(["## 工具调用与分析记录", "\n\n".join(state.researcher_notes)])
        if len(parts) == 5:
            parts.extend(["## 可用材料", "该分支未记录到可用搜索材料。"])
        text = "\n\n".join(parts)
        if len(text) <= max_chars:
            return text
        return truncate(text, max_chars) + "\n\n[部分原始研究材料因长度限制已截断。]"

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
            return await self._summarize_webpage(state, content, self._summary_instance(state, content))
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
            summary = await self._summarize_webpage(state, content, self._summary_instance(state, content))
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

    async def _summarize_webpage(self, state: DeepResearchState, content: str, instance: str) -> dict:
        settings = get_settings()
        bounded = truncate(content, max(1000, settings.research_search_summary_raw_content_max_chars))
        prompt = SUMMARIZE_WEBPAGE_PROMPT.format(webpage_content=bounded, date=today_str())
        context = dict(state.trace_context())
        context["llm.timeout.seconds"] = max(5, settings.research_search_summary_timeout_seconds)
        context["agent.instance"] = instance
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

    @staticmethod
    def _summary_instance(state: DeepResearchState, content: str) -> str:
        digest = hashlib.sha1(content.encode("utf-8")).hexdigest()[:12]
        return f"{state.agent_worker_id or 'search'}:page:{digest}"

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


# 报告多角度起草的角度定义（借鉴 CC judge panel 思想）
REPORT_DRAFT_ANGLES = [
    {"key": "data-driven", "desc": "数据驱动", "focus": "突出数值、对比表格、来源引用，用数据支撑每个论点。"},
    {"key": "narrative", "desc": "叙事驱动", "focus": "突出趋势、因果与演进，讲清来龙去脉。"},
    {"key": "comparative", "desc": "对比驱动", "focus": "突出多维度横向对比，用对比表格/矩阵呈现。"},
]


class ReportAgent:
    async def run(self, state: DeepResearchState) -> str:
        state.status = WorkflowStatus.IN_REPORT
        await event_publisher.publish_event(
            state.research_id,
            EventType.REPORT,
            "正在生成研究报告...",
            None,
        )
        section_team_completed = False
        if report_section_team_enabled(state.workflow_template):
            try:
                state.report = await report_section_team.run(
                    state,
                    self._quality_context_text(state.report_quality_context),
                )
                complete_title = "研究报告已完成"
                section_team_completed = True
            except Exception as exc:
                logger.exception(
                    "section report team failed research_id=%s model_id=%s budget=%s",
                    state.research_id,
                    state.trace_metadata_model.model_id,
                    state.budget_name,
                )
                await event_publisher.publish_event(
                    state.research_id,
                    EventType.ERROR,
                    "章节报告团队执行失败，回退到原报告流程",
                    summarize(f"{exc.__class__.__name__}: {exc}"),
                )

        # 未启用章节团队或团队降级时，保留原有多角度/单次生成协议。
        if not section_team_completed and state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC:
            try:
                state.report = await self._draft_judge_synthesize(state)
                complete_title = "研究报告已完成"
            except Exception as exc:
                logger.exception(
                    "multi-angle report failed research_id=%s model_id=%s budget=%s",
                    state.research_id,
                    state.trace_metadata_model.model_id,
                    state.budget_name,
                )
                await event_publisher.publish_event(
                    state.research_id,
                    EventType.ERROR,
                    "多角度报告生成失败，使用兜底报告",
                    summarize(f"{exc.__class__.__name__}: {exc}"),
                )
                state.report = self._fallback_report(state, exc)
                complete_title = "研究报告已完成（降级）"
        elif not section_team_completed and (state.budget_name or "").upper() == "HIGH":
            try:
                state.report = await self._lightweight_high_report(state)
                complete_title = "研究报告已完成"
            except Exception as exc:
                logger.exception(
                    "lightweight HIGH report failed research_id=%s model_id=%s",
                    state.research_id,
                    state.trace_metadata_model.model_id,
                )
                await event_publisher.publish_event(
                    state.research_id,
                    EventType.ERROR,
                    "HIGH 双角度报告生成失败，回退单报告流程",
                    summarize(f"{exc.__class__.__name__}: {exc}"),
                )
                try:
                    state.report = await self._single_report(state)
                    complete_title = "研究报告已完成"
                except Exception as fallback_exc:
                    logger.exception(
                        "HIGH fallback report failed research_id=%s model_id=%s",
                        state.research_id,
                        state.trace_metadata_model.model_id,
                    )
                    state.report = self._fallback_report(state, fallback_exc)
                    complete_title = "研究报告已完成（降级）"
        elif not section_team_completed:
            try:
                state.report = await self._single_report(state)
                complete_title = "研究报告已完成"
            except Exception as exc:
                logger.exception(
                    "report generation failed research_id=%s model_id=%s budget=%s",
                    state.research_id,
                    state.trace_metadata_model.model_id,
                    state.budget_name,
                )
                await event_publisher.publish_event(
                    state.research_id,
                    EventType.ERROR,
                    "报告生成模型失败，使用兜底报告",
                    summarize(f"{exc.__class__.__name__}: {exc}"),
                )
                state.report = self._fallback_report(state, exc)
                complete_title = "研究报告已完成（降级）"
        # 声明交叉验证（借鉴点 A2），claimVerification 从编排模板读
        if state.workflow_mode == WorkflowMode.ULTRA_DYNAMIC and claim_verification_enabled(state.workflow_template):
            try:
                state.report = await self.verify_report_claims(state, state.report)
            except Exception as exc:
                logger.exception(
                    "claim verification failed research_id=%s model_id=%s",
                    state.research_id,
                    state.trace_metadata_model.model_id,
                )
        await event_publisher.publish_event(state.research_id, EventType.REPORT, complete_title, None)
        # Eval MVP v2：report_final 落库（state.report 已终态、即将 publish 的唯一收口点）
        report_artifact_id: str | None = None
        if state.run_id and state.report:
            from app.infrastructure.eval_repository import eval_repository, safe_record

            report_text = state.report
            source_catalog: list[dict[str, str]] = []
            citation_audit: dict = {}
            try:
                from app.application.claim_manifest import normalize_report_citations

                source_catalog = await eval_repository.load_source_catalog(state.run_id)
                _, citation_audit = normalize_report_citations(
                    report_text,
                    source_catalog=source_catalog,
                )
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="report_citation_audit",
                        stage_name="ReportAgent:citation-audit",
                        round_no=state.dynamic_round_no,
                        content=json.dumps(citation_audit, ensure_ascii=False),
                        outcome=(
                            "success"
                            if not citation_audit.get("unresolved_marker_ids")
                            else "unresolved_citations"
                        ),
                        metadata={
                            "resolved_count": len(citation_audit.get("resolved_marker_ids") or []),
                            "unresolved_count": len(citation_audit.get("unresolved_marker_ids") or []),
                        },
                    ),
                    context=f"report_citation_audit research_id={state.research_id}",
                )
            except Exception:
                logger.exception(
                    "report citation audit failed research_id=%s",
                    state.research_id,
                )
            try:
                report_artifact_id = await eval_repository.upsert_artifact(
                    run_id=state.run_id,
                    research_id=state.research_id,
                    artifact_type="report_final",
                    stage_name="ReportAgent.run",
                    round_no=state.dynamic_round_no,
                    content=report_text,
                    outcome="success",
                    fallback_used=0,
                )
            except Exception:
                logger.exception(
                    "report_final persist failed research_id=%s run_id=%s",
                    state.research_id,
                    state.run_id,
                )
            # Eval MVP v2 Commit 5：Claim-Citation Manifest 落库
            # 从终态 report Markdown 提取 claim-citation 对，与 report_final artifact 关联。
            # report_artifact_id 可能为 None（upsert 失败时）——write_claim_manifest 接受 None。
            try:
                from app.application.claim_manifest import extract_claims_from_report

                claims = extract_claims_from_report(
                    report_text,
                    source_catalog=source_catalog,
                )
                await safe_record(
                    lambda: eval_repository.replace_claim_manifest(
                        state.run_id,
                        state.research_id,
                        report_artifact_id,
                        claims,
                    ),
                    context=f"claim_manifest research_id={state.research_id}",
                )
            except Exception:
                logger.exception(
                    "claim manifest extraction failed research_id=%s",
                    state.research_id,
                )
        await event_publisher.publish_message(state.research_id, "assistant", state.report)
        return state.report

    async def _single_report(self, state: DeepResearchState) -> str:
        findings_text = await self._report_findings_text(state)
        prompt = REPORT_AGENT_PROMPT.format(
            research_brief=state.research_brief or "",
            date=today_str(),
            findings=findings_text,
            quality_context=self._quality_context_text(state.report_quality_context),
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
        return response.ai_message.text

    async def _lightweight_high_report(self, state: DeepResearchState) -> str:
        findings = await self._report_findings_text(state)
        quality_context = self._quality_context_text(state.report_quality_context)
        angle_by_key = {item["key"]: item for item in REPORT_DRAFT_ANGLES}
        angles = [angle_by_key["comparative"], angle_by_key["data-driven"]]
        drafts = await asyncio.gather(
            *(self._draft_by_angle(state, angle, findings, quality_context) for angle in angles),
        )
        valid = [(angle["key"], draft) for angle, draft in zip(angles, drafts) if draft]
        if not valid:
            raise RuntimeError("all HIGH report angles failed")
        if len(valid) == 1:
            return valid[0][1]
        draft_by_key = dict(valid)
        prompt = HIGH_REPORT_SYNTHESIS_PROMPT.format(
            research_brief=state.research_brief or "",
            comparative_draft=draft_by_key["comparative"],
            data_driven_draft=draft_by_key["data-driven"],
        )
        await event_publisher.publish_event(
            state.research_id,
            EventType.AGENT_RUNTIME,
            "HIGH 报告融合: 比较分析 + 数据证据",
            json.dumps(
                {"kind": "high_report_synthesize", "angles": ["comparative", "data-driven"]},
                ensure_ascii=False,
            ),
        )
        try:
            response = await model_handler.get_chat_client(state.research_id).run_agent(
                ResearchAgentRequest.text_only(
                    "ReportAgent:high-synthesis",
                    "",
                    [ResearchMessage.user(prompt)],
                    state.trace_context(),
                ),
            )
            state.add_token_usage(response.token_usage)
            synthesis_text = response.ai_message.text
            # Eval MVP v2 Commit 4：HIGH Synthesis 落库（融合 comparative+data-driven）
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                _captured = synthesis_text
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="report_synthesis",
                        stage_name="ReportAgent:high-synthesis",
                        round_no=state.dynamic_round_no,
                        content=_captured,
                        outcome="success",
                        metadata={"angles": ["comparative", "data-driven"]},
                    ),
                    context=f"report_synthesis research_id={state.research_id}",
                )
            return synthesis_text
        except Exception:
            logger.exception("HIGH report synthesis failed, fallback to comparative draft")
            # Eval MVP v2 Commit 4：fallback 仍留存前序 Draft（已由 _draft_by_angle 落库）；
            # 这里把 fallback 标记写入 synthesis artifact，便于后续 Synthesis Uplift 分析区分。
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                _fallback = draft_by_key["comparative"]
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="report_synthesis",
                        stage_name="ReportAgent:high-synthesis",
                        round_no=state.dynamic_round_no,
                        content=_fallback,
                        outcome="fallback",
                        fallback_used=1,
                        metadata={"fallback_type": "comparative_draft"},
                    ),
                    context=f"report_synthesis fallback research_id={state.research_id}",
                )
            return draft_by_key["comparative"]

    @staticmethod
    def _angles_for_state(state: DeepResearchState) -> list[dict]:
        """从编排模板读取起草角度，fallback 到默认全部角度。"""
        angle_keys = draft_angles(state.workflow_template)
        if angle_keys:
            key_set = set(angle_keys)
            order = {k: i for i, k in enumerate(angle_keys)}
            angles = sorted(
                (a for a in REPORT_DRAFT_ANGLES if a["key"] in key_set),
                key=lambda a: order.get(a["key"], 999),
            )
            if angles:
                return angles
        return list(REPORT_DRAFT_ANGLES)

    async def _draft_judge_synthesize(self, state: DeepResearchState) -> str:
        """多角度起草 + 评委打分 + 融合（借鉴 CC judge panel）。"""
        findings = await self._report_findings_text(state)
        quality_context = self._quality_context_text(state.report_quality_context)

        # 角度从编排模板读（借鉴点 E），fallback 到全部角度
        angles = self._angles_for_state(state)

        # 阶段1：多角度并行起草
        drafts = await asyncio.gather(
            *(self._draft_by_angle(state, angle, findings, quality_context) for angle in angles)
        )
        valid = [(a, d) for a, d in zip(angles, drafts) if d]
        if not valid:
            raise RuntimeError("all draft angles failed")
        if len(valid) == 1 or not report_judge_enabled(state.workflow_template):
            return valid[0][1]

        # 阶段2：评委并行打分
        judged = await asyncio.gather(*(self._judge_draft(state, draft) for _, draft in valid))
        scored = list(zip(valid, judged))

        def _total(j: dict) -> float:
            s = j.get("scores", {}) if isinstance(j, dict) else {}
            return sum(v for v in s.values() if isinstance(v, (int, float)))

        scored.sort(key=lambda x: _total(x[1]), reverse=True)
        (_, champion_draft), champion_judge = scored[0]
        champion_score = _total(champion_judge)
        runner_ups = scored[1:]

        # 阶段3：融合（冠军为底 + 嫁接落选亮点）
        return await self._synthesize_report(state, champion_draft, champion_score, runner_ups)

    async def _report_findings_text(self, state: DeepResearchState) -> str:
        try:
            report_context = await ReportContextBuilder().build(
                research_id=state.research_id,
                research_brief=state.research_brief or "",
            )
            await event_publisher.publish_event(
                state.research_id,
                EventType.AGENT_RUNTIME,
                "报告上下文已装配",
                json.dumps(
                    {
                        "kind": "report_context",
                        "sections": {key: len(value) for key, value in report_context.section_contexts.items()},
                        "dropped": len(report_context.dropped),
                        "estimatedTokens": report_context.total_estimated_tokens,
                    },
                    ensure_ascii=False,
                ),
            )
            rendered = render_report_context(report_context)
            if has_selected_context(report_context):
                return rendered
        except Exception:
            logger.exception("build report context failed research_id=%s", state.research_id)
        return self._bounded_findings(state.supervisor_notes)

    async def _draft_by_angle(
        self,
        state: DeepResearchState,
        angle: dict,
        findings: str,
        quality_context: str,
    ) -> str | None:
        prompt = REPORT_DRAFT_ANGLE_PROMPT.format(
            date=today_str(),
            angle_desc=angle["desc"],
            angle_focus=angle["focus"],
            research_brief=state.research_brief or "",
            findings=findings,
            quality_context=quality_context,
        )
        await event_publisher.publish_event(
            state.research_id,
            EventType.AGENT_RUNTIME,
            f"报告起草: {angle['desc']}",
            json.dumps({"kind": "report_draft", "angle": angle["key"], "angleDesc": angle["desc"]}, ensure_ascii=False),
        )
        try:
            response = await model_handler.get_chat_client(state.research_id).run_agent(
                ResearchAgentRequest.text_only(
                    "ReportAgent:" + angle["key"],
                    "",
                    [ResearchMessage.user(prompt)],
                    state.trace_context(),
                ),
            )
            state.add_token_usage(response.token_usage)
            draft_text = response.ai_message.text
            # Eval MVP v2 Commit 4：HIGH 双 Draft / ULTRA 多角度 Draft 落库
            # angle['key'] 区分 comparative/data-driven/narrative；stage_name 与 run_agent 入口一致。
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                _captured = draft_text
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="report_draft",
                        stage_name="ReportAgent:" + angle["key"],
                        round_no=state.dynamic_round_no,
                        angle=angle["key"],
                        content=_captured,
                        outcome="success",
                        metadata={"angle_desc": angle.get("desc")},
                    ),
                    context=f"report_draft angle={angle['key']} research_id={state.research_id}",
                )
            return draft_text
        except Exception:
            logger.exception("report draft failed angle=%s", angle["key"])
            return None

    async def _judge_draft(self, state: DeepResearchState, draft: str) -> dict:
        prompt = REPORT_JUDGE_PROMPT.format(
            research_brief=state.research_brief or "",
            draft=draft,
        )
        try:
            response = await model_handler.get_chat_client(state.research_id).run_agent(
                ResearchAgentRequest.text_only(
                    "ReportJudge",
                    "",
                    [ResearchMessage.user(prompt)],
                    state.trace_context(),
                ),
            )
            state.add_token_usage(response.token_usage)
            verdict = extract_json(response.ai_message.text)
            if not isinstance(verdict, dict):
                verdict = {"scores": {}, "verdict": "neutral"}
        except Exception:
            verdict = {"scores": {}, "verdict": "neutral"}
        await event_publisher.publish_event(
            state.research_id,
            EventType.AGENT_RUNTIME,
            f"报告评审: {verdict.get('verdict', 'neutral')}",
            json.dumps(
                {
                    "kind": "report_judge",
                    "scores": verdict.get("scores", {}),
                    "verdict": verdict.get("verdict"),
                    "highlight": verdict.get("highlight"),
                    "gap": verdict.get("gap"),
                    "graftSuggestions": verdict.get("graftSuggestions") or [],
                },
                ensure_ascii=False,
            ),
        )
        return verdict

    async def _synthesize_report(
        self,
        state: DeepResearchState,
        champion_draft: str,
        champion_score: float,
        runner_ups: list,
    ) -> str:
        parts: list[str] = []
        for i, ((_, draft), j) in enumerate(runner_ups):
            scores = j.get("scores", {}) if isinstance(j, dict) else {}
            total = sum(v for v in scores.values() if isinstance(v, (int, float)))
            suggestions = [
                str(item)
                for item in list(j.get("graftSuggestions") or [])
                if str(item).strip()
            ][:3]
            suggestion_text = "；".join(suggestions) if suggestions else "无"
            parts.append(
                f"[Runner-up {i + 1}, 总分 {total}]\n"
                f"亮点: {j.get('highlight', '')}\n"
                f"必须嫁接建议: {suggestion_text}\n"
                f"{draft}"
            )
        runner_up_text = "\n\n---\n".join(parts)
        prompt = REPORT_SYNTHESIS_PROMPT.format(
            research_brief=state.research_brief or "",
            champion_score=champion_score,
            champion_draft=champion_draft,
            runner_up_drafts=runner_up_text,
        )
        await event_publisher.publish_event(
            state.research_id,
            EventType.AGENT_RUNTIME,
            "报告融合: 冠军 + 嫁接落选亮点",
            json.dumps(
                {"kind": "report_synthesize", "championScore": champion_score, "runnerUpCount": len(runner_ups)},
                ensure_ascii=False,
            ),
        )
        try:
            response = await model_handler.get_chat_client(state.research_id).run_agent(
                ResearchAgentRequest.text_only(
                    "ReportSynthesizer",
                    "",
                    [ResearchMessage.user(prompt)],
                    state.trace_context(),
                ),
            )
            state.add_token_usage(response.token_usage)
            return response.ai_message.text
        except Exception:
            logger.exception("report synthesis failed, fallback to champion draft")
            return champion_draft

    async def verify_report_claims(self, state: DeepResearchState, report: str) -> str:
        """报告声明交叉验证：抽取带引用的关键声明，独立代理查验来源支撑。

        借鉴 CC 声明级 cross-check：未验证标注 [未验证]，无来源标注 [缺来源]。
        """
        import re

        sentences = re.split(r"(?<=[。.!?])\s*", report)
        claims = [s.strip() for s in sentences if re.search(r"\[\d+\]", s) and len(s.strip()) > 15]
        if not claims:
            return report
        evidence_text = "\n\n".join(state.supervisor_notes)
        if len(evidence_text) > 8000:
            evidence_text = evidence_text[:8000] + "\n\n[证据已截断]"
        if not evidence_text.strip():
            return report
        claims_to_verify = claims[:8]

        async def verify_one(claim: str) -> tuple[str, dict]:
            prompt = ULTRA_CLAIM_VERIFY_PROMPT.format(claim=claim, evidence=evidence_text)
            try:
                response = await model_handler.get_chat_client(state.research_id).run_agent(
                    ResearchAgentRequest.text_only(
                        "ClaimVerifier",
                        "",
                        [ResearchMessage.user(prompt)],
                        state.trace_context(),
                    ),
                )
                state.add_token_usage(response.token_usage)
                verdict = extract_json(response.ai_message.text)
                if not isinstance(verdict, dict):
                    verdict = {"verdict": "unverified"}
            except Exception:
                verdict = {"verdict": "unverified"}
            # Eval MVP v2 Commit 5：单 claim 验证结果落库（report_phase=claim_verify）
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                _claim = claim
                _verdict = verdict
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="claim_verification",
                        stage_name="ClaimVerifier",
                        agent_name="ClaimVerifier",
                        round_no=state.dynamic_round_no,
                        content=_claim[:500],
                        outcome=_verdict.get("verdict", "unverified"),
                        metadata={
                            "claim": _claim[:500],
                            "verdict": _verdict.get("verdict"),
                            "scores": _verdict.get("scores", {}),
                        },
                    ),
                    context=f"claim_verification research_id={state.research_id}",
                )
            return claim, verdict

        results = await asyncio.gather(*(verify_one(c) for c in claims_to_verify))
        verified_count = sum(1 for _, v in results if v.get("verdict") == "verified")
        annotations: dict[str, str] = {}
        for claim, v in results:
            verdict = v.get("verdict", "unverified")
            if verdict == "verified":
                continue
            annotations[claim] = "[缺来源]" if verdict == "no_source" else "[未验证]"

        await event_publisher.publish_event(
            state.research_id,
            EventType.AGENT_RUNTIME,
            f"声明交叉验证: {verified_count}/{len(results)} 通过",
            json.dumps(
                {
                    "kind": "claim_verification",
                    "verified": verified_count,
                    "total": len(results),
                    "unverified": len(results) - verified_count,
                },
                ensure_ascii=False,
            ),
        )

        if not annotations:
            return report
        annotated = report
        for claim, tag in annotations.items():
            if claim in annotated:
                annotated = annotated.replace(claim, claim + " " + tag, 1)
        annotated += (
            "\n\n---\n**声明交叉验证**："
            f"{verified_count}/{len(results)} 个关键声明经独立代理查验有来源支撑；"
            "其余标注 [未验证] 或 [缺来源]，请人工复核。"
        )
        return annotated

    @staticmethod
    def _bounded_findings(supervisor_notes: list[str]) -> str:
        findings = "\n".join(supervisor_notes)
        max_chars = max(1000, get_settings().research_report_findings_max_chars)
        if len(findings) <= max_chars:
            return findings
        return truncate(findings, max_chars) + "\n\n[部分研究材料因长度限制已截断，以上保留最相关的前序材料。]"

    def _fallback_report(self, state: DeepResearchState, exc: Exception) -> str:
        findings = self._bounded_findings(state.supervisor_notes)
        quality_context = self._quality_context_text(state.report_quality_context)
        return (
            "# 研究报告（降级生成）\n\n"
            "## 生成说明\n\n"
            "最终报告模型生成阶段失败，系统已基于已收集的研究材料生成兜底报告，避免研究结果丢失。"
            f"错误摘要：{_safe_error_summary(exc)}\n\n"
            "## 研究方向\n\n"
            f"{state.research_brief or '未记录研究方向。'}\n\n"
            "## 已收集研究材料\n\n"
            f"{findings or '未收集到可用研究材料。'}\n\n"
            "## 报告前验证\n\n"
            f"{quality_context}\n\n"
            "## 后续建议\n\n"
            "- 优先复核标记为失败或降级的研究分支。\n"
            "- 对营养数值、单位换算和来源引用类结论进行人工校验。\n"
            "- 如需更完整成稿，可在模型服务稳定后基于以上材料重新生成正式报告。\n"
        )

    @staticmethod
    def _quality_context_text(context: dict | None) -> str:
        if not context:
            return "未提供额外的质量上下文。"
        return render_report_quality_markdown(context)


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
    task_id: str
    worker_id: str


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
