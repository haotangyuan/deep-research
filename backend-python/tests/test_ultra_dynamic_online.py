from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.application.agents import ResearchResult, ResearchTask, report_agent, researcher_agent, scope_agent
from app.application.pipeline import AgentPipeline
from app.application.workflow_template import load_template, normalize_template
from app.core.constants import WorkflowMode, WorkflowStatus
from app.domain.runtime import ResearchMemory
from app.domain.state import BudgetSnapshot, DeepResearchState, TavilySearchResult, TraceMetadataModel


def _make_state(
    *,
    round_no: int = 1,
    max_rounds: int = 3,
    conduct_count: int = 0,
    total_conduct_count: int = 0,
    max_conduct_count: int = 6,
    max_total_conduct_count: int = 12,
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
            max_total_conduct_count=max_total_conduct_count,
            max_search_count=4,
            max_concurrent_units=3,
        ),
        budget_name="ULTRA",
        conduct_count=conduct_count,
        total_conduct_count=total_conduct_count,
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


def test_fact_lookup_template_uses_documented_nested_schema() -> None:
    template = load_template("fact_lookup")

    assert template["version"] == 1
    assert template["reviewer"]["count"] == 2
    assert template["report"]["draftAngles"] == ["data-driven"]
    assert template["report"]["claimVerification"] is False
    assert template["budget"]["maxConductCount"] == 3
    assert template["budget"]["maxTotalConductCount"] == 3


def test_ultra_conduct_budget_resets_per_round_but_keeps_total_guardrail() -> None:
    from app.application.agents import supervisor_agent

    state = _make_state(
        round_no=2,
        conduct_count=0,
        total_conduct_count=6,
        max_conduct_count=6,
        max_total_conduct_count=12,
    )

    assert supervisor_agent._reserve_conduct_slot(state) is True
    assert state.conduct_count == 1
    assert state.total_conduct_count == 7

    state.conduct_count = 6
    assert supervisor_agent._reserve_conduct_slot(state) is False

    state.conduct_count = 0
    state.total_conduct_count = 12
    assert supervisor_agent._reserve_conduct_slot(state) is False


def test_ultra_task_ids_are_unique_across_rounds_and_respect_remaining_total_budget() -> None:
    from app.application.agents import supervisor_agent

    response = """
    {
      "researchTasks": [
        {"title": "任务一", "researchTopic": "主题一"},
        {"title": "任务二", "researchTopic": "主题二"},
        {"title": "任务三", "researchTopic": "主题三"}
      ]
    }
    """
    round_one = _make_state(round_no=1, total_conduct_count=0)
    round_two = _make_state(round_no=2, total_conduct_count=10)

    first_tasks = supervisor_agent._parse_research_tasks(response, round_one)
    second_tasks = supervisor_agent._parse_research_tasks(response, round_two)

    assert len(first_tasks) == 3
    assert len(second_tasks) == 2
    assert first_tasks[0].task_id != second_tasks[0].task_id
    assert "round-1" in first_tasks[0].task_id
    assert "round-2" in second_tasks[0].task_id


def test_template_validation_rejects_unknown_or_impossible_config() -> None:
    with pytest.raises(ValueError):
        normalize_template(
            {
                "type": "general",
                "maxRounds": 1,
                "reviewer": {"count": 1, "lenses": ["unknown_lens"], "continueThreshold": 1},
                "report": {"draftAngles": ["data-driven"]},
                "budget": {"maxConductCount": 1, "maxSearchCount": 1, "maxConcurrentUnits": 1},
            },
        )

    with pytest.raises(ValueError):
        normalize_template(
            {
                "type": "general",
                "maxRounds": 1,
                "reviewer": {"count": 1, "lenses": ["evidence_sufficiency"], "continueThreshold": 2},
                "report": {"draftAngles": ["unknown-angle"]},
                "budget": {"maxConductCount": 1, "maxSearchCount": 1, "maxConcurrentUnits": 1},
            },
        )


