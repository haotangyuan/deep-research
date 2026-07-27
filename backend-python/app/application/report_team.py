from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from typing import Any

from app.application.context_retrieval import rank_nodes_for_query
from app.core.config import get_settings
from app.core.constants import EventType
from app.core.json_utils import extract_json, truncate
from app.domain.context import (
    ContextLevel,
    ContextNodeType,
    ResearchContextNodeData,
    ResearchContextPath,
    TypedQuery,
)
from app.domain.report_team import (
    ReportAgentMessage,
    ReportSectionArtifact,
    ReportSectionSpec,
    SharedReportClaim,
)
from app.domain.runtime import ResearchAgentRequest, ResearchMessage
from app.domain.state import DeepResearchState
from app.infrastructure.context_store import ResearchContextStore
from app.infrastructure.events import event_publisher
from app.infrastructure.llm import model_handler
from app.infrastructure.observability import stage_span


logger = logging.getLogger(__name__)


DEFAULT_SECTIONS = [
    ReportSectionSpec(
        section_id="executive-findings",
        title="核心结论",
        objective="提炼最重要、证据充分且可执行的研究结论。",
        evidence_requirements=["关键事实", "核心数字", "结论边界"],
        related_sections=["evidence-analysis", "risks"],
    ),
    ReportSectionSpec(
        section_id="background",
        title="背景与现状",
        objective="说明研究对象的背景、现状、时间线和必要定义。",
        evidence_requirements=["时间", "定义", "现状数据"],
        related_sections=["evidence-analysis"],
    ),
    ReportSectionSpec(
        section_id="evidence-analysis",
        title="关键证据与分析",
        objective="组织主要证据，解释数据、机制、对比和因果关系。",
        evidence_requirements=["数字", "引用", "多来源交叉验证"],
        related_sections=["executive-findings", "risks", "recommendations"],
    ),
    ReportSectionSpec(
        section_id="risks",
        title="风险与不确定性",
        objective="揭示证据冲突、限制条件、反例和仍未覆盖的信息。",
        evidence_requirements=["冲突", "反面证据", "不确定性"],
        related_sections=["executive-findings", "evidence-analysis", "recommendations"],
    ),
    ReportSectionSpec(
        section_id="recommendations",
        title="建议与后续方向",
        objective="基于前述证据提出分优先级、带条件的建议和后续行动。",
        evidence_requirements=["行动依据", "适用条件", "优先级"],
        related_sections=["evidence-analysis", "risks"],
    ),
]


SECTION_PLAN_PROMPT = """
你是报告章节规划器。请根据研究简报规划 3-6 个互补章节，让每个章节可由独立 Agent 撰写，
但明确标注与其他章节的依赖关系。不要设置“参考文献”章节，来源统一由各章节保留。

研究简报：
{research_brief}

只输出 JSON：
{{
  "sections": [
    {{
      "sectionId": "稳定的英文短标识",
      "title": "章节标题",
      "objective": "本章需要回答的问题",
      "evidenceRequirements": ["数字或证据要求"],
      "relatedSections": ["其他 sectionId"]
    }}
  ]
}}
"""


SECTION_DRAFT_PROMPT = """
你是报告章节 Agent，只负责章节《{section_title}》。

研究简报：
{research_brief}

章节目标：
{section_objective}

证据要求：{evidence_requirements}

系统已先用 L0 召回、再用 L1 精排，并按需读取了 L2 原文。只允许使用下列材料，不得编造事实。
每个重要数字和事实必须保留来源 URL 或 research:// 路径。证据冲突必须明确陈述。

<section_evidence>
{evidence_context}
</section_evidence>

只输出 JSON，不要代码块：
{{
  "draftMarkdown": "完整章节 Markdown，不要包含整份报告标题",
  "claims": [
    {{
      "claim": "可被其他章节复用的具体声明",
      "sourcePaths": ["research://..."],
      "sourceUrls": ["https://..."],
      "confidence": 0.0
    }}
  ],
  "requests": [
    {{"targetSection": "sectionId", "question": "希望其他章节核实的问题"}}
  ]
}}
"""


