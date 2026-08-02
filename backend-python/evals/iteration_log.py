"""把一次 Eval 的问题、证据、修改和复验沉淀为可版本化迭代记录。"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "iterations"


def _affected_case(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": case.get("item_id"),
        "item_label": case.get("item_label"),
        "variant": case.get("variant"),
        "research_id": case.get("research_id"),
        "run_id": case.get("run_id"),
        "hard_gate_passed": case.get("hard_gate_passed"),
    }


def build_iteration_record(
    payload: dict[str, Any],
    *,
    artifacts: dict[str, str] | None = None,
) -> dict[str, Any]:
    diagnosis = payload.get("diagnosis") or {}
    grouped: dict[str, dict[str, Any]] = {}
    for case in diagnosis.get("cases") or []:
        for cause in case.get("root_causes") or []:
            code = str(cause.get("code") or "unknown")
            problem = grouped.setdefault(
                code,
                {
                    "code": code,
                    "title": cause.get("title"),
                    "severity": cause.get("severity"),
                    "root_cause": cause.get("title"),
                    "agent_modules": list(cause.get("agent_modules") or []),
                    "recommendation": cause.get("recommendation"),
                    "affected_cases": [],
                    "evidence": [],
                },
            )
            problem["affected_cases"].append(_affected_case(case))
            problem["evidence"].append(
                {
                    "item_id": case.get("item_id"),
                    "variant": case.get("variant"),
                    "metrics": list(cause.get("evidence") or []),
                    "confidence": cause.get("confidence"),
                }
            )

    live_results = list(payload.get("live_results") or [])
    return {
        "schema_version": "1.0.0",
        "iteration_id": str(payload.get("experiment_id") or "untracked"),
        "experiment_id": payload.get("experiment_id"),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "dataset": {
            "name": payload.get("dataset_name"),
            "version": payload.get("dataset_version"),
        },
        "run_scope": {
            "case_count": len(live_results),
            "item_ids": sorted(
                {str(item.get("item_id")) for item in live_results if item.get("item_id")}
            ),
            "variants": sorted(
                {str(item.get("variant")) for item in live_results if item.get("variant")}
            ),
            "repeat_no": payload.get("repeat_no"),
            "runs": [
                {
                    "item_id": item.get("item_id"),
                    "variant": item.get("variant"),
                    "research_id": item.get("research_id"),
                    "run_id": item.get("run_id"),
                    "status": item.get("status"),
                    "outcome": item.get("outcome"),
                    "tokens": int(item.get("input_tokens") or 0)
                    + int(item.get("output_tokens") or 0),
                }
                for item in live_results
            ],
        },
        "eval_summary": diagnosis.get("summary") or {},
        "artifacts": artifacts or {},
        "problems": list(grouped.values()),
        "changes": [],
        "validation": {
            "status": "pending",
            "checks": [],
            "before_after": [],
        },
        "next_actions": list(
            (diagnosis.get("summary") or {}).get("optimization_backlog") or []
        ),
    }


def _slug(record: dict[str, Any]) -> str:
    return str(record.get("experiment_id") or record.get("iteration_id") or "untracked")


def render_iteration_markdown(record: dict[str, Any]) -> str:
    dataset = record.get("dataset") or {}
    scope = record.get("run_scope") or {}
    summary = record.get("eval_summary") or {}
    lines = [
        f"# Eval 迭代记录：{record.get('iteration_id')}",
        "",
        f"- Experiment：`{record.get('experiment_id')}`",
        f"- Dataset：`{dataset.get('name')}@{dataset.get('version')}`",
        f"- 范围：{scope.get('case_count', 0)} cases；档位 {', '.join(scope.get('variants') or [])}",
        f"- Hard Gate：{summary.get('hard_gate_pass_count', 0)}/{summary.get('case_count', 0)} 通过",
        "",
        "## 跑了什么",
        "",
        "| Item | 档位 | Run ID | 状态 | Token |",
        "|---|---|---|---|---:|",
    ]
    for run in scope.get("runs") or []:
        lines.append(
            f"| {run.get('item_id')} | {run.get('variant')} | `{run.get('run_id')}` "
            f"| {run.get('status')}/{run.get('outcome')} | {run.get('tokens', 0)} |"
        )

    lines += ["", "## 暴露了什么问题，怎么看出来的", ""]
    for problem in record.get("problems") or []:
        cases = ", ".join(
            f"{case.get('item_id')}/{case.get('variant')}"
            for case in problem.get("affected_cases") or []
        )
        evidence = "; ".join(
            ", ".join(
                f"{metric.get('metric')}={metric.get('value')}"
                for metric in item.get("metrics") or []
            )
            for item in problem.get("evidence") or []
        )
        lines += [
            f"### `{problem.get('code')}`：{problem.get('title')}",
            "",
            f"- 影响：{cases or '-'}",
            f"- 指标证据：{evidence or '-'}",
            f"- 根因模块：{', '.join(problem.get('agent_modules') or []) or '-'}",
            f"- 建议：{problem.get('recommendation') or '-'}",
            "",
        ]

    lines += ["## 怎么改的", ""]
    changes = record.get("changes") or []
    if changes:
        for change in changes:
            lines.append(
                f"- `{', '.join(change.get('problem_codes') or [])}`："
                f"{change.get('summary')}（{', '.join(change.get('files') or [])}）"
            )
    else:
        lines.append("- 尚未修改。")

    validation = record.get("validation") or {}
    lines += ["", "## 改完是否正常", "", f"- 状态：`{validation.get('status', 'pending')}`"]
    for check in validation.get("checks") or []:
        lines.append(f"- {check.get('name')}：{check.get('result')} — {check.get('evidence', '')}")
    for item in validation.get("before_after") or []:
        lines.append(
            f"- {item.get('case')} / {item.get('metric')}："
            f"{item.get('before')} → {item.get('after')}"
        )

    artifacts = record.get("artifacts") or {}
    if artifacts:
        lines += ["", "## 关联产物", ""]
        lines.extend(f"- {key}: `{value}`" for key, value in artifacts.items())
    lines.append("")
    return "\n".join(lines)


def write_iteration_record(
    record: dict[str, Any],
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(record)
    json_path = output_dir / f"{slug}.json"
    md_path = output_dir / f"{slug}.md"
    json_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_iteration_markdown(record), encoding="utf-8")
    _write_index(output_dir)
    return json_path, md_path


def _write_index(output_dir: Path) -> None:
    records: list[dict[str, Any]] = []
    for path in sorted(output_dir.glob("*.json")):
        if path.name == "index.json":
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        records.append(
            {
                "iteration_id": record.get("iteration_id"),
                "experiment_id": record.get("experiment_id"),
                "created_at": record.get("created_at"),
                "dataset": record.get("dataset"),
                "case_count": (record.get("run_scope") or {}).get("case_count"),
                "problem_codes": [
                    item.get("code") for item in record.get("problems") or []
                ],
                "validation_status": (record.get("validation") or {}).get("status"),
                "record": path.name,
            }
        )
    (output_dir / "index.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def record_payload(
    payload: dict[str, Any],
    *,
    artifacts: dict[str, str] | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[Path, Path]:
    record = build_iteration_record(payload, artifacts=artifacts)
    existing_path = output_dir / f"{_slug(record)}.json"
    if existing_path.exists():
        try:
            existing = json.loads(existing_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        record["created_at"] = existing.get("created_at") or record["created_at"]
        record["changes"] = list(existing.get("changes") or [])
        record["validation"] = existing.get("validation") or record["validation"]
    return write_iteration_record(record, output_dir=output_dir)


def update_record(
    record_path: Path,
    *,
    change: dict[str, Any] | None = None,
    validation: dict[str, Any] | None = None,
    artifacts: dict[str, str] | None = None,
) -> tuple[Path, Path]:
    record = json.loads(record_path.read_text(encoding="utf-8"))
    if change and change not in (record.get("changes") or []):
        record.setdefault("changes", []).append(change)
    if validation:
        record["validation"] = validation
    if artifacts:
        record.setdefault("artifacts", {}).update(artifacts)
    return write_iteration_record(record, output_dir=record_path.parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-json")
    source.add_argument("--record")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--change-json")
    parser.add_argument("--validation-json")
    parser.add_argument("--artifacts-json")
    args = parser.parse_args()
    if args.record:
        json_path, md_path = update_record(
            Path(args.record),
            change=json.loads(args.change_json) if args.change_json else None,
            validation=json.loads(args.validation_json) if args.validation_json else None,
            artifacts=json.loads(args.artifacts_json) if args.artifacts_json else None,
        )
        print(f"[iteration] JSON={json_path.resolve()}")
        print(f"[iteration] Markdown={md_path.resolve()}")
        return 0
    source = Path(args.from_json)
    payload = json.loads(source.read_text(encoding="utf-8"))
    json_path, md_path = record_payload(
        payload,
        artifacts={"eval_json": str(source.resolve())},
        output_dir=Path(args.output_dir),
    )
    print(f"[iteration] JSON={json_path.resolve()}")
    print(f"[iteration] Markdown={md_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
