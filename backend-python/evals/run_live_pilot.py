"""正式 Eval Dataset 的两题三档真实试跑入口。

默认选取：
- fv1_fact_02：边界清楚的 NIST 标准事实题；
- fv1_ec_01：适合 Reviewer / 多轮研究的证据冲突题。

运行流程：
1. 把正式 Dataset 幂等写入 eval_dataset_item；
2. 创建一个 tier_comparison experiment；
3. 每题分别真实运行 MEDIUM / HIGH / ULTRA（repeat_no 固定为 0）；
4. 关联 research_run，执行完整 evaluator，并生成 JSON + Markdown 配对报告。

本脚本不会自动执行 DDL；数据库 Eval 表结构不满足时会明确退出。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select, text

from app.core.auth import generate_token
from app.domain.models import ResearchArtifact, ResearchRun
from app.infrastructure.db import SessionLocal, engine
from app.infrastructure.eval_repository import eval_repository
from evals.diagnosis import diagnose_experiment, render_diagnosis_markdown
from evals.iteration_log import record_payload
from evals.mvp_single_case import _load_model_record, build_chat_fn
from evals.runner import (
    build_paired_diff_report,
    evaluate_case_run,
    load_dataset_json,
    seed_dataset,
)

DEFAULT_ITEM_IDS = ("fv1_fact_02", "fv1_ec_01")
DEFAULT_VARIANTS = ("MEDIUM", "HIGH", "ULTRA")
TERMINAL_SUCCESS = {"COMPLETED"}
TERMINAL_FAILURE = {
    "FAILED",
    "ERROR",
    "ABORTED",
    "CANCELLED",
    "FAILED_TOO_MANY_STEPS",
    "NEED_CLARIFICATION",
    "AWAITING_DIRECTION_CONFIRM",
}
REQUIRED_EVAL_COLUMNS = {
    "eval_dataset_item": {
        "id",
        "dataset_name",
        "dataset_version",
        "query_snapshot",
        "query_sha256",
        "evaluation_contract_json",
    },
    "eval_experiment": {"id", "dataset_name", "dataset_version", "experiment_type"},
    "eval_case_run": {
        "id",
        "experiment_id",
        "dataset_item_id",
        "variant_name",
        "repeat_no",
        "run_id",
    },
    "eval_score": {
        "id",
        "case_run_id",
        "metric_name",
        "evaluator_name",
        "evaluator_version",
    },
}


def _log(message: str) -> None:
    print(message, flush=True)


async def _check_eval_schema() -> None:
    """只读确认正式 Eval 所需表列存在，不在试跑脚本中隐式迁移数据库。"""
    table_names = tuple(REQUIRED_EVAL_COLUMNS)
    placeholders = ", ".join(f":table_{idx}" for idx in range(len(table_names)))
    params = {f"table_{idx}": name for idx, name in enumerate(table_names)}
    query = text(
        "SELECT TABLE_NAME, COLUMN_NAME "
        "FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() "
        f"AND TABLE_NAME IN ({placeholders})"
    )
    async with SessionLocal() as session:
        rows = (await session.execute(query, params)).all()
    actual: dict[str, set[str]] = {}
    for table_name, column_name in rows:
        actual.setdefault(str(table_name), set()).add(str(column_name))
    problems: list[str] = []
    for table_name, required in REQUIRED_EVAL_COLUMNS.items():
        missing = sorted(required - actual.get(table_name, set()))
        if missing:
            problems.append(f"{table_name}: missing={missing}")
    if problems:
        joined = "; ".join(problems)
        raise RuntimeError(
            "Eval 数据库结构不满足试跑要求；请先执行非破坏性的 Eval 建表迁移 "
            f"migrations/20260721_eval_mvp_v2_eval_tables.sql。{joined}"
        )


async def _latest_run(research_id: str, wait_seconds: int = 30) -> ResearchRun | None:
    """终态后等待 research_run 收尾，避免 API 状态先于异步快照提交。"""
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        async with SessionLocal() as session:
            run = await session.scalar(
                select(ResearchRun)
                .where(ResearchRun.research_id == research_id)
                .order_by(ResearchRun.attempt_no.desc())
                .limit(1)
            )
        if run is not None and run.end_time is not None:
            return run
        await asyncio.sleep(2)
    return run


async def _run_one_live_case(
    client: httpx.AsyncClient,
    *,
    headers: dict[str, str],
    research_id: str,
    item: dict[str, Any],
    variant: str,
    model_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    label = f"{item['item_id']}/{variant}"
    _log(f"[created] {label} research_id={research_id}")

    sent = await client.post(
        f"/api/v1/research/{research_id}/messages",
        headers={**headers, "Content-Type": "application/json"},
        json={
            "content": item["query_snapshot"],
            "modelId": model_id,
            "budget": variant,
            "hitlMode": "NONE",
        },
    )
    sent.raise_for_status()
    _log(f"[accepted] {label}")

    started = time.monotonic()
    deadline = started + timeout_seconds
    last_status: str | None = None
    response_data: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = await client.get(
            f"/api/v1/research/{research_id}/messages",
            headers=headers,
        )
        response.raise_for_status()
        response_data = response.json().get("data") or {}
        status = str(response_data.get("status") or "").upper()
        if status != last_status:
            _log(f"[status] {label} status={status} elapsed={int(time.monotonic() - started)}s")
            last_status = status
        if status in TERMINAL_SUCCESS | TERMINAL_FAILURE:
            break
        await asyncio.sleep(6)
    else:
        status = "TIMEOUT"

    elapsed = int(time.monotonic() - started)
    if status not in TERMINAL_SUCCESS:
        run = await _latest_run(research_id)
        return {
            "item_id": item["item_id"],
            "variant": variant,
            "research_id": research_id,
            "run_id": run.id if run is not None else None,
            "status": status,
            "outcome": run.outcome if run is not None else None,
            "elapsed_seconds": elapsed,
            "input_tokens": int(run.input_tokens or 0) if run is not None else 0,
            "output_tokens": int(run.output_tokens or 0) if run is not None else 0,
            "report_chars": 0,
            "error": str(response_data)[:1000],
        }

    run = await _latest_run(research_id)
    if run is None:
        return {
            "item_id": item["item_id"],
            "variant": variant,
            "research_id": research_id,
            "status": "COMPLETED_WITHOUT_RESEARCH_RUN",
            "elapsed_seconds": elapsed,
        }
    async with SessionLocal() as session:
        report = await session.scalar(
            select(ResearchArtifact.content)
            .where(
                ResearchArtifact.run_id == run.id,
                ResearchArtifact.artifact_type == "report_final",
            )
            .order_by(ResearchArtifact.update_time.desc())
            .limit(1)
        )
    _log(
        f"[completed] {label} elapsed={elapsed}s run_id={run.id} "
        f"tokens={int(run.input_tokens or 0) + int(run.output_tokens or 0)} "
        f"report_chars={len(report or '')}"
    )
    return {
        "item_id": item["item_id"],
        "variant": variant,
        "research_id": research_id,
        "run_id": run.id,
        "status": status,
        "outcome": run.outcome,
        "elapsed_seconds": elapsed,
        "input_tokens": int(run.input_tokens or 0),
        "output_tokens": int(run.output_tokens or 0),
        "report_chars": len(report or ""),
    }


def _score_value(score: dict[str, Any]) -> str:
    value = score.get("score_value")
    if isinstance(value, (int, float)):
        return f"{value:.4f}"
    label = score.get("label_value")
    if label is not None:
        return str(label)
    passed = score.get("passed")
    return "-" if passed is None else str(passed)


def _build_markdown(
    *,
    experiment_id: str,
    live_results: list[dict[str, Any]],
    score_results: list[dict[str, Any]],
    paired_report: str,
    diagnosis_report: str | None = None,
) -> str:
    lines = [
        "# 正式 Dataset 两题三档试跑",
        "",
        f"- experiment_id: `{experiment_id}`",
        f"- repeat_no: `0`（每题每档只跑 1 次）",
    ]
    if diagnosis_report:
        lines += ["", diagnosis_report, "", "# 原始运行与 Eval 指标"]
    lines += [
        "",
        "## 真实运行结果",
        "",
        "| Item | Variant | Status | Outcome | Tokens | Seconds | Report chars |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for row in live_results:
        tokens = int(row.get("input_tokens") or 0) + int(row.get("output_tokens") or 0)
        lines.append(
            f"| {row['item_id']} | {row['variant']} | {row.get('status', '-')} "
            f"| {row.get('outcome', '-')} | {tokens} | {row.get('elapsed_seconds', 0)} "
            f"| {row.get('report_chars', 0)} |"
        )
    lines += ["", "## 各 Case Eval 指标", ""]
    for result in score_results:
        lines += [
            f"### {result['item_id']} / {result['variant']}",
            "",
            "| Group | Metric | Value | Passed | Reason |",
            "|---|---|---:|---:|---|",
        ]
        for score in sorted(
            result.get("scores") or [],
            key=lambda item: (str(item.get("metric_group")), str(item.get("metric_name"))),
        ):
            reason = str(score.get("reason") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| {score.get('metric_group') or '-'} | {score['metric_name']} "
                f"| {_score_value(score)} | {score.get('passed', '-')} | {reason} |"
            )
        lines.append("")
    lines += ["", paired_report, ""]
    return "\n".join(lines)


async def run(args: argparse.Namespace) -> int:
    await _check_eval_schema()
    dataset = load_dataset_json(args.dataset)
    item_by_id = {str(item["item_id"]): item for item in dataset.get("items", [])}
    missing_items = [item_id for item_id in args.item_ids if item_id not in item_by_id]
    if missing_items:
        raise ValueError(f"Dataset 不存在这些 item_id: {missing_items}")
    items = [item_by_id[item_id] for item_id in args.item_ids]

    seeded_ids = await seed_dataset(args.dataset)
    dataset_db_ids = {
        str(item["item_id"]): db_id
        for item, db_id in zip(dataset.get("items", []), seeded_ids, strict=True)
    }
    model_record = await _load_model_record(args.model_id)
    if model_record is None:
        raise RuntimeError(f"model 表不存在 id={args.model_id}")
    judge_chat_fn = build_chat_fn(model_record)
    judge_model = str(model_record.get("model") or model_record.get("name") or args.model_id)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    experiment_id = await eval_repository.create_experiment(
        name=f"formal_v1_two_item_pilot_{stamp}",
        dataset_name=dataset["dataset_name"],
        dataset_version=str(dataset["dataset_version"]),
        experiment_type="tier_comparison",
        workflow_version="workspace",
        evaluator_version="live-pilot-1",
        judge_model=judge_model,
        config={
            "item_ids": list(args.item_ids),
            "variants": list(args.variants),
            "repeat_no": 0,
            "model_id": args.model_id,
        },
        status="running",
    )
    _log(f"[experiment] {experiment_id}")

    token = generate_token(args.user_id)
    headers = {"Authorization": f"Bearer {token}"}
    timeout = httpx.Timeout(30.0, connect=10.0)
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout) as client:
        case_specs = [
            (item, variant)
            for item in items
            for variant in args.variants
        ]
        # create(num=N) 会补足并返回 N 个不同的 NEW 会话。不能对 create(num=1)
        # 做并发调用，否则多个请求可能在任一请求进入 QUEUE 前拿到同一个 NEW 会话。
        created = await client.get(
            "/api/v1/research/create",
            params={"num": len(case_specs)},
            headers=headers,
        )
        created.raise_for_status()
        create_data = created.json().get("data") or {}
        research_ids = list(create_data.get("researchIds") or [])
        if len(research_ids) != len(case_specs) or len(set(research_ids)) != len(case_specs):
            raise RuntimeError(
                "create API 未返回足够的唯一 research_id："
                f"expected={len(case_specs)} actual={len(research_ids)} unique={len(set(research_ids))}"
            )
        tasks = [
            _run_one_live_case(
                client,
                headers=headers,
                research_id=research_id,
                item=item,
                variant=variant,
                model_id=args.model_id,
                timeout_seconds=args.case_timeout,
            )
            for (item, variant), research_id in zip(case_specs, research_ids, strict=True)
        ]
        live_results = list(await asyncio.gather(*tasks, return_exceptions=True))

    normalized_live_results: list[dict[str, Any]] = []
    for index, result in enumerate(live_results):
        if isinstance(result, Exception):
            item = items[index // len(args.variants)]
            variant = args.variants[index % len(args.variants)]
            _log(f"[failed] {item['item_id']}/{variant}: {result}")
            normalized_live_results.append(
                {
                    "item_id": item["item_id"],
                    "variant": variant,
                    "status": "CLIENT_ERROR",
                    "error": repr(result),
                }
            )
        else:
            normalized_live_results.append(result)

    score_results: list[dict[str, Any]] = []
    experiment_summary: dict[str, dict[str, dict[str, float | None]]] = {}
    for live in normalized_live_results:
        run_id = live.get("run_id")
        if not run_id:
            continue
        item_id = str(live["item_id"])
        variant = str(live["variant"])
        case_run_id = await eval_repository.upsert_case_run(
            experiment_id=experiment_id,
            dataset_item_id=dataset_db_ids[item_id],
            variant_name=variant,
            repeat_no=0,
            run_id=str(run_id),
        )
        _log(f"[eval] {item_id}/{variant} case_run_id={case_run_id}")
        scores = await evaluate_case_run(
            case_run_id,
            chat_fn=judge_chat_fn,
            judge_model=judge_model,
        )
        serialized = [asdict(score) for score in scores]
        score_results.append(
            {
                "item_id": item_id,
                "variant": variant,
                "case_run_id": case_run_id,
                "scores": serialized,
            }
        )
        experiment_summary.setdefault(variant, {})[f"{dataset_db_ids[item_id]}::0"] = {
            score.metric_name: score.score_value for score in scores
        }
        _log(f"[eval-completed] {item_id}/{variant} metrics={len(scores)}")

    recorded_count = sum(1 for result in normalized_live_results if result.get("run_id"))
    success_count = sum(
        1 for result in normalized_live_results if result.get("status") in TERMINAL_SUCCESS
    )
    experiment_status = "completed" if recorded_count == len(normalized_live_results) else "partial"
    await eval_repository.complete_experiment(experiment_id, status=experiment_status)

    paired_report = build_paired_diff_report(experiment_summary)
    item_metadata = {
        str(item["item_id"]): item
        for item in dataset.get("items", [])
    }
    diagnosis = diagnose_experiment(
        normalized_live_results,
        score_results,
        item_metadata=item_metadata,
    )
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_stem = f"formal_v1_two_item_pilot_{stamp}"
    json_path = output_dir / f"{output_stem}.json"
    md_path = output_dir / f"{output_stem}.md"
    payload = {
        "experiment_id": experiment_id,
        "dataset_name": dataset["dataset_name"],
        "dataset_version": dataset["dataset_version"],
        "repeat_no": 0,
        "live_results": normalized_live_results,
        "eval_results": score_results,
        "experiment_summary": experiment_summary,
        "diagnosis": diagnosis,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        _build_markdown(
            experiment_id=experiment_id,
            live_results=normalized_live_results,
            score_results=score_results,
            paired_report=paired_report,
            diagnosis_report=render_diagnosis_markdown(diagnosis),
        ),
        encoding="utf-8",
    )
    iteration_json, iteration_md = record_payload(
        payload,
        artifacts={
            "eval_json": str(json_path.resolve()),
            "eval_markdown": str(md_path.resolve()),
        },
    )
    _log(f"[output] JSON={json_path.resolve()}")
    _log(f"[output] Markdown={md_path.resolve()}")
    _log(f"[iteration] JSON={iteration_json.resolve()}")
    _log(f"[iteration] Markdown={iteration_md.resolve()}")
    _log(
        f"[summary] recorded={recorded_count}/{len(normalized_live_results)} "
        f"successful={success_count}/{len(normalized_live_results)} status={experiment_status}"
    )
    return 0 if recorded_count == len(normalized_live_results) else 1


async def rebuild_from_output(args: argparse.Namespace) -> int:
    """不重跑 Agent，只重新关联 Run 并用当前 evaluator 重建试跑报告。"""
    await _check_eval_schema()
    source_path = Path(args.rebuild_from)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    dataset = load_dataset_json(args.dataset)
    seeded_ids = await seed_dataset(args.dataset)
    dataset_db_ids = {
        str(item["item_id"]): db_id
        for item, db_id in zip(dataset.get("items", []), seeded_ids, strict=True)
    }
    model_record = await _load_model_record(args.model_id)
    if model_record is None:
        raise RuntimeError(f"model 表不存在 id={args.model_id}")
    judge_chat_fn = build_chat_fn(model_record)
    judge_model = str(model_record.get("model") or model_record.get("name") or args.model_id)

    experiment_id = str(payload["experiment_id"])
    live_results = list(payload.get("live_results") or [])
    score_results: list[dict[str, Any]] = []
    experiment_summary: dict[str, dict[str, dict[str, float | None]]] = {}
    for live in live_results:
        research_id = str(live.get("research_id") or "")
        run = await _latest_run(research_id) if research_id else None
        if run is None:
            continue
        live.update(
            {
                "run_id": run.id,
                "outcome": run.outcome,
                "input_tokens": int(run.input_tokens or 0),
                "output_tokens": int(run.output_tokens or 0),
            }
        )
        async with SessionLocal() as session:
            report = await session.scalar(
                select(ResearchArtifact.content)
                .where(
                    ResearchArtifact.run_id == run.id,
                    ResearchArtifact.artifact_type == "report_final",
                )
                .order_by(ResearchArtifact.update_time.desc())
                .limit(1)
            )
        live["report_chars"] = len(report or "")
        item_id = str(live["item_id"])
        variant = str(live["variant"])
        case_run_id = await eval_repository.upsert_case_run(
            experiment_id=experiment_id,
            dataset_item_id=dataset_db_ids[item_id],
            variant_name=variant,
            repeat_no=0,
            run_id=run.id,
        )
        _log(f"[re-eval] {item_id}/{variant} case_run_id={case_run_id}")
        scores = await evaluate_case_run(
            case_run_id,
            chat_fn=judge_chat_fn,
            judge_model=judge_model,
        )
        serialized = [asdict(score) for score in scores]
        score_results.append(
            {
                "item_id": item_id,
                "variant": variant,
                "case_run_id": case_run_id,
                "scores": serialized,
            }
        )
        experiment_summary.setdefault(variant, {})[f"{dataset_db_ids[item_id]}::0"] = {
            score.metric_name: score.score_value for score in scores
        }

    recorded_count = sum(1 for live in live_results if live.get("run_id"))
    experiment_status = "completed" if recorded_count == len(live_results) else "partial"
    await eval_repository.complete_experiment(experiment_id, status=experiment_status)
    payload["live_results"] = live_results
    payload["eval_results"] = score_results
    payload["experiment_summary"] = experiment_summary
    payload["rebuilt_with_evaluator_version"] = "current-workspace"

    paired_report = build_paired_diff_report(experiment_summary)
    item_metadata = {
        str(item["item_id"]): item
        for item in dataset.get("items", [])
    }
    diagnosis = diagnose_experiment(
        live_results,
        score_results,
        item_metadata=item_metadata,
    )
    payload["diagnosis"] = diagnosis
    final_json_path = source_path.with_name(f"{source_path.stem}_final.json")
    final_md_path = source_path.with_name(f"{source_path.stem}_final.md")
    final_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    final_md_path.write_text(
        _build_markdown(
            experiment_id=experiment_id,
            live_results=live_results,
            score_results=score_results,
            paired_report=paired_report,
            diagnosis_report=render_diagnosis_markdown(diagnosis),
        ),
        encoding="utf-8",
    )
    iteration_json, iteration_md = record_payload(
        payload,
        artifacts={
            "eval_json": str(final_json_path.resolve()),
            "eval_markdown": str(final_md_path.resolve()),
        },
    )
    _log(f"[output] JSON={final_json_path.resolve()}")
    _log(f"[output] Markdown={final_md_path.resolve()}")
    _log(f"[iteration] JSON={iteration_json.resolve()}")
    _log(f"[iteration] Markdown={iteration_md.resolve()}")
    _log(f"[summary] recorded={recorded_count}/{len(live_results)} status={experiment_status}")
    await engine.dispose()
    return 0 if recorded_count == len(live_results) else 1


def diagnose_existing_output(args: argparse.Namespace) -> int:
    """只消费现有 JSON，不访问 Agent/DB/Judge，补充自动根因诊断报告。"""
    source_path = Path(args.diagnose_from)
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    dataset = load_dataset_json(args.dataset)
    item_metadata = {
        str(item["item_id"]): item
        for item in dataset.get("items", [])
    }
    live_results = list(payload.get("live_results") or [])
    score_results = list(payload.get("eval_results") or [])
    experiment_summary = payload.get("experiment_summary") or {}
    diagnosis = diagnose_experiment(
        live_results,
        score_results,
        item_metadata=item_metadata,
    )
    payload["diagnosis"] = diagnosis
    paired_report = build_paired_diff_report(experiment_summary)
    diagnosed_json_path = source_path.with_name(f"{source_path.stem}_diagnosed.json")
    diagnosed_md_path = source_path.with_name(f"{source_path.stem}_diagnosed.md")
    diagnosed_json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    diagnosed_md_path.write_text(
        _build_markdown(
            experiment_id=str(payload["experiment_id"]),
            live_results=live_results,
            score_results=score_results,
            paired_report=paired_report,
            diagnosis_report=render_diagnosis_markdown(diagnosis),
        ),
        encoding="utf-8",
    )
    iteration_json, iteration_md = record_payload(
        payload,
        artifacts={
            "eval_json": str(diagnosed_json_path.resolve()),
            "eval_markdown": str(diagnosed_md_path.resolve()),
        },
    )
    _log(f"[output] JSON={diagnosed_json_path.resolve()}")
    _log(f"[output] Markdown={diagnosed_md_path.resolve()}")
    _log(f"[iteration] JSON={iteration_json.resolve()}")
    _log(f"[iteration] Markdown={iteration_md.resolve()}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="正式 Dataset 两题三档真实试跑")
    parser.add_argument(
        "--dataset",
        default="formal_v1_40questions.json",
        help="evals/datasets 下的 Dataset 文件名",
    )
    parser.add_argument("--item-ids", nargs="+", default=list(DEFAULT_ITEM_IDS))
    parser.add_argument("--variants", nargs="+", default=list(DEFAULT_VARIANTS))
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--user-id", type=int, default=3)
    parser.add_argument(
        "--model-id",
        default="bda582c2d9824a3ab1486b7eb6169f09",
    )
    parser.add_argument("--case-timeout", type=int, default=2400)
    parser.add_argument("--output", default="evals/pilot_output")
    parser.add_argument(
        "--rebuild-from",
        default=None,
        help="已有试跑 JSON；提供后不重跑 Agent，只关联 Run 并用当前 evaluator 重建报告",
    )
    parser.add_argument(
        "--diagnose-from",
        default=None,
        help="已有完整试跑 JSON；仅生成根因诊断，不访问 Agent、DB 或 Judge",
    )
    args = parser.parse_args(argv)
    args.variants = [str(variant).upper() for variant in args.variants]
    invalid = sorted(set(args.variants) - set(DEFAULT_VARIANTS))
    if invalid:
        parser.error(f"不支持的 variant: {invalid}")
    try:
        if args.diagnose_from:
            return diagnose_existing_output(args)
        if args.rebuild_from:
            return asyncio.run(rebuild_from_output(args))
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        _log("[stopped] 用户中断")
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"[error] {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