CONSISTENCY_PROMPT = """
你是跨章节一致性 Agent。检查下列章节初稿和共享声明，找出需要跨章节借鉴或修正的内容：
- 数字、时间、主体或术语不一致；
- 一个章节拥有另一个章节需要的证据；
- 重复论述；
- 结论没有体现风险章节的限制条件；
- 建议没有对应证据。

研究简报：{research_brief}

<section_artifacts>
{artifacts}
</section_artifacts>

只输出 JSON，不要重写章节：
{{
  "messages": [
    {{
      "fromAgent": "consistency-agent 或来源章节 ID",
      "toAgent": "目标章节 ID",
      "type": "evidence_response|conflict_detected|terminology_update|section_dependency|review_request",
      "subject": "短标题",
      "instruction": "具体、可执行的修订要求",
      "relatedClaimIds": []
    }}
  ]
}}
"""


SECTION_REVISION_PROMPT = """
你是章节《{section_title}》的负责 Agent。根据共享声明和邮箱消息修订初稿。
可以借鉴其他章节的事实，但必须保留其 sourcePaths/sourceUrls；不得把不确定结论改成确定结论。
消除重复，解决冲突；无法解决时在正文中明确说明。

<current_draft>
{draft}
</current_draft>

<shared_claims>
{shared_claims}
</shared_claims>

<mailbox>
{messages}
</mailbox>

只输出修订后的完整章节 Markdown，不要输出解释或整份报告标题。
"""


REPORT_MERGE_PROMPT = """
你是主 ReportAgent。研究和章节撰写已经由章节 Agent 完成，你只负责：
1. 按合理顺序合并章节；
2. 删除重复段落；
3. 优化段落衔接和全文逻辑；
4. 统一术语、标题层级和语气；
5. 完整保留数字、限定条件、引用 URL 与 research:// 来源路径。

禁止引入章节中不存在的新事实，禁止擅自改变数字，禁止隐去未解决冲突。

研究简报：
{research_brief}

报告质量约束：
{quality_context}

<final_sections>
{sections}
</final_sections>

输出完整 Markdown 报告。不要描述你的合并过程。
"""


