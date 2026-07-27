"""Eval MVP v2 — source_quality / source_freshness evaluator 测试（§7.7 漏 2 指标补齐）。

验证：
- source_freshness 确定性：无来源→0；多来源多域名→高分；同域名重复→多样性低。
- source_quality judge：monkeypatch chat_fn 返回固定 JSON，验证 metric 映射 + prompt 带来源。
- 12 项核心指标全集：default_evaluators(chat_fn) 应能产全 §7.7 的 12 个 metric_name。
"""
from __future__ import annotations

import json

import pytest

from evals.evaluators.base import EvalContext
from evals.evaluators.source_freshness import SourceFreshnessEvaluator, _domain
from evals.evaluators.source_quality_judge import SourceQualityJudgeEvaluator
from evals.runner import default_evaluators

# v2 §7.7 MVP 核心 12 指标
CORE_12_METRICS = {
    "required_point_coverage",
    "critical_fact_recall",
    "claim_factuality",
    "citation_completeness",
    "citation_correctness",
    "effective_citation_count",
    "source_quality",
    "source_freshness",
    "analysis_depth",
    "multi_source_synthesis",
    "uncertainty_calibration",
    "instruction_following",
}


def _ctx(report: str, **kw) -> EvalContext:
    return EvalContext(case_run_id="cr1", report=report, **kw)


@pytest.mark.asyncio
async def test_source_freshness_zero_when_no_sources() -> None:
    ev = SourceFreshnessEvaluator()
    results = await ev.evaluate(_ctx("报告"))
    assert len(results) == 1
    r = results[0]
    assert r.metric_name == "source_freshness"
    assert r.metric_group == "source"
    assert r.score_value == 0.0
    assert r.passed == 0
    assert r.evaluator_version == "1.0.0"


@pytest.mark.asyncio
async def test_source_freshness_high_with_diverse_domains() -> None:
    ev = SourceFreshnessEvaluator()
    ctx = _ctx(
        "报告",
        sources=[
            {"url": "https://a.com/x", "score": 0.9},
            {"url": "https://b.com/y", "score": 0.8},
            {"url": "https://gov.cn/z", "score": 0.7},
        ],
    )
    r = (await ev.evaluate(ctx))[0]
    # 3 来源 >= 阈值，全有效，3 不同域名 → 高分
    assert r.score_value >= 0.9
    assert r.passed == 1
    assert r.details["source_count"] == 3
    assert r.details["unique_domain_count"] == 3
    assert "近似" in r.reason  # 标注是近似值


@pytest.mark.asyncio
async def test_source_freshness_lower_with_duplicate_domains_than_diverse() -> None:
    ev = SourceFreshnessEvaluator()
    dup_ctx = _ctx(
        "报告",
        sources=[
            {"url": "https://a.com/1", "score": 0.9},
            {"url": "https://a.com/2", "score": 0.9},
            {"url": "https://a.com/3", "score": 0.9},
        ],
    )
    div_ctx = _ctx(
        "报告",
        sources=[
            {"url": "https://a.com/1", "score": 0.9},
            {"url": "https://b.com/2", "score": 0.9},
            {"url": "https://c.com/3", "score": 0.9},
        ],
    )
    dup = (await ev.evaluate(dup_ctx))[0]
    div = (await ev.evaluate(div_ctx))[0]
    # 同域名 → unique=1, domain_diversity=1/3 → 低于多域名
    assert dup.details["unique_domain_count"] == 1
    assert dup.details["domain_diversity"] == pytest.approx(0.3333, abs=0.01)
    assert div.details["unique_domain_count"] == 3
    assert div.details["domain_diversity"] == 1.0
    assert dup.score_value < div.score_value


def test_domain_extraction_strips_www() -> None:
    assert _domain("https://www.example.com/x") == "example.com"
    assert _domain("https://gov.cn") == "gov.cn"
    assert _domain("") == ""
    assert _domain("not a url") == ""


@pytest.mark.asyncio
async def test_source_quality_judge_maps_llm_json() -> None:
    captured = {}

    async def fake_chat(sys_p, user_p):
        captured["user"] = user_p
        return json.dumps({"metrics": {"source_quality": 0.85}, "reasons": {"source_quality": "权威来源占比高"}})

    ev = SourceQualityJudgeEvaluator(chat_fn=fake_chat, judge_model="mimo")
    ctx = _ctx(
        "报告 [来源](https://gov.cn)。",
        sources=[{"url": "https://gov.cn/x", "title": "官方", "score": 0.9}],
    )
    results = {r.metric_name: r for r in await ev.evaluate(ctx)}
    r = results["source_quality"]
    assert r.score_value == 0.85
    assert r.passed == 1
    assert r.judge_model == "mimo"
    assert r.metric_group == "source"
    # prompt 必须带来源列表
    assert "source_quality" in captured["user"]
    assert "gov.cn" in captured["user"]


@pytest.mark.asyncio
async def test_source_quality_judge_handles_malformed() -> None:
    async def fake_chat(sys_p, user_p):
        return "not json"

    ev = SourceQualityJudgeEvaluator(chat_fn=fake_chat)
    r = (await ev.evaluate(_ctx("报告", sources=[{"url": "https://a.com"}])))[0]
    assert r.score_value is None
    assert r.passed is None


@pytest.mark.asyncio
async def test_default_evaluators_cover_all_12_core_metrics() -> None:
    """§7.7 核心 12 指标必须全部能由 default_evaluators(chat_fn) 产出。"""
    async def fake_chat(sys_p, user_p):
        # 各 judge 要的 metric 都给分，覆盖全集
        return json.dumps(
            {
                "metrics": {
                    "claim_factuality": 0.9,
                    "citation_completeness": 0.8,
                    "citation_correctness": 0.7,
                    "required_point_coverage": 0.8,
                    "critical_fact_recall": 0.7,
                    "analysis_depth": 0.8,
                    "multi_source_synthesis": 0.7,
                    "uncertainty_calibration": 0.6,
                    "instruction_following": 0.9,
                    "source_quality": 0.85,
                },
                "reasons": {},
            }
        )

    evs = default_evaluators(chat_fn=fake_chat, judge_model="mimo")
    # 确定性 evaluator 也产 effective_citation_count；source_freshness 产 source_freshness
    ctx = _ctx(
        "市场规模 5000 亿 [来源](https://a.com)。",
        sources=[{"url": "https://a.com", "score": 0.9}, {"url": "https://b.com", "score": 0.8}],
        run={"outcome": "success"},
        dataset_item={"required_points_json": ["市场规模"]},
    )
    produced: set[str] = set()
    for ev in evs:
        try:
            for r in await ev.evaluate(ctx):
                produced.add(r.metric_name)
        except Exception:  # noqa: BLE001
            continue
    missing = CORE_12_METRICS - produced
    assert not missing, f"§7.7 核心 12 指标缺失: {missing}"


def test_default_evaluators_offline_has_source_freshness() -> None:
    """无 chat_fn 时 source_freshness 仍应可用（确定性）。source_quality 则不可。"""
    offline = default_evaluators()
    names = {e.name for e in offline}
    assert "source_freshness" in names
    assert "source_quality_judge" not in names
