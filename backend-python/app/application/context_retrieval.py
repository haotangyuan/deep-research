from __future__ import annotations

import json
from typing import Any

from app.domain.context import ContextLevel, ContextNodeType, SelectedContextItem, TypedQuery
from app.infrastructure.context_store import normalize_query_terms, score_context_text


def build_typed_queries_for_sections(research_brief: str, sections: list[str]) -> list[TypedQuery]:
    queries: list[TypedQuery] = []
    for section in sections:
        context_type = ContextNodeType.EVIDENCE
        if any(key in section for key in ["背景", "概述", "方案", "技术"]):
            context_type = ContextNodeType.SOURCE_OVERVIEW
        queries.append(
            TypedQuery(
                query=f"{research_brief} {section}",
                intent=f"为报告章节「{section}」检索证据",
                context_type=context_type,
                priority=5 if any(key in section for key in ["结论", "风险", "原因", "方案"]) else 3,
                section_hint=section,
            )
        )
    return queries


def _metadata(node: Any) -> dict[str, Any]:
    raw = getattr(node, "metadata_json", None)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def rank_nodes_for_query(query: TypedQuery, nodes: list[Any]) -> list[Any]:
    terms = normalize_query_terms(f"{query.query} {query.section_hint or ''}")
    ranked: list[Any] = []
    for node in nodes:
        meta = _metadata(node)
        score = score_context_text(
            query_terms=terms,
            title=getattr(node, "title", None),
            content=getattr(node, "content", None),
            section_hint=meta.get("sectionHint") or meta.get("section_hint"),
            source_strength=meta.get("strength") or meta.get("sourceStrength"),
        )
        if getattr(node, "node_type", None) == query.context_type.value:
            score += 0.8
        if score <= 0:
            continue
        setattr(node, "score", score)
        ranked.append(node)
    ranked.sort(key=lambda item: getattr(item, "score", 0.0), reverse=True)
    return ranked


def select_budgeted_nodes(items: list[Any], max_chars: int) -> tuple[list[Any], list[dict[str, Any]]]:
    selected: list[Any] = []
    dropped: list[dict[str, Any]] = []
    used = 0
    for item in items:
        size = len(getattr(item, "content", "") or "")
        if used + size <= max_chars:
            selected.append(item)
            used += size
        else:
            dropped.append({"path": getattr(item, "path", ""), "reason": "budget_exceeded", "chars": size})
    return selected, dropped


def to_selected_context_item(node: Any, reason: str) -> SelectedContextItem:
    meta = _metadata(node)
    return SelectedContextItem(
        path=node.path,
        node_type=ContextNodeType(node.node_type),
        level=ContextLevel(node.level),
        title=node.title,
        content=node.content or "",
        source_url=meta.get("sourceUrl") or meta.get("url"),
        score=float(getattr(node, "score", 0.0)),
        reason=reason,
    )
