from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.agents import ResearchResult, ResearchTask, report_agent
from app.application.pipeline import AgentPipeline
from app.core.constants import WorkflowMode, WorkflowStatus
from app.domain.state import BudgetSnapshot, DeepResearchState, TavilySearchResult, TraceMetadataModel


def _make_state(
    *,
    round_no: int = 1,
    max_rounds: int = 3,
    conduct_count: int = 0,
    max_conduct_count: int = 6,
) -> DeepResearchState:
    return DeepResearchState(
        research_id="research-ultra",
        chat_history=[],
        status=WorkflowStatus.IN_RESEARCH,
        workflow_mode=WorkflowMode.ULTRA_DYNAMIC,
        dynamic_round_no=round_no,
        dynamic_max_rounds=max_rounds,
        trace_metadata_model=TraceMetadataModel(
            research_id="research-ultra",
            user_id=7,
            model_id="model-1",
            budget_level="ULTRA",
            agent_framework="agentscope-python",
        ),
        research_brief="研究中国 AI 搜索市场的格局、商业模式与监管风险",
        budget=BudgetSnapshot(
            max_conduct_count=max_conduct_count,
            max_search_count=4,
            max_concurrent_units=3,
        ),
        budget_name="ULTRA",
        conduct_count=conduct_count,
    )


def _make_branch_state(*urls: str) -> DeepResearchState:
    state = _make_state()
    state.search_results = {
        url: TavilySearchResult(url=url, title=f"title-{idx}", content="content", score=0.8)
        for idx, url in enumerate(urls, start=1)
    }
    state.search_notes = [f"URL: {url}" for url in urls]
    return state


def test_collect_evidence_entries_classifies_sources() -> None:
    from app.application.ultra_dynamic import collect_evidence_entries

    results = [
        ResearchResult(
            0,
            "政策监管",
            "中国 AI 搜索监管趋势",
            "findings",
            _make_branch_state(
                "https://www.gov.cn/policy/2026-07/01/content_1.htm",
                "https://www.reuters.com/world/china/ai-search-2026-07-01/",
            ),
        ),
        ResearchResult(
            1,
            "商业模式",
            "AI 搜索商业模式",
            "findings",
            _make_branch_state(
                "https://arxiv.org/abs/2607.12345",
                "https://www.mckinsey.com/featured-insights/artificial-intelligence/report",
            ),
        ),
    ]

    entries = collect_evidence_entries("research-ultra", round_no=1, results=results)

    assert [item.source_type for item in entries] == ["official", "news", "academic", "report"]


def test_fallback_round_decision_requests_continue_when_evidence_is_thin() -> None:
    from app.application.ultra_dynamic import build_fallback_round_decision, collect_evidence_entries

    state = _make_state(round_no=1, max_rounds=3, conduct_count=1, max_conduct_count=6)
    results = [
        ResearchResult(
            0,
            "市场格局",
            "AI 搜索市场格局",
            "仅有粗略结论，缺少高质量来源",
            _make_branch_state("https://example.com/blog/post"),
        ),
    ]
    evidence = collect_evidence_entries(state.research_id, round_no=1, results=results)

    decision = build_fallback_round_decision(state, results, evidence)

    assert decision["nextAction"] == "continue"
    assert decision["blockingGaps"]
    assert decision["qualityScoreboard"]["evidence"] < 4


@pytest.mark.asyncio
async def test_finalize_round_updates_state_and_persists_records(monkeypatch) -> None:
    from app.application.ultra_dynamic import UltraDynamicRoundCoordinator

    state = _make_state(round_no=1, max_rounds=4, conduct_count=2, max_conduct_count=6)
    state.current_planning_round_id = 99
    tasks = [ResearchTask(0, "政策监管", "中国 AI 搜索监管趋势", "task-0", "worker-0")]
    results = [
        ResearchResult(
            0,
            "政策监管",
            "中国 AI 搜索监管趋势",
            "已有政策摘要，但仍缺官方原文对照",
            _make_branch_state("https://www.gov.cn/policy/2026-07/01/content_1.htm"),
        ),
    ]
    persisted: dict[str, list] = {"round": [], "items": [], "decision": [], "evidence": []}

    class FakeClient:
        async def run_agent(self, _request):
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(
                    text="""
{
  "strategy": "先补官方原文与最新监管解释",
  "deltaSummary": "已有监管脉络，但缺政策原文交叉验证。",
  "qualityScoreboard": {"coverage": 3, "evidence": 2, "freshness": 4, "sourceDiversity": 2, "consistency": 3},
  "sectionScoreboard": [
    {
      "section": "政策监管",
      "status": "needs_more_evidence",
      "evidenceStatus": "partial",
      "confidence": "medium",
      "gaps": ["缺政策原文"],
      "recommendedSourceTypes": ["official"]
    }
  ],
  "sourceTypeBreakdown": {"official": 1, "academic": 0, "report": 0, "news": 0, "company": 0, "other": 0},
  "nextFocus": {
    "sections": ["政策监管"],
    "directives": ["补官方原文"],
    "requiredSourceTypes": ["official"]
  },
  "nextAction": "continue",
  "blockingGaps": ["缺政策原文"]
}
""",
                ),
            )

    async def publish_event(*_args, **_kwargs):
        return 1

    async def save_round(round_id: int, summary: dict):
        persisted["round"].append((round_id, summary))

    async def save_items(round_id: int, _tasks, _results):
        persisted["items"].append(round_id)

    async def save_decision(round_id: int, decision: dict, summary: str):
        persisted["decision"].append((round_id, decision, summary))

    async def save_evidence(round_id: int, evidence):
        persisted["evidence"].append((round_id, evidence))

    monkeypatch.setattr("app.application.ultra_dynamic.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.ultra_dynamic.event_publisher.publish_event", publish_event)
    monkeypatch.setattr("app.application.ultra_dynamic.event_publisher.publish_message", publish_event)

    coordinator = UltraDynamicRoundCoordinator()
    monkeypatch.setattr(coordinator, "_persist_round_summary", save_round)
    monkeypatch.setattr(coordinator, "_persist_work_item_results", save_items)
    monkeypatch.setattr(coordinator, "_persist_decision_log", save_decision)
    monkeypatch.setattr(coordinator, "_persist_evidence_entries", save_evidence)

    decision = await coordinator.finalize_round(state, tasks, results)

    assert decision["nextAction"] == "continue"
    assert state.latest_dynamic_decision["nextAction"] == "continue"
    assert state.dynamic_next_focus["sections"] == ["政策监管"]
    assert persisted["round"]
    assert persisted["items"] == [99]
    assert persisted["decision"]
    assert persisted["evidence"]


