"""Eval MVP v2 — 三档回放变体（MEDIUM/HIGH/ULTRA）。

v2 §10.1：相同 Dataset Item、模型、时间边界下回放三档，回答「升级档位是否整体更好」。
注意：不能回答具体哪个机制有效——那是 mechanism_variants 的职责。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from evals.schemas import TierVariant

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _load_template(name: str = "ultra_default.json") -> dict[str, Any]:
    """读取 ULTRA 模板。失败时返回内联默认（保证离线可跑）。"""
    path = _TEMPLATE_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    # 内联 fallback，与 ultra_default.json 对齐
    return {
        "version": 1,
        "type": "general",
        "mode": "ultra_dynamic",
        "maxRounds": 5,
        "reviewer": {"count": 3, "lenses": ["evidence_sufficiency", "source_authority", "coverage_completeness"], "continueThreshold": 2},
        "report": {"draftAngles": ["data-driven", "narrative", "comparative"], "judgeEnabled": True, "claimVerification": True, "sectionTeamEnabled": True},
        "intervention": {"enabled": True, "applyMode": "next_round_planner_bias"},
        "budget": {"maxConductCount": 6, "maxTotalConductCount": 12, "maxSearchCount": 4, "maxConcurrentUnits": 3},
    }


def tier_variants(*, ultra_template: str = "ultra_default.json") -> list[TierVariant]:
    """三档变体。MEDIUM/HIGH 为 FIXED 模式（无 template），ULTRA 用 ultra_template。"""
    return [
        TierVariant(name="MEDIUM", budget_name="MEDIUM", template=None, label="低成本范围明确问题"),
        TierVariant(name="HIGH", budget_name="HIGH", template=None, label="双视角报告 + 更多预算"),
        TierVariant(
            name="ULTRA",
            budget_name="ULTRA",
            template=_load_template(ultra_template),
            label="Gap-driven 多轮 + 章节团队 + ClaimVerifier",
        ),
    ]


def tier_variant_by_name(name: str) -> TierVariant:
    name = name.upper()
    for v in tier_variants():
        if v.name == name:
            return v
    raise ValueError(f"unknown tier variant: {name}")