class ReportSectionTeam:
    """Bounded multi-agent report workflow backed by the Research Context FS."""

    def __init__(self, store: ResearchContextStore | None = None) -> None:
        self.store = store or ResearchContextStore()

    async def run(self, state: DeepResearchState, quality_context: str) -> str:
        async with stage_span("ReportSectionTeam", state) as span:
            sections = await self._plan_sections(state)
            await self._write_plan(state, sections)
            source_nodes = await self.store.list_nodes(
                state.research_id,
                node_types=[
                    ContextNodeType.EVIDENCE.value,
                    ContextNodeType.BRANCH_SUMMARY.value,
                    ContextNodeType.SOURCE_ABSTRACT.value,
                    ContextNodeType.SOURCE_OVERVIEW.value,
                ],
            )
            span.set_attribute("report.section.count", len(sections))
            span.set_attribute("report.source.nodes", len(source_nodes))
            await self._publish(state, "报告章节团队已启动", {
                "kind": "report_team",
                "phase": "draft",
                "sectionCount": len(sections),
            })
            artifacts = await asyncio.gather(
                *(self._draft_section(state, spec, source_nodes) for spec in sections),
            )
            messages = await self._review_cross_section_consistency(state, artifacts)
            revised = await asyncio.gather(
                *(self._revise_section(state, artifact, artifacts, messages) for artifact in artifacts),
            )
            await self._publish(state, "报告章节通信与修订已完成", {
                "kind": "report_team",
                "phase": "revised",
                "sectionCount": len(revised),
                "messageCount": len(messages),
            })
            return await self._merge_sections(state, revised, quality_context)

    async def _plan_sections(self, state: DeepResearchState) -> list[ReportSectionSpec]:
        async with stage_span("ReportSectionPlanner", state) as span:
            prompt = SECTION_PLAN_PROMPT.format(research_brief=state.research_brief or "")
            try:
                response = await self._call(state, "ReportSectionPlanner", prompt, agent_id="section-planner")
                payload = extract_json(response)
                raw_sections = payload.get("sections") if isinstance(payload, dict) else None
                planned: list[ReportSectionSpec] = []
                used: set[str] = set()
                for index, item in enumerate(raw_sections or []):
                    if not isinstance(item, dict):
                        continue
                    section_id = self._slug(str(item.get("sectionId") or item.get("title") or f"section-{index + 1}"))
                    if not section_id or section_id in used:
                        section_id = f"section-{index + 1}"
                    used.add(section_id)
                    title = str(item.get("title") or "").strip()
                    objective = str(item.get("objective") or "").strip()
                    if not title or not objective:
                        continue
                    planned.append(
                        ReportSectionSpec(
                            section_id=section_id,
                            title=title,
                            objective=objective,
                            evidence_requirements=self._string_list(item.get("evidenceRequirements"))[:8],
                            related_sections=self._string_list(item.get("relatedSections"))[:8],
                        ),
                    )
                if 3 <= len(planned) <= 6:
                    span.set_attribute("report.section.count", len(planned))
                    return planned
            except Exception:
                logger.exception("report section planning failed research_id=%s", state.research_id)
            span.set_attribute("report.section.count", len(DEFAULT_SECTIONS))
            span.set_attribute("report.plan.fallback", True)
            return [item.model_copy(deep=True) for item in DEFAULT_SECTIONS]

    async def _draft_section(
        self,
        state: DeepResearchState,
        spec: ReportSectionSpec,
        nodes: list[Any],
    ) -> ReportSectionArtifact:
        async with stage_span("ReportSectionDraft", state) as span:
            span.set_attribute("report.section.id", spec.section_id)
            span.set_attribute("report.section.title", spec.title)
            evidence_context, evidence_paths, raw_paths = await self._retrieve_section_context(state, spec, nodes)
            span.set_attribute("report.evidence.nodes", len(evidence_paths))
            span.set_attribute("report.raw.nodes", len(raw_paths))
            await self._write_json_node(
                state,
                f"sections/{spec.section_id}/evidence.json",
                ContextNodeType.REPORT_SECTION_EVIDENCE,
                {
                    "section": spec.model_dump(),
                    "evidencePaths": evidence_paths,
                    "rawPaths": raw_paths,
                    "content": evidence_context,
                },
                title=spec.title,
            )
            prompt = SECTION_DRAFT_PROMPT.format(
                section_title=spec.title,
                research_brief=state.research_brief or "",
                section_objective=spec.objective,
                evidence_requirements="、".join(spec.evidence_requirements) or "使用最相关的高质量证据",
                evidence_context=evidence_context,
            )
            response = await self._call(state, f"ReportSectionAgent:{spec.section_id}", prompt, agent_id=spec.section_id)
            try:
                payload = extract_json(response)
            except Exception:
                logger.warning(
                    "report section returned malformed JSON; preserving raw draft research_id=%s section=%s",
                    state.research_id,
                    spec.section_id,
                )
                payload = {}
            draft = str(payload.get("draftMarkdown") or "").strip() if isinstance(payload, dict) else ""
            if not draft:
                draft = response.strip()
            claims = self._parse_claims(spec.section_id, payload.get("claims") if isinstance(payload, dict) else None)
            span.set_attribute("report.claim.count", len(claims))
            artifact = ReportSectionArtifact(
                spec=spec,
                evidence_context=evidence_context,
                evidence_paths=evidence_paths,
                raw_paths=raw_paths,
                draft=draft,
                claims=claims,
                metadata={"requests": payload.get("requests") if isinstance(payload, dict) else []},
            )
            # Eval MVP v2 Commit 4：ULTRA 章节初稿落库（section_id 维度）
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                _draft = draft
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="report_section_draft",
                        stage_name=f"ReportSectionAgent:{spec.section_id}",
                        round_no=state.dynamic_round_no,
                        section_id=spec.section_id,
                        content=_draft,
                        outcome="success",
                        metadata={
                            "section_title": spec.title,
                            "claim_count": len(claims),
                            "raw_source_count": len(raw_paths),
                        },
                    ),
                    context=f"report_section_draft section={spec.section_id} research_id={state.research_id}",
                )
            await self._write_text_node(
                state,
                f"sections/{spec.section_id}/draft.md",
                ContextNodeType.REPORT_SECTION_DRAFT,
                draft,
                title=spec.title,
            )
            for claim in claims:
                await self._write_json_node(
                    state,
                    f"shared/claims/{claim.claim_id}.json",
                    ContextNodeType.REPORT_SHARED_CLAIM,
                    claim.model_dump(),
                    title=claim.claim,
                )
            await self._publish(state, f"章节初稿完成：{spec.title}", {
                "kind": "report_section",
                "phase": "draft",
                "sectionId": spec.section_id,
                "claimCount": len(claims),
                "rawSourceCount": len(raw_paths),
            })
            return artifact

    async def _retrieve_section_context(
        self,
        state: DeepResearchState,
        spec: ReportSectionSpec,
        nodes: list[Any],
    ) -> tuple[str, list[str], list[str]]:
        query_text = " ".join(
            [state.research_brief or "", spec.title, spec.objective, *spec.evidence_requirements],
        )
        abstracts = [node for node in nodes if node.node_type == ContextNodeType.SOURCE_ABSTRACT.value]
        overviews = [node for node in nodes if node.node_type == ContextNodeType.SOURCE_OVERVIEW.value]
        derived = [
            node for node in nodes
            if node.node_type in {ContextNodeType.EVIDENCE.value, ContextNodeType.BRANCH_SUMMARY.value}
        ]
        l0_query = TypedQuery(
            query=query_text,
            intent=f"为章节「{spec.title}」广泛召回来源",
            context_type=ContextNodeType.SOURCE_ABSTRACT,
            priority=5,
            section_hint=spec.title,
        )
        l0_ranked = rank_nodes_for_query(l0_query, abstracts)[:12]
        recalled_parents = {node.parent_path for node in l0_ranked if node.parent_path}
        l1_pool = [node for node in overviews if not recalled_parents or node.parent_path in recalled_parents]
        l1_query = l0_query.model_copy(update={"context_type": ContextNodeType.SOURCE_OVERVIEW})
        l1_ranked = rank_nodes_for_query(l1_query, l1_pool)[:6]
        evidence_query = l0_query.model_copy(update={"context_type": ContextNodeType.EVIDENCE})
        evidence_ranked = rank_nodes_for_query(evidence_query, derived)[:10]

        detail_keys = {"数字", "比例", "时间", "引用", "冲突", "风险", "数据", "规模", "对比"}
        needs_deep_raw = any(key in query_text for key in detail_keys) or len(evidence_ranked) < 3
        raw_candidates = l1_ranked if needs_deep_raw else l1_ranked[:3]
        raw_parts: list[str] = []
        raw_paths: list[str] = []
        raw_limit = max(200, get_settings().research_context_raw_excerpt_max_chars)
        for node in raw_candidates:
            if not node.parent_path:
                continue
            raw = await self.store.read_raw_for_parent(state.research_id, node.parent_path, raw_limit)
            if not raw:
                continue
            raw_path = node.parent_path.rstrip("/") + "/raw.txt"
            raw_paths.append(raw_path)
            raw_parts.append(
                "\n".join([
                    f"### L2 Raw Excerpt: {node.title or raw_path}",
                    f"- Path: {raw_path}",
                    f"- Source: {self._source_url(node)}",
                    raw,
                ]),
            )

        selected = [*evidence_ranked, *l1_ranked, *l0_ranked]
        seen: set[str] = set()
        parts: list[str] = []
        paths: list[str] = []
        for node in selected:
            if node.path in seen:
                continue
            seen.add(node.path)
            paths.append(node.path)
            parts.append(
                "\n".join([
                    f"### {node.level} {node.node_type}: {node.title or node.path}",
                    f"- Path: {node.path}",
                    f"- Source: {self._source_url(node)}",
                    node.content or "",
                ]),
            )
        parts.extend(raw_parts)
        if not parts:
            parts.append("No matching Research Context FS nodes were found. Clearly disclose this evidence gap.")
        return "\n\n".join(parts), paths, raw_paths

    async def _review_cross_section_consistency(
        self,
        state: DeepResearchState,
        artifacts: list[ReportSectionArtifact],
    ) -> list[ReportAgentMessage]:
        async with stage_span("ReportConsistency", state) as span:
            rendered = []
            for artifact in artifacts:
                rendered.append(
                    f"## [{artifact.spec.section_id}] {artifact.spec.title}\n"
                    f"{artifact.draft}\n\n"
                    f"Shared claims:\n{json.dumps([item.model_dump() for item in artifact.claims], ensure_ascii=False)}\n"
                    f"Peer requests:\n{json.dumps(artifact.metadata.get('requests') or [], ensure_ascii=False)}",
                )
            prompt = CONSISTENCY_PROMPT.format(
                research_brief=state.research_brief or "",
                artifacts="\n\n---\n\n".join(rendered),
            )
            try:
                response = await self._call(state, "ReportConsistencyAgent", prompt, agent_id="consistency-agent")
                payload = extract_json(response)
                raw_messages = payload.get("messages") if isinstance(payload, dict) else None
            except Exception:
                logger.exception("report consistency review failed research_id=%s", state.research_id)
                raw_messages = []
            section_ids = {artifact.spec.section_id for artifact in artifacts}
            messages = self._peer_request_messages(artifacts, section_ids)
            for index, item in enumerate(raw_messages or []):
                if not isinstance(item, dict):
                    continue
                target = str(item.get("toAgent") or "").strip()
                instruction = str(item.get("instruction") or "").strip()
                if target not in section_ids or not instruction:
                    continue
                digest = self._digest(f"{target}|{index}|{instruction}")
                messages.append(
                    ReportAgentMessage(
                        message_id=f"msg-{digest}",
                        from_agent=str(item.get("fromAgent") or "consistency-agent"),
                        to_agent=target,
                        message_type=str(item.get("type") or "review_request"),
                        subject=str(item.get("subject") or "跨章节一致性修订"),
                        instruction=instruction,
                        related_claim_ids=self._string_list(item.get("relatedClaimIds")),
                    ),
                )
            if not messages and len(artifacts) > 1:
                for artifact in artifacts:
                    messages.append(
                        ReportAgentMessage(
                            message_id=f"msg-{self._digest(artifact.spec.section_id + '|shared-review')}",
                            from_agent="consistency-agent",
                            to_agent=artifact.spec.section_id,
                            message_type="review_request",
                            subject="共享声明复核",
                            instruction="复核其他章节的共享声明；如与本章相关，带来源引用后纳入，并显式处理冲突。",
                        ),
                    )
            span.set_attribute("report.message.count", len(messages))
            span.set_attribute("report.section.count", len(artifacts))
            for message in messages:
                await self._write_json_node(
                    state,
                    f"mailboxes/{message.to_agent}/{message.message_id}.json",
                    ContextNodeType.REPORT_AGENT_MESSAGE,
                    message.model_dump(),
                    title=message.subject,
                )
            return messages

    def _peer_request_messages(
        self,
        artifacts: list[ReportSectionArtifact],
        section_ids: set[str],
    ) -> list[ReportAgentMessage]:
        messages: list[ReportAgentMessage] = []
        for artifact in artifacts:
            for index, item in enumerate(artifact.metadata.get("requests") or []):
                if not isinstance(item, dict):
                    continue
                target = str(item.get("targetSection") or "").strip()
                question = str(item.get("question") or "").strip()
                if target not in section_ids or target == artifact.spec.section_id or not question:
                    continue
                digest = self._digest(f"{artifact.spec.section_id}|{target}|{index}|{question}")
                messages.append(
                    ReportAgentMessage(
                        message_id=f"msg-{digest}",
                        from_agent=artifact.spec.section_id,
                        to_agent=target,
                        message_type="evidence_request",
                        subject="章节证据协作请求",
                        instruction=question,
                    ),
                )
        return messages

    async def _revise_section(
        self,
        state: DeepResearchState,
        artifact: ReportSectionArtifact,
        artifacts: list[ReportSectionArtifact],
        messages: list[ReportAgentMessage],
    ) -> ReportSectionArtifact:
        async with stage_span("ReportSectionRevise", state) as span:
            span.set_attribute("report.section.id", artifact.spec.section_id)
            peer_claims = [
                claim.model_dump()
                for peer in artifacts
                if peer.spec.section_id != artifact.spec.section_id
                for claim in peer.claims
            ]
            mailbox = [item.model_dump() for item in messages if item.to_agent == artifact.spec.section_id]
            span.set_attribute("report.peer.claims", len(peer_claims))
            span.set_attribute("report.mailbox.messages", len(mailbox))
            prompt = SECTION_REVISION_PROMPT.format(
                section_title=artifact.spec.title,
                draft=artifact.draft,
                shared_claims=json.dumps(peer_claims, ensure_ascii=False, indent=2),
                messages=json.dumps(mailbox, ensure_ascii=False, indent=2),
            )
            try:
                revision = await self._call(
                    state,
                    f"ReportSectionReviser:{artifact.spec.section_id}",
                    prompt,
                    agent_id=artifact.spec.section_id,
                )
                artifact.revision = revision.strip() or artifact.draft
                revision_fallback = 0
            except Exception:
                logger.exception(
                    "report section revision failed research_id=%s section=%s",
                    state.research_id,
                    artifact.spec.section_id,
                )
                artifact.revision = artifact.draft
                revision_fallback = 1
            # Eval MVP v2 Commit 4：ULTRA 章节修订落库（fallback 时 content=原 draft、fallback_used=1）
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                _revision = artifact.final_text
                _fb = revision_fallback
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="report_section_revision",
                        stage_name=f"ReportSectionReviser:{artifact.spec.section_id}",
                        round_no=state.dynamic_round_no,
                        section_id=artifact.spec.section_id,
                        content=_revision,
                        outcome="fallback_to_draft" if _fb else "success",
                        fallback_used=_fb,
                        metadata={
                            "peer_claim_count": len(peer_claims),
                            "mailbox_count": len(mailbox),
                        },
                    ),
                    context=f"report_section_revision section={artifact.spec.section_id} research_id={state.research_id}",
                )
            await self._write_text_node(
                state,
                f"sections/{artifact.spec.section_id}/revision.md",
                ContextNodeType.REPORT_SECTION_REVISION,
                artifact.final_text,
                title=artifact.spec.title,
            )
            return artifact

    async def _merge_sections(
        self,
        state: DeepResearchState,
        artifacts: list[ReportSectionArtifact],
        quality_context: str,
    ) -> str:
        async with stage_span("ReportMerge", state) as span:
            span.set_attribute("report.section.count", len(artifacts))
            sections = "\n\n---\n\n".join(
                f"<!-- section:{artifact.spec.section_id} -->\n{artifact.final_text}"
                for artifact in artifacts
            )
            prompt = REPORT_MERGE_PROMPT.format(
                research_brief=state.research_brief or "",
                quality_context=quality_context or "无额外约束",
                sections=sections,
            )
            report = await self._call(state, "ReportAgent:merge", prompt, agent_id="report-merger")
            # Eval MVP v2 Commit 4：ULTRA 合并报告落库（与 report_final 区分：此处是 merge 产物）
            if state.run_id:
                from app.infrastructure.eval_repository import eval_repository, safe_record

                _merged = report
                _section_ids = [a.spec.section_id for a in artifacts]
                await safe_record(
                    lambda: eval_repository.upsert_artifact(
                        run_id=state.run_id,
                        research_id=state.research_id,
                        artifact_type="report_merged",
                        stage_name="ReportAgent:merge",
                        round_no=state.dynamic_round_no,
                        content=_merged,
                        outcome="success",
                        metadata={
                            "section_count": len(artifacts),
                            "section_ids": _section_ids,
                        },
                    ),
                    context=f"report_merged research_id={state.research_id}",
                )
            await self._write_text_node(
                state,
                "final.md",
                ContextNodeType.REPORT_CONTEXT,
                report,
                title="最终研究报告",
            )
            return report

    async def _call(self, state: DeepResearchState, stage: str, prompt: str, *, agent_id: str) -> str:
        # report.section.id 用于 Eval MVP v2 的 LLM 阶段归因；保留 report.agent.id 兼容旧消费者
        runtime_context = {**state.trace_context(), "report.agent.id": agent_id, "report.section.id": agent_id}
        response = await model_handler.get_chat_client(state.research_id).run_agent(
            ResearchAgentRequest.text_only(
                stage,
                "",
                [ResearchMessage.user(prompt)],
                runtime_context,
            ),
        )
        state.add_token_usage(response.token_usage)
        return response.ai_message.text

    async def _write_plan(self, state: DeepResearchState, sections: list[ReportSectionSpec]) -> None:
        await self._write_json_node(
            state,
            "plan.json",
            ContextNodeType.REPORT_PLAN,
            {"sections": [item.model_dump() for item in sections]},
            title="报告章节规划",
        )

    async def _write_json_node(
        self,
        state: DeepResearchState,
        name: str,
        node_type: ContextNodeType,
        payload: dict[str, Any],
        *,
        title: str,
    ) -> None:
        await self._write_text_node(
            state,
            name,
            node_type,
            json.dumps(payload, ensure_ascii=False),
            title=title,
        )

    async def _write_text_node(
        self,
        state: DeepResearchState,
        name: str,
        node_type: ContextNodeType,
        content: str,
        *,
        title: str,
    ) -> None:
        # 兜底截断：content 列为 MEDIUMTEXT(16MB)，按 utf8mb4 最坏 4 字节/字符
        # 留余量截到 300 万字符，正常章节 draft 远低于此，仅在病态超长时触发
        report_root = ResearchContextPath.report(state.research_id, "workspace")
        path = report_root.child(name)
        await self.store.put_node(
            ResearchContextNodeData(
                research_id=state.research_id,
                path=path.raw,
                node_type=node_type,
                level=ContextLevel.DERIVED,
                title=title,
                content=truncate(content, 3_000_000),
                parent_path=report_root.raw,
                round_no=state.dynamic_round_no,
                metadata={"reportAgentTeam": True},
            ),
        )

    async def _publish(self, state: DeepResearchState, title: str, payload: dict[str, Any]) -> None:
        await event_publisher.publish_event(
            state.research_id,
            EventType.AGENT_RUNTIME,
            title,
            json.dumps(payload, ensure_ascii=False),
        )

    def _parse_claims(self, section_id: str, raw: Any) -> list[SharedReportClaim]:
        claims: list[SharedReportClaim] = []
        for index, item in enumerate(raw or []):
            if isinstance(item, str):
                item = {"claim": item}
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("claim") or "").strip()
            if not claim_text:
                continue
            confidence = item.get("confidence", 0.5)
            try:
                confidence = max(0.0, min(1.0, float(confidence)))
            except (TypeError, ValueError):
                confidence = 0.5
            claim_id = f"claim-{self._digest(f'{section_id}|{index}|{claim_text}') }"
            claims.append(
                SharedReportClaim(
                    claim_id=claim_id,
                    section_id=section_id,
                    claim=claim_text,
                    source_paths=self._string_list(item.get("sourcePaths")),
                    source_urls=self._string_list(item.get("sourceUrls")),
                    confidence=confidence,
                ),
            )
        return claims[:20]

    @staticmethod
    def _source_url(node: Any) -> str:
        try:
            metadata = json.loads(node.metadata_json or "{}")
        except Exception:
            metadata = {}
        return str(metadata.get("sourceUrl") or metadata.get("url") or "unknown")

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _slug(value: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
        return slug[:48]

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]


report_section_team = ReportSectionTeam()
