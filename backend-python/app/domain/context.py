from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class ContextLevel(StrEnum):
    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    DERIVED = "derived"


class ContextNodeType(StrEnum):
    BRIEF = "brief"
    PLAN = "plan"
    BRANCH_WORKING_MEMORY = "branch_working_memory"
    BRANCH_SUMMARY = "branch_summary"
    SOURCE_ABSTRACT = "source_abstract"
    SOURCE_OVERVIEW = "source_overview"
    SOURCE_RAW = "source_raw"
    EVIDENCE = "evidence"
    REPORT_CONTEXT = "report_context"
    REPORT_PLAN = "report_plan"
    REPORT_SECTION_EVIDENCE = "report_section_evidence"
    REPORT_SECTION_DRAFT = "report_section_draft"
    REPORT_SECTION_REVISION = "report_section_revision"
    REPORT_SHARED_CLAIM = "report_shared_claim"
    REPORT_AGENT_MESSAGE = "report_agent_message"


class ResearchContextPath(BaseModel):
    raw: str

    @classmethod
    def source(cls, research_id: str, branch_index: int, source_key: str) -> "ResearchContextPath":
        return cls(raw=f"research://{research_id}/branches/branch-{branch_index:03d}/sources/{source_key}")

    @classmethod
    def branch(cls, research_id: str, branch_index: int) -> "ResearchContextPath":
        return cls(raw=f"research://{research_id}/branches/branch-{branch_index:03d}")

    @classmethod
    def report(cls, research_id: str, name: str) -> "ResearchContextPath":
        return cls(raw=f"research://{research_id}/report/{name}")

    def child(self, name: str) -> "ResearchContextPath":
        return ResearchContextPath(raw=self.raw.rstrip("/") + "/" + name.lstrip("/"))


class ResearchContextNodeData(BaseModel):
    research_id: str
    path: str
    node_type: ContextNodeType
    level: ContextLevel
    title: str | None = None
    content: str = ""
    content_ref: str | None = None
    parent_path: str | None = None
    branch_index: int | None = None
    round_no: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "ready"


class EvidenceItem(BaseModel):
    claim: str
    evidence_text: str
    source_url: str | None = None
    source_title: str | None = None
    source_path: str | None = None
    source_type: str = "other"
    strength: str = "medium"
    section_hint: str | None = None
    confidence: float = 0.5

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, value: float) -> float:
        return max(0.0, min(1.0, float(value)))


class BranchEvidencePackage(BaseModel):
    branch_index: int
    task_title: str
    research_topic: str
    branch_summary: str
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    source_paths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)


class TypedQuery(BaseModel):
    query: str
    intent: str
    context_type: ContextNodeType
    priority: int = 3
    section_hint: str | None = None
    filters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("priority")
    @classmethod
    def validate_priority(cls, value: int) -> int:
        if value < 1 or value > 5:
            raise ValueError("priority must be between 1 and 5")
        return value


class SelectedContextItem(BaseModel):
    path: str
    node_type: ContextNodeType
    level: ContextLevel
    title: str | None = None
    content: str
    source_url: str | None = None
    score: float = 0.0
    reason: str | None = None


class ReportContext(BaseModel):
    research_id: str
    research_brief: str
    section_contexts: dict[str, list[SelectedContextItem]] = Field(default_factory=dict)
    dropped: list[dict[str, Any]] = Field(default_factory=list)
    total_estimated_tokens: int = 0


def estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + 3) // 4)


def stable_source_key(url: str) -> str:
    digest = hashlib.sha1(url.strip().encode("utf-8")).hexdigest()[:12]
    return f"src-{digest}"
