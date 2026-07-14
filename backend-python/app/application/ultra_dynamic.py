from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from sqlalchemy import select

from app.application.prompts import ULTRA_REVIEWER_LENS_PROMPT
from app.application.workflow_template import continue_threshold, reviewer_count, reviewer_lenses
from app.core.constants import EventType
from app.core.json_utils import extract_json, truncate
from app.core.timeutil import now_local, today_str
from app.domain.models import (
    ResearchDecisionLog,
    ResearchEvidenceLedger,
    ResearchPlanningRound,
    ResearchWorkItem,
)
from app.domain.runtime import ResearchAgentRequest, ResearchMessage
from app.infrastructure.db import SessionLocal
from app.infrastructure.events import event_publisher
from app.infrastructure.llm import model_handler
from app.infrastructure.observability import stage_span

if TYPE_CHECKING:
    from app.application.agents import ResearchResult, ResearchTask
    from app.domain.state import DeepResearchState


SOURCE_TYPE_KEYS = ("official", "academic", "report", "news", "company", "other")


# 对抗性审查的评审视角（借鉴 CC Adversarial Verify 思想）
REVIEWER_LENSES = [
    {
        "key": "evidence_sufficiency",
        "desc": "证据充分性",
        "focus": "重点判断每个章节是否有足够来源支撑，证据是否逐字保留、可追溯。",
    },
    {
        "key": "source_authority",
        "desc": "来源权威性",
        "focus": "重点判断来源类型分布是否合理（official/academic/report 占比），是否过度依赖低权威来源。",
    },
    {
        "key": "coverage_completeness",
        "desc": "覆盖完整性",
        "focus": "重点判断研究简报的核心问题是否被完整覆盖，有无遗漏维度。",
    },
]


@dataclass(frozen=True)
class EvidenceLedgerEntry:
    research_id: str
    round_no: int
    task_index: int
    task_title: str
    source_url: str
    source_title: str | None
    source_type: str
    strength_score: str | None
    section_hint: str
    snippet: str | None


def classify_source_type(url: str | None) -> str:
    hostname = (urlparse(url or "").hostname or "").lower()
    path = (urlparse(url or "").path or "").lower()
    if not hostname:
        return "other"
    if hostname.endswith(".gov") or ".gov." in hostname or hostname.endswith(".gouv.fr") or hostname.endswith(".int"):
        return "official"
    if hostname.endswith(".edu") or ".edu." in hostname or hostname in {
        "arxiv.org",
        "doi.org",
        "pubmed.ncbi.nlm.nih.gov",
        "nature.com",
        "www.nature.com",
        "sciencedirect.com",
        "link.springer.com",
    }:
        return "academic"
    if path.endswith(".pdf") or hostname in {
        "www.mckinsey.com",
        "mckinsey.com",
        "www2.deloitte.com",
        "www.pwc.com",
        "www.bcg.com",
        "www.gartner.com",
        "www.forrester.com",
        "www.cbinsights.com",
    }:
        return "report"
    if "news" in path or hostname in {
        "www.reuters.com",
        "reuters.com",
        "www.bloomberg.com",
        "bloomberg.com",
        "www.ft.com",
        "ft.com",
        "www.wsj.com",
        "wsj.com",
        "www.nytimes.com",
        "nytimes.com",
        "techcrunch.com",
        "www.techcrunch.com",
    }:
        return "news"
    parts = hostname.split(".")
    if len(parts) >= 2 and parts[-1] == "com":
        return "company"
    return "other"


