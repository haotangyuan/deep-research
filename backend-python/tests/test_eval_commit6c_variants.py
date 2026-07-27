"""Eval MVP v2 Commit 6c — tier/mechanism 变体测试。

纯逻辑：变体定义、override 合成、模板可被 normalize_template 接受。
不跑真实 pipeline（那是 6e runner 的事）。
"""
from __future__ import annotations

from evals.mechanism_variants import (
    all_mechanism_groups,
    build_template,
    high_draft_ablation,
    reviewer_ablation,
    ultra_claim_verifier_ablation,
    ultra_round_ablation,
    ultra_section_team_ablation,
)
from evals.schemas import MechanismVariant, TierVariant
from evals.tier_variants import tier_variant_by_name, tier_variants
from app.application.workflow_template import normalize_template


def test_tier_variants_cover_three_budgets() -> None:
    tiers = tier_variants()
    assert {t.budget_name for t in tiers} == {"MEDIUM", "HIGH", "ULTRA"}
    assert tier_variant_by_name("ultra").budget_name == "ULTRA"
    assert tier_variant_by_name("medium").budget_name == "MEDIUM"


def test_tier_variant_rejects_unknown_budget() -> None:
    import pytest

    with pytest.raises(ValueError):
        TierVariant(name="X", budget_name="TURBO", template=None)


def test_all_mechanism_groups_have_pairs() -> None:
    groups = all_mechanism_groups()
    # §11.4 优先三组：high dual / ultra round2 / section team，每组至少 2 variant
    assert "high_report_ablation" in groups
    assert "multi_round_ablation" in groups
    assert "section_team_ablation" in groups
    for key, variants in groups.items():
        assert len(variants) >= 2, f"{key} 应成对对比"
        assert all(isinstance(v, MechanismVariant) for v in variants)


def test_section_team_override_disables_and_enables() -> None:
    single, team = ultra_section_team_ablation()
    assert build_template(single)["report"]["sectionTeamEnabled"] is False
    assert build_template(team)["report"]["sectionTeamEnabled"] is True


def test_round_ablation_freezes_single_round() -> None:
    r1, r2 = ultra_round_ablation()
    assert build_template(r1)["maxRounds"] == 1
    assert build_template(r1)["intervention"]["enabled"] is False
    assert build_template(r2)["maxRounds"] >= 2


def test_claim_verifier_ablation_toggles_flag() -> None:
    no_v, with_v = ultra_claim_verifier_ablation()
    assert build_template(no_v)["report"]["claimVerification"] is False
    assert build_template(with_v)["report"]["claimVerification"] is True


def test_reviewer_ablation_lens_diversity() -> None:
    single, same, diff = reviewer_ablation()
    assert build_template(single)["reviewer"]["count"] == 1
    same_lens = build_template(same)["reviewer"]["lenses"]
    assert len(set(same_lens)) == 1 and len(same_lens) == 3
    diff_lens = build_template(diff)["reviewer"]["lenses"]
    assert len(set(diff_lens)) == 3  # 三个不同 Lens


def test_high_draft_ablation_pair() -> None:
    single, dual = high_draft_ablation()
    assert single.base_budget == "HIGH" and dual.base_budget == "HIGH"


def test_built_templates_normalize_validly() -> None:
    """合成后的模板能被 normalize_template 接受（不抛 ValueError）。"""
    for group in all_mechanism_groups().values():
        for variant in group:
            tpl = build_template(variant)
            if tpl is None:
                continue
            normalized = normalize_template(tpl)
            assert normalized["version"] == 1
            assert "report" in normalized and "budget" in normalized
