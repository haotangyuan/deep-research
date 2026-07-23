"""Deep Research Eval 单题端到端 MVP — 端到端测试。

验收第 12 条：至少一个端到端测试验证关键结论。
不连真 MySQL、不调真模型（Claim 判定用注入的 fake_chat）。
对应规格第 2 节 6 个预置问题。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.mvp_context import build_context, load_fixture
from evals.mvp_evaluators import (
    evaluate_claim_verifier,
    evaluate_claims,
    evaluate_consistency,
    evaluate_intent,
    evaluate_review,
)
from evals.mvp_report import aggregate

FIXTURE = Path("evals/fixtures/mvp_single_case.json")


def _by_name(metrics):
    return {m.metric_name: m for m in metrics}


def _fake_chat_factory():
    """根据 user_prompt 里的 claim_id 返回对应 verdict，模拟真实 LLM 判定。"""

    async def fake_chat(system_prompt: str, user_prompt: str) -> str:
        # claim_id 出现在 user_prompt 第一行
        verdict_map = {
            "claim_cost": "supported",
            "claim_fresh": "supported",
            "claim_forbidden": "unsupported",
        }
        verdict = "not_verifiable"
        for cid, v in verdict_map.items():
            if cid in user_prompt:
                verdict = v
                break
        return json.dumps({"verdict": verdict, "reason": f"fake judge: {verdict}"}, ensure_ascii=False)

    return fake_chat


@pytest.fixture
def ctx():
    return build_context(load_fixture(FIXTURE))


@pytest.mark.asyncio
async def test_context_completeness(ctx):
    comp = ctx.completeness
    assert comp["evaluable"] is True
    assert comp["missing"] == []
    assert comp["case_available"] is True
    assert comp["consistency_pre_post_available"] is True
    assert comp["verifier_pre_post_available"] is True


@pytest.mark.asyncio
async def test_intent_misses_security_constraint(ctx):
    """预置问题 1：Intent 漏掉安全约束。"""
    results = _by_name(await evaluate_intent(ctx))
    recall = results["intent_constraint_recall"]
    assert recall.score_value < 1.0
    assert "security" in recall.details["missing_constraints"]
    assert results["intent_passed"].passed == 0


@pytest.mark.asyncio
async def test_reviewer_finds_gap_but_not_closed(ctx):
    """预置问题 2/3：Reviewer 发现 security gap，但最终报告未关闭。"""
    results = _by_name(await evaluate_review(ctx))
    assert results["review_gap_recall"].score_value == 1.0
    assert results["review_gap_closure_rate"].score_value < 1.0
    assert "security" in results["review_gap_recall"].details["blocking_gaps"]


@pytest.mark.asyncio
async def test_claims_support_status(ctx):
    """预置问题 4：最终报告含 Unsupported Critical Claim。用 fake_chat 判定。"""
    chat_fn = _fake_chat_factory()
    results = _by_name(await evaluate_claims(ctx, chat_fn=chat_fn))
    assert results["claim_total_claims"].score_value == 3
    assert results["claim_supported_claims"].score_value == 2
    assert results["claim_unsupported_claims"].score_value == 1
    assert results["unsupported_critical_claim_count"].score_value == 1
    assert results["unsupported_critical_claim_count"].passed == 0


@pytest.mark.asyncio
async def test_consistency_resolves_contradiction(ctx):
    """预置问题 5：Consistency 前有矛盾，后消除。"""
    results = _by_name(await evaluate_consistency(ctx))
    assert results["consistency_contradictions_before"].score_value >= 1
    assert results["consistency_contradictions_after"].score_value == 0
    assert results["consistency_contradictions_after"].passed == 1
    assert results["consistency_new_regressions"].score_value == 0


@pytest.mark.asyncio
async def test_claim_verifier_detects_unsupported(ctx):
    """预置问题 6：ClaimVerifier 正确发现并标记 Unsupported Claim。"""
    results = _by_name(await evaluate_claim_verifier(ctx))
    assert results["verifier_unsupported_detection_recall"].score_value == 1.0
    assert results["verifier_claim_correction_rate"].score_value == 1.0
    assert results["verifier_false_warning_count"].score_value == 0


@pytest.mark.asyncio
async def test_hard_gate_failed_end_to_end(ctx):
    """端到端：聚合后 hard_gate=failed，diagnosis 覆盖关键结论。"""
    chat_fn = _fake_chat_factory()
    intent = await evaluate_intent(ctx)
    review = await evaluate_review(ctx)
    claims = await evaluate_claims(ctx, chat_fn=chat_fn)
    consistency = await evaluate_consistency(ctx)
    verifier = await evaluate_claim_verifier(ctx)
    result = aggregate(ctx, intent, review, claims, consistency, verifier)

    assert result["context_complete"] is True
    assert result["result_eval"]["hard_gate"] == "failed"
    assert "unsupported_critical_claim" in result["result_eval"]["failure_codes"]
    assert result["result_eval"]["unsupported_critical_claim_count"] == 1

    # diagnosis 覆盖关键结论（可回溯）
    diag_text = " ".join(result["diagnosis"])
    assert "Intent 漏掉安全约束" in diag_text
    assert "Reviewer 正确发现安全 Gap" in diag_text
    assert "Unsupported Critical Claim" in diag_text

    # 回溯信息
    assert result["trace"]["per_claim"], "应有 per_claim 追溯"
    assert result["trace"]["evidence_ids"]
    assert result["trace"]["blocking_gaps"]
