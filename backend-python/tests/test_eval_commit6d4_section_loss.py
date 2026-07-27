"""Eval MVP v2 — Section Team Revision/Merge Information Loss 测试（§9.3）。

验证：
- 无 section artifact → 三指标 None，不报失败。
- draft 全部保留进 revision/merged → retention=1, loss=0。
- revision 丢失 claim → retention<1。
- merged 丢失 citation → merge_information_loss>0。
"""
from __future__ import annotations

import pytest

from evals.evaluators.base import EvalContext
from evals.evaluators.section_loss import RevisionMergeLossEvaluator, _claims, _citations


def _ctx(report="merged", **kw) -> EvalContext:
    return EvalContext(case_run_id="cr1", report=report, **kw)


@pytest.mark.asyncio
async def test_no_section_artifacts_returns_none() -> None:
    ev = RevisionMergeLossEvaluator()
    results = {r.metric_name: r for r in await ev.evaluate(_ctx())}
    assert set(results) == {
        "merge_information_loss",
        "claim_retention_after_revision",
        "citation_retention_after_revision",
    }
    assert all(r.score_value is None for r in results.values())
    assert all(r.passed is None for r in results.values())


@pytest.mark.asyncio
async def test_full_retention_zero_loss() -> None:
    ev = RevisionMergeLossEvaluator()
    draft = "市场规模 5000 亿 [来源](https://a.com)。头部玩家 [1] 占 60%。"
    ctx = _ctx(
        report=draft,  # merged == draft → 全保留
        section_artifacts={"exec": {"draft": draft, "revision": draft}},
    )
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    assert results["claim_retention_after_revision"].score_value == 1.0
    assert results["citation_retention_after_revision"].score_value == 1.0
    assert results["merge_information_loss"].score_value == 0.0
    assert results["merge_information_loss"].passed == 1


@pytest.mark.asyncio
async def test_revision_drops_claim_lowers_retention() -> None:
    ev = RevisionMergeLossEvaluator()
    draft = "市场规模 5000 亿。头部玩家占 60%。风险率 30%。"  # 3 个含数字 claim
    revision = "市场规模 5000 亿。头部玩家占 60%。"  # 丢了「风险率 30%」
    ctx = _ctx(report=revision, section_artifacts={"s": {"draft": draft, "revision": revision}})
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    cr = results["claim_retention_after_revision"].score_value
    # 3 个 claim 保留 2 个 → 0.667
    assert 0.6 <= cr <= 0.7
    assert results["claim_retention_after_revision"].passed == 0  # < 0.8


@pytest.mark.asyncio
async def test_merge_drops_citation_raises_loss() -> None:
    ev = RevisionMergeLossEvaluator()
    draft = "市场 5000 亿 [来源](https://a.com)。玩家 [1] 占 60%。"
    merged = "市场 5000 亿。玩家占 60%。"  # 丢了两个 citation，但 claim 在
    ctx = _ctx(report=merged, section_artifacts={"s": {"draft": draft, "revision": draft}})
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    loss = results["merge_information_loss"].score_value
    # citation 全丢 → cite_retention=0；claim 在 → claim_retention=1；retention=0.5；loss=0.5
    assert 0.4 <= loss <= 0.6
    assert loss > 0
    assert results["merge_information_loss"].details["citation_retention_in_merge"] == 0.0


def test_claim_and_citation_extraction() -> None:
    text = "市场 5000 亿 [来源](https://a.com)。无数字句。[2]。"
    claims = _claims(text)
    cits = _citations(text)
    # 含数字的句子是 claim；「无数字句」不算
    assert any("5000" in c for c in claims)
    assert not any("无数字句" in c for c in claims)
    # citation：md url + [2]
    assert "https://a.com" in cits
    assert "[2]" in cits


@pytest.mark.asyncio
async def test_draft_without_revision() -> None:
    ev = RevisionMergeLossEvaluator()
    ctx = _ctx(report="merged 5000 亿 [来源](https://a.com)。", section_artifacts={"s": {"draft": "draft 5000 亿 [来源](https://a.com)。"}})
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    # 有 draft 无 revision → retention 指标 None，但 merge_loss 仍可算
    assert results["claim_retention_after_revision"].score_value is None
    assert results["merge_information_loss"].score_value is not None