def collect_evidence_entries(
    research_id: str,
    round_no: int,
    results: list["ResearchResult"],
) -> list[EvidenceLedgerEntry]:
    entries: list[EvidenceLedgerEntry] = []
    for result in results:
        branch_state = result.branch_state
        if branch_state is None:
            continue
        seen_urls: set[str] = set()
        if branch_state.branch_evidence_package and branch_state.branch_evidence_package.evidence_items:
            for item in branch_state.branch_evidence_package.evidence_items:
                url = (item.source_url or "").strip()
                if url and url in seen_urls:
                    continue
                if url:
                    seen_urls.add(url)
                entries.append(
                    EvidenceLedgerEntry(
                        research_id=research_id,
                        round_no=round_no,
                        task_index=result.index,
                        task_title=result.title,
                        source_url=url or None,
                        source_title=item.source_title,
                        source_type=item.source_type,
                        strength_score=item.strength,
                        section_hint=truncate(item.section_hint or result.title, 256) or None,
                        snippet=truncate(item.evidence_text or item.claim, 500) or None,
                    ),
                )
        # 优先用 Researcher 结构化来源（LLM 判定 type/strength，借鉴点 B）
        for src in branch_state.researcher_sources:
            url = (src.url or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            entries.append(
                EvidenceLedgerEntry(
                    research_id=research_id,
                    round_no=round_no,
                    task_index=result.index,
                    task_title=result.title,
                    source_url=url,
                    source_title=src.title,
                    source_type=src.type or classify_source_type(url),
                    strength_score=src.strength,
                    section_hint=truncate(src.section_hint or result.title, 256) or None,
                    snippet=truncate(src.snippet or "", 500) or None,
                ),
            )
        # fallback：search_results 里未被 researcher_sources 覆盖的 URL（URL 启发式分类）
        for item in branch_state.search_results.values():
            url = (item.url or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            entries.append(
                EvidenceLedgerEntry(
                    research_id=research_id,
                    round_no=round_no,
                    task_index=result.index,
                    task_title=result.title,
                    source_url=url,
                    source_title=item.title,
                    source_type=classify_source_type(url),
                    strength_score=_format_strength(item.score),
                    section_hint=truncate(result.title, 256) or None,
                    snippet=truncate(item.content or item.raw_content or "", 500) or None,
                ),
            )
    return entries


def build_fallback_round_decision(
    state: "DeepResearchState",
    results: list["ResearchResult"],
    evidence_entries: list[EvidenceLedgerEntry],
) -> dict[str, Any]:
    breakdown = _source_type_breakdown(evidence_entries)
    weak_sections: list[dict[str, Any]] = []
    blocking_gaps: list[str] = []
    for result in results:
        source_count = len(result.branch_state.search_results) if result.branch_state is not None else 0
        if source_count >= 2 and len(result.findings or "") >= 120:
            section_state = "strong"
            evidence_status = "sufficient"
            confidence = "high"
            gaps: list[str] = []
            recommended_source_types: list[str] = []
        else:
            section_state = "needs_more_evidence"
            evidence_status = "partial" if source_count > 0 else "weak"
            confidence = "medium" if source_count > 0 else "low"
            gaps = ["证据覆盖不足"] if source_count > 0 else ["缺少有效来源"]
            recommended_source_types = _recommended_source_types(breakdown)
            blocking_gaps.extend(gaps)
        weak_sections.append(
            {
                "section": result.title,
                "status": section_state,
                "evidenceStatus": evidence_status,
                "confidence": confidence,
                "gaps": gaps,
                "recommendedSourceTypes": recommended_source_types,
            },
        )
    if not breakdown["official"]:
        blocking_gaps.append("缺官方来源")
    if not (breakdown["academic"] or breakdown["report"]):
        blocking_gaps.append("缺权威研究或行业报告")
    quality_scoreboard = {
        "coverage": _clamp_score(len(results) + 1),
        "evidence": _clamp_score(len(evidence_entries)),
        "freshness": 4 if any("2026" in (entry.source_url or "") for entry in evidence_entries) else 3,
        "sourceDiversity": _clamp_score(sum(1 for key in SOURCE_TYPE_KEYS if breakdown[key] > 0)),
        "consistency": 3 if results else 1,
    }
    can_continue = (
        state.dynamic_round_no < max(1, state.dynamic_max_rounds)
        and state.conduct_count < state.budget.max_conduct_count
    )
    weak_section_names = [item["section"] for item in weak_sections if item["status"] != "strong"]
    next_action = "continue" if (blocking_gaps or weak_section_names) and can_continue else "report"
    directives = []
    if not breakdown["official"]:
        directives.append("补官方来源")
    if not (breakdown["academic"] or breakdown["report"]):
        directives.append("补权威研究或行业报告")
    if not directives and weak_section_names:
        directives.append("补弱 section 证据")
    return {
        "strategy": "优先补足弱 section 的高置信来源，再进入报告",
        "deltaSummary": "本轮已形成初步结论，但证据覆盖和来源结构仍需补强。",
        "qualityScoreboard": quality_scoreboard,
        "sectionScoreboard": weak_sections,
        "sourceTypeBreakdown": breakdown,
        "nextFocus": {
            "sections": weak_section_names[:3],
            "directives": directives[:3],
            "requiredSourceTypes": _recommended_source_types(breakdown),
        },
        "nextAction": next_action,
        "blockingGaps": _dedupe_list(blocking_gaps)[:5],
    }


def build_report_quality_context(
    decision: dict[str, Any] | None,
    forced_reason: str | None = None,
) -> dict[str, Any]:
    decision = decision or {}
    weak_sections = [
        str(item.get("section") or "")
        for item in list(decision.get("sectionScoreboard") or [])
        if str(item.get("status") or "") != "strong" and str(item.get("section") or "")
    ]
    blocking_gaps = [str(item) for item in list(decision.get("blockingGaps") or []) if str(item).strip()]
    if forced_reason or decision.get("nextAction") == "continue" or weak_sections or blocking_gaps:
        status = "needs_disclosure"
        summary = "报告前验证未完全通过"
        if forced_reason:
            blocking_gaps = _dedupe_list([forced_reason, *blocking_gaps])
    else:
        status = "ready"
        summary = "报告前验证通过"
    return {
        "status": status,
        "summary": summary,
        "strategy": decision.get("strategy"),
        "weakSections": weak_sections,
        "blockingGaps": blocking_gaps,
        "qualityScoreboard": decision.get("qualityScoreboard") or {},
        "sourceTypeBreakdown": decision.get("sourceTypeBreakdown") or {},
        "nextFocus": decision.get("nextFocus") or {},
    }


def render_dynamic_focus_prompt_block(focus: dict[str, Any] | None, round_no: int, remaining_rounds: int) -> str:
    if not focus:
        return ""
    sections = [str(item).strip() for item in list(focus.get("sections") or []) if str(item).strip()]
    directives = [str(item).strip() for item in list(focus.get("directives") or []) if str(item).strip()]
    required_source_types = [
        str(item).strip() for item in list(focus.get("requiredSourceTypes") or []) if str(item).strip()
    ]
    lines = [
        "<DynamicPlannerBias>",
        f"当前为 ULTRA 动态工作流第 {round_no} 轮规划。",
        f"剩余可用动态轮次：{max(0, remaining_rounds)}。",
    ]
    if sections:
        lines.append("系统判定的弱 section：" + "、".join(sections))
    if directives:
        lines.append("本轮补强动作：" + "、".join(directives))
    if required_source_types:
        lines.append("优先来源类型：" + "、".join(required_source_types))
    lines.append("要求：下一轮任务拆解应优先覆盖这些缺口，并说明为何这些任务能补齐证据。")
    lines.append("</DynamicPlannerBias>")
    return "\n".join(lines)


def render_dynamic_decision_markdown(decision: dict[str, Any]) -> str:
    scoreboard = decision.get("qualityScoreboard") or {}
    weak_sections = [
        str(item.get("section") or "")
        for item in list(decision.get("sectionScoreboard") or [])
        if str(item.get("status") or "") != "strong" and str(item.get("section") or "")
    ]
    next_focus = decision.get("nextFocus") or {}
    lines = [
        f"策略：{decision.get('strategy') or '未提供'}",
        f"本轮增量：{decision.get('deltaSummary') or '未提供'}",
        "",
        "质量评分：",
        f"- coverage: {scoreboard.get('coverage', 0)}",
        f"- evidence: {scoreboard.get('evidence', 0)}",
        f"- freshness: {scoreboard.get('freshness', 0)}",
        f"- sourceDiversity: {scoreboard.get('sourceDiversity', 0)}",
        f"- consistency: {scoreboard.get('consistency', 0)}",
    ]
    if weak_sections:
        lines.extend(["", "弱 section：", *[f"- {section}" for section in weak_sections]])
    focus_sections = [str(item) for item in list(next_focus.get("sections") or []) if str(item).strip()]
    directives = [str(item) for item in list(next_focus.get("directives") or []) if str(item).strip()]
    if focus_sections or directives:
        lines.append("")
        lines.append("下一轮 focus：")
        lines.extend(f"- {section}" for section in focus_sections)
        lines.extend(f"- {directive}" for directive in directives)
    gaps = [str(item) for item in list(decision.get("blockingGaps") or []) if str(item).strip()]
    if gaps:
        lines.extend(["", "阻塞缺口：", *[f"- {gap}" for gap in gaps]])
    return "\n".join(lines).strip()


def render_report_quality_markdown(context: dict[str, Any]) -> str:
    lines = [str(context.get("summary") or "报告前验证已完成")]
    weak_sections = [str(item) for item in list(context.get("weakSections") or []) if str(item).strip()]
    gaps = [str(item) for item in list(context.get("blockingGaps") or []) if str(item).strip()]
    if weak_sections:
        lines.extend(["", "弱 section：", *[f"- {item}" for item in weak_sections]])
    if gaps:
        lines.extend(["", "证据缺口：", *[f"- {item}" for item in gaps]])
    return "\n".join(lines).strip()


class UltraDynamicRoundCoordinator:
    async def start_round(self, state: "DeepResearchState") -> None:
        round_no = max(1, state.dynamic_round_no)
        planner_bias = self._planner_bias_payload(state)
        round_goal = self._round_goal(state, planner_bias)
        round_id = await self._create_round_record(
            state.research_id,
            round_no,
            round_goal,
            int(state.active_intervention["id"]) if state.active_intervention and state.active_intervention.get("id") else None,
            planner_bias,
        )
        state.current_planning_round_id = round_id
        state.current_planning_round_goal = round_goal

    async def persist_planned_tasks(self, state: "DeepResearchState", tasks: list["ResearchTask"]) -> None:
        if not state.current_planning_round_id:
            return
        await self._persist_work_items(state.current_planning_round_id, state.research_id, max(1, state.dynamic_round_no), tasks)

    async def finalize_round(
        self,
        state: "DeepResearchState",
        tasks: list["ResearchTask"],
        results: list["ResearchResult"],
    ) -> dict[str, Any]:
        round_no = max(1, state.dynamic_round_no)
        evidence_entries = collect_evidence_entries(state.research_id, round_no, results)
        decision = await self._adversarial_review(state, results, evidence_entries)
        state.latest_dynamic_decision = decision
        state.dynamic_next_focus = decision.get("nextFocus") or None
        state.report_quality_context = build_report_quality_context(decision)
        state.dynamic_round_history.append(
            {
                "roundNo": round_no,
                "nextAction": decision.get("nextAction"),
                "strategy": decision.get("strategy"),
                "blockingGaps": list(decision.get("blockingGaps") or []),
            },
        )
        summary = {
            "roundNo": round_no,
            "taskCount": len(tasks),
            "evidenceCount": len(evidence_entries),
            "nextAction": decision.get("nextAction"),
            "qualityScoreboard": decision.get("qualityScoreboard") or {},
        }
        await self._persist_round_summary(state.current_planning_round_id or 0, summary)
        await self._persist_work_item_results(state.current_planning_round_id or 0, tasks, results)
        await self._persist_decision_log(
            state.current_planning_round_id or 0,
            decision,
            render_dynamic_decision_markdown(decision),
        )
        await self._persist_evidence_entries(state.current_planning_round_id or 0, evidence_entries)
        title = "动态决策：进入下一轮补强" if decision.get("nextAction") == "continue" else "动态决策：进入报告生成"
        content = render_dynamic_decision_markdown(decision)
        await event_publisher.publish_event(
            state.research_id,
            EventType.SUPERVISOR,
            title,
            content,
            state.current_supervisor_event_id,
        )
        await event_publisher.publish_message(
            state.research_id,
            "assistant",
            (
                f"第 {round_no} 轮复盘后，系统决定继续下一轮补强。"
                if decision.get("nextAction") == "continue"
                else f"第 {round_no} 轮复盘后，系统判断已具备进入报告的条件。"
            ),
        )
        return decision

    async def _adversarial_review(
        self,
        state: "DeepResearchState",
        results: list["ResearchResult"],
        evidence_entries: list[EvidenceLedgerEntry],
    ) -> dict[str, Any]:
        """对抗性审查：N 个独立 reviewer 从不同 lens 并行评审，投票决定 nextAction。

        借鉴 CC Adversarial Verify：默认倾向 refuted（report），多数（≥2）同意 continue 才 continue。
        """
        fallback = build_fallback_round_decision(state, results, evidence_entries)
        findings_text = self._render_round_findings(results)
        evidence_text = self._render_evidence(evidence_entries)
        round_no = max(1, state.dynamic_round_no)
        remaining_rounds = max(0, state.dynamic_max_rounds - state.dynamic_round_no)
        round_goal = state.current_planning_round_goal or state.research_brief or ""

        async def run_reviewer(lens: dict[str, str]) -> dict[str, Any]:
            prompt = ULTRA_REVIEWER_LENS_PROMPT.format(
                date=today_str(),
                lens_desc=lens["desc"],
                lens_focus=lens["focus"],
                round_no=round_no,
                remaining_rounds=remaining_rounds,
                round_goal=round_goal,
                findings=findings_text,
                evidence=evidence_text,
            )
            try:
                response = await model_handler.get_chat_client(state.research_id).run_agent(
                    ResearchAgentRequest.text_only(
                        "UltraDynamicReviewer:" + lens["key"],
                        "",
                        [ResearchMessage.user(prompt)],
                        state.trace_context(),
                    ),
                )
                state.add_token_usage(response.token_usage)
                raw = extract_json(response.ai_message.text)
                if not isinstance(raw, dict):
                    raw = {}
            except Exception:
                raw = {}
            vote = {
                "lens": lens["key"],
                "lensDesc": lens["desc"],
                "nextAction": raw.get("nextAction") or "report",
                "scores": raw.get("scores") or {},
                "gaps": raw.get("gaps") or [],
                "rationale": raw.get("rationale") or "",
            }
            await event_publisher.publish_event(
                state.research_id,
                EventType.AGENT_RUNTIME,
                f"评审投票: {lens['desc']} → {vote['nextAction']}",
                json.dumps(
                    {"kind": "adversarial_reviewer", **vote},
                    ensure_ascii=False,
                ),
                state.current_supervisor_event_id,
            )
            return vote

        # reviewer 数量与 lens 从编排模板读（借鉴点 E），fallback 到默认 lens
        async with stage_span("UltraDynamicReview", state) as span:
            configured_lenses = reviewer_lenses(state.workflow_template)
            lens_map = {lens["key"]: lens for lens in REVIEWER_LENSES}
            lenses = [lens_map[key] for key in configured_lenses if key in lens_map]
            if not lenses:
                lenses = list(REVIEWER_LENSES)
            count = reviewer_count(state.workflow_template)
            lenses = lenses[: max(1, min(count, len(lenses)))]
            span.set_attribute("review.lens.count", len(lenses))
            span.set_attribute("review.continue.threshold", continue_threshold(state.workflow_template))
            votes = await asyncio.gather(*(run_reviewer(lens) for lens in lenses))

            # 聚合：达到模板阈值才 continue，否则 report（默认 refuted 倾向）
            continue_count = sum(1 for v in votes if v.get("nextAction") == "continue")
            threshold = continue_threshold(state.workflow_template)
            report_count = len(votes) - continue_count
            next_action = "continue" if continue_count >= threshold else "report"
            if continue_count == len(votes):
                consensus = "continue"
            elif report_count == len(votes):
                consensus = "report"
            else:
                consensus = "split"

            # 评分合并：取各维度最低（短板原则）
            merged_scores: dict[str, Any] = {}
            for dim in ("coverage", "evidence", "freshness", "sourceDiversity", "consistency"):
                dim_scores = [
                    v.get("scores", {}).get(dim)
                    for v in votes
                    if isinstance(v.get("scores", {}).get(dim), (int, float))
                ]
                merged_scores[dim] = min(dim_scores) if dim_scores else 1

            all_gaps: list[str] = []
            for v in votes:
                all_gaps.extend(v.get("gaps") or [])

            # 决策结果落入 span 属性，支持在 Langfuse 按 nextAction / 评分维度切片 trace
            span.set_attribute("review.next.action", next_action)
            span.set_attribute("review.continue.votes", continue_count)
            span.set_attribute("review.report.votes", report_count)
            span.set_attribute("review.total.votes", len(votes))
            span.set_attribute("review.consensus", consensus)
            span.set_attribute("review.gaps.count", len(all_gaps[:5]))
            for dim in ("coverage", "evidence", "freshness", "sourceDiversity", "consistency"):
                score = merged_scores.get(dim)
                if isinstance(score, (int, float)):
                    span.set_attribute(f"review.score.{dim}", int(score))

            return {
                "nextAction": next_action,
                "strategy": f"{continue_count}/{len(votes)} 评审同意 {'继续补强' if next_action == 'continue' else '进入报告'}",
                "deltaSummary": fallback.get("deltaSummary", ""),
                "qualityScoreboard": merged_scores,
                "sectionScoreboard": fallback.get("sectionScoreboard", []),
                "sourceTypeBreakdown": fallback.get("sourceTypeBreakdown", {}),
                "nextFocus": fallback.get("nextFocus", {}),
                "blockingGaps": all_gaps[:5],
                "reviewSummary": {
                    "continueVotes": continue_count,
                    "reportVotes": report_count,
                    "totalVotes": len(votes),
                    "continueThreshold": threshold,
                    "consensus": consensus,
                },
                "votes": votes,
            }

    async def _create_round_record(
        self,
        research_id: str,
        round_no: int,
        round_goal: str,
        intervention_id: int | None,
        planner_bias: dict[str, Any],
    ) -> int:
        now = now_local()
        async with SessionLocal() as session:
            model = ResearchPlanningRound(
                research_id=research_id,
                round_no=round_no,
                status="planned",
                round_goal=round_goal,
                intervention_id=intervention_id,
                planner_bias_json=json.dumps(planner_bias, ensure_ascii=False) if planner_bias else None,
                create_time=now,
                update_time=now,
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return int(model.id)

    async def _persist_work_items(
        self,
        round_id: int,
        research_id: str,
        round_no: int,
        tasks: list["ResearchTask"],
    ) -> None:
        now = now_local()
        async with SessionLocal() as session:
            session.add_all(
                [
                    ResearchWorkItem(
                        research_id=research_id,
                        round_id=round_id,
                        round_no=round_no,
                        task_key=task.task_id,
                        title=task.title,
                        description=task.research_topic,
                        priority="high" if task.index == 0 else "normal",
                        status="planned",
                        create_time=now,
                        update_time=now,
                    )
                    for task in tasks
                ],
            )
            await session.commit()

    async def _persist_work_item_results(
        self,
        round_id: int,
        tasks: list["ResearchTask"],
        results: list["ResearchResult"],
    ) -> None:
        if round_id <= 0:
            return
        async with SessionLocal() as session:
            result_by_index = {item.index: item for item in results}
            records = await session.execute(select(ResearchWorkItem).where(ResearchWorkItem.round_id == round_id))
            for record in records.scalars():
                task = next((item for item in tasks if item.task_id == record.task_key), None)
                result = result_by_index.get(task.index) if task is not None else None
                record.status = "completed" if result and result.findings else "failed"
                record.result_summary = truncate(result.findings or "", 4000) if result else None
                record.verification_state = "reviewed"
                record.update_time = now_local()
            await session.commit()

    async def _persist_decision_log(self, round_id: int, decision: dict[str, Any], summary: str) -> None:
        async with SessionLocal() as session:
            round_no = None
            research_id = ""
            if round_id > 0:
                round_model = await session.get(ResearchPlanningRound, round_id)
                if round_model is not None:
                    round_no = round_model.round_no
                    research_id = round_model.research_id
            if not research_id:
                return
            session.add(
                ResearchDecisionLog(
                    research_id=research_id,
                    round_id=round_id,
                    round_no=round_no,
                    decision_type="round_review",
                    action=str(decision.get("nextAction") or ""),
                    summary=summary,
                    payload_json=json.dumps(decision, ensure_ascii=False),
                    create_time=now_local(),
                ),
            )
            await session.commit()

    async def _persist_evidence_entries(self, round_id: int, evidence_entries: list[EvidenceLedgerEntry]) -> None:
        if round_id <= 0 or not evidence_entries:
            return
        async with SessionLocal() as session:
            session.add_all(
                [
                    ResearchEvidenceLedger(
                        research_id=item.research_id,
                        round_id=round_id,
                        work_item_id=None,
                        source_url=item.source_url,
                        source_title=item.source_title,
                        source_type=item.source_type,
                        strength_score=item.strength_score,
                        section_hint=item.section_hint,
                        snippet=item.snippet,
                        create_time=now_local(),
                    )
                    for item in evidence_entries
                ],
            )
            await session.commit()

    async def _persist_round_summary(self, round_id: int, summary: dict[str, Any]) -> None:
        if round_id <= 0:
            return
        async with SessionLocal() as session:
            round_model = await session.get(ResearchPlanningRound, round_id)
            if round_model is None:
                return
            round_model.status = "completed"
            round_model.summary_json = json.dumps(summary, ensure_ascii=False)
            round_model.update_time = now_local()
            round_model.completed_time = now_local()
            await session.commit()

    def _normalize_round_decision(self, raw: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        decision = dict(fallback)
        if isinstance(raw.get("strategy"), str) and raw["strategy"].strip():
            decision["strategy"] = raw["strategy"].strip()
        if isinstance(raw.get("deltaSummary"), str) and raw["deltaSummary"].strip():
            decision["deltaSummary"] = raw["deltaSummary"].strip()
        if raw.get("nextAction") in {"continue", "report"}:
            decision["nextAction"] = raw["nextAction"]
        if isinstance(raw.get("qualityScoreboard"), dict):
            decision["qualityScoreboard"] = {
                "coverage": _clamp_score(raw["qualityScoreboard"].get("coverage"), decision["qualityScoreboard"]["coverage"]),
                "evidence": _clamp_score(raw["qualityScoreboard"].get("evidence"), decision["qualityScoreboard"]["evidence"]),
                "freshness": _clamp_score(raw["qualityScoreboard"].get("freshness"), decision["qualityScoreboard"]["freshness"]),
                "sourceDiversity": _clamp_score(
                    raw["qualityScoreboard"].get("sourceDiversity"),
                    decision["qualityScoreboard"]["sourceDiversity"],
                ),
                "consistency": _clamp_score(
                    raw["qualityScoreboard"].get("consistency"),
                    decision["qualityScoreboard"]["consistency"],
                ),
            }
        if isinstance(raw.get("sectionScoreboard"), list):
            decision["sectionScoreboard"] = [
                {
                    "section": str(item.get("section") or ""),
                    "status": str(item.get("status") or "needs_more_evidence"),
                    "evidenceStatus": str(item.get("evidenceStatus") or "partial"),
                    "confidence": str(item.get("confidence") or "medium"),
                    "gaps": [str(gap) for gap in list(item.get("gaps") or []) if str(gap).strip()],
                    "recommendedSourceTypes": [
                        str(source_type)
                        for source_type in list(item.get("recommendedSourceTypes") or [])
                        if str(source_type).strip()
                    ],
                }
                for item in raw["sectionScoreboard"]
                if isinstance(item, dict) and str(item.get("section") or "").strip()
            ] or decision["sectionScoreboard"]
        if isinstance(raw.get("sourceTypeBreakdown"), dict):
            decision["sourceTypeBreakdown"] = {
                key: int(raw["sourceTypeBreakdown"].get(key, decision["sourceTypeBreakdown"].get(key, 0)) or 0)
                for key in SOURCE_TYPE_KEYS
            }
        if isinstance(raw.get("nextFocus"), dict):
            decision["nextFocus"] = {
                "sections": [str(item) for item in list(raw["nextFocus"].get("sections") or []) if str(item).strip()][:3],
                "directives": [
                    str(item) for item in list(raw["nextFocus"].get("directives") or []) if str(item).strip()
                ][:3],
                "requiredSourceTypes": [
                    str(item)
                    for item in list(raw["nextFocus"].get("requiredSourceTypes") or [])
                    if str(item).strip()
                ][:3],
            }
        if isinstance(raw.get("blockingGaps"), list):
            decision["blockingGaps"] = [str(item) for item in raw["blockingGaps"] if str(item).strip()][:5]
        return decision

    def _planner_bias_payload(self, state: "DeepResearchState") -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if state.dynamic_next_focus:
            payload["nextFocus"] = state.dynamic_next_focus
        if state.active_intervention:
            payload["intervention"] = state.active_intervention
        return payload

    def _round_goal(self, state: "DeepResearchState", planner_bias: dict[str, Any]) -> str:
        sections = list(((planner_bias.get("nextFocus") or {}).get("sections") or []))
        if sections:
            return f"围绕 {state.research_brief or '当前研究主题'} 补强「{'、'.join(sections[:3])}」"
        return state.research_brief or "ULTRA 动态研究轮次"

    @staticmethod
    def _render_round_findings(results: list["ResearchResult"]) -> str:
        chunks = []
        for result in results:
            chunks.append(
                "\n".join(
                    [
                        f"## {result.title}",
                        f"topic: {result.research_topic}",
                        truncate(result.findings or "", 2500),
                    ],
                ).strip(),
            )
        return "\n\n".join(chunks).strip()

    @staticmethod
    def _render_evidence(entries: list[EvidenceLedgerEntry]) -> str:
        if not entries:
            return "无可用来源。"
        return "\n".join(
            [
                f"- [{item.source_type}] {item.source_title or item.source_url} | {item.source_url}"
                for item in entries[:20]
            ],
        )


def _source_type_breakdown(entries: list[EvidenceLedgerEntry]) -> dict[str, int]:
    breakdown = {key: 0 for key in SOURCE_TYPE_KEYS}
    for item in entries:
        breakdown[item.source_type] = breakdown.get(item.source_type, 0) + 1
    return breakdown


def _recommended_source_types(breakdown: dict[str, int]) -> list[str]:
    recommended = []
    if not breakdown.get("official"):
        recommended.append("official")
    if not breakdown.get("academic"):
        recommended.append("academic")
    if not breakdown.get("report"):
        recommended.append("report")
    return recommended[:3] or ["official"]


def _clamp_score(value: Any, default: int | None = None) -> int:
    try:
        numeric = int(value)
    except Exception:
        numeric = int(default or 1)
    return max(1, min(5, numeric))


def _format_strength(score: float | None) -> str | None:
    if score is None:
        return None
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def _dedupe_list(values: list[str]) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for item in values:
        value = str(item).strip()
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output
