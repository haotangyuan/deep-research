from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.domain.context import BranchEvidencePackage
from app.infrastructure.observability import ResearchTraceMetadata
from app.domain.runtime import ResearchMessage, ResearchTokenUsage


class BudgetSnapshot(BaseModel):
    """Research budget.

    ``max_conduct_count`` is the per-round branch limit. ULTRA may execute
    multiple rounds, so ``max_total_conduct_count`` is a separate run-level
    guardrail. Fixed workflows omit it and retain the historical single-round
    behavior.
    """

    max_conduct_count: int
    max_search_count: int
    max_concurrent_units: int
    max_total_conduct_count: int | None = None

    @property
    def total_conduct_limit(self) -> int:
        return max(1, int(self.max_total_conduct_count or self.max_conduct_count))


class TraceMetadataModel(BaseModel):
    research_id: str
    user_id: int
    model_id: str
    budget_level: str
    agent_framework: str

    def to_trace_metadata(self) -> ResearchTraceMetadata:
        return ResearchTraceMetadata(
            research_id=self.research_id,
            user_id=self.user_id,
            model_id=self.model_id,
            budget_level=self.budget_level,
            agent_framework=self.agent_framework,
        )


class TavilySearchResult(BaseModel):
    url: str | None = None
    title: str | None = None
    content: str | None = None
    raw_content: str | None = None
    score: float | None = None


class ResearcherSource(BaseModel):
    """Researcher 结构化输出的来源条目（借鉴 CC StructuredOutput 思想）。"""
    url: str
    title: str | None = None
    type: str = "other"  # official|academic|report|news|company|other
    strength: str = "medium"  # high|medium|low
    snippet: str | None = None
    section_hint: str | None = None

    @field_validator("type")
    @classmethod
    def normalize_type(cls, value: str) -> str:
        allowed = {"official", "academic", "report", "news", "company", "other"}
        normalized = (value or "other").strip().lower()
        return normalized if normalized in allowed else "other"

    @field_validator("strength")
    @classmethod
    def normalize_strength(cls, value: str) -> str:
        allowed = {"high", "medium", "low"}
        normalized = (value or "medium").strip().lower()
        return normalized if normalized in allowed else "medium"


