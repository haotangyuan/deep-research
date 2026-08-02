"""Eval MVP v2 Commit 4 — HIGH/ULTRA 报告 Artifact 持久化测试。

验证 `_draft_by_angle` / `_lightweight_high_report` / `_draft_section` /
`_revise_section` / `_merge_sections` 在 `state.run_id` 存在时，
会通过 `eval_repository.upsert_artifact` 写入对应 artifact_type；且
`safe_record` 吞异常不会让研究失败。

遵循 CLAUDE.md「不 mock MySQL/Redis」的精神，但此处验证的是「调用契约」
（artifact_type/stage_name/section_id/angle 维度正确），故 monkeypatch
`eval_repository.upsert_artifact` 为记录器，避免真连 DB（与既有
test_report_team.py 同档：FakeClient + FakeStore）。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.application.agents import ReportAgent
from app.application.report_team import ReportSectionTeam
from app.core.constants import WorkflowMode, WorkflowStatus
from app.domain.runtime import ResearchMessage
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel


def _state(*, run_id: str | None = "run-commit4") -> DeepResearchState:
    s = DeepResearchState(
        research_id="research-commit4",
        chat_history=[ResearchMessage.user("研究 AI 市场")],
        status=WorkflowStatus.IN_REPORT,
        workflow_mode=WorkflowMode.ULTRA_DYNAMIC,
        dynamic_round_no=2,
        trace_metadata_model=TraceMetadataModel(
            research_id="research-commit4",
            user_id=7,
            model_id="model-1",
            budget_level="ULTRA",
            agent_framework="agentscope-python",
        ),
        research_brief="研究 AI 市场的规模、风险与行动建议",
        budget=BudgetSnapshot(max_conduct_count=6, max_search_count=4, max_concurrent_units=3),
        budget_name="ULTRA",
    )
    s.run_id = run_id
    return s


class _Store:
    """最小 context store，复用 test_report_team 的节点结构。"""

    def __init__(self) -> None:
        self.written: list = []
        parent = "research://research-commit4/branches/branch-001/sources/src-ai"
        metadata = json.dumps({"url": "https://example.com/ai"}, ensure_ascii=False)
        self.nodes = [
            SimpleNamespace(
                path=parent + "/overview.md",
                parent_path=parent,
                node_type="source_overview",
                level="L1",
                title="AI 市场规模",
                content="2026 年 AI 市场数据、风险与建议概览",
                metadata_json=metadata,
            ),
        ]

    async def list_nodes(self, _research_id, node_types=None):
        return [n for n in self.nodes if not node_types or n.node_type in node_types]

    async def read_raw_for_parent(self, _research_id, _parent, max_chars):
        return "包含精确数字的 L2 原文。" * 20

    async def put_node(self, node):
        self.written.append(node)


class _Artifacts:
    """记录所有 upsert_artifact 调用的 (artifact_type, 维度) 快照。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def upsert_artifact(self, **kwargs):
        self.calls.append(kwargs)
        return "artifact-id"

    async def write_claim_manifest(self, *args, **kwargs):
        return 0

    async def replace_claim_manifest(self, *args, **kwargs):
        return 0

    async def load_source_catalog(self, _run_id):
        return []


async def _noop_event(*_args, **_kwargs) -> int:
    return 1


@pytest.mark.asyncio
async def test_ultra_section_team_persists_draft_revision_merge_artifacts(monkeypatch) -> None:
    store = _Store()
    team = ReportSectionTeam(store)
    recorded = _Artifacts()
    monkeypatch.setattr(
        "app.infrastructure.eval_repository.eval_repository.upsert_artifact",
        recorded.upsert_artifact,
    )

    class FakeClient:
        async def run_agent(self, request):
            if request.stage_name == "ReportSectionPlanner":
                text = json.dumps(
                    {
                        "sections": [
                            {"sectionId": "findings", "title": "核心结论", "objective": "总结"},
                            {"sectionId": "risks", "title": "风险", "objective": "识别风险"},
                            {"sectionId": "actions", "title": "建议", "objective": "提出行动"},
                        ]
                    },
                    ensure_ascii=False,
                )
            elif request.stage_name.startswith("ReportSectionAgent:"):
                sid = request.stage_name.split(":", 1)[1]
                text = json.dumps(
                    {
                        "draftMarkdown": f"## {sid}\n初稿 [来源](https://example.com/ai)",
                        "claims": [],
                        "requests": [],
                    },
                    ensure_ascii=False,
                )
            elif request.stage_name == "ReportConsistencyAgent":
                text = json.dumps({"messages": []}, ensure_ascii=False)
            elif request.stage_name.startswith("ReportSectionReviser:"):
                sid = request.stage_name.split(":", 1)[1]
                text = f"## {sid}\n已修订。"
            else:
                assert request.stage_name == "ReportAgent:merge"
                text = "# 最终报告\n已完成合并。"
            return SimpleNamespace(token_usage=None, ai_message=SimpleNamespace(text=text))

    monkeypatch.setattr("app.application.report_team.model_handler.get_chat_client", lambda _rid: FakeClient())

    async def _noop_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.report_team.event_publisher.publish_event", _noop_event)

    report = await team.run(_state(), "报告需标注不确定性")
    assert report.startswith("# 最终报告")

    types = sorted(c["artifact_type"] for c in recorded.calls)
    # 3 个 section_draft + 3 个 section_revision + 1 个 report_merged
    assert types.count("report_section_draft") == 3
    assert types.count("report_section_revision") == 3
    assert types.count("report_merged") == 1
    # section_id 维度正确
    drafts = [c for c in recorded.calls if c["artifact_type"] == "report_section_draft"]
    assert {d["section_id"] for d in drafts} == {"findings", "risks", "actions"}
    assert all(d["stage_name"].startswith("ReportSectionAgent:") for d in drafts)
    merged = [c for c in recorded.calls if c["artifact_type"] == "report_merged"][0]
    assert merged["stage_name"] == "ReportAgent:merge"