@pytest.mark.asyncio
async def test_scope_agent_publishes_intent_reason_and_candidates(monkeypatch) -> None:
    state = _make_state()
    memory = ResearchMemory(10)
    published: list[tuple] = []

    class FakeClient:
        async def run_agent(self, _request):
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(
                    text="""
{
  "researchBrief": "我想快速了解 Redis 是什么。",
  "researchType": "fact_lookup",
  "typeConfidence": 0.91,
  "typeReason": "用户请求是定义类事实查询，不需要多轮行业或学术综述。",
  "typeCandidates": [
    {"type": "fact_lookup", "confidence": 0.91, "reason": "定义类问题"},
    {"type": "general", "confidence": 0.09, "reason": "范围很小但仍可通用处理"}
  ]
}
""",
                ),
            )

    async def publish_event(*args, **kwargs):
        published.append((args, kwargs))
        return 1

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", publish_event)

    await scope_agent._write_research_brief(memory, state)

    assert state.research_type == "fact_lookup"
    assert state.research_type_confidence == pytest.approx(0.91)
    assert state.research_type_reason == "用户请求是定义类事实查询，不需要多轮行业或学术综述。"
    assert state.research_type_candidates[0]["type"] == "fact_lookup"
    intent_payload = next(
        args[3]
        for args, _kwargs in published
        if len(args) >= 4 and args[2].startswith("意图识别:")
    )
    assert '"reason": "用户请求是定义类事实查询，不需要多轮行业或学术综述。"' in intent_payload
    assert '"candidates"' in intent_payload


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
async def test_finalize_round_uses_nested_reviewer_count(monkeypatch) -> None:
    from app.application.ultra_dynamic import UltraDynamicRoundCoordinator

    state = _make_state(round_no=1, max_rounds=4, conduct_count=2, max_conduct_count=6)
    state.workflow_template = {"reviewer": {"count": 1}}
    state.current_planning_round_id = 99
    tasks = [ResearchTask(0, "政策监管", "中国 AI 搜索监管趋势", "task-0", "worker-0")]
    results = [
        ResearchResult(
            0,
            "政策监管",
            "中国 AI 搜索监管趋势",
            "已有政策摘要",
            _make_branch_state("https://www.gov.cn/policy/2026-07/01/content_1.htm"),
        ),
    ]
    reviewer_calls: list[str] = []

    class FakeClient:
        async def run_agent(self, request):
            reviewer_calls.append(request.stage_name)
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(
                    text='{"nextAction":"report","scores":{"coverage":4,"evidence":4,"freshness":4,"sourceDiversity":4,"consistency":4},"gaps":[],"rationale":"ok"}',
                ),
            )

    async def noop(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.ultra_dynamic.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.ultra_dynamic.event_publisher.publish_event", noop)
    monkeypatch.setattr("app.application.ultra_dynamic.event_publisher.publish_message", noop)

    coordinator = UltraDynamicRoundCoordinator()
    monkeypatch.setattr(coordinator, "_persist_round_summary", noop)
    monkeypatch.setattr(coordinator, "_persist_work_item_results", noop)
    monkeypatch.setattr(coordinator, "_persist_decision_log", noop)
    monkeypatch.setattr(coordinator, "_persist_evidence_entries", noop)

    decision = await coordinator.finalize_round(state, tasks, results)

    assert decision["nextAction"] == "report"
    assert reviewer_calls == ["UltraDynamicReviewer:evidence_sufficiency"]


@pytest.mark.asyncio
async def test_finalize_round_records_review_summary(monkeypatch) -> None:
    from app.application.ultra_dynamic import UltraDynamicRoundCoordinator

    state = _make_state(round_no=1, max_rounds=4, conduct_count=2, max_conduct_count=6)
    state.workflow_template = {
        "reviewer": {
            "count": 2,
            "lenses": ["evidence_sufficiency", "source_authority"],
            "continueThreshold": 2,
        },
    }
    state.current_planning_round_id = 99
    tasks = [ResearchTask(0, "政策监管", "中国 AI 搜索监管趋势", "task-0", "worker-0")]
    results = [
        ResearchResult(
            0,
            "政策监管",
            "中国 AI 搜索监管趋势",
            "已有政策摘要",
            _make_branch_state("https://www.gov.cn/policy/2026-07/01/content_1.htm"),
        ),
    ]

    class FakeClient:
        async def run_agent(self, request):
            action = "continue" if request.stage_name.endswith("evidence_sufficiency") else "report"
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(
                    text=(
                        '{"nextAction":"%s","scores":{"coverage":4,"evidence":3,"freshness":4,'
                        '"sourceDiversity":3,"consistency":4},"gaps":["补官方来源"],"rationale":"ok"}'
                    )
                    % action,
                ),
            )

    async def noop(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.ultra_dynamic.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.ultra_dynamic.event_publisher.publish_event", noop)
    monkeypatch.setattr("app.application.ultra_dynamic.event_publisher.publish_message", noop)

    coordinator = UltraDynamicRoundCoordinator()
    monkeypatch.setattr(coordinator, "_persist_round_summary", noop)
    monkeypatch.setattr(coordinator, "_persist_work_item_results", noop)
    monkeypatch.setattr(coordinator, "_persist_decision_log", noop)
    monkeypatch.setattr(coordinator, "_persist_evidence_entries", noop)

    decision = await coordinator.finalize_round(state, tasks, results)

    assert decision["nextAction"] == "report"
    assert decision["reviewSummary"] == {
        "continueVotes": 1,
        "reportVotes": 1,
        "totalVotes": 2,
        "continueThreshold": 2,
        "consensus": "split",
    }


def test_parse_compressed_research_normalizes_sources() -> None:
    state = _make_branch_state("https://example.com/source")
    text = """
{
  "findings": "结论",
  "sources": [
    {
      "url": "https://example.com/source",
      "title": "Example",
      "type": "blog",
      "strength": "excellent",
      "snippet": "snippet",
      "sectionHint": "章节"
    },
    {
      "url": "https://example.com/source",
      "title": "Duplicate",
      "type": "official",
      "strength": "high"
    },
    {
      "url": "not-a-url",
      "title": "Bad",
      "type": "official",
      "strength": "high"
    }
  ]
}
"""

    findings, sources = researcher_agent._parse_compressed_research(text, state)

    assert findings == "结论"
    assert len(sources) == 1
    assert sources[0].url == "https://example.com/source"
    assert sources[0].type == "other"
    assert sources[0].strength == "medium"
    assert sources[0].section_hint == "章节"


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
            captured[request.stage_name] = request.messages[-1].text
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

    assert "报告前验证未完全通过" in captured["ReportAgent:data-driven"]
    assert "政策监管" in captured["ReportAgent:data-driven"]
    assert "缺政策原文" in captured["ReportAgent:data-driven"]


@pytest.mark.asyncio
async def test_report_agent_uses_nested_report_template(monkeypatch) -> None:
    calls: list[str] = []
    state = _make_state()
    state.workflow_template = {
        "report": {
            "draftAngles": ["data-driven"],
            "claimVerification": False,
        },
    }
    state.supervisor_notes = ["## 研究任务拆解\n\n1. 市场格局"]

    class FakeClient:
        async def run_agent(self, request):
            calls.append(request.stage_name)
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

    assert calls == ["ReportAgent:data-driven"]


@pytest.mark.asyncio
async def test_report_agent_can_disable_judge_from_template(monkeypatch) -> None:
    calls: list[str] = []
    state = _make_state()
    state.workflow_template = {
        "report": {
            "draftAngles": ["data-driven", "narrative"],
            "judgeEnabled": False,
            "claimVerification": False,
        },
    }
    state.supervisor_notes = ["## 研究任务拆解\n\n1. 市场格局"]

    class FakeClient:
        async def run_agent(self, request):
            calls.append(request.stage_name)
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(text=f"# {request.stage_name} 报告"),
            )

    async def publish_event(*_args, **_kwargs):
        return 1

    async def publish_message(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", publish_event)
    monkeypatch.setattr("app.application.agents.event_publisher.publish_message", publish_message)

    report = await report_agent.run(state)

    assert calls == ["ReportAgent:data-driven", "ReportAgent:narrative"]
    assert report == "# ReportAgent:data-driven 报告"


@pytest.mark.asyncio
async def test_report_synthesis_receives_judge_graft_suggestions(monkeypatch) -> None:
    prompts_by_stage: dict[str, str] = {}
    state = _make_state()
    state.workflow_template = {
        "report": {
            "draftAngles": ["data-driven", "narrative"],
            "claimVerification": False,
        },
    }
    state.supervisor_notes = ["## 研究任务拆解\n\n1. 市场格局"]

    class FakeClient:
        async def run_agent(self, request):
            prompts_by_stage[request.stage_name] = request.messages[-1].text
            if request.stage_name.startswith("ReportAgent:"):
                return SimpleNamespace(
                    token_usage=None,
                    ai_message=SimpleNamespace(text=f"# {request.stage_name}\n\n正文 [1]"),
                )
            if request.stage_name == "ReportJudge":
                text = """
{
  "scores": {"coverage": 4, "evidence": 4, "structure": 4, "readability": 4, "sourcing": 4},
  "verdict": "strong",
  "highlight": "结构清晰",
  "gap": "数据略少",
  "graftSuggestions": ["保留关键对比表", "补充风险小结"]
}
"""
                return SimpleNamespace(token_usage=None, ai_message=SimpleNamespace(text=text))
            return SimpleNamespace(token_usage=None, ai_message=SimpleNamespace(text="# final"))

    async def publish_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", publish_event)
    monkeypatch.setattr("app.application.agents.event_publisher.publish_message", publish_event)

    await report_agent.run(state)

    assert "必须嫁接建议" in prompts_by_stage["ReportSynthesizer"]
    assert "保留关键对比表" in prompts_by_stage["ReportSynthesizer"]


@pytest.mark.asyncio
async def test_high_report_uses_two_angles_and_one_synthesis_without_judge(monkeypatch) -> None:
    calls: list[str] = []
    prompts_by_stage: dict[str, str] = {}
    state = _make_state()
    state.workflow_mode = WorkflowMode.FIXED
    state.workflow_template = {}
    state.budget_name = "HIGH"
    state.supervisor_notes = ["## 研究结论\n\n对比证据"]

    class FakeClient:
        async def run_agent(self, request):
            calls.append(request.stage_name)
            prompts_by_stage[request.stage_name] = request.messages[-1].text
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(text=f"# {request.stage_name} 报告"),
            )

    async def publish_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", publish_event)
    monkeypatch.setattr("app.application.agents.event_publisher.publish_message", publish_event)

    report = await report_agent.run(state)

    assert calls == [
        "ReportAgent:comparative",
        "ReportAgent:data-driven",
        "ReportAgent:high-synthesis",
    ]
    assert "ReportJudge" not in calls
    assert "# ReportAgent:comparative 报告" in prompts_by_stage["ReportAgent:high-synthesis"]
    assert "# ReportAgent:data-driven 报告" in prompts_by_stage["ReportAgent:high-synthesis"]
    assert report == "# ReportAgent:high-synthesis 报告"


@pytest.mark.asyncio
async def test_medium_report_keeps_single_report_agent(monkeypatch) -> None:
    calls: list[str] = []
    state = _make_state()
    state.workflow_mode = WorkflowMode.FIXED
    state.workflow_template = {}
    state.budget_name = "MEDIUM"
    state.supervisor_notes = ["## 研究结论\n\n基础证据"]

    class FakeClient:
        async def run_agent(self, request):
            calls.append(request.stage_name)
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(text="# MEDIUM 报告"),
            )

    async def publish_event(*_args, **_kwargs):
        return 1

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", publish_event)
    monkeypatch.setattr("app.application.agents.event_publisher.publish_message", publish_event)

    report = await report_agent.run(state)

    assert calls == ["ReportAgent"]
    assert report == "# MEDIUM 报告"
