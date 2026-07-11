from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.core.config import get_settings


# 支持的研究类型枚举（与 ScopeAgent 输出对应）
RESEARCH_TYPES = {
    "tech_comparison",
    "market_analysis",
    "academic_review",
    "fact_lookup",
    "trend_forecast",
    "general",
}

DEFAULT_REVIEWER_LENSES = [
    "evidence_sufficiency",
    "source_authority",
    "coverage_completeness",
]

DEFAULT_DRAFT_ANGLES = ["data-driven", "narrative", "comparative"]


class ReviewerTemplate(BaseModel):
    count: int = Field(default=3, ge=1, le=len(DEFAULT_REVIEWER_LENSES))
    lenses: list[str] = Field(default_factory=lambda: list(DEFAULT_REVIEWER_LENSES), min_length=1)
    continueThreshold: int = Field(default=2, ge=1)

    @field_validator("lenses")
    @classmethod
    def validate_lenses(cls, value: list[str]) -> list[str]:
        invalid = [item for item in value if item not in DEFAULT_REVIEWER_LENSES]
        if invalid:
            raise ValueError("unknown reviewer lens: " + ", ".join(invalid))
        return value

    @model_validator(mode="after")
    def validate_threshold(self) -> "ReviewerTemplate":
        if self.continueThreshold > self.count:
            raise ValueError("reviewer continueThreshold cannot exceed reviewer count")
        return self


class ReportTemplate(BaseModel):
    draftAngles: list[str] = Field(default_factory=lambda: list(DEFAULT_DRAFT_ANGLES), min_length=1)
    judgeEnabled: bool = True
    claimVerification: bool = True
    sectionTeamEnabled: bool = False

    @field_validator("draftAngles")
    @classmethod
    def validate_angles(cls, value: list[str]) -> list[str]:
        invalid = [item for item in value if item not in DEFAULT_DRAFT_ANGLES]
        if invalid:
            raise ValueError("unknown report draft angle: " + ", ".join(invalid))
        return value


class BudgetTemplate(BaseModel):
    maxConductCount: int = Field(default=6, ge=1)
    maxSearchCount: int = Field(default=4, ge=1)
    maxConcurrentUnits: int = Field(default=3, ge=1)


class InterventionTemplate(BaseModel):
    enabled: bool = True
    applyMode: str = "next_round_planner_bias"


