from __future__ import annotations

from app.application.context_writer import branch_index_from_task_id, build_source_context_nodes
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


def test_branch_index_is_unique_across_dynamic_rounds() -> None:
    research_id = "research-1"

    assert branch_index_from_task_id(f"{research_id}-round-1-task-0") == 0
    assert branch_index_from_task_id(f"{research_id}-round-1-task-5") == 5
    assert branch_index_from_task_id(f"{research_id}-round-2-task-0") == 1000
    assert branch_index_from_task_id(f"{research_id}-round-3-task-2") == 2002
    assert branch_index_from_task_id(f"{research_id}-task-4") == 4