@pytest.mark.asyncio
async def test_ultra_pipeline_can_continue_without_pending_intervention(monkeypatch) -> None:
    state = _make_state(round_no=0, max_rounds=3, conduct_count=0, max_conduct_count=6)
    pipeline = AgentPipeline()
    rounds: list[int] = []
    report_calls: list[str] = []

    async def fake_supervisor_run(current_state: DeepResearchState) -> None:
        rounds.append(current_state.dynamic_round_no)
        if len(rounds) == 1:
            current_state.latest_dynamic_decision = {
                "strategy": "补官方来源",
                "deltaSummary": "第一轮缺官方来源",
                "qualityScoreboard": {"coverage": 2, "evidence": 2, "freshness": 4, "sourceDiversity": 1, "consistency": 3},
                "sectionScoreboard": [],
                "sourceTypeBreakdown": {"official": 0, "academic": 0, "report": 1, "news": 0, "company": 0, "other": 0},
                "nextFocus": {"sections": ["政策监管"], "directives": ["补官方来源"], "requiredSourceTypes": ["official"]},
                "nextAction": "continue",
                "blockingGaps": ["缺官方来源"],
            }
        else:
            current_state.latest_dynamic_decision = {
                "strategy": "证据已基本够用",
                "deltaSummary": "第二轮已补官方来源",
                "qualityScoreboard": {"coverage": 4, "evidence": 4, "freshness": 4, "sourceDiversity": 3, "consistency": 4},
                "sectionScoreboard": [],
                "sourceTypeBreakdown": {"official": 1, "academic": 0, "report": 1, "news": 0, "company": 0, "other": 0},
                "nextFocus": {"sections": [], "directives": [], "requiredSourceTypes": []},
                "nextAction": "report",
                "blockingGaps": [],
            }

    async def fake_report_run(current_state: DeepResearchState) -> str:
        report_calls.append(current_state.report_quality_context["status"])
        current_state.status = WorkflowStatus.IN_REPORT
        current_state.report = "# report"
        return current_state.report

    async def no_pending(_research_id: str) -> bool:
        return False

    async def no_cancel(_research_id: str) -> bool:
        return False

    async def noop(*_args, **_kwargs):
        return None

    async def publish_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.pipeline.supervisor_agent.run", fake_supervisor_run)
    monkeypatch.setattr("app.application.pipeline.report_agent.run", fake_report_run)
    monkeypatch.setattr("app.application.pipeline.has_pending_intervention", no_pending)
    monkeypatch.setattr("app.application.pipeline.is_cancelled", no_cancel)
    monkeypatch.setattr("app.application.pipeline.update_research_session", noop)
    monkeypatch.setattr("app.application.pipeline.save_workflow_checkpoint", noop)
    monkeypatch.setattr("app.application.pipeline.event_publisher.publish_event", publish_event)
    monkeypatch.setattr("app.application.pipeline.event_publisher.publish_message", noop)

    await pipeline._execute_ultra_dynamic_phase_and_3(state)

    assert rounds == [1, 2]
    assert report_calls == ["ready"]


@pytest.mark.asyncio
async def test_report_agent_includes_quality_context(monkeypatch) -> None:
    captured: dict[str, str] = {}
    state = _make_state()
    state.supervisor_notes = ["## 研究任务拆解\n\n1. 市场格局"]
    state.report_quality_context = {
        "status": "needs_disclosure",
        "summary": "报告前验证未完全通过",
        "weakSections": ["政策监管"],
        "blockingGaps": ["缺政策原文"],
    }

    class FakeClient:
        async def run_agent(self, request):
            captured["prompt"] = request.messages[-1].text
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(text="# 报告\n\n## 来源\n\n[1] [示例](https://example.com)"),
            )

    async def publish_event(*_args, **_kwargs):
        return 1

    async def publish_message(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", publish_event)
    monkeypatch.setattr("app.application.agents.event_publisher.publish_message", publish_message)

    await report_agent.run(state)

    assert "报告前验证未完全通过" in captured["prompt"]
    assert "政策监管" in captured["prompt"]
    assert "缺政策原文" in captured["prompt"]