@pytest.mark.asyncio
async def test_no_run_id_skips_persistence(monkeypatch) -> None:
    """run_id=None 时不应调用 upsert_artifact（ad-hoc 调用不落库）。"""
    store = _Store()
    team = ReportSectionTeam(store)
    recorded = _Artifacts()
    monkeypatch.setattr(
        "app.infrastructure.eval_repository.eval_repository.upsert_artifact",
        recorded.upsert_artifact,
    )

    class FakeClient:
        async def run_agent(self, request):
            if request.stage_name == "ReportSectionPlanner":
                text = json.dumps(
                    {"sections": [{"sectionId": "a", "title": "A", "objective": "o"}]},
                    ensure_ascii=False,
                )
            elif request.stage_name.startswith("ReportSectionAgent:"):
                text = json.dumps({"draftMarkdown": "draft", "claims": [], "requests": []}, ensure_ascii=False)
            elif request.stage_name == "ReportConsistencyAgent":
                text = json.dumps({"messages": []}, ensure_ascii=False)
            elif request.stage_name.startswith("ReportSectionReviser:"):
                text = "revised"
            else:
                text = "# merged"
            return SimpleNamespace(token_usage=None, ai_message=SimpleNamespace(text=text))

    monkeypatch.setattr("app.application.report_team.model_handler.get_chat_client", lambda _rid: FakeClient())
    monkeypatch.setattr("app.application.report_team.event_publisher.publish_event", _noop_event)

    await team.run(_state(run_id=None), "ctx")
    assert recorded.calls == []


@pytest.mark.asyncio
async def test_safe_record_isolates_failure(monkeypatch) -> None:
    """upsert_artifact 抛错时，报告流程仍正常完成（safe_record 吞异常）。"""

    async def boom(**kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.infrastructure.eval_repository.eval_repository.upsert_artifact", boom)
    store = _Store()
    team = ReportSectionTeam(store)

    class FakeClient:
        async def run_agent(self, request):
            if request.stage_name == "ReportSectionPlanner":
                text = json.dumps(
                    {"sections": [{"sectionId": "a", "title": "A", "objective": "o"}]},
                    ensure_ascii=False,
                )
            elif request.stage_name.startswith("ReportSectionAgent:"):
                text = json.dumps({"draftMarkdown": "draft", "claims": [], "requests": []}, ensure_ascii=False)
            elif request.stage_name == "ReportConsistencyAgent":
                text = json.dumps({"messages": []}, ensure_ascii=False)
            elif request.stage_name.startswith("ReportSectionReviser:"):
                text = "revised"
            else:
                text = "# merged"
            return SimpleNamespace(token_usage=None, ai_message=SimpleNamespace(text=text))

    monkeypatch.setattr("app.application.report_team.model_handler.get_chat_client", lambda _rid: FakeClient())
    monkeypatch.setattr("app.application.report_team.event_publisher.publish_event", _noop_event)

    report = await team.run(_state(), "ctx")
    assert report.startswith("# merged")  # 抛错被吞，流程不受影响


@pytest.mark.asyncio
async def test_high_dual_draft_and_synthesis_persist(monkeypatch) -> None:
    """HIGH 路径：_draft_by_angle(comparative/data-driven) + _lightweight_high_report synthesis 落库。"""
    from app.application.agents import ReportAgent

    recorded = _Artifacts()
    monkeypatch.setattr(
        "app.infrastructure.eval_repository.eval_repository.upsert_artifact",
        recorded.upsert_artifact,
    )

    class FakeClient:
        async def run_agent(self, request):
            if request.stage_name.startswith("ReportAgent:"):
                # comparative / data-driven draft 与 high-synthesis 共用此分支
                text = f"draft for {request.stage_name}"
            else:
                text = "synthesis"
            return SimpleNamespace(token_usage=None, ai_message=SimpleNamespace(text=text))

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _rid: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", _noop_event)

    state = _state()
    state.budget_name = "HIGH"
    state.supervisor_notes = ["## 研究任务\n\nAI 市场数据点"]
    agent = ReportAgent()
    report = await agent._lightweight_high_report(state)
    assert "synthesis" in report

    drafts = [c for c in recorded.calls if c["artifact_type"] == "report_draft"]
    assert sorted(d["angle"] for d in drafts) == ["comparative", "data-driven"]
    assert all(d["stage_name"].startswith("ReportAgent:") for d in drafts)
    syn = [c for c in recorded.calls if c["artifact_type"] == "report_synthesis"]
    assert len(syn) == 1
    assert syn[0]["stage_name"] == "ReportAgent:high-synthesis"
    assert syn[0]["outcome"] == "success"
