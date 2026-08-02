"""Eval MVP v2 Commit 6e — Runner。

两条路径：
1. ``seed_dataset``：把 6 题 JSON 灌进 eval_dataset_item（供配对回放）。
2. ``evaluate_case_run``：给定已跑完的 case_run（run_id 已落库），从 research_artifact
   读 report_final + claim_manifest + run 行，装配 EvalContext，跑全部 evaluator，写
   eval_score。
3. ``run_experiment``：遍历 experiment 下所有 case_run 做评估并聚合。

真实「回放一次研究」(replay) 需调用 pipeline + live LLM/Tavily，留给集成 smoke；
本模块聚焦「评估侧」可离线、可单测。
"""
from __future__ import annotations

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.domain.models import (
    EvalCaseRun,
    EvalDatasetItem,
    ResearchArtifact,
    ResearchClaimManifest,
    ResearchLlmCall,
    ResearchRun,
)
from app.infrastructure.db import SessionLocal
from app.infrastructure.eval_repository import eval_repository
from evals.evaluators.base import BaseEvaluator, ChatFn, EvalContext
from evals.evaluators.claim_extractor import ClaimExtractorEvaluator
from evals.evaluators.cost_effectiveness import CostEffectivenessEvaluator
from evals.evaluators.citation_judge import CitationJudgeEvaluator
from evals.evaluators.coverage_judge import CoverageJudgeEvaluator
from evals.evaluators.deterministic import DeterministicEvaluator
from evals.evaluators.hard_gate import HardGateEvaluator
from evals.evaluators.intent_alignment import IntentAlignmentEvaluator
from evals.evaluators.report_quality_judge import ReportQualityJudgeEvaluator
from evals.evaluators.reviewer_effectiveness import ReviewerEffectivenessEvaluator
from evals.evaluators.round_delta import RoundDeltaEvaluator
from evals.evaluators.section_loss import RevisionMergeLossEvaluator
from evals.evaluators.source_freshness import SourceFreshnessEvaluator
from evals.evaluators.source_quality_judge import SourceQualityJudgeEvaluator
from evals.evaluators.synthesis_uplift import SynthesisUpliftEvaluator
from evals.schemas import MetricResult

logger = logging.getLogger(__name__)

_DATASET_DIR = Path(__file__).resolve().parent / "datasets"

_MECHANISM_TAG_BY_SUITE = {
    "high_report_ablation": "synthesis_applicable",
    "reviewer_ablation": "reviewer_applicable",
    "multi_round_ablation": "multi_round_applicable",
    "section_team_ablation": "section_team_applicable",
    "claim_verifier_ablation": "claim_verifier_applicable",
}

