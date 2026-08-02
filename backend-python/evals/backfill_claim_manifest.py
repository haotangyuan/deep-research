"""用当前引用解析器回填既有 Run 的 Claim Manifest，并输出逐 Run 审计结果。"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.application.claim_manifest import (
    extract_claims_from_report,
    normalize_report_citations,
)
from app.domain.models import ResearchArtifact
from app.infrastructure.db import SessionLocal, engine
from app.infrastructure.eval_repository import eval_repository


async def backfill_run(run_id: str, research_id: str) -> dict[str, Any]:
    async with SessionLocal() as session:
        report_artifact = await session.scalar(
            select(ResearchArtifact)
            .where(
                ResearchArtifact.run_id == run_id,
                ResearchArtifact.artifact_type == "report_final",
            )
            .order_by(ResearchArtifact.update_time.desc())
            .limit(1)
        )
    if report_artifact is None or not report_artifact.content:
        return {
            "run_id": run_id,
            "research_id": research_id,
            "status": "skipped",
            "reason": "report_final missing",
        }

    source_catalog = await eval_repository.load_source_catalog(run_id)
    _, audit = normalize_report_citations(
        report_artifact.content,
        source_catalog=source_catalog,
    )
    claims = extract_claims_from_report(
        report_artifact.content,
        source_catalog=source_catalog,
    )
    written = await eval_repository.replace_claim_manifest(
        run_id,
        research_id,
        report_artifact.id,
        claims,
    )
    await eval_repository.upsert_artifact(
        run_id=run_id,
        research_id=research_id,
        artifact_type="report_citation_audit",
        stage_name="EvalBackfill:citation-audit",
        round_no=report_artifact.round_no,
        content=json.dumps(audit, ensure_ascii=False),
        outcome="success" if not audit["unresolved_marker_ids"] else "unresolved_citations",
        metadata={
            "resolved_count": len(audit["resolved_marker_ids"]),
            "unresolved_count": len(audit["unresolved_marker_ids"]),
            "backfill": True,
        },
    )
    cited_claims = sum(
        any(citation.get("citation_url") for citation in claim.get("citations") or [])
        for claim in claims
    )
    unresolved_claims = [
        {
            "claim_id": claim.get("claim_id"),
            "claim_text": claim.get("claim_text"),
            "importance": claim.get("importance"),
            "citation_markers": [
                citation.get("citation_marker")
                for citation in claim.get("citations") or []
                if not citation.get("citation_url")
            ],
        }
        for claim in claims
        if not any(
            citation.get("citation_url") for citation in claim.get("citations") or []
        )
    ]
    return {
        "run_id": run_id,
        "research_id": research_id,
        "status": "backfilled",
        "claim_count": len(claims),
        "manifest_row_count": written,
        "cited_claim_count": cited_claims,
        "claim_traceability": cited_claims / len(claims) if claims else None,
        "citation_audit": audit,
        "unresolved_claims": unresolved_claims,
        "report_headings": [
            line.strip()
            for line in report_artifact.content.splitlines()
            if line.lstrip().startswith("#")
        ],
    }


async def run(source_path: Path, output_path: Path | None = None) -> int:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    targets = [
        item
        for item in payload.get("live_results") or []
        if item.get("run_id")
    ]
    results = [
        await backfill_run(str(item["run_id"]), str(item.get("research_id") or ""))
        for item in targets
    ]
    output = {
        "source_eval": str(source_path.resolve()),
        "experiment_id": payload.get("experiment_id"),
        "results": results,
    }
    destination = output_path or source_path.with_name(
        f"{source_path.stem}_citation_backfill.json"
    )
    destination.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[backfill] output={destination.resolve()}")
    for result in results:
        audit = result.get("citation_audit") or {}
        print(
            f"[backfill] run={result['run_id']} status={result['status']} "
            f"traceability={result.get('claim_traceability')} "
            f"unresolved={audit.get('unresolved_marker_ids', [])}"
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
