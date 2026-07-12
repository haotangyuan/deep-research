from __future__ import annotations

from app.application.context_writer import build_branch_package_nodes
from app.domain.context import BranchEvidencePackage, EvidenceItem


def test_build_branch_package_nodes_writes_summary_and_evidence() -> None:
    package = BranchEvidencePackage(
        branch_index=1,
        task_title="政策监管",
        research_topic="AI 搜索监管",
        branch_summary="官方政策正在形成。",
        evidence_items=[
            EvidenceItem(
                claim="监管趋严",
                evidence_text="官方发布新规。",
                source_url="https://www.gov.cn/policy",
                source_type="official",
                strength="high",
                section_hint="监管风险",
                confidence=0.9,
            )
        ],
    )

    nodes = build_branch_package_nodes("research-1", round_no=1, package=package)

    assert nodes[0].node_type == "branch_summary"
    assert nodes[1].node_type == "evidence"
    assert "监管趋严" in nodes[1].content
