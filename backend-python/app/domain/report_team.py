from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ReportSectionSpec(BaseModel):
    section_id: str
    title: str
    objective: str
    evidence_requirements: list[str] = Field(default_factory=list)
    related_sections: list[str] = Field(default_factory=list)


class SharedReportClaim(BaseModel):
    claim_id: str
    section_id: str
    claim: str
    source_paths: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    confidence: float = 0.5
    status: str = "proposed"


class ReportAgentMessage(BaseModel):
    message_id: str
    from_agent: str
    to_agent: str
    message_type: str
    subject: str
    instruction: str
    related_claim_ids: list[str] = Field(default_factory=list)
    status: str = "pending"


class ReportSectionArtifact(BaseModel):
    spec: ReportSectionSpec
    evidence_context: str
    evidence_paths: list[str] = Field(default_factory=list)
    raw_paths: list[str] = Field(default_factory=list)
    draft: str
    revision: str | None = None
    claims: list[SharedReportClaim] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def final_text(self) -> str:
        return (self.revision or self.draft).strip()