class DeepResearchState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    research_id: str
    chat_history: list[ResearchMessage] = Field(default_factory=list)
    status: str
    workflow_mode: str = "fixed"
    dynamic_round_no: int = 0
    dynamic_max_rounds: int = 1
    active_intervention: dict[str, Any] | None = None
    current_planning_round_id: int | None = None
    current_planning_round_goal: str | None = None
    latest_dynamic_decision: dict[str, Any] | None = None
    dynamic_round_history: list[dict[str, Any]] = Field(default_factory=list)
    dynamic_next_focus: dict[str, Any] | None = None
    report_quality_context: dict[str, Any] | None = None
    trace_metadata_model: TraceMetadataModel

    clarify_with_user_schema: dict[str, Any] | None = None
    research_question: dict[str, Any] | None = None
    research_brief: str | None = None
    research_type: str | None = None
    research_type_confidence: float = 0.0
    research_type_reason: str | None = None
    research_type_candidates: list[dict[str, Any]] = Field(default_factory=list)
    workflow_template: dict[str, Any] | None = None

    budget: BudgetSnapshot
    budget_name: str

    supervisor_iterations: int = 0
    conduct_count: int = 0
    total_conduct_count: int = 0
    supervisor_notes: list[str] = Field(default_factory=list)

    research_topic: str | None = None
    researcher_iterations: int = 0
    search_count: int = 0
    researcher_notes: list[str] = Field(default_factory=list)
    compressed_research: str | None = None
    researcher_sources: list[ResearcherSource] = Field(default_factory=list)
    branch_evidence_package: BranchEvidencePackage | None = None

    query: str | None = None
    max_results: int | None = None
    topic: str | None = None
    search_results: dict[str, TavilySearchResult] = Field(default_factory=dict)
    search_notes: list[str] = Field(default_factory=list)

    report: str | None = None

    current_scope_event_id: int | None = None
    current_supervisor_event_id: int | None = None
    current_research_event_id: int | None = None
    current_search_event_id: int | None = None

    hitl_mode: str | None = None
    skip_scope_phase: bool = False
    hitl_feedback: str | None = None

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    agent_worker_id: str | None = None
    agent_task_id: str | None = None
    agent_runtime_snapshot: dict[str, Any] | None = None

    # --- Eval MVP v2 落库链路 run 字段 ---
    # 见 docs/deep-research-eval-mvp-v2-tier-mechanism.md §6.1。
    # 全部带默认值，旧 checkpoint 经 model_validate 可安全加载。
    # 每次 _run_now（retry/resume）新建一组；fork_for_research/fork_for_search
    # 必须传播它们，否则子状态 LLM 调用拿不到 run.id → 跳过记录 → 漏计。
    run_id: str | None = None
    run_attempt_no: int | None = None
    run_trace_id: str | None = None
    run_trigger_type: str | None = None
    run_version_snapshot: dict[str, Any] | None = None
    run_start_input_tokens: int = 0
    run_start_output_tokens: int = 0
    run_start_perf_ts: float | None = None

    @property
    def trace_metadata(self) -> ResearchTraceMetadata:
        return self.trace_metadata_model.to_trace_metadata()

    def trace_context(self) -> dict[str, Any]:
        meta = self.trace_metadata
        return {
            "research.id": meta.research_id,
            "user.id": meta.user_id,
            "model.id": meta.model_id,
            "budget.level": meta.budget_level,
            "agent.framework": meta.agent_framework,
            "agent.worker.id": self.agent_worker_id,
            "agent.task.id": self.agent_task_id,
            "budget.conduct.per_round_limit": self.budget.max_conduct_count,
            "budget.conduct.total_limit": self.budget.total_conduct_limit,
            "budget.conduct.round_used": self.conduct_count,
            "budget.conduct.total_used": self.total_conduct_count,
            # Eval MVP v2：LLM 阶段归因维度
            "research.round.no": self.dynamic_round_no,
            "run.id": self.run_id,
            "run.attempt": self.run_attempt_no,
        }

    @property
    def remaining_total_conduct_slots(self) -> int:
        return max(0, self.budget.total_conduct_limit - self.total_conduct_count)

    def fork_for_research(
        self,
        topic: str,
        research_event_id: int | None,
        worker_id: str | None = None,
        task_id: str | None = None,
    ) -> "DeepResearchState":
        return DeepResearchState(
            research_id=self.research_id,
            chat_history=self.chat_history,
            status=self.status,
            workflow_mode=self.workflow_mode,
            dynamic_round_no=self.dynamic_round_no,
            dynamic_max_rounds=self.dynamic_max_rounds,
            active_intervention=self.active_intervention,
            current_planning_round_id=self.current_planning_round_id,
            current_planning_round_goal=self.current_planning_round_goal,
            latest_dynamic_decision=self.latest_dynamic_decision,
            dynamic_round_history=self.dynamic_round_history,
            dynamic_next_focus=self.dynamic_next_focus,
            report_quality_context=self.report_quality_context,
            trace_metadata_model=self.trace_metadata_model,
            research_brief=self.research_brief,
            research_type=self.research_type,
            research_type_confidence=self.research_type_confidence,
            workflow_template=self.workflow_template,
            budget=self.budget,
            budget_name=self.budget_name,
            conduct_count=self.conduct_count,
            total_conduct_count=self.total_conduct_count,
            current_supervisor_event_id=self.current_supervisor_event_id,
            current_research_event_id=research_event_id,
            research_topic=topic,
            researcher_iterations=0,
            search_count=0,
            researcher_notes=[],
            search_results={},
            search_notes=[],
            researcher_sources=[],
            branch_evidence_package=None,
            total_input_tokens=0,
            total_output_tokens=0,
            agent_worker_id=worker_id,
            agent_task_id=task_id,
            # Eval MVP v2：子状态复用父 run 的 run_*，保证 LLM 调用归因到正确 run。
            run_id=self.run_id,
            run_attempt_no=self.run_attempt_no,
            run_trace_id=self.run_trace_id,
            run_trigger_type=self.run_trigger_type,
            run_version_snapshot=self.run_version_snapshot,
            run_start_input_tokens=self.run_start_input_tokens,
            run_start_output_tokens=self.run_start_output_tokens,
            run_start_perf_ts=self.run_start_perf_ts,
        )

    def fork_for_search(self, query: str, max_results: int, topic: str) -> "DeepResearchState":
        return DeepResearchState(
            research_id=self.research_id,
            chat_history=self.chat_history,
            status=self.status,
            workflow_mode=self.workflow_mode,
            dynamic_round_no=self.dynamic_round_no,
            dynamic_max_rounds=self.dynamic_max_rounds,
            active_intervention=self.active_intervention,
            current_planning_round_id=self.current_planning_round_id,
            current_planning_round_goal=self.current_planning_round_goal,
            latest_dynamic_decision=self.latest_dynamic_decision,
            dynamic_round_history=self.dynamic_round_history,
            dynamic_next_focus=self.dynamic_next_focus,
            report_quality_context=self.report_quality_context,
            trace_metadata_model=self.trace_metadata_model,
            research_brief=self.research_brief,
            budget=self.budget,
            budget_name=self.budget_name,
            conduct_count=self.conduct_count,
            total_conduct_count=self.total_conduct_count,
            research_topic=self.research_topic,
            current_supervisor_event_id=self.current_supervisor_event_id,
            current_research_event_id=self.current_research_event_id,
            query=query,
            max_results=max_results,
            topic=topic,
            search_results={},
            search_notes=[],
            researcher_sources=[],
            branch_evidence_package=None,
            total_input_tokens=0,
            total_output_tokens=0,
            agent_worker_id=self.agent_worker_id,
            agent_task_id=self.agent_task_id,
            # Eval MVP v2：search 子状态复用父 run 的 run_*。
            run_id=self.run_id,
            run_attempt_no=self.run_attempt_no,
            run_trace_id=self.run_trace_id,
            run_trigger_type=self.run_trigger_type,
            run_version_snapshot=self.run_version_snapshot,
            run_start_input_tokens=self.run_start_input_tokens,
            run_start_output_tokens=self.run_start_output_tokens,
            run_start_perf_ts=self.run_start_perf_ts,
        )

    def add_token_usage(self, token_usage: ResearchTokenUsage | None) -> None:
        if token_usage is None:
            return
        self.total_input_tokens += int(token_usage.input_token_count or 0)
        self.total_output_tokens += int(token_usage.output_token_count or 0)

    def merge_token_usage_from(self, other: "DeepResearchState | None") -> None:
        if other is None:
            return
        self.total_input_tokens += int(other.total_input_tokens or 0)
        self.total_output_tokens += int(other.total_output_tokens or 0)
