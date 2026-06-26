from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .observability import ResearchTraceMetadata
from .runtime import ResearchMessage, ResearchTokenUsage


class BudgetSnapshot(BaseModel):
    max_conduct_count: int
    max_search_count: int
    max_concurrent_units: int


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


class DeepResearchState(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    research_id: str
    chat_history: list[ResearchMessage] = Field(default_factory=list)
    status: str
    trace_metadata_model: TraceMetadataModel

    clarify_with_user_schema: dict[str, Any] | None = None
    research_question: dict[str, Any] | None = None
    research_brief: str | None = None

    budget: BudgetSnapshot
    budget_name: str

    supervisor_iterations: int = 0
    conduct_count: int = 0
    supervisor_notes: list[str] = Field(default_factory=list)

    research_topic: str | None = None
    researcher_iterations: int = 0
    search_count: int = 0
    researcher_notes: list[str] = Field(default_factory=list)
    compressed_research: str | None = None

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
        }

    def fork_for_research(self, topic: str, research_event_id: int | None) -> "DeepResearchState":
        return DeepResearchState(
            research_id=self.research_id,
            chat_history=self.chat_history,
            status=self.status,
            trace_metadata_model=self.trace_metadata_model,
            research_brief=self.research_brief,
            budget=self.budget,
            budget_name=self.budget_name,
            current_supervisor_event_id=self.current_supervisor_event_id,
            current_research_event_id=research_event_id,
            research_topic=topic,
            researcher_iterations=0,
            search_count=0,
            researcher_notes=[],
            search_results={},
            search_notes=[],
            total_input_tokens=0,
            total_output_tokens=0,
        )

    def fork_for_search(self, query: str, max_results: int, topic: str) -> "DeepResearchState":
        return DeepResearchState(
            research_id=self.research_id,
            chat_history=self.chat_history,
            status=self.status,
            trace_metadata_model=self.trace_metadata_model,
            research_brief=self.research_brief,
            budget=self.budget,
            budget_name=self.budget_name,
            research_topic=self.research_topic,
            current_supervisor_event_id=self.current_supervisor_event_id,
            current_research_event_id=self.current_research_event_id,
            query=query,
            max_results=max_results,
            topic=topic,
            search_results={},
            search_notes=[],
            total_input_tokens=0,
            total_output_tokens=0,
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
