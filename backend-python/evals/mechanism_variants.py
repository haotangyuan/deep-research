"""Eval MVP v2 — 机制消融变体（v2 §10.2-10.6）。

冻结同一份 Evidence / Pre-Verification Report 后对比「开/关某机制」。
每对 variant 共享 base_budget + base_template，仅 overrides 不同，保证公平性（§10.7）。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from evals.schemas import MechanismVariant

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def _load_template(name: str) -> dict[str, Any]:
    path = _TEMPLATE_DIR / name
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _apply_overrides(template: dict[str, Any] | None, overrides: dict[str, Any]) -> dict[str, Any]:
    """把 overrides 应用到模板的 report/reviewer 子树。返回深拷贝。"""
    base = copy.deepcopy(template or {})
    report = dict(base.get("report") or {})
    reviewer = dict(base.get("reviewer") or {})
    for key, val in overrides.items():
        if key in ("claimVerification", "sectionTeamEnabled", "judgeEnabled", "draftAngles"):
            report[key] = val
        elif key in ("reviewerCount", "lenses", "continueThreshold"):
            reviewer[key] = val
        else:
            base[key] = val
    base["report"] = report
    base["reviewer"] = reviewer
    return base


def high_draft_ablation() -> list[MechanismVariant]:
    """§10.2 HIGH Single vs Dual Draft。"""
    return [
        MechanismVariant(
            name="high_single_draft",
            base_budget="HIGH",
            base_template=None,
            overrides={"sectionTeamEnabled": False},
            label="HIGH budget + 单 ReportAgent",
        ),
        MechanismVariant(
            name="high_dual_draft",
            base_budget="HIGH",
            base_template=None,
            overrides={"sectionTeamEnabled": False},  # HIGH 走 _lightweight_high_report 双 Draft
            label="HIGH budget + comparative/data-driven + synthesis",
        ),
    ]


def ultra_round_ablation() -> list[MechanismVariant]:
    """§10.4 Multi-round：Round 1 only vs Gap-directed Round 2。

    override maxRounds=1 冻结单轮；基线用 maxRounds>=2 + intervention。
    """
    base = _load_template("ultra_default.json")
    single_round = copy.deepcopy(base)
    single_round["maxRounds"] = 1
    single_round["intervention"] = {"enabled": False, "applyMode": "off"}
    return [
        MechanismVariant(
            name="ultra_round1_only",
            base_budget="ULTRA",
            base_template=single_round,
            overrides={},
            label="Round 1 only，不进第二轮",
        ),
        MechanismVariant(
            name="ultra_gap_round2",
            base_budget="ULTRA",
            base_template=copy.deepcopy(base),
            overrides={},
            label="Round 2 with Reviewer Gap-directed research",
        ),
    ]


def ultra_section_team_ablation() -> list[MechanismVariant]:
    """§10.5 Section Team：single ReportAgent vs Section Team。"""
    base = _load_template("ultra_default.json")
    return [
        MechanismVariant(
            name="ultra_single_report",
            base_budget="ULTRA",
            base_template=copy.deepcopy(base),
            overrides={"sectionTeamEnabled": False},
            label="ULTRA 单 ReportAgent",
        ),
        MechanismVariant(
            name="ultra_section_team",
            base_budget="ULTRA",
            base_template=copy.deepcopy(base),
            overrides={"sectionTeamEnabled": True},
            label="ULTRA 章节团队",
        ),
    ]


def ultra_claim_verifier_ablation() -> list[MechanismVariant]:
    """§10.6 ClaimVerifier：without vs with verifier。"""
    base = _load_template("ultra_default.json")
    return [
        MechanismVariant(
            name="ultra_no_claim_verifier",
            base_budget="ULTRA",
            base_template=copy.deepcopy(base),
            overrides={"claimVerification": False},
            label="不跑 ClaimVerifier",
        ),
        MechanismVariant(
            name="ultra_with_claim_verifier",
            base_budget="ULTRA",
            base_template=copy.deepcopy(base),
            overrides={"claimVerification": True},
            label="跑 ClaimVerifier",
        ),
    ]


def reviewer_ablation() -> list[MechanismVariant]:
    """§10.3 Reviewer：单 / 三相同 Lens / 三不同 Lens。

    注：「无 Reviewer」无法在模板层表达（``ReviewerTemplate.count`` 校验 ``ge=1``），
    需运行时 gate，留作后续 commit 的 runner flag。本 MVP 用「单 Reviewer」作为最小基线。
    """
    base = _load_template("ultra_default.json")
    single = copy.deepcopy(base)
    single["reviewer"] = {"count": 1, "lenses": ["evidence_sufficiency"], "continueThreshold": 1}
    same_lens = copy.deepcopy(base)
    same_lens["reviewer"] = {"count": 3, "lenses": ["evidence_sufficiency"] * 3, "continueThreshold": 2}
    return [
        MechanismVariant("reviewer_single", "ULTRA", single, {}, "单 Reviewer"),
        MechanismVariant("reviewer_same_lens", "ULTRA", same_lens, {}, "三个相同 Lens Reviewer"),
        MechanismVariant("reviewer_diff_lens", "ULTRA", copy.deepcopy(base), {}, "三个不同 Lens Reviewer（基线）"),
    ]


def all_mechanism_groups() -> dict[str, list[MechanismVariant]]:
    """所有机制消融组，供 runner 选择。键即 experiment_type 后缀。"""
    return {
        "high_report_ablation": high_draft_ablation(),
        "multi_round_ablation": ultra_round_ablation(),
        "section_team_ablation": ultra_section_team_ablation(),
        "claim_verifier_ablation": ultra_claim_verifier_ablation(),
        "reviewer_ablation": reviewer_ablation(),
    }


def build_template(variant: MechanismVariant) -> dict[str, Any] | None:
    """把 variant 的 base_template + overrides 合成最终送入 pipeline 的模板。"""
    return _apply_overrides(variant.base_template, variant.overrides) or None
