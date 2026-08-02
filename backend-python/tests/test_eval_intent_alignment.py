from __future__ import annotations

import pytest

from evals.evaluators.base import EvalContext
from evals.evaluators.intent_alignment import IntentAlignmentEvaluator


def _ctx(*, actual_type=None, actual_clarify=None, outcome="success") -> EvalContext:
    metadata = {}
    if actual_type is not None:
        metadata["research_type"] = actual_type
    if actual_clarify is not None:
        metadata["clarification"] = {"needClarification": actual_clarify}
    return EvalContext(
        case_run_id="case-1",
        report="",
        dataset_item={
            "evaluation_contract_json": {
                "expected_intent": {
                    "research_type": "academic_review",
                    "should_clarify": False,
                }
            }
        },
        intent_metadata=metadata,
        run={"outcome": outcome},
    )


@pytest.mark.asyncio
async def test_intent_alignment_passes_matching_type_and_clarification() -> None:
    results = {
        result.metric_name: result
        for result in await IntentAlignmentEvaluator().evaluate(
            _ctx(actual_type="academic_review", actual_clarify=False)
        )
    }
    assert results["intent_type_accuracy"].score_value == 1
    assert results["clarification_decision_accuracy"].score_value == 1
    assert results["intent_alignment"].passed == 1


@pytest.mark.asyncio
async def test_intent_alignment_infers_wrong_clarification_from_hitl_wait() -> None:
    results = {
        result.metric_name: result
        for result in await IntentAlignmentEvaluator().evaluate(_ctx(outcome="hitl_wait"))
    }
    assert results["intent_type_accuracy"].score_value is None
    assert results["clarification_decision_accuracy"].score_value == 0
    assert results["intent_alignment"].passed == 0
