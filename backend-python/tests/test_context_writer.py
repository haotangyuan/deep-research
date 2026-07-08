from __future__ import annotations

from app.application.context_writer import build_source_context_nodes
from app.domain.state import TavilySearchResult


def test_build_source_context_nodes_creates_three_layers() -> None:
    nodes = build_source_context_nodes(
        research_id="research-1",
        branch_index=0,
        round_no=1,
        source=TavilySearchResult(
            url="https://example.com/report",
            title="AI Search Report",
            content="short summary",
            raw_content="raw content " * 100,
            score=0.9,
        ),
    )

    assert [node.level for node in nodes] == ["L0", "L1", "L2"]
    assert [node.node_type for node in nodes] == ["source_abstract", "source_overview", "source_raw"]
    assert nodes[0].content.startswith("AI Search Report")
    assert "https://example.com/report" in nodes[1].metadata["url"]
