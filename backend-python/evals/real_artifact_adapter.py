"""真实产物 → MvpEvalContext adapter。

从一个真实 ULTRA research 的最新 research_run 读取 artifact，映射进 MvpEvalContext，
然后用 5 个 MVP evaluator 评估。

映射规则（真实 artifact → MvpEvalContext 字段）：
- research_run 行                → run
- research_brief artifact        → intent（brief 文本 + research_type；intent 子字段生产无，部分标 not_evaluable）
- evidence_item artifact         → evidence（content 是 EvidenceItem.model_dump JSON）
- source_snapshot artifact       → sources（metadata 含 url/title/score）
- round_review artifact          → review + rounds（metadata/content 含 nextAction/blockingGaps/score）
- report_final artifact          → reports.final
- claim_verification artifact    → claim_verifier（metadata/content 含 verdict）
- ResearchClaimManifest 行        → claims
- intent 子字段 / consistency 前后报告 / claim_verifier 前后报告：生产无结构化来源，
  留空 → completeness 标 not_evaluable，对应 evaluator 不默认通过。

usage:
    PYTHONPATH=. python -m evals.real_artifact_adapter --research-id <rid> --model-id <mid> --output evals/mvp_output
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from sqlalchemy import select

from app.domain.models import ResearchArtifact, ResearchClaimManifest, ResearchRun
from app.infrastructure.db import SessionLocal
from evals.evaluators.base import ChatFn
from evals.mvp_context import MvpEvalContext, build_context, check_completeness
from evals.mvp_evaluators import (
    evaluate_claim_verifier,
    evaluate_claims,
    evaluate_consistency,
    evaluate_intent,
    evaluate_review,
)
from evals.mvp_report import aggregate, write_json, write_markdown
from evals.mvp_single_case import build_chat_fn, _load_model_record


async def _latest_run_id(research_id: str) -> tuple[str | None, dict[str, Any]]:
    """取最新 attempt 的 research_run 行。"""
    async with SessionLocal() as session:
        run = await session.scalar(
            select(ResearchRun)
            .where(ResearchRun.research_id == research_id)
            .order_by(ResearchRun.attempt_no.desc())
        )
        if run is None:
            return None, {}
        run_row = {
            "run_id": run.id,
            "status": run.status,
            "outcome": run.outcome,
            "input_tokens": run.input_tokens or 0,
            "output_tokens": run.output_tokens or 0,
            "duration_ms": run.active_duration_ms,
            "budget_level": run.budget_level,
            "workflow_version": run.template_version,
            "trace_id": run.trace_id,
        }
        return run.id, run_row


async def _load_artifacts(run_id: str) -> dict[str, list[ResearchArtifact]]:
    """按 artifact_type 分组读取。"""
    by_type: dict[str, list[ResearchArtifact]] = {}
    async with SessionLocal() as session:
        arts = (await session.scalars(
            select(ResearchArtifact).where(ResearchArtifact.run_id == run_id)
        )).all()
        for a in arts:
            by_type.setdefault(a.artifact_type, []).append(a)
    return by_type


async def _load_manifest(run_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (await session.scalars(
            select(ResearchClaimManifest).where(ResearchClaimManifest.run_id == run_id)
        )).all()
    claims: list[dict[str, Any]] = []
    # ResearchClaimManifest 每行是一个 claim+citation 组合，需按 claim_id 聚合
    by_claim: dict[str, dict[str, Any]] = {}
    for r in rows:
        cid = r.claim_id
        slot = by_claim.setdefault(cid, {
            "claim_id": cid,
            "claim_text": r.claim_text,
            "importance": r.importance or "minor",
            "requires_citation": True,
            "citations": [],
        })
        if r.citation_url or r.citation_excerpt:
            slot["citations"].append({
                "citation_id": r.citation_id,
                "evidence_id": r.evidence_id,
                "excerpt": r.citation_excerpt,
                "url": r.citation_url,
            })
    return list(by_claim.values())


def _meta(a: ResearchArtifact) -> dict[str, Any]:
    if not a.metadata_json:
        return {}
    try:
        return json.loads(a.metadata_json) or {}
    except Exception:  # noqa: BLE001
        return {}


async def build_from_real_run(research_id: str) -> MvpEvalContext:
    """从真实 research 的最新 run 装配 MvpEvalContext。"""
    run_id, run_row = await _latest_run_id(research_id)
    if not run_id:
        raise SystemExit(f"research {research_id} 没有找到任何 research_run 行（pipeline 可能未跑）")

    arts = await _load_artifacts(run_id)
    claims = await _load_manifest(run_id)

    # intent：从 research_brief + research_type 推（生产无 intent 子字段，尽力而为）
    brief_art = arts.get("research_brief", [])
    brief_text = brief_art[-1].content if brief_art else ""
    research_type = ""
    if brief_art:
        research_type = _meta(brief_art[-1]).get("researchType", "")
    intent = {
        "task_type": research_type or "general",
        "language": "zh-CN",
        "require_citations": True,
        "audience": "enterprise_technical_decision_maker",
        "required_points": [],  # 生产无 required_points 结构化映射，留空 → Intent evaluator 会判
        "constraints": {},
        "routing": research_type or "general",
        "research_brief": brief_text,
    }

    # plan：从 research_planning_round/work_item 表读（这里简化为空，标 not_evaluable）
    plan: dict[str, Any] = {}

    # tool_calls：生产无单独 tool_calls artifact，留空
    tool_calls: list[dict[str, Any]] = []

    # context_nodes：L0/L1/L2 artifact（生产有 research_context_node 但 artifact_type 不同）
    context_nodes: list[dict[str, Any]] = []

    # sources：source_snapshot artifact → metadata(url/title/score)
    sources: list[dict[str, Any]] = []
    for a in arts.get("source_snapshot", []):
        m = _meta(a)
        sources.append({
            "source_id": m.get("url") or f"src_{a.round_no}_{a.id[:8]}",
            "url": (m.get("url") or "").strip(),
            "source_type": "article",
            "fetched_at": "",
            "snapshot": (a.content or "")[:300],
            "title": m.get("title") or "",
            "score": m.get("score"),
        })

    # evidence：evidence_item artifact，content 是 EvidenceItem.model_dump JSON
    evidence: list[dict[str, Any]] = []
    for i, a in enumerate(arts.get("evidence_item", []), 1):
        ev_text = ""
        claim_tag = ""
        source_id = ""
        try:
            d = json.loads(a.content) if a.content else {}
            ev_text = d.get("evidence_text") or d.get("branch_summary") or a.content or ""
            claim_tag = d.get("claim") or d.get("section_hint") or ""
            source_id = d.get("source_url") or ""
        except Exception:  # noqa: BLE001
            ev_text = a.content or ""
        evidence.append({
            "evidence_id": f"ev_{i}",
            "evidence_text": ev_text,
            "claim": claim_tag,
            "source_id": source_id,
            "strength": _meta(a).get("strength", "medium"),
            "_artifact_id": a.id,
        })
        # 把 source_url 回填到 sources 的 source_id 映射（evidence.source_id 用 url）
    # 重建 evidence→source 关联：evidence.source_id 是 url，sources.source_id 也是 url
    src_by_url = {s["url"]: s for s in sources if s["url"]}
    for ev in evidence:
        if ev["source_id"] in src_by_url:
            ev["source_id"] = src_by_url[ev["source_id"]]["source_id"]

    # review + rounds：round_review artifact，content 是 decision JSON（含 nextAction/blockingGaps/score）
    review: dict[str, Any] = {"blocking_gaps": [], "score": 0.0, "next_action": "", "lenses": []}
    rounds: list[dict[str, Any]] = []
    for a in sorted(arts.get("round_review", []), key=lambda x: x.round_no or 0):
        decision: dict[str, Any] = {}
        try:
            decision = json.loads(a.content) if a.content else {}
        except Exception:  # noqa: BLE001
            decision = _meta(a)
        blocking = list(decision.get("blockingGaps") or [])
        nxt = decision.get("nextAction", "")
        score = decision.get("score") or (decision.get("qualityScoreboard") or {}).get("coverage", 0.0)
        if a.round_no:
            rounds.append({
                "round_no": a.round_no,
                "new_sources": [],
                "new_evidence": [],
                "gaps": blocking,
                "tokens": 0,
            })
        if blocking:
            review["blocking_gaps"] = blocking
            review["next_action"] = nxt
            review["score"] = float(score) if score else 0.0

    # reports：生产只有 report_final（无 pre/post consistency、pre/post verification 结构化）
    report_final = ""
    final_art = arts.get("report_final", [])
    if final_art:
        report_final = final_art[-1].content or ""
    reports = {"final": report_final}  # 其余键留空 → Consistency/ClaimVerifier 前后对比标 not_evaluable

    # claim_verifier：claim_verification artifact，metadata/content 含 verdict
    claim_verifier: list[dict[str, Any]] = []
    for a in arts.get("claim_verification", []):
        m = _meta(a)
        verdict = (a.outcome or m.get("verdict") or "unverified")
        claim_text = m.get("claim", "")
        # 尝试关联到 claim_id
        cid = ""
        for c in claims:
            if c.get("claim_text") and c["claim_text"] in claim_text:
                cid = c["claim_id"]
                break
        claim_verifier.append({
            "claim_id": cid,
            "verdict": verdict if verdict in ("verified", "unverified") else "unverified",
            "reason": str(m.get("verdict", "")),
            "post_action": "keep" if verdict == "verified" else "removed",
        })

    # 构造 raw dict 喂给 build_context（复用其关联建立逻辑）
    raw = {
        "case": {
            "case_id": f"real_{research_id[:12]}",
            "query": brief_text or research_id,
            "task_type": research_type or "general",
            "language": "zh-CN",
            "as_of_date": "",
            "required_points": [],  # 真实 run 无 required_points 标注
            "explicit_constraints": {"require_citations": True, "audience": "enterprise_technical_decision_maker"},
            "critical_facts": [],
            "forbidden_claims": [],
        },
        "run": run_row,
        "intent": intent,
        "plan": plan,
        "tool_calls": tool_calls,
        "context_nodes": context_nodes,
        "sources": sources,
        "evidence": evidence,
        "review": review,
        "rounds": rounds,
        "reports": reports,
        "claims": claims,
        "claim_verifier": claim_verifier,
        "gold": {},  # 真实 run 无 gold
    }
    ctx = build_context(raw)
    return ctx


async def run(research_id: str, model_id: str, output: str, chat_fn_override: ChatFn | None = None) -> dict[str, Any]:
    ctx = await build_from_real_run(research_id)
    if not ctx.completeness.get("evaluable"):
        print(f"[warn] 真实产物 EvalContext 不完整，missing={ctx.completeness.get('missing')}", file=sys.stderr)

    chat_fn: ChatFn | None = chat_fn_override
    if chat_fn is None:
        record = await _load_model_record(model_id)
        if record is None:
            raise SystemExit(f"DB model 表未找到 id={model_id}")
        chat_fn = build_chat_fn(record)

    intent = await evaluate_intent(ctx)
    review = await evaluate_review(ctx)
    claims = await evaluate_claims(ctx, chat_fn=chat_fn)
    consistency = await evaluate_consistency(ctx)
    verifier = await evaluate_claim_verifier(ctx)

    result = aggregate(ctx, intent, review, claims, consistency, verifier)
    result["research_id"] = research_id
    result["source"] = "real_ultra_run"
    write_json(result, output)
    write_markdown(result, ctx, output)
    print(f"[ok] hard_gate={result['result_eval']['hard_gate']} research_id={research_id}")
    print(f"[ok] missing={ctx.completeness.get('missing')}")
    print(f"[ok] claims={len(ctx.claims)} evidence={len(ctx.evidence)} sources={len(ctx.sources)}")
    return result


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="真实 ULTRA 产物 → MVP eval")
    p.add_argument("--research-id", required=True)
    p.add_argument("--model-id", required=True, help="Claim 判定用 LLM 的 DB model id")
    p.add_argument("--output", default="evals/mvp_output")
    args = p.parse_args(argv)
    try:
        asyncio.run(run(args.research_id, args.model_id, args.output))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
