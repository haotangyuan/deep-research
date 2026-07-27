"""Eval MVP v2 — 公共数据结构（schemas）。

Variant / Experiment 的纯数据契约，runner/evaluator 共享。不依赖 ORM，便于离线脚本与
DB 层解耦。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TierVariant:
    """三档回放变体。``budget_name`` 决定 MEDIUM/HIGH/ULTRA；``template`` 仅 ULTRA 使用。"""

    name: str  # "MEDIUM" / "HIGH" / "ULTRA"
    budget_name: str  # 透传到 state.budget_name
    template: dict[str, Any] | None = None  # ULTRA 用，MEDIUM/HIGH 为 None（FIXED 模式）
    label: str = ""  # 人类可读说明

    def __post_init__(self) -> None:
        if self.budget_name.upper() not in ("MEDIUM", "HIGH", "ULTRA"):
            raise ValueError(f"unsupported budget_name: {self.budget_name}")


@dataclass(frozen=True)
class MechanismVariant:
    """机制消融变体（v2 §10）。冻结同一 Evidence/Pre-Verification Report 后对比。

    ``base_template`` 为基线模板；``overrides`` 描述对模板的修改（开关/预算）。
    Runner 负责 apply_overrides 后送入 pipeline。
    """

    name: str  # e.g. "high_single_draft" / "high_dual_draft"
    base_budget: str  # "HIGH" 或 "ULTRA"
    base_template: dict[str, Any] | None
    overrides: dict[str, Any] = field(default_factory=dict)
    label: str = ""

    def is_disabled(self, key: str) -> bool:
        """override 里显式关闭某机制（claimVerification/sectionTeamEnabled/...）。"""
        return bool(self.overrides.get(key)) is False


@dataclass(frozen=True)
class CaseRunRequest:
    """runner 单次回放请求：dataset_item × variant × repeat。"""

    dataset_item_id: str
    experiment_id: str
    variant_name: str
    repeat_no: int = 0
    budget_name: str = "ULTRA"
    template: dict[str, Any] | None = None


@dataclass(frozen=True)
class MetricResult:
    """evaluator 产出的单条分数。写入 eval_score。"""

    metric_name: str
    metric_group: str  # gate/recall/factuality/source/analysis/presentation/mechanism/cost
    evaluator_name: str
    evaluator_version: str
    score_value: float | None = None
    label_value: str | None = None
    passed: int | None = None
    judge_model: str | None = None
    reason: str | None = None
    details: dict[str, Any] | None = None
