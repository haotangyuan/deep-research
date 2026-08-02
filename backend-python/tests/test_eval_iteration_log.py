from __future__ import annotations

import json

from evals.iteration_log import build_iteration_record, record_payload


def _payload() -> dict:
    return {
        "experiment_id": "exp-1",
        "dataset_name": "formal",
        "dataset_version": "1",
        "repeat_no": 0,
        "live_results": [
            {
                "item_id": "item-1",
                "variant": "MEDIUM",
                "research_id": "research-1",
                "run_id": "run-1",
                "status": "COMPLETED",
                "outcome": "success",
                "input_tokens": 10,
                "output_tokens": 5,
            }
        ],
        "diagnosis": {
            "summary": {
                "case_count": 1,
                "hard_gate_pass_count": 0,
                "optimization_backlog": ["修复引用链路"],
            },
            "cases": [
                {
                    "item_id": "item-1",
                    "item_label": "测试题",
                    "variant": "MEDIUM",
                    "research_id": "research-1",
                    "run_id": "run-1",
                    "hard_gate_passed": 0,
                    "root_causes": [
                        {
                            "code": "citation_claim_linkage_failure",
                            "title": "引用关联丢失",
                            "severity": "blocking",
                            "agent_modules": ["ReportAgent"],
                            "recommendation": "修复引用映射",
                            "confidence": 0.96,
                            "evidence": [
                                {"metric": "citation_traceability", "value": 0.1}
                            ],
                        }
                    ],
                }
            ],
        },
    }


def test_build_iteration_record_keeps_run_problem_and_evidence() -> None:
    record = build_iteration_record(_payload())
    assert record["run_scope"]["runs"][0]["tokens"] == 15
    assert record["problems"][0]["code"] == "citation_claim_linkage_failure"
    assert record["problems"][0]["evidence"][0]["metrics"][0]["value"] == 0.1
    assert record["validation"]["status"] == "pending"


def test_record_payload_preserves_manual_change_and_validation(tmp_path) -> None:
    json_path, _ = record_payload(_payload(), output_dir=tmp_path)
    record = json.loads(json_path.read_text(encoding="utf-8"))
    record["changes"] = [{"problem_codes": ["x"], "summary": "done", "files": []}]
    record["validation"] = {"status": "passed", "checks": [], "before_after": []}
    json_path.write_text(json.dumps(record), encoding="utf-8")

    record_payload(_payload(), output_dir=tmp_path)
    updated = json.loads(json_path.read_text(encoding="utf-8"))
    assert updated["changes"][0]["summary"] == "done"
    assert updated["validation"]["status"] == "passed"
    assert (tmp_path / "index.json").exists()
