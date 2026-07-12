from __future__ import annotations

from types import SimpleNamespace

from app.application.context_retrieval import build_typed_queries_for_sections, rank_nodes_for_query, select_budgeted_nodes
from app.domain.context import ContextNodeType, TypedQuery


def test_build_typed_queries_for_sections_creates_section_queries() -> None:
    queries = build_typed_queries_for_sections(
        research_brief="研究 AI 搜索市场格局和监管风险",
        sections=["市场格局", "监管风险"],
    )

    assert [query.section_hint for query in queries] == ["市场格局", "监管风险"]
    assert all(query.priority >= 3 for query in queries)


def test_rank_nodes_prefers_matching_evidence() -> None:
    query = TypedQuery(
        query="监管 风险 官方",
        intent="查找监管风险",
        context_type=ContextNodeType.EVIDENCE,
        priority=5,
        section_hint="监管风险",
    )
    nodes = [
        SimpleNamespace(
            title="市场规模",
            content="用户增长",
            metadata_json='{"sectionHint":"市场格局","strength":"medium"}',
            path="a",
            node_type="evidence",
            level="derived",
        ),
        SimpleNamespace(
            title="监管风险",
            content="官方新规",
            metadata_json='{"sectionHint":"监管风险","strength":"high"}',
            path="b",
            node_type="evidence",
            level="derived",
        ),
    ]

    ranked = rank_nodes_for_query(query, nodes)

    assert ranked[0].path == "b"


def test_select_budgeted_nodes_drops_over_budget_items() -> None:
    items = [
        SimpleNamespace(path="a", content="a" * 10, score=2.0),
        SimpleNamespace(path="b", content="b" * 100, score=1.0),
    ]

    selected, dropped = select_budgeted_nodes(items, max_chars=20)

    assert [item.path for item in selected] == ["a"]
    assert dropped[0]["path"] == "b"
