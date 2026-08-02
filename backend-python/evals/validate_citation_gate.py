"""按 Hard Gate 的确定性口径复验既有 Run 的引用链路，不重跑 LLM Judge。"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.domain.models import ResearchClaimManifest
from app.infrastructure.db import SessionLocal, engine


def _before_metrics(payload: dict[str, Any]) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    for case in payload.get("eval_results") or []:
        scores = {
            str(score.get("metric_name")): score
            for score in case.get("scores") or []
        }
        gate = scores.get("hard_gate_passed") or {}
        result[(str(case.get("item_id")), str(case.get("variant")))] = {
            "citation_traceability": (scores.get("citation_traceability") or {}).get(
                "score_value"
            ),
            "unsupported_critical_claim_count": (
                scores.get("unsupported_critical_claim_count") or {}
            ).get("score_value"),
            "failure_reason_codes": (gate.get("details") or {}).get(
                "failure_reason_codes"
            )
            or [],
        }
    return result


async def validate_run(run_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        rows = (
            await session.scalars(
                select(ResearchClaimManifest).where(
                    ResearchClaimManifest.run_id == run_id
                )
            )
        ).all()
    claims: dict[str, dict[str, Any]] = {}
    for row in rows:
        claim = claims.setdefault(
            row.claim_id,
            {"importance": row.importance or "minor", "has_url": False},
        )
        claim["has_url"] = claim["has_url"] or bool(row.citation_url)
    total = len(claims)
    cited = sum(bool(claim["has_url"]) for claim in claims.values())
    traceability = cited / total if total else None
    unsupported = sum(
        claim["importance"] == "critical" and not claim["has_url"]
        for claim in claims.values()
    )
    failure_codes: list[str] = []
    if traceability is not None and traceability < 0.95:
        failure_codes.append("dangling_citation")
    if unsupported > 0:
        failure_codes.append("unsupported_critical_claim")
    return {
        "claim_count": total,
        "cited_claim_count": cited,
        "citation_traceability": traceability,
        "unsupported_critical_claim_count": unsupported,
        "citation_gate_passed": not failure_codes,
        "failure_reason_codes": failure_codes,
    }


async def run(source_path: Path, output_path: Path | None = None) -> int:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    before = _before_metrics(payload)
    results: list[dict[str, Any]] = []
    for item in payload.get("live_results") or []:
        if not item.get("run_id"):
            continue
        key = (str(item.get("item_id")), str(item.get("variant")))
        after = await validate_run(str(item["run_id"]))
        results.append(
            {
                "item_id": key[0],
                "variant": key[1],
                "run_id": item["run_id"],
                "before": before.get(key) or {},
                "after": after,
            }
        )
    output = {
        "experiment_id": payload.get("experiment_id"),
        "validation_scope": (
            "citation-only Hard Gate：citation_traceability 与 "
            "unsupported_critical_claim_count；不重跑 LLM Judge"
        ),
        "results": results,
    }
    destination = output_path or source_path.with_name(
        f"{source_path.stem}_citation_validation.json"
    )
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[validation] output={destination.resolve()}")
    for result in results:
        after = result["after"]
        print(
            f"[validation] {result['item_id']}/{result['variant']} "
            f"traceability={after['citation_traceability']} "
            f"unsupported={after['unsupported_critical_claim_count']} "
            f"passed={after['citation_gate_passed']} "
            f"failures={after['failure_reason_codes']}"
        )
    await engine.dispose()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-json", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    return asyncio.run(
        run(
            Path(args.from_json),
            Path(args.output) if args.output else None,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
