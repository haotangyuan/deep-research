from __future__ import annotations

from app.application.agents import researcher_agent
from app.core.constants import WorkflowStatus
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel


def _state() -> DeepResearchState:
    return DeepResearchState(
        research_id="research-1",
        chat_history=[],
        status=WorkflowStatus.IN_RESEARCH,
        trace_metadata_model=TraceMetadataModel(
            research_id="research-1",
            user_id=1,
            model_id="model-1",
            budget_level="ULTRA",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=1, max_search_count=1, max_concurrent_units=1),
        budget_name="ULTRA",
        research_topic="AI 搜索市场",
    )


def test_parse_evidence_package_extracts_findings_sources_and_items() -> None:
    text = """
{
  "branchSummary": "市场增长，但商业化仍早期。",
  "findings": "AI 搜索市场增长。[1]",
  "evidenceItems": [
    {
      "claim": "AI 搜索市场增长",
      "evidenceText": "多家报告提到用户使用增加",
      "sourceUrl": "https://example.com/report",
      "sourceTitle": "Report",
      "sourceType": "report",
      "strength": "high",
      "sectionHint": "市场规模",
      "confidence": 0.8
    }
  ],
  "sources": [
    {"url": "https://example.com/report", "title": "Report", "type": "report", "strength": "high", "snippet": "用户使用增加", "sectionHint": "市场规模"}
  ],
  "gaps": ["缺少官方统计"],
  "conflicts": []
}
"""
    findings, sources, package = researcher_agent._parse_evidence_package(text, _state(), branch_index=0)

    assert "市场增长" in findings
    assert sources[0].url == "https://example.com/report"
    assert package.evidence_items[0].claim == "AI 搜索市场增长"
    assert package.gaps == ["缺少官方统计"]
