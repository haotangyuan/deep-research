from __future__ import annotations

import json
import re

from app.core.config import get_settings
from app.core.json_utils import truncate
from app.domain.context import (
    BranchEvidencePackage,
    ContextLevel,
    ContextNodeType,
    ResearchContextNodeData,
    ResearchContextPath,
    stable_source_key,
)
from app.domain.state import TavilySearchResult
from app.infrastructure.context_store import ResearchContextStore


def build_source_context_nodes(
    *,
    research_id: str,
    branch_index: int,
    round_no: int | None,
    source: TavilySearchResult,
) -> list[ResearchContextNodeData]:
    settings = get_settings()
    url = (source.url or "").strip()
    source_key = stable_source_key(url or source.title or "")
    base = ResearchContextPath.source(research_id, branch_index, source_key)
    title = source.title or url or source_key
    summary_text = source.content or source.raw_content or ""
    raw_text = source.raw_content or source.content or ""
    metadata = {"url": url, "score": source.score}

    return [
        ResearchContextNodeData(
            research_id=research_id,
            path=base.child("abstract.md").raw,
            node_type=ContextNodeType.SOURCE_ABSTRACT,
            level=ContextLevel.L0,
            title=title,
            content=truncate(f"{title}\n{summary_text}", settings.research_context_l0_max_chars),
            parent_path=base.raw,
            branch_index=branch_index,
            round_no=round_no,
            metadata=metadata,
        ),
        ResearchContextNodeData(
            research_id=research_id,
            path=base.child("overview.md").raw,
            node_type=ContextNodeType.SOURCE_OVERVIEW,
            level=ContextLevel.L1,
            title=title,
            content=truncate(summary_text or raw_text, settings.research_context_l1_max_chars),
            parent_path=base.raw,
            branch_index=branch_index,
            round_no=round_no,
            metadata=metadata,
        ),
        ResearchContextNodeData(
            research_id=research_id,
            path=base.child("raw.txt").raw,
            node_type=ContextNodeType.SOURCE_RAW,
            level=ContextLevel.L2,
            title=title,
            content=truncate(raw_text, settings.research_context_l2_max_chars),
            parent_path=base.raw,
            branch_index=branch_index,
            round_no=round_no,
            metadata=metadata,
        ),
    ]


async def write_search_context(
    *,
    store: ResearchContextStore,
    research_id: str,
    branch_index: int,
    round_no: int | None,
    search_results: list[TavilySearchResult],
    state: object | None = None,
) -> int:
    count = 0
    run_id = getattr(state, "run_id", None) if state is not None else None
    for source in search_results:
        await store.put_nodes(
            build_source_context_nodes(
                research_id=research_id,
                branch_index=branch_index,
                round_no=round_no,
                source=source,
            )
        )
        count += 1
        # Eval MVP v2：source_snapshot 落库（截断前的 raw_content，供离线 eval 复盘）
        if run_id:
            from app.infrastructure.eval_repository import eval_repository, safe_record

            raw_text = source.raw_content or source.content or ""
            await safe_record(
                lambda: eval_repository.upsert_artifact(
                    run_id=run_id,
                    research_id=research_id,
                    artifact_type="source_snapshot",
                    stage_name="SearchAgent",
                    round_no=round_no,
                    content=raw_text,
                    metadata={
                        "url": (source.url or "").strip(),
                        "title": source.title,
                        "score": source.score,
                        "task_key": getattr(state, "agent_task_id", None),
                        "branch_index": branch_index,
                    },
                    outcome="success",
                    fallback_used=0,
                ),
                context=f"source_snapshot research_id={research_id}",
            )
    return count


def branch_index_from_task_id(task_id: str | None) -> int:
    match = re.search(r"-round-(\d+)-task-(\d+)$", task_id or "")
    if match:
        round_no = max(1, int(match.group(1)))
        task_index = int(match.group(2))
        # Keep the existing numeric branch path format while reserving a
        # collision-free range for each dynamic round.
        return (round_no - 1) * 1000 + task_index
    suffix = (task_id or "").rsplit("-", 1)[-1]
    return int(suffix) if suffix.isdigit() else 0


def build_branch_package_nodes(
    research_id: str,
    *,
    round_no: int | None,
    package: BranchEvidencePackage,
) -> list[ResearchContextNodeData]:
    settings = get_settings()
    branch_path = ResearchContextPath.branch(research_id, package.branch_index)
    nodes = [
        ResearchContextNodeData(
            research_id=research_id,
            path=branch_path.child("summary.md").raw,
            node_type=ContextNodeType.BRANCH_SUMMARY,
            level=ContextLevel.L1,
            title=package.task_title,
            content=truncate(package.branch_summary, settings.research_context_l1_max_chars),
            parent_path=branch_path.raw,
            branch_index=package.branch_index,
            round_no=round_no,
            metadata={"gaps": package.gaps, "conflicts": package.conflicts},
        )
    ]
    for index, item in enumerate(package.evidence_items, start=1):
        nodes.append(
            ResearchContextNodeData(
                research_id=research_id,
                path=branch_path.child(f"evidence/evidence-{index:03d}.json").raw,
                node_type=ContextNodeType.EVIDENCE,
                level=ContextLevel.DERIVED,
                title=item.claim,
                content=json.dumps(item.model_dump(), ensure_ascii=False),
                parent_path=branch_path.raw,
                branch_index=package.branch_index,
                round_no=round_no,
                metadata={
                    "sectionHint": item.section_hint,
                    "sourceUrl": item.source_url,
                    "strength": item.strength,
                    "confidence": item.confidence,
                },
            )
        )
    return nodes


async def write_branch_package_context(
    *,
    store: ResearchContextStore,
    research_id: str,
    round_no: int | None,
    package: BranchEvidencePackage,
    state: object | None = None,
) -> int:
    nodes = build_branch_package_nodes(research_id, round_no=round_no, package=package)
    await store.put_nodes(nodes)
    run_id = getattr(state, "run_id", None) if state is not None else None
    if run_id and package.evidence_items:
        from app.infrastructure.eval_repository import eval_repository, safe_record

        for item in package.evidence_items:
            content = json.dumps(item.model_dump(), ensure_ascii=False)
            await safe_record(
                lambda: eval_repository.upsert_artifact(
                    run_id=run_id,
                    research_id=research_id,
                    artifact_type="evidence_item",
                    stage_name="ResearcherAgent",
                    round_no=round_no,
                    section_id=item.section_hint,
                    content=content,
                    metadata={
                        "task_key": package.task_key,
                        "branch_index": package.branch_index,
                        "task_title": package.task_title,
                        "research_topic": package.research_topic,
                        "source_url": item.source_url,
                        "source_type": item.source_type,
                        "strength": item.strength,
                        "confidence": item.confidence,
                    },
                    outcome="success",
                    fallback_used=0,
                ),
                context=f"evidence_item research_id={research_id}",
            )
    return len(nodes)