class UltraWorkflowTemplate(BaseModel):
    version: int = Field(default=1, ge=1)
    type: str = "general"
    mode: str = "ultra_dynamic"
    maxRounds: int = Field(default=5, ge=1)
    reviewer: ReviewerTemplate = Field(default_factory=ReviewerTemplate)
    report: ReportTemplate = Field(default_factory=ReportTemplate)
    intervention: InterventionTemplate = Field(default_factory=InterventionTemplate)
    budget: BudgetTemplate = Field(default_factory=BudgetTemplate)

    @field_validator("type")
    @classmethod
    def validate_type(cls, value: str) -> str:
        if value not in RESEARCH_TYPES:
            raise ValueError("unknown research type: " + value)
        return value

    @field_validator("mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        if value != "ultra_dynamic":
            raise ValueError("workflow template mode must be ultra_dynamic")
        return value


def _template_dir() -> Path:
    return Path(get_settings().research_ultra_template_dir)


def _read(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return normalize_template(json.load(f))


def normalize_template(template: dict[str, Any]) -> dict[str, Any]:
    """兼容旧扁平字段，并输出方案文档定义的嵌套模板结构。"""
    normalized = dict(template or {})
    normalized.setdefault("version", 1)

    reviewer = dict(normalized.get("reviewer") or {})
    reviewer.setdefault("count", int(normalized.get("reviewerCount", 3)))
    reviewer.setdefault("lenses", list(DEFAULT_REVIEWER_LENSES))
    reviewer.setdefault("continueThreshold", min(2, max(1, int(reviewer.get("count") or 3))))
    normalized["reviewer"] = reviewer

    report = dict(normalized.get("report") or {})
    report.setdefault("draftAngles", list(normalized.get("draftAngles") or DEFAULT_DRAFT_ANGLES))
    report.setdefault("judgeEnabled", True)
    report.setdefault("claimVerification", bool(normalized.get("claimVerification", True)))
    report.setdefault("sectionTeamEnabled", bool(normalized.get("sectionTeamEnabled", False)))
    normalized["report"] = report

    budget = dict(normalized.get("budget") or {})
    budget.setdefault("maxConductCount", int(normalized.get("maxConductCount", 6)))
    budget.setdefault("maxSearchCount", int(normalized.get("maxSearchCount", 4)))
    budget.setdefault("maxConcurrentUnits", int(normalized.get("maxConcurrentUnits", 3)))
    normalized["budget"] = budget

    normalized.setdefault("mode", "ultra_dynamic")
    normalized.setdefault("intervention", {"enabled": True, "applyMode": "next_round_planner_bias"})
    try:
        return UltraWorkflowTemplate.model_validate(normalized).model_dump(mode="json")
    except ValidationError as exc:
        raise ValueError("invalid ultra workflow template: " + str(exc)) from exc


def reviewer_count(template: dict[str, Any] | None) -> int:
    reviewer = (template or {}).get("reviewer") if isinstance(template, dict) else None
    value = (reviewer or {}).get("count") if isinstance(reviewer, dict) else (template or {}).get("reviewerCount")
    try:
        return max(1, int(value or 3))
    except (TypeError, ValueError):
        return 3


def reviewer_lenses(template: dict[str, Any] | None) -> list[str]:
    reviewer = (template or {}).get("reviewer") if isinstance(template, dict) else None
    lenses = (reviewer or {}).get("lenses") if isinstance(reviewer, dict) else None
    if not lenses and isinstance(template, dict):
        lenses = template.get("reviewerLenses")
    if isinstance(lenses, list) and lenses:
        return [str(item) for item in lenses if str(item).strip()]
    return list(DEFAULT_REVIEWER_LENSES)


def continue_threshold(template: dict[str, Any] | None) -> int:
    reviewer = (template or {}).get("reviewer") if isinstance(template, dict) else None
    value = (reviewer or {}).get("continueThreshold") if isinstance(reviewer, dict) else None
    try:
        return max(1, int(value or min(2, reviewer_count(template))))
    except (TypeError, ValueError):
        return min(2, reviewer_count(template))


def draft_angles(template: dict[str, Any] | None) -> list[str]:
    report = (template or {}).get("report") if isinstance(template, dict) else None
    angles = (report or {}).get("draftAngles") if isinstance(report, dict) else None
    if not angles and isinstance(template, dict):
        angles = template.get("draftAngles")
    if isinstance(angles, list) and angles:
        return [str(item) for item in angles if str(item).strip()]
    return list(DEFAULT_DRAFT_ANGLES)


def claim_verification_enabled(template: dict[str, Any] | None) -> bool:
    report = (template or {}).get("report") if isinstance(template, dict) else None
    if isinstance(report, dict) and "claimVerification" in report:
        return bool(report.get("claimVerification"))
    if isinstance(template, dict) and "claimVerification" in template:
        return bool(template.get("claimVerification"))
    return True


def report_judge_enabled(template: dict[str, Any] | None) -> bool:
    report = (template or {}).get("report") if isinstance(template, dict) else None
    if isinstance(report, dict) and "judgeEnabled" in report:
        return bool(report.get("judgeEnabled"))
    return True


def report_section_team_enabled(template: dict[str, Any] | None) -> bool:
    report = (template or {}).get("report") if isinstance(template, dict) else None
    if isinstance(report, dict) and "sectionTeamEnabled" in report:
        return bool(report.get("sectionTeamEnabled"))
    if isinstance(template, dict) and "sectionTeamEnabled" in template:
        return bool(template.get("sectionTeamEnabled"))
    return False


def template_budget(template: dict[str, Any] | None) -> dict[str, int]:
    budget = (template or {}).get("budget") if isinstance(template, dict) else None
    if not isinstance(budget, dict):
        budget = {}
    return {
        "max_conduct_count": max(1, int(budget.get("maxConductCount", 6))),
        "max_search_count": max(1, int(budget.get("maxSearchCount", 4))),
        "max_concurrent_units": max(1, int(budget.get("maxConcurrentUnits", 3))),
    }


def load_template(research_type: str | None) -> dict[str, Any]:
    """加载指定类型的模板，不存在则 fallback 到 default。"""
    base = _template_dir()
    if research_type and research_type in RESEARCH_TYPES and research_type != "general":
        path = base / f"ultra_{research_type}.json"
        if path.exists():
            return _read(path)
    return _read(base / "ultra_default.json")


def select_template(research_type: str | None, confidence: float) -> dict[str, Any]:
    """按意图识别结果选模板：置信度 >= 0.7 且有对应模板才用类型模板，否则 default。

    借鉴点 E：意图识别 + 模板分配，零额外 LLM 调用（复用 ScopeAgent 输出）。
    """
    if (
        research_type
        and research_type in RESEARCH_TYPES
        and research_type != "general"
        and confidence >= 0.7
    ):
        base = _template_dir()
        path = base / f"ultra_{research_type}.json"
        if path.exists():
            return _read(path)
    return load_template("general")
