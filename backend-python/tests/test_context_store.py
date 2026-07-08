from __future__ import annotations

from app.domain.context import ContextLevel, ContextNodeType, ResearchContextNodeData
from app.infrastructure.context_store import normalize_query_terms, score_context_text


def test_normalize_query_terms_keeps_chinese_and_ascii_terms() -> None:
    assert normalize_query_terms("AI 搜索 market-size 2026") == {"ai", "搜索", "market", "size", "2026"}


def test_score_context_text_rewards_title_and_section_hint() -> None:
    score = score_context_text(
        query_terms={"市场", "规模"},
        title="AI 搜索市场规模",
        content="报告提到行业收入和用户规模。",
        section_hint="市场规模",
        source_strength="high",
    )

    assert score > 1.0


def test_context_node_data_uses_ready_status() -> None:
    node = ResearchContextNodeData(
        research_id="research-1",
        path="research://research-1/brief/question.md",
        node_type=ContextNodeType.BRIEF,
        level=ContextLevel.L1,
        content="question",
    )

    assert node.status == "ready"
