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

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.core.config import get_settings
from app.domain.models import (
    EvalCaseRun,
    EvalDatasetItem,
    ResearchArtifact,
    ResearchClaimManifest,
    ResearchRun,
    ResearchSpanAttribute,
    ResearchStageUsage,
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


def load_dataset_json(name: str = "mvp_v1_6questions.json") -> dict[str, Any]:
    path = _DATASET_DIR / name
    return json.loads(path.read_text(encoding="utf-8"))


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
            original_budget_level=item.get("original_budget_level"),
            privacy_status="privacy_reviewed",
            annotation_status="ready",
            sample_reason=item.get("sample_reason"),
            split_name="test",
        )
        item_ids.append(iid)
    return item_ids


def default_evaluators(*, chat_fn: ChatFn | None = None, judge_model: str | None = None) -> list[BaseEvaluator]:
    """12 核心指标 + 机制/成本诊断的全套 evaluator。

    有 chat_fn 时启用 LLM judges；否则只跑确定性 + 机制/成本（离线）。
    """
    judges: list[BaseEvaluator] = [
        DeterministicEvaluator(),
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
    """从 DB 装配一个 case_run 的评估输入。"""
    async with SessionLocal() as session:
        # 关联 run_id
        case_run = await session.scalar(select(EvalCaseRun).where(EvalCaseRun.id == case_run_id))
    run_id = getattr(case_run, "run_id", None) if case_run else None
    # eval_case_run 直链字段（§18 score→trace/artifact 跳转与成本核算）
    estimated_cost = getattr(case_run, "estimated_cost", None) if case_run else None
    gate_passed = getattr(case_run, "gate_passed", None) if case_run else None
    run_row: dict[str, Any] = {}
    report = ""
    merged_report = ""
    report_synthesis = ""
    manifest: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    section_artifacts: dict[str, dict[str, Any]] = {}
    report_drafts: list[dict[str, Any]] = []
    artifact_counts: dict[str, int] = {}
    # trace 标量装配（research_span_attribute）与阶段 token 聚合（research_stage_usage）
    review_attributes: dict[int, dict[str, Any]] = {}
    report_quality: dict[str, Any] = {}
    reviewer_tokens: int = 0
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
                    "trace_id": run.trace_id,  # §18 score→trace 直链
                    "estimated_cost": estimated_cost,  # eval_case_run 直链
                    "gate_passed": gate_passed,  # eval_case_run 直链
                }
            arts = (
                await session.scalars(select(ResearchArtifact).where(ResearchArtifact.run_id == run_id))
            ).all()
            report_artifact_id: str | None = None
            for a in arts:
                artifact_counts[a.artifact_type] = artifact_counts.get(a.artifact_type, 0) + 1
                if a.artifact_type == "report_final":
                    report = a.content or ""
                    report_artifact_id = a.id  # §18 score→artifact 直链
                elif a.artifact_type == "report_merged":
                    merged_report = a.content or ""
                elif a.artifact_type == "source_snapshot":
                    meta: dict[str, Any] = {}
                    if a.metadata_json:
                        try:
                            meta = json.loads(a.metadata_json) or {}
                        except Exception:  # noqa: BLE001
                            meta = {}
                    sources.append(
                        {
                            "url": (meta.get("url") or "").strip(),
                            "title": meta.get("title") or "",
                            "score": meta.get("score"),
                            "round_no": a.round_no,
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
            # trace 标量落地表（research_span_attribute）装配：review.*（UltraDynamicReview，
            # per-round）+ report.quality.*（UltraReportGate）。数值类用 attr_value_num，
            # 字符串用 attr_value_str，结构化用 attr_value_json。
            span_rows = (
                await session.scalars(
                    select(ResearchSpanAttribute).where(ResearchSpanAttribute.run_id == run_id)
                )
            ).all()
            seen_lens: set[str] = set()
            for sa in span_rows:
                rno = sa.round_no or 0
                if sa.attr_value_num is not None:
                    value: Any = float(sa.attr_value_num)
                elif sa.attr_value_str is not None:
                    value = sa.attr_value_str
                elif sa.attr_value_json:
                    try:
                        value = json.loads(sa.attr_value_json) or {}
                    except Exception:  # noqa: BLE001
                        continue
                else:
                    continue
                if sa.span_scope == "UltraDynamicReview":
                    review_attributes.setdefault(rno, {})[sa.attr_key] = value
                elif sa.span_scope == "UltraReportGate":
                    report_quality[sa.attr_key] = value
            # 阶段 token 聚合（research_stage_usage）：
            # reviewer stage_name 形如 'UltraDynamicReviewer:{lens}'（每 lens 一行），
            # 用前缀匹配聚合 reviewer_tokens；lens 从 stage_name 后缀或 reviewer_lens 列取。
            stage_rows = (
                await session.scalars(
                    select(ResearchStageUsage).where(
                        ResearchStageUsage.run_id == run_id,
                        ResearchStageUsage.stage_name.like("UltraDynamicReviewer%"),
                    )
                )
            ).all()
            tok_in = 0
            tok_out = 0
            per_round_tokens: dict[int, int] = {}
            for sr in stage_rows:
                in_t = int(sr.input_tokens or 0)
                out_t = int(sr.output_tokens or 0)
                tok_in += in_t
                tok_out += out_t
                rno = sr.round_no or 0
                per_round_tokens[rno] = per_round_tokens.get(rno, 0) + in_t + out_t
                lens = sr.reviewer_lens
                if not lens and sr.stage_name and ":" in sr.stage_name:
                    lens = sr.stage_name.split(":", 1)[1]
                if lens:
                    seen_lens.add(lens)
            reviewer_tokens = tok_in + tok_out
            reviewer_lenses = sorted(seen_lens)
            run_row["reviewer_tokens"] = reviewer_tokens
            run_row["reviewer_lenses"] = reviewer_lenses
            # per-round reviewer tokens 回填进 review_attributes，供 round_delta 算 marginal
            for rno, rt in per_round_tokens.items():
                review_attributes.setdefault(rno, {})["review.tokens"] = rt
            # review.consensus 来自 span_attribute(UltraDynamicReview)，取最后一轮
            last_round = max(review_attributes) if review_attributes else None
            if last_round is not None:
                run_row["review_consensus"] = review_attributes[last_round].get("review.consensus")
            # §18 跳转链路：trace_id + report_artifact_id 存进 run_row，供 upsert_score 回填
            if report_artifact_id is not None:
                run_row["report_artifact_id"] = report_artifact_id
            cm = (
                await session.scalars(select(ResearchClaimManifest).where(ResearchClaimManifest.run_id == run_id))
            ).all()
            for row in cm:
                manifest.append(
                    {
                        "claim_id": row.claim_id,
                        "claim_text": row.claim_text,
                        "importance": row.importance,
                        "citations": [{"citation_url": row.citation_url, "excerpt": row.citation_excerpt}]
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
                    "required_points_json": json.loads(di.required_points_json) if di.required_points_json else [],
                    "reference_facts_json": json.loads(di.reference_facts_json) if di.reference_facts_json else [],
                }
    return EvalContext(
        case_run_id=case_run_id,
        report=report,
        dataset_item=dataset_item,
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
    # §18 跳转链路：每条 score 直链 trace_id + report_artifact_id（来自 run 行 + report_final artifact）
    score_trace_id = ctx.run.get("trace_id") if ctx.run else None
    score_report_artifact_id = ctx.run.get("report_artifact_id") if ctx.run else None

    # 阶段1：普通 evaluator（非 hard_gate）
    for ev in evaluators:
        if ev.name == "hard_gate":
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
                trace_id=score_trace_id,
                report_artifact_id=score_report_artifact_id,
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
                trace_id=score_trace_id,
                report_artifact_id=score_report_artifact_id,
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
    return all_results


async def run_experiment(
    experiment_id: str,
    *,
    chat_fn: ChatFn | None = None,
    judge_model: str | None = None,
) -> dict[str, dict[str, dict[str, float | None]]]:
    """遍历 experiment 下所有 case_run 做评估。

    返回 ``{variant_name: {case_run_id: {metric_name: score}}}``，供
    ``build_paired_diff_report`` 做跨 variant 配对差值（§18/§19）。
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
        variant = cr.variant_name or "_unknown"
        summary.setdefault(variant, {})[cr.id] = {s.metric_name: s.score_value for s in scores}
    return summary


def _metric_means(runs: dict[str, dict[str, float | None]]) -> dict[str, float]:
    """对 {case_run_id: {metric: score}} 按 metric 求均值（跳过 None）。"""
    buckets: dict[str, list[float]] = {}
    for scores in runs.values():
        for m, v in scores.items():
            if isinstance(v, (int, float)):
                buckets.setdefault(m, []).append(float(v))
    return {m: round(sum(vs) / len(vs), 4) for m, vs in buckets.items() if vs}


def build_paired_diff_report(
    experiment_summary: dict[str, dict[str, dict[str, float | None]]],
) -> str:
    """生成配对差异报告（Markdown，§18/§19 决策输出）。

    experiment_summary: ``{variant_name: {case_run_id: {metric_name: score}}}``。
    真实计算：① 每 variant 各 metric 均值；② 相邻档位（MEDIUM→HIGH→ULTRA）的 metric 差值；
    ③ cost per pass / quality uplift 的决策建议。
    """
    lines = ["# Eval 配对差异报告", ""]
    if not experiment_summary:
        lines.append("（无数据）")
        return "\n".join(lines)

    # ① 每 variant metric 均值
    means: dict[str, dict[str, float]] = {v: _metric_means(runs) for v, runs in experiment_summary.items()}
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
    variants = list(means.keys())
    lines.append("## 相邻档位差值（uplift）")
    if len(variants) >= 2:
        diff_pairs = list(zip(variants[:-1], variants[1:]))
        pair_labels = [f"{lo}→{hi}" for lo, hi in diff_pairs]
        lines.append("| Metric | " + " | ".join(pair_labels) + " |")
        lines.append("|---|" + "|".join(["---"] * len(diff_pairs)) + "|")
        for m in all_metrics:
            deltas = []
            for lo, hi in diff_pairs:
                lo_v = means[lo].get(m)
                hi_v = means[hi].get(m)
                if lo_v is not None and hi_v is not None:
                    deltas.append(f"{hi_v - lo_v:+.4f}")
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
    cost_metric = next((m for m in all_metrics if "cost" in m), None)
    if quality_metric and len(variants) >= 2:
        q_lo = _mean(variants[0], quality_metric)
        q_hi = _mean(variants[-1], quality_metric)
        if q_lo is not None and q_hi is not None:
            lines.append(
                f"- 质量代理 `{quality_metric}`：{variants[0]}={q_lo:.4f} → {variants[-1]}={q_hi:.4f}"
                f"，差值 {q_hi - q_lo:+.4f}"
            )
    if cost_metric and len(variants) >= 2:
        c_lo = _mean(variants[0], cost_metric)
        c_hi = _mean(variants[-1], cost_metric)
        if c_lo is not None and c_hi is not None and c_hi > 0:
            q_lo = _mean(variants[0], quality_metric) or 0
            q_hi = _mean(variants[-1], quality_metric) or 0
            if q_hi - q_lo > 0 and c_hi - c_lo > 0:
                marginal = (q_hi - q_lo) / max(c_hi - c_lo, 1e-9)
                lines.append(
                    f"- 边际质量/成本：升级 {variants[0]}→{variants[-1]}，"
                    f"质量 +{q_hi - q_lo:.4f} / 成本 +{c_hi - c_lo:.4f} = {marginal:.4f} 质量/单位成本"
                )
    lines += [
        "- 哪些 Task Type 在 HIGH/ULTRA 上有正 Uplift？见 `synthesis_uplift` / `quality_delta_per_round`。",
        "- 哪个机制被更轻量 Variant 支配？比较 `marginal_quality_per_1k_tokens`。",
        "- Reviewer 哪个 Lens 有效？见 `reviewer_consensus_predictiveness`。",
        "- ClaimVerifier 是否值得全量跑？见 `unsupported_claim_detection_recall` vs `verification_token_cost`。",
    ]
    return "\n".join(lines)
