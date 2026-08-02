from __future__ import annotations

from evals.diagnosis import (
    diagnose_case,
    diagnose_experiment,
    render_diagnosis_markdown,
)


def _metric(
    name: str,
    value=None,
    *,
    passed=None,
    label=None,
    details=None,
):
    return {
        "metric_name": name,
        "score_value": value,
        "passed": passed,
        "label_value": label,
        "details": details,
    }


def _base_scores(*, gate=0, failure_codes=None):
    return [
        _metric("workflow_completed", passed=1),
        _metric("report_non_empty", passed=1),
        _metric("intent_alignment", 1.0, passed=1),
        _metric("intent_type_accuracy", 1.0, passed=1),
        _metric("clarification_decision_accuracy", 1.0, passed=1),
        _metric("required_point_coverage", 1.0, passed=1),
        _metric("critical_fact_recall", 1.0, passed=1),
        _metric("claim_factuality", 0.95, passed=1),
        _metric("analysis_depth", 0.9, passed=1),
        _metric("instruction_following", 1.0, passed=1),
        _metric("citation_completeness", 0.8, passed=1),
        _metric("citation_correctness", 0.8, passed=1),
        _metric("source_quality", 0.9, passed=1),
        _metric("hard_gate_passed", float(gate), passed=gate, details={
            "failure_reason_codes": failure_codes or [],
        }),
    ]


def test_diagnose_case_maps_good_content_bad_traceability_to_citation_pipeline() -> None:
    scores = _base_scores(
        gate=0,
        failure_codes=["dangling_citation", "unsupported_critical_claim"],
    )
    scores.append(_metric("citation_traceability", 0.0, passed=0))
    result = diagnose_case(
        {
            "item_id": "q1",
            "variant": "HIGH",
            "outcome": "success",
            "input_tokens": 80_000,
            "output_tokens": 20_000,
            "scores": scores,
        }
    )
    assert result["root_causes"][0]["code"] == "citation_claim_linkage_failure"
    assert "ReportAgent" in result["primary_agent_modules"]
    assert result["agent_function_status"]["report_content"] == "effective"
    assert result["agent_function_status"]["citation_pipeline"] == "ineffective"
    assert result["total_tokens_k"] == 100.0


def test_diagnose_case_maps_wrong_clarification_to_scope_agent() -> None:
    scores = [
        _metric("workflow_completed", passed=0),
        _metric("report_non_empty", passed=0),
        _metric("intent_alignment", 0.0, passed=0),
        _metric("intent_type_accuracy", None, passed=None),
        _metric("clarification_decision_accuracy", 0.0, passed=0),
        _metric(
            "hard_gate_passed",
            0.0,
            passed=0,
            details={
                "failure_reason_codes": [
                    "workflow_failed",
                    "report_empty",
                    "missing_required_points",
                ]
            },
        ),
    ]
    result = diagnose_case(
        {
            "item_id": "q2",
            "variant": "ULTRA",
            "status": "CANCELLED",
            "outcome": "hitl_wait",
            "input_tokens": 1000,
            "output_tokens": 500,
            "scores": scores,
        }
    )
    assert result["root_causes"][0]["code"] == "scope_clarification_error"
    assert result["primary_agent_modules"] == ["ScopeAgent"]
    assert result["result_status"] == "failed"


def test_experiment_diagnosis_generates_tier_decision_and_markdown() -> None:
    medium_scores = _base_scores(gate=0, failure_codes=["dangling_citation"])
    medium_scores.append(_metric("citation_traceability", 0.0, passed=0))
    high_scores = _base_scores(gate=0, failure_codes=["dangling_citation"])
    high_scores.append(_metric("citation_traceability", 0.0, passed=0))
    live = [
        {
            "item_id": "q1",
            "variant": "MEDIUM",
            "outcome": "success",
            "input_tokens": 40_000,
            "output_tokens": 10_000,
        },
        {
            "item_id": "q1",
            "variant": "HIGH",
            "outcome": "success",
            "input_tokens": 80_000,
            "output_tokens": 20_000,
        },
    ]
    evaluated = [
        {"item_id": "q1", "variant": "MEDIUM", "scores": medium_scores},
        {"item_id": "q1", "variant": "HIGH", "scores": high_scores},
    ]
    diagnosis = diagnose_experiment(
        live,
        evaluated,
        item_metadata={"q1": {"sample_reason": "测试题"}},
    )
    comparison = diagnosis["tier_comparisons"][0]
    assert comparison["token_delta_k"] == 50.0
    assert "不建议升级" in comparison["decision"]
    markdown = render_diagnosis_markdown(diagnosis)
    assert "指标证据" in markdown
    assert "Agent 模块" in markdown
    assert "优化建议" in markdown
    assert "MEDIUM→HIGH" in markdown
