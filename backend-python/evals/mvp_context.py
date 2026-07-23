"""Deep Research Eval 单题端到端 MVP — EvalContext 与完整性检查。

按规格 docs/deep-research-eval-mvp-single-case.md 第 3 节实现：
- ``MvpEvalContext``：承载单题评估所需的全部产物（离线 Fixture 装配）。
- ``build_context``：按固定执行顺序读取 Fixture 并建立 Claim→Evidence→Source、
  Gap→Round 关联。
- ``check_completeness``：检查关键字段是否齐备；缺失字段对应指标标 not_evaluable，
  不默认通过。

与现有 v2 框架的关系：本 dataclass 字段集按规格定义，不复用
``evals.evaluators.base.EvalContext``（字段不同），但 evaluator 产出仍复用
``evals.schemas.MetricResult``。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MvpEvalContext:
    """单题评估输入。``build_context`` 装配，evaluator 只读。"""

    case: dict[str, Any] = field(default_factory=dict)
    run: dict[str, Any] = field(default_factory=dict)
    intent: dict[str, Any] = field(default_factory=dict)
    plan: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    context_nodes: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    review: dict[str, Any] = field(default_factory=dict)
    rounds: list[dict[str, Any]] = field(default_factory=list)
    reports: dict[str, str] = field(default_factory=dict)
    claims: list[dict[str, Any]] = field(default_factory=list)
    claim_verifier: list[dict[str, Any]] = field(default_factory=list)
    gold: dict[str, Any] = field(default_factory=dict)
    completeness: dict[str, Any] = field(default_factory=dict)
    # 建立的关联索引（运行时辅助，不进 JSON）
    evidence_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    source_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    claim_by_id: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims_by_evidence: dict[str, list[str]] = field(default_factory=dict)


def load_fixture(path: str | Path) -> dict[str, Any]:
    """读取离线 Fixture JSON。"""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_context(raw: dict[str, Any]) -> MvpEvalContext:
    """按规格第 3 节执行顺序装配 EvalContext 并建立关联。"""
    ctx = MvpEvalContext(
        case=raw.get("case", {}) or {},
        run=raw.get("run", {}) or {},
        intent=raw.get("intent", {}) or {},
        plan=raw.get("plan", {}) or {},
        tool_calls=list(raw.get("tool_calls", []) or []),
        context_nodes=list(raw.get("context_nodes", []) or []),
        sources=list(raw.get("sources", []) or []),
        evidence=list(raw.get("evidence", []) or []),
        review=raw.get("review", {}) or {},
        rounds=list(raw.get("rounds", []) or []),
        reports=dict(raw.get("reports", {}) or {}),
        claims=list(raw.get("claims", []) or []),
        claim_verifier=list(raw.get("claim_verifier", []) or []),
        gold=raw.get("gold", {}) or {},
    )

    # 建立 Claim→Evidence→Source 关联
    for ev in ctx.evidence:
        ev_id = ev.get("evidence_id")
        if ev_id:
            ctx.evidence_by_id[ev_id] = ev
        src_id = ev.get("source_id")
        if src_id and src_id not in ctx.source_by_id:
            for src in ctx.sources:
                if src.get("source_id") == src_id:
                    ctx.source_by_id[src_id] = src
                    break
    for src in ctx.sources:
        src_id = src.get("source_id")
        if src_id and src_id not in ctx.source_by_id:
            ctx.source_by_id[src_id] = src
    for claim in ctx.claims:
        claim_id = claim.get("claim_id")
        if claim_id:
            ctx.claim_by_id[claim_id] = claim
        for cite in claim.get("citations", []) or []:
            ev_id = cite.get("evidence_id")
            if ev_id:
                ctx.claims_by_evidence.setdefault(ev_id, []).append(claim_id or "")

    # 执行完整性检查
    ctx.completeness = check_completeness(ctx)
    return ctx


def _nonempty_dict(d: dict[str, Any] | None) -> bool:
    return bool(d)


def _nonempty_list(lst: list[Any] | None) -> bool:
    return bool(lst)


def _has_pre_post(reports: dict[str, str], pre_key: str, post_key: str) -> bool:
    return bool(reports.get(pre_key)) and bool(reports.get(post_key))


def check_completeness(ctx: MvpEvalContext) -> dict[str, Any]:
    """规格第 3 节完整性检查。缺失字段进 missing，evaluable=False 时不默认通过。"""
    case_available = _nonempty_dict(ctx.case) and bool(ctx.case.get("query")) and bool(ctx.case.get("required_points"))
    intent_available = _nonempty_dict(ctx.intent)
    review_available = _nonempty_dict(ctx.review) and bool(ctx.review.get("blocking_gaps") is not None)
    claims_available = _nonempty_list(ctx.claims)
    evidence_available = _nonempty_list(ctx.evidence)
    consistency_pre_post_available = _has_pre_post(ctx.reports, "pre_consistency", "post_consistency")
    verifier_pre_post_available = _has_pre_post(ctx.reports, "pre_verification", "post_verification")

    missing: list[str] = []
    for name, ok in [
        ("case", case_available),
        ("intent", intent_available),
        ("review", review_available),
        ("claims", claims_available),
        ("evidence", evidence_available),
        ("consistency_pre_post", consistency_pre_post_available),
        ("verifier_pre_post", verifier_pre_post_available),
    ]:
        if not ok:
            missing.append(name)

    evaluable = not missing
    return {
        "case_available": case_available,
        "intent_available": intent_available,
        "review_available": review_available,
        "claims_available": claims_available,
        "evidence_available": evidence_available,
        "consistency_pre_post_available": consistency_pre_post_available,
        "verifier_pre_post_available": verifier_pre_post_available,
        "missing": missing,
        "evaluable": evaluable,
    }
