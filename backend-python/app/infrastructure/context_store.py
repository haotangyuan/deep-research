from __future__ import annotations

import json
import re
from collections.abc import Iterable

from sqlalchemy import select

from app.core.timeutil import now_local
from app.domain.context import ResearchContextNodeData, estimate_tokens
from app.domain.models import ResearchContextEdge, ResearchContextNode
from app.infrastructure.db import SessionLocal


ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]+")
CHINESE_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")
CONTEXT_TITLE_MAX_CHARS = 512


def normalize_context_title(title: str | None) -> str | None:
    return title[:CONTEXT_TITLE_MAX_CHARS] if title else title


def normalize_query_terms(text: str) -> set[str]:
    terms = {match.group(0).lower() for match in ASCII_WORD_RE.finditer(text or "")}
    for run_match in CHINESE_RUN_RE.finditer(text or ""):
        run = run_match.group(0)
        if len(run) <= 2:
            terms.add(run)
            continue
        terms.update(run[index : index + 2] for index in range(len(run) - 1))
    return terms


def score_context_text(
    *,
    query_terms: set[str],
    title: str | None,
    content: str | None,
    section_hint: str | None,
    source_strength: str | None,
) -> float:
    hay_title = (title or "").lower()
    hay_content = (content or "").lower()
    hay_section = (section_hint or "").lower()
    score = 0.0
    for term in query_terms:
        if term in hay_title:
            score += 1.5
        if term in hay_section:
            score += 1.0
        if term in hay_content:
            score += 0.5
    if source_strength == "high":
        score += 0.5
    elif source_strength == "medium":
        score += 0.2
    return score


class ResearchContextStore:
    async def put_node(self, node: ResearchContextNodeData) -> None:
        async with SessionLocal() as session:
            existing = await session.scalar(select(ResearchContextNode).where(ResearchContextNode.path == node.path))
            metadata_json = json.dumps(node.metadata, ensure_ascii=False)
            now = now_local()
            if existing is None:
                existing = ResearchContextNode(
                    research_id=node.research_id,
                    path=node.path,
                    node_type=node.node_type.value,
                    level=node.level.value,
                    create_time=now,
                )
                session.add(existing)
            existing.title = normalize_context_title(node.title)
            existing.content = node.content
            existing.content_ref = node.content_ref
            existing.parent_path = node.parent_path
            existing.branch_index = node.branch_index
            existing.round_no = node.round_no
            existing.token_estimate = estimate_tokens(node.content)
            existing.char_count = len(node.content or "")
            existing.metadata_json = metadata_json
            existing.status = node.status
            existing.update_time = now
            await session.commit()

    async def put_nodes(self, nodes: Iterable[ResearchContextNodeData]) -> None:
        for node in nodes:
            await self.put_node(node)

    async def link(
        self,
        research_id: str,
        from_path: str,
        to_path: str,
        relation_type: str,
        metadata: dict | None = None,
    ) -> None:
        async with SessionLocal() as session:
            session.add(
                ResearchContextEdge(
                    research_id=research_id,
                    from_path=from_path,
                    to_path=to_path,
                    relation_type=relation_type,
                    metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
                    create_time=now_local(),
                )
            )
            await session.commit()

    async def list_nodes(self, research_id: str, node_types: list[str] | None = None) -> list[ResearchContextNode]:
        async with SessionLocal() as session:
            stmt = select(ResearchContextNode).where(
                ResearchContextNode.research_id == research_id,
                ResearchContextNode.status == "ready",
            )
            if node_types:
                stmt = stmt.where(ResearchContextNode.node_type.in_(node_types))
            result = await session.scalars(stmt)
            return list(result)

    async def list_nodes_by_prefix(
        self,
        research_id: str,
        path_prefix: str,
        node_types: list[str] | None = None,
    ) -> list[ResearchContextNode]:
        async with SessionLocal() as session:
            stmt = select(ResearchContextNode).where(
                ResearchContextNode.research_id == research_id,
                ResearchContextNode.path.startswith(path_prefix),
                ResearchContextNode.status == "ready",
            )
            if node_types:
                stmt = stmt.where(ResearchContextNode.node_type.in_(node_types))
            result = await session.scalars(stmt)
            return list(result)

    async def read_raw_for_parent(self, research_id: str, parent_path: str, max_chars: int) -> str | None:
        async with SessionLocal() as session:
            node = await session.scalar(
                select(ResearchContextNode).where(
                    ResearchContextNode.research_id == research_id,
                    ResearchContextNode.parent_path == parent_path,
                    ResearchContextNode.node_type == "source_raw",
                    ResearchContextNode.status == "ready",
                )
            )
            if node is None or not node.content:
                return None
            return node.content[:max_chars]