_SUPPORTED_RESEARCH_TYPES = {
    "tech_comparison",
    "market_analysis",
    "academic_review",
    "fact_lookup",
    "trend_forecast",
    "general",
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """递归合并 Dataset 默认值，避免 40 个 Item 重复同一份契约。"""
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_dataset_json(name: str = "mvp_v1_6questions.json") -> dict[str, Any]:
    """加载并展开 Dataset 默认值和机制抽样标签。

    源 JSON 保持适合人工维护的紧凑形式；返回值中的每个 Item 都是可直接落库的
    完整契约。``mechanism_suites`` 是机制样本的唯一选择清单，并同步展开为 Item
    的 ``mechanism_tags``，避免清单和标签分别维护后发生漂移。
    """
    path = _DATASET_DIR / name
    data = json.loads(path.read_text(encoding="utf-8"))
    defaults = data.get("defaults") or {}
    mechanism_suites = data.get("mechanism_suites") or {}
    memberships: dict[str, set[str]] = {}
    for suite_name, item_ids in mechanism_suites.items():
        for item_id in item_ids:
            memberships.setdefault(str(item_id), set()).add(str(suite_name))

    normalized_items: list[dict[str, Any]] = []
    for raw_item in data.get("items", []):
        item = _deep_merge(defaults, raw_item)
        contract = item.setdefault("evaluation_contract", {})
        expected_type = (contract.get("expected_intent") or {}).get("research_type")
        if expected_type not in _SUPPORTED_RESEARCH_TYPES:
            raise ValueError(
                f"item {item.get('item_id')} expected_intent.research_type "
                f"不在 Agent 路由枚举中: {expected_type}"
            )
        constraints = contract.setdefault("constraints", {})
        constraints["language"] = item.get("language")
        constraints["as_of_date"] = item.get("as_of_date")
        tags = contract.setdefault("mechanism_tags", {})
        for suite_name in memberships.get(str(item.get("item_id")), set()):
            tag_name = _MECHANISM_TAG_BY_SUITE.get(suite_name)
            if tag_name:
                tags[tag_name] = True
        normalized_items.append(item)
    data["items"] = normalized_items
    return data


def select_mechanism_item_ids(data: dict[str, Any], suite_name: str) -> list[str]:
    """从正式 E2E Dataset 中抽取某个机制实验的 Item ID。"""
    suites = data.get("mechanism_suites") or {}
    if suite_name not in suites:
        raise KeyError(f"unknown mechanism suite: {suite_name}")
    known_ids = {str(item.get("item_id")) for item in data.get("items", [])}
    selected = [str(item_id) for item_id in suites[suite_name]]
    missing = sorted(set(selected) - known_ids)
    if missing:
        raise ValueError(f"mechanism suite {suite_name} contains unknown item ids: {missing}")
    return selected


async def seed_dataset(json_path: str | None = None) -> list[str]:
    """把 dataset JSON 灌进 eval_dataset_item。幂等（同 query_sha256 去重）。

    返回写入的 dataset_item_id 列表。
    """
    data = load_dataset_json(json_path) if json_path else load_dataset_json()
    item_ids: list[str] = []
    for item in data.get("items", []):
        iid = await eval_repository.upsert_dataset_item(
            dataset_name=data["dataset_name"],
            dataset_version=data["dataset_version"],
            query_snapshot=item["query_snapshot"],
            item_id=item["item_id"],
            task_type=item.get("task_type"),
            language=item.get("language"),
            as_of_date=item.get("as_of_date"),
            required_points=item.get("required_points"),
            reference_facts=item.get("reference_facts"),
            forbidden_claims=item.get("forbidden_claims"),
            source_policy=item.get("source_policy"),
            evaluation_contract=item.get("evaluation_contract"),
            privacy_status=item.get("privacy_status") or "privacy_reviewed",
            annotation_status=item.get("annotation_status") or "ready",
            sample_reason=item.get("sample_reason"),
            split_name=item.get("split_name") or "test",
        )
        item_ids.append(iid)
    return item_ids


def default_evaluators(*, chat_fn: ChatFn | None = None, judge_model: str | None = None) -> list[BaseEvaluator]:
    """12 核心指标 + 机制/成本诊断的全套 evaluator。

    有 chat_fn 时启用 LLM judges；否则只跑确定性 + 机制/成本（离线）。
    """
    judges: list[BaseEvaluator] = [
        DeterministicEvaluator(),
        IntentAlignmentEvaluator(),
        ClaimExtractorEvaluator(),
        CostEffectivenessEvaluator(),
        ReviewerEffectivenessEvaluator(),
        RoundDeltaEvaluator(),
        SourceFreshnessEvaluator(),
        RevisionMergeLossEvaluator(),
        SynthesisUpliftEvaluator(),
    ]
    if chat_fn is not None:
        judges += [
            CitationJudgeEvaluator(chat_fn=chat_fn, judge_model=judge_model),
            CoverageJudgeEvaluator(chat_fn=chat_fn, judge_model=judge_model),
            ReportQualityJudgeEvaluator(chat_fn=chat_fn, judge_model=judge_model),
            SourceQualityJudgeEvaluator(chat_fn=chat_fn, judge_model=judge_model),
        ]
    # HardGate 后置聚合器：读其他 evaluator 的 prior_results 做 gate 判定（两阶段跑）
    judges.append(HardGateEvaluator())
    return judges


async def _load_case_context(case_run_id: str) -> EvalContext:
    """从精简后的 8 张核心表装配一个 case_run 的评估输入。

    过程正文统一读取 ``research_artifact``；成本事实读取 ``research_llm_call``。
    不再从 ``research_span_attribute`` / ``research_stage_usage`` / workflow_event
    拼装重复事实。
    """

    def _json_dict(raw: str | None) -> dict[str, Any]:
        if not raw:
            return {}
        try:
            value = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {}
        return value if isinstance(value, dict) else {}

    def _review_attrs(decision: dict[str, Any]) -> dict[str, Any]:
        summary = decision.get("reviewSummary") if isinstance(decision.get("reviewSummary"), dict) else {}
        scoreboard = (
            decision.get("qualityScoreboard")
            if isinstance(decision.get("qualityScoreboard"), dict)
            else {}
        )
        gaps = list(decision.get("blockingGaps") or [])
        attrs: dict[str, Any] = {
            "review.next.action": decision.get("nextAction"),
            "review.continue.votes": int(summary.get("continueVotes") or 0),
            "review.report.votes": int(summary.get("reportVotes") or 0),
            "review.total.votes": int(summary.get("totalVotes") or 0),
            "review.consensus": summary.get("consensus"),
            "review.gaps.count": len(gaps),
        }
        for dim in ("coverage", "evidence", "freshness", "sourceDiversity", "consistency"):
            score = scoreboard.get(dim)
            if isinstance(score, (int, float)):
                attrs[f"review.score.{dim}"] = float(score)
        return attrs

    async with SessionLocal() as session:
        case_run = await session.scalar(select(EvalCaseRun).where(EvalCaseRun.id == case_run_id))
    run_id = getattr(case_run, "run_id", None) if case_run else None
    estimated_cost = getattr(case_run, "estimated_cost", None) if case_run else None
    gate_passed = getattr(case_run, "gate_passed", None) if case_run else None
    run_row: dict[str, Any] = {}
    report = ""
    research_brief = ""
    intent_metadata: dict[str, Any] = {}
    research_plans: list[dict[str, Any]] = []
    evidence_items: list[dict[str, Any]] = []
    round_reviews: list[dict[str, Any]] = []
    merged_report = ""
    report_synthesis = ""
    manifest: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    section_artifacts: dict[str, dict[str, Any]] = {}
    report_drafts: list[dict[str, Any]] = []
    artifact_counts: dict[str, int] = {}
    review_attributes: dict[int, dict[str, Any]] = {}
    report_quality: dict[str, Any] = {}
    reviewer_lenses: list[str] = []
    if run_id:
        async with SessionLocal() as session:
            run = await session.scalar(select(ResearchRun).where(ResearchRun.id == run_id))
            if run:
                run_row = {
                    "outcome": run.outcome,
                    "input_tokens": run.input_tokens,
                    "output_tokens": run.output_tokens,
                    "duration_ms": run.active_duration_ms,
                    "budget_level": run.budget_level,
                    "trace_id": run.trace_id,
                    "estimated_cost": estimated_cost,
                    "gate_passed": gate_passed,
                }
            arts = (
                await session.scalars(select(ResearchArtifact).where(ResearchArtifact.run_id == run_id))
            ).all()
            for a in arts:
                artifact_counts[a.artifact_type] = artifact_counts.get(a.artifact_type, 0) + 1
                meta = _json_dict(a.metadata_json)
                if a.artifact_type == "report_final":
                    report = a.content or ""
                elif a.artifact_type == "research_brief":
                    research_brief = a.content or ""
                    intent_metadata = meta
                elif a.artifact_type == "research_plan":
                    plan = _json_dict(a.content)
                    plan.setdefault("round_no", a.round_no or 0)
                    plan["artifact_id"] = a.id
                    research_plans.append(plan)
                elif a.artifact_type == "evidence_item":
                    evidence = _json_dict(a.content)
                    evidence.update(
                        {
                            "artifact_id": a.id,
                            "round_no": a.round_no or 0,
                            "section_id": a.section_id or None,
                            "task_key": meta.get("task_key"),
                            "branch_index": meta.get("branch_index"),
                            "task_title": meta.get("task_title"),
                            "research_topic": meta.get("research_topic"),
                        }
                    )
                    evidence_items.append(evidence)
                elif a.artifact_type == "round_review":
                    decision = _json_dict(a.content)
                    if not decision:
                        decision = dict(meta)
                    decision["artifact_id"] = a.id
                    decision["round_no"] = a.round_no or 0
                    round_reviews.append(decision)
                    review_attributes[a.round_no or 0] = _review_attrs(decision)
                elif a.artifact_type == "report_merged":
                    merged_report = a.content or ""
                elif a.artifact_type == "source_snapshot":
                    sources.append(
                        {
                            "url": (meta.get("url") or "").strip(),
                            "title": meta.get("title") or "",
                            "score": meta.get("score"),
                            "round_no": a.round_no,
                            "task_key": meta.get("task_key"),
                            "branch_index": meta.get("branch_index"),
                        }
                    )
                elif a.artifact_type in ("report_section_draft", "report_section_revision"):
                    sid = a.section_id or "_default"
                    slot = "draft" if a.artifact_type == "report_section_draft" else "revision"
                    section_artifacts.setdefault(sid, {})[slot] = a.content or ""
                elif a.artifact_type == "report_draft":
                    report_drafts.append(
                        {"angle": a.angle or "unknown", "content": a.content or "", "round_no": a.round_no}
                    )
                elif a.artifact_type == "report_synthesis":
                    report_synthesis = a.content or ""

            research_plans.sort(key=lambda item: int(item.get("round_no") or 0))
            evidence_items.sort(key=lambda item: int(item.get("round_no") or 0))
            round_reviews.sort(key=lambda item: int(item.get("round_no") or 0))

            # Token 唯一事实源：research_llm_call。research_stage_usage 只是可重建投影。
            llm_calls = (
                await session.scalars(select(ResearchLlmCall).where(ResearchLlmCall.run_id == run_id))
            ).all()
            seen_lens: set[str] = set()
            reviewer_tokens = 0
            per_round_tokens: dict[int, int] = {}
            for call in llm_calls:
                stage_name = call.stage_name or ""
                if not stage_name.startswith("UltraDynamicReviewer"):
                    continue
                tokens = int(call.input_tokens or 0) + int(call.output_tokens or 0)
                reviewer_tokens += tokens
                rno = call.round_no or 0
                per_round_tokens[rno] = per_round_tokens.get(rno, 0) + tokens
                lens = call.reviewer_lens
                if not lens and ":" in stage_name:
                    lens = stage_name.split(":", 1)[1]
                if lens:
                    seen_lens.add(lens)
            reviewer_lenses = sorted(seen_lens)
            run_row["reviewer_tokens"] = reviewer_tokens
            run_row["reviewer_lenses"] = reviewer_lenses
            for rno, rt in per_round_tokens.items():
                review_attributes.setdefault(rno, {})["review.tokens"] = rt

            last_round = max(review_attributes) if review_attributes else None
            if last_round is not None:
                run_row["review_consensus"] = review_attributes[last_round].get("review.consensus")
            if round_reviews:
                last_decision = round_reviews[-1]
                blocking_gaps = list(last_decision.get("blockingGaps") or [])
                weak_sections = [
                    item
                    for item in list(last_decision.get("sectionScoreboard") or [])
                    if isinstance(item, dict) and item.get("status") != "ready"
                ]
                report_quality = {
                    "report.quality.status": (
                        "ready"
                        if last_decision.get("nextAction") == "report" and not blocking_gaps
                        else "needs_disclosure"
                    ),
                    "report.weak.sections.count": len(weak_sections),
                    "report.blocking.gaps.count": len(blocking_gaps),
                    "report.blocking.gaps": blocking_gaps,
                }

            cm = (
                await session.scalars(select(ResearchClaimManifest).where(ResearchClaimManifest.run_id == run_id))
            ).all()
            for row in cm:
                manifest.append(
                    {
                        "claim_id": row.claim_id,
                        "claim_text": row.claim_text,
                        "importance": row.importance,
                        "citations": [
                            {
                                "citation_url": row.citation_url,
                                "excerpt": row.citation_excerpt,
                                "evidence_id": row.evidence_id,
                            }
                        ]
                        if row.citation_url
                        else [],
                    }
                )
    # dataset_item 上下文
    dataset_item: dict[str, Any] = {}
    if case_run and getattr(case_run, "dataset_item_id", None):
        async with SessionLocal() as session:
            di = await session.scalar(
                select(EvalDatasetItem).where(EvalDatasetItem.id == case_run.dataset_item_id)
            )
            if di:
                dataset_item = {
                    "query_snapshot": di.query_snapshot,
                    "task_type": di.task_type,
                    "language": di.language,
                    "as_of_date": str(di.as_of_date) if di.as_of_date else None,
                    "required_points_json": json.loads(di.required_points_json) if di.required_points_json else [],
                    "reference_facts_json": json.loads(di.reference_facts_json) if di.reference_facts_json else [],
                    "forbidden_claims_json": json.loads(di.forbidden_claims_json)
                    if di.forbidden_claims_json
                    else [],
                    "source_policy_json": json.loads(di.source_policy_json) if di.source_policy_json else {},
                    "evaluation_contract_json": json.loads(di.evaluation_contract_json)
                    if di.evaluation_contract_json
                    else {},
                }
    return EvalContext(
        case_run_id=case_run_id,
        report=report,
        dataset_item=dataset_item,
        research_brief=research_brief,
        intent_metadata=intent_metadata,
        research_plans=research_plans,
        evidence_items=evidence_items,
        round_reviews=round_reviews,
        claim_manifest=manifest,
        sources=sources,
        section_artifacts=section_artifacts,
        merged_report=merged_report,
        report_drafts=report_drafts,
        report_synthesis=report_synthesis,
        run=run_row,
        artifact_counts=artifact_counts,
        reviewer_lenses=reviewer_lenses,
        review_attributes=review_attributes,
        report_quality=report_quality,
    )


async def evaluate_case_run(
    case_run_id: str,
    *,
    evaluators: list[BaseEvaluator] | None = None,
    chat_fn: ChatFn | None = None,
    judge_model: str | None = None,
) -> list[MetricResult]:
    """评估单个 case_run：装配上下文 → 跑 evaluator → 写 eval_score。返回全部分数。

    两阶段：普通 evaluator 先跑并收集结果，塞进 ctx.prior_results 后再跑 HardGate
    后置聚合器，最终把 gate_passed/failure_reasons 回填到 eval_case_run（§8.1/§18）。
    """
    evaluators = evaluators or default_evaluators(chat_fn=chat_fn, judge_model=judge_model)
    ctx = await _load_case_context(case_run_id)
    all_results: list[MetricResult] = []

    # 阶段1：质量/过程 evaluator。成本依赖 Hard Gate，留到阶段3计算，避免把
    # 尚未回填的 gate_passed=None 错当成 0。
    for ev in evaluators:
        if ev.name in {"hard_gate", "cost_effectiveness"}:
            continue
        try:
            results = await ev.evaluate(ctx)
        except Exception:  # noqa: BLE001
            logger.exception("evaluator %s failed case_run=%s", ev.name, case_run_id)
            continue
        for r in results:
            all_results.append(r)
            await eval_repository.upsert_score(
                case_run_id=case_run_id,
                metric_name=r.metric_name,
                evaluator_name=r.evaluator_name,
                evaluator_version=r.evaluator_version,
                metric_group=r.metric_group,
                score_value=r.score_value,
                label_value=r.label_value,
                passed=r.passed,
                judge_model=r.judge_model,
                reason=r.reason,
                details=r.details,
            )
            ctx.prior_results[r.metric_name] = r

    # 阶段2：HardGate 后置聚合（读 ctx.prior_results）
    gate_ev = next((e for e in evaluators if e.name == "hard_gate"), None)
    if gate_ev is not None:
        try:
            gate_results = await gate_ev.evaluate(ctx)
        except Exception:  # noqa: BLE001
            logger.exception("hard_gate failed case_run=%s", case_run_id)
            gate_results = []
        for r in gate_results:
            all_results.append(r)
            await eval_repository.upsert_score(
                case_run_id=case_run_id,
                metric_name=r.metric_name,
                evaluator_name=r.evaluator_name,
                evaluator_version=r.evaluator_version,
                metric_group=r.metric_group,
                score_value=r.score_value,
                label_value=r.label_value,
                passed=r.passed,
                judge_model=r.judge_model,
                reason=r.reason,
                details=r.details,
            )
            # 回填 eval_case_run.gate_passed + failure_reasons_json（§18 可查询）
            failures = (r.details or {}).get("failure_reason_codes") or []
            try:
                await eval_repository.update_case_run_gate(
                    case_run_id,
                    gate_passed=int(r.score_value or 0),
                    failure_reasons=failures,
                )
            except Exception:  # noqa: BLE001
                logger.exception("update_case_run_gate failed case_run=%s", case_run_id)
            ctx.prior_results[r.metric_name] = r
            ctx.run["gate_passed"] = int(r.score_value or 0)

    # 阶段3：成本 evaluator。此时 gate_passed 已确定，可正确计算 tokens/cost per pass。
    cost_evaluators = [e for e in evaluators if e.name == "cost_effectiveness"]
    for ev in cost_evaluators:
        try:
            cost_results = await ev.evaluate(ctx)
        except Exception:  # noqa: BLE001
            logger.exception("cost evaluator failed case_run=%s", case_run_id)
            cost_results = []
        for r in cost_results:
            all_results.append(r)
            await eval_repository.upsert_score(
                case_run_id=case_run_id,
                metric_name=r.metric_name,
                evaluator_name=r.evaluator_name,
                evaluator_version=r.evaluator_version,
                metric_group=r.metric_group,
                score_value=r.score_value,
                label_value=r.label_value,
                passed=r.passed,
                judge_model=r.judge_model,
                reason=r.reason,
                details=r.details,
            )
            ctx.prior_results[r.metric_name] = r
    return all_results


async def run_experiment(
    experiment_id: str,
    *,
    chat_fn: ChatFn | None = None,
    judge_model: str | None = None,
) -> dict[str, dict[str, dict[str, float | None]]]:
    """遍历 experiment 下所有 case_run 做评估。

    返回 ``{variant_name: {dataset_item_id::repeat_no: {metric_name: score}}}``，
    让不同 Variant 按同一 Item 和 Repeat 做真实配对。
    """
    async with SessionLocal() as session:
        case_runs = (
            await session.scalars(select(EvalCaseRun).where(EvalCaseRun.experiment_id == experiment_id))
        ).all()
    summary: dict[str, dict[str, dict[str, float | None]]] = {}
    for cr in case_runs:
        if not cr.run_id:
            continue
        scores = await evaluate_case_run(cr.id, chat_fn=chat_fn, judge_model=judge_model)
        variant = cr.variant_name
        pair_key = f"{cr.dataset_item_id}::{cr.repeat_no}"
        summary.setdefault(variant, {})[pair_key] = {
            score.metric_name: score.score_value for score in scores
        }
    return summary


def _metric_means(runs: dict[str, dict[str, float | None]]) -> dict[str, float]:
    """对 {pair_key: {metric: score}} 按 metric 求均值（跳过 None）。"""
    buckets: dict[str, list[float]] = {}
    for scores in runs.values():
        for m, v in scores.items():
            if isinstance(v, (int, float)):
                buckets.setdefault(m, []).append(float(v))
    return {m: round(sum(vs) / len(vs), 4) for m, vs in buckets.items() if vs}


def _paired_metric_deltas(
    low_runs: dict[str, dict[str, float | None]],
    high_runs: dict[str, dict[str, float | None]],
) -> dict[str, float]:
    """只在双方都有同一 Item/Repeat 和 Metric 时计算 high-low。"""
    buckets: dict[str, list[float]] = {}
    for pair_key in low_runs.keys() & high_runs.keys():
        low_scores = low_runs[pair_key]
        high_scores = high_runs[pair_key]
        for metric in low_scores.keys() & high_scores.keys():
            low_value = low_scores[metric]
            high_value = high_scores[metric]
            if isinstance(low_value, (int, float)) and isinstance(high_value, (int, float)):
                buckets.setdefault(metric, []).append(float(high_value) - float(low_value))
    return {
        metric: round(sum(values) / len(values), 4)
        for metric, values in buckets.items()
        if values
    }


def build_paired_diff_report(
    experiment_summary: dict[str, dict[str, dict[str, float | None]]],
) -> str:
    """生成配对差异报告（Markdown，§18/§19 决策输出）。

    experiment_summary: ``{variant_name: {item_id::repeat_no: {metric_name: score}}}``。
    真实计算：① 每 variant 各 metric 均值；② 相邻档位仅对共同 Item/Repeat 计算配对差值；
    ③ cost per pass / quality uplift 的决策建议。
    """
    lines = ["# Eval 配对差异报告", ""]
    if not experiment_summary:
        lines.append("（无数据）")
        return "\n".join(lines)

    # ① 每 variant metric 均值
    tier_order = ("MEDIUM", "HIGH", "ULTRA")
    variants = [variant for variant in tier_order if variant in experiment_summary]
    variants.extend(sorted(set(experiment_summary) - set(variants)))
    means: dict[str, dict[str, float]] = {
        variant: _metric_means(experiment_summary[variant]) for variant in variants
    }
    all_metrics = sorted({m for vm in means.values() for m in vm})
    lines.append("## 各 Variant 指标均值")
    header = "| Metric | " + " | ".join(means.keys()) + " |"
    sep = "|---|" + "|".join(["---"] * len(means)) + "|"
    lines += [header, sep]
    for m in all_metrics:
        row = f"| {m} | " + " | ".join(
            (f"{means[v].get(m):.4f}" if m in means[v] else "-") for v in means
        ) + " |"
        lines.append(row)
    lines.append("")

    # ② 相邻档位差值（按 variant 顺序 MEDIUM→HIGH→ULTRA）
    lines.append("## 相邻档位差值（uplift）")
    if len(variants) >= 2:
        diff_pairs = list(zip(variants[:-1], variants[1:]))
        paired_deltas = {
            (low, high): _paired_metric_deltas(
                experiment_summary[low],
                experiment_summary[high],
            )
            for low, high in diff_pairs
        }
        pair_labels = [f"{lo}→{hi}" for lo, hi in diff_pairs]
        lines.append("| Metric | " + " | ".join(pair_labels) + " |")
        lines.append("|---|" + "|".join(["---"] * len(diff_pairs)) + "|")
        for m in all_metrics:
            deltas = []
            for lo, hi in diff_pairs:
                delta = paired_deltas[(lo, hi)].get(m)
                if delta is not None:
                    deltas.append(f"{delta:+.4f}")
                else:
                    deltas.append("-")
            lines.append(f"| {m} | {' | '.join(deltas)} |")
    else:
        lines.append("（仅一个 variant，无配对差值）")
    lines.append("")

    # ③ 决策输出（§19）
    lines.append("## 决策输出（§19）")
    # 找质量/成本代理 metric
    def _mean(v: str, m: str) -> float | None:
        return means.get(v, {}).get(m)

    # effective_citation_count 作质量代理，total_cost/cost_per_pass 作成本代理
    quality_metric = next((m for m in all_metrics if "effective_citation" in m or "coverage" in m), None)
    cost_metric = next(
        (m for m in ("total_tokens_k", "total_cost") if m in all_metrics),
        None,
    )
    edge_deltas = (
        _paired_metric_deltas(
            experiment_summary[variants[0]],
            experiment_summary[variants[-1]],
        )
        if len(variants) >= 2
        else {}
    )
    if quality_metric and len(variants) >= 2:
        q_lo = _mean(variants[0], quality_metric)
        q_hi = _mean(variants[-1], quality_metric)
        q_delta = edge_deltas.get(quality_metric)
        if q_lo is not None and q_hi is not None and q_delta is not None:
            lines.append(
                f"- 质量代理 `{quality_metric}`：{variants[0]}={q_lo:.4f} → {variants[-1]}={q_hi:.4f}"
                f"，配对差值 {q_delta:+.4f}"
            )
    if cost_metric and len(variants) >= 2:
        quality_delta = edge_deltas.get(quality_metric) if quality_metric else None
        cost_delta = edge_deltas.get(cost_metric)
        if quality_delta is not None and cost_delta is not None:
            if quality_delta > 0 and cost_delta > 0:
                marginal = quality_delta / max(cost_delta, 1e-9)
                lines.append(
                    f"- 边际质量/成本：升级 {variants[0]}→{variants[-1]}，"
                    f"质量 +{quality_delta:.4f} / 成本 +{cost_delta:.4f} "
                    f"= {marginal:.4f} 质量/单位成本"
                )
    lines += [
        "- 哪些 Task Type 在 HIGH/ULTRA 上有正 Uplift？见 `synthesis_uplift` / `quality_delta_per_round`。",
        "- 哪个机制被更轻量 Variant 支配？比较 `marginal_quality_per_1k_tokens`。",
        "- Reviewer 哪个 Lens 有效？见 `reviewer_consensus_predictiveness`。",
        "- ClaimVerifier 是否值得全量跑？见 `unsupported_claim_detection_recall` vs `verification_token_cost`。",
    ]
    return "\n".join(lines)
