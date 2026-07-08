from __future__ import annotations

from app.application.context_retrieval import (
    build_typed_queries_for_sections,
    rank_nodes_for_query,
    select_budgeted_nodes,
    to_selected_context_item,
)
from app.domain.context import ContextNodeType, ReportContext, estimate_tokens
from app.infrastructure.context_store import ResearchContextStore


DEFAULT_REPORT_SECTIONS = ["核心结论", "背景与现状", "关键证据", "风险与不确定性", "建议与后续方向"]


class ReportContextBuilder:
    def __init__(self, store: ResearchContextStore | None = None) -> None:
        self.store = store or ResearchContextStore()

    async def build(
        self,
        *,
        research_id: str,
        research_brief: str,
        sections: list[str] | None = None,
    ) -> ReportContext:
        from app.core.config import get_settings

        settings = get_settings()
        section_names = sections or DEFAULT_REPORT_SECTIONS
        queries = build_typed_queries_for_sections(research_brief, section_names)
        nodes = await self.store.list_nodes(
            research_id,
            node_types=[
                ContextNodeType.EVIDENCE.value,
                ContextNodeType.BRANCH_SUMMARY.value,
                ContextNodeType.SOURCE_ABSTRACT.value,
                ContextNodeType.SOURCE_OVERVIEW.value,
            ],
        )
        section_contexts = {}
        dropped = []
        for query in queries:
            ranked = rank_nodes_for_query(query, nodes)
            selected, section_dropped = select_budgeted_nodes(ranked, settings.research_context_section_max_chars)
            section_contexts[query.section_hint or query.intent] = [
                to_selected_context_item(node, reason=query.intent) for node in selected
            ]
            dropped.extend(section_dropped)
            if should_expand_raw(
                query.section_hint or "",
                len(selected),
                needs_numbers=any(key in query.query for key in ["规模", "数字", "比例", "时间"]),
            ):
                dropped.append({"section": query.section_hint, "reason": "raw_expansion_deferred_to_later_phase"})
        context = ReportContext(
            research_id=research_id,
            research_brief=research_brief,
            section_contexts=section_contexts,
            dropped=dropped,
        )
        enforce_report_context_budget(context, settings.research_context_report_max_chars)
        context.total_estimated_tokens = estimate_tokens(render_report_context(context))
        return context


def render_report_context(context: ReportContext) -> str:
    parts = ["# Report Context", "", f"Research ID: {context.research_id}", "", "## Research Brief", context.research_brief]
    for section, items in context.section_contexts.items():
        parts.extend(["", f"## {section}"])
        if not items:
            parts.append("No selected context.")
            continue
        for index, item in enumerate(items, start=1):
            parts.extend(
                [
                    "",
                    f"### Evidence {index}: {item.title or item.path}",
                    f"- Path: {item.path}",
                    f"- Type: {item.node_type.value}",
                    f"- Level: {item.level.value}",
                    f"- Source: {item.source_url or 'unknown'}",
                    f"- Score: {item.score:.2f}",
                    "",
                    item.content,
                ]
            )
    return "\n".join(parts)


def should_expand_raw(section: str, selected_count: int, needs_numbers: bool) -> bool:
    if selected_count == 0:
        return True
    if needs_numbers and selected_count < 3:
        return True
    if any(key in section for key in ["数字", "规模", "时间线", "引用", "证据"]) and selected_count < 2:
        return True
    return False


def has_selected_context(context: ReportContext) -> bool:
    return any(items for items in context.section_contexts.values())


def enforce_report_context_budget(context: ReportContext, max_chars: int) -> None:
    used = len(context.research_brief or "")
    for section, items in list(context.section_contexts.items()):
        kept = []
        for item in items:
            size = len(item.path or "") + len(item.content or "") + len(item.title or "") + len(item.source_url or "")
            if used + size <= max_chars:
                kept.append(item)
                used += size
                continue
            context.dropped.append({"path": item.path, "section": section, "reason": "report_budget_exceeded", "chars": size})
        context.section_contexts[section] = kept
