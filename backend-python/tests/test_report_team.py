from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.application.report_team import ReportSectionTeam
from app.application.workflow_template import report_section_team_enabled
from app.core.constants import WorkflowMode, WorkflowStatus
from app.domain.context import ContextNodeType
from app.domain.runtime import ResearchMessage
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel


def _state() -> DeepResearchState:
    return DeepResearchState(
        research_id="research-report-team",
        chat_history=[ResearchMessage.user("研究 AI 市场")],
        status=WorkflowStatus.IN_REPORT,
        workflow_mode=WorkflowMode.ULTRA_DYNAMIC,
        dynamic_round_no=2,
        trace_metadata_model=TraceMetadataModel(
            research_id="research-report-team",
            user_id=7,
            model_id="model-1",
            budget_level="ULTRA",
            agent_framework="agentscope-python",
        ),
        research_brief="研究 AI 市场的规模、风险与行动建议",
        budget=BudgetSnapshot(max_conduct_count=6, max_search_count=4, max_concurrent_units=3),
        budget_name="ULTRA",
    )


class FakeStore:
    def __init__(self) -> None:
        self.written = []
        parent = "research://research-report-team/branches/branch-001/sources/src-ai"
        metadata = json.dumps({"url": "https://example.com/ai"}, ensure_ascii=False)
        self.nodes = [
            SimpleNamespace(
                path=parent + "/abstract.md",
                parent_path=parent,
                node_type="source_abstract",
                level="L0",
                title="AI 市场规模",
                content="AI 市场增长摘要",
                metadata_json=metadata,
            ),
            SimpleNamespace(
                path=parent + "/overview.md",
                parent_path=parent,
                node_type="source_overview",
                level="L1",
                title="AI 市场规模",
                content="2026 年 AI 市场数据、风险与建议概览",
                metadata_json=metadata,
            ),
            SimpleNamespace(
                path="research://research-report-team/branches/branch-001/evidence/evidence-001.json",
                parent_path="research://research-report-team/branches/branch-001",
                node_type="evidence",
                level="derived",
                title="AI 市场增长",
                content='{"claim":"AI 市场增长","evidence_text":"2026 年数据"}',
                metadata_json=json.dumps({"sourceUrl": "https://example.com/ai", "strength": "high"}),
            ),
        ]

    async def list_nodes(self, _research_id, node_types=None):
        return [node for node in self.nodes if not node_types or node.node_type in node_types]

    async def read_raw_for_parent(self, _research_id, parent_path, max_chars):
        return ("这是包含精确数字与时间的 L2 原文。" * 20)[:max_chars]

    async def put_node(self, node):
        self.written.append(node)


@pytest.mark.asyncio
async def test_report_section_team_uses_l2_communication_revision_and_merge(monkeypatch) -> None:
    store = FakeStore()
    team = ReportSectionTeam(store)
    stages: list[str] = []

    class FakeClient:
        async def run_agent(self, request):
            stages.append(request.stage_name)
            if request.stage_name == "ReportSectionPlanner":
                text = json.dumps(
                    {
                        "sections": [
                            {"sectionId": "findings", "title": "核心结论", "objective": "总结市场数据"},
                            {"sectionId": "risks", "title": "风险", "objective": "识别冲突与不确定性"},
                            {"sectionId": "actions", "title": "建议", "objective": "提出有证据的行动"},
                        ],
                    },
                    ensure_ascii=False,
                )
            elif request.stage_name.startswith("ReportSectionAgent:"):
                section_id = request.stage_name.split(":", 1)[1]
                text = json.dumps(
                    {
                        "draftMarkdown": f"## {section_id}\n\n初稿 [来源](https://example.com/ai)",
                        "claims": [
                            {
                                "claim": f"{section_id} 的共享结论",
                                "sourcePaths": [
                                    "research://research-report-team/branches/branch-001/sources/src-ai/raw.txt",
                                ],
                                "sourceUrls": ["https://example.com/ai"],
                                "confidence": 0.8,
                            },
                        ],
                        "requests": (
                            [{"targetSection": "risks", "question": "请核实增长结论的风险边界。"}]
                            if section_id == "findings"
                            else []
                        ),
                    },
                    ensure_ascii=False,
                )
            elif request.stage_name == "ReportConsistencyAgent":
                text = json.dumps(
                    {
                        "messages": [
                            {
                                "fromAgent": "findings",
                                "toAgent": "risks",
                                "type": "section_dependency",
                                "subject": "引用市场结论",
                                "instruction": "将 findings 的增长结论作为风险边界的前提。",
                            },
                        ],
                    },
                    ensure_ascii=False,
                )
            elif request.stage_name.startswith("ReportSectionReviser:"):
                text = f"## {request.stage_name.split(':', 1)[1]}\n\n已根据共享声明修订。"
            else:
                assert request.stage_name == "ReportAgent:merge"
                text = "# 最终报告\n\n已完成逻辑合并。"
            return SimpleNamespace(token_usage=None, ai_message=SimpleNamespace(text=text))

    async def publish_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.report_team.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.report_team.event_publisher.publish_event", publish_event)

    report = await team.run(_state(), "报告需标注不确定性")

    assert report.startswith("# 最终报告")
    assert stages.count("ReportSectionPlanner") == 1
    assert len([stage for stage in stages if stage.startswith("ReportSectionAgent:")]) == 3
    assert len([stage for stage in stages if stage.startswith("ReportSectionReviser:")]) == 3
    assert "ReportConsistencyAgent" in stages
    assert stages[-1] == "ReportAgent:merge"
    assert any(node.node_type == ContextNodeType.REPORT_AGENT_MESSAGE for node in store.written)
    mailbox_payloads = [
        json.loads(node.content)
        for node in store.written
        if node.node_type == ContextNodeType.REPORT_AGENT_MESSAGE
    ]
    assert any(item["message_type"] == "evidence_request" for item in mailbox_payloads)
    assert any(node.node_type == ContextNodeType.REPORT_SECTION_REVISION for node in store.written)
    assert any("/raw.txt" in node.content for node in store.written if node.node_type == ContextNodeType.REPORT_SECTION_EVIDENCE)
    assert store.written[-1].path.endswith("/report/workspace/final.md")


def test_report_section_team_requires_explicit_template_switch() -> None:
    assert report_section_team_enabled(None) is False
    assert report_section_team_enabled({"report": {"sectionTeamEnabled": True}}) is True
