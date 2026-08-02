"""Eval MVP v2 Commit 5 — Claim-Citation Manifest 提取器与 ClaimVerifier 落库测试。

分两类：
1. 纯逻辑：``extract_claims_from_report`` 的 claim/citation 抽取（无 DB）。
2. 调用契约：``verify_report_claims`` 在 ``state.run_id`` 存在时为每个 claim
   落一条 ``claim_verification`` artifact（monkeypatch upsert_artifact 为记录器，
   避免真连 DB；与 test_eval_commit4_artifacts.py 同档）。

遵循 v2 §6.4：MVP manifest 由「从最终 Markdown 生成」的 extractor 产出。
"""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.application.agents import ReportAgent
from app.application.claim_manifest import (
    extract_claims_from_report,
    extract_reference_map,
    normalize_report_citations,
)


def test_extract_empty_or_short_returns_empty() -> None:
    assert extract_claims_from_report(None) == []
    assert extract_claims_from_report("") == []
    assert extract_claims_from_report("短句。") == []


def test_extract_md_link_citations() -> None:
    report = (
        "AI 市场规模 2026 年达 5000 亿美元，详见 [报告](https://example.com/report)。"
        "另一句没有引用的内容不进 manifest。"
        "风险点：数据隐私监管收紧 [来源](https://example.com/risk)。"
    )
    claims = extract_claims_from_report(report)
    # 两句带链接进 manifest，纯文本句被忽略
    assert len(claims) == 2
    assert all(c["requires_citation"] is True for c in claims)
    urls = [c["citations"][0]["citation_url"] for c in claims]
    assert "https://example.com/report" in urls
    assert "https://example.com/risk" in urls
    # claim_id 稳定
    assert all(c["claim_id"].startswith("claim-") for c in claims)
    # 含数值/URL 的句子判 critical
    assert claims[0]["importance"] == "critical"


def test_extract_numeric_marker_citations_no_url() -> None:
    report = "某公司 2025 年收入同比增长 18%[1]，利润率提升[2]。"
    claims = extract_claims_from_report(report)
    assert len(claims) == 1
    cites = claims[0]["citations"]
    markers = {c.get("citation_marker") for c in cites}
    assert markers == {"[1]", "[2]"}
    # 无 URL 的 marker 不产生 citation_url
    assert all(not c.get("citation_url") for c in cites)


def test_extract_multiple_citations_one_sentence() -> None:
    report = "该结论同时见 [论文](https://a.com) 与 [数据](https://b.com) 及 [3]。"
    claims = extract_claims_from_report(report)
    assert len(claims) == 1
    cites = claims[0]["citations"]
    urls = sorted(c["citation_url"] for c in cites if c.get("citation_url"))
    assert urls == ["https://a.com", "https://b.com"]
    assert any(c.get("citation_marker") == "[3]" for c in cites)


def test_extract_section_id_propagated() -> None:
    report = "结论见 [文献](https://c.com)。"
    claims = extract_claims_from_report(report, section_id="intro")
    assert claims[0]["section_id"] == "intro"


@pytest.mark.parametrize(
    ("references", "expected_url"),
    [
        ("[1] [官方报告](https://example.com/a)", "https://example.com/a"),
        ("| [1] | 官方报告 | https://example.com/b | 标准 |", "https://example.com/b"),
        ("[1] 官方报告: https://example.com/c", "https://example.com/c"),
        ("[1] 官方报告\nhttps://example.com/d", "https://example.com/d"),
    ],
)
def test_numeric_marker_resolves_common_reference_formats(
    references: str,
    expected_url: str,
) -> None:
    report = (
        "NIST 在 2023 年发布该框架，包含四个核心功能[1]。\n\n"
        "## 来源\n"
        f"{references}"
    )
    claims = extract_claims_from_report(report)
    assert len(claims) == 1
    assert claims[0]["citations"][0]["citation_url"] == expected_url
    # 来源列表是索引，不应被重复抽成事实 Claim。
    assert "官方报告" not in claims[0]["claim_text"]


def test_missing_reference_stays_dangling_and_is_audited() -> None:
    report = "一个关键结论在 2025 年增长 18%[2]。\n\n## 参考来源\n[1] A: https://a.com"
    _, audit = normalize_report_citations(report)
    assert audit["marker_ids"] == ["2"]
    assert audit["resolved_marker_ids"] == []
    assert audit["unresolved_marker_ids"] == ["2"]
    claims = extract_claims_from_report(report)
    assert not claims[0]["citations"][0].get("citation_url")


def test_reference_title_can_resolve_from_source_catalog_conservatively() -> None:
    report = "该标准在风险治理生命周期中明确包含四个核心功能[1]。\n\n## Sources\n[1] NIST AI Risk Management Framework"
    references = extract_reference_map(
        report,
        source_catalog=[
            {
                "title": "NIST AI Risk Management Framework",
                "url": "https://www.nist.gov/itl/ai-risk-management-framework",
                "evidence_id": "source-1",
            }
        ],
    )
    assert references["1"]["citation_url"].startswith("https://www.nist.gov/")
    claims = extract_claims_from_report(
        report,
        source_catalog=[
            {
                "title": "NIST AI Risk Management Framework",
                "url": "https://www.nist.gov/itl/ai-risk-management-framework",
            }
        ],
    )
    assert claims[0]["citations"][0]["citation_url"].startswith("https://www.nist.gov/")


class _Artifacts:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def upsert_artifact(self, **kwargs):
        self.calls.append(kwargs)
        return "artifact-id"

    async def write_claim_manifest(self, run_id, research_id, report_artifact_id, claims):
        self.calls.append({"_kind": "manifest", "report_artifact_id": report_artifact_id, "claims": claims})
        return len(claims)

    async def replace_claim_manifest(self, run_id, research_id, report_artifact_id, claims):
        return await self.write_claim_manifest(run_id, research_id, report_artifact_id, claims)

    async def load_source_catalog(self, _run_id):
        return []


async def _noop_event(*_args, **_kwargs) -> int:
    return 1


@pytest.mark.asyncio
async def test_verify_report_claims_persists_per_claim_artifacts(monkeypatch) -> None:
    """每个被验证的 claim 落一条 claim_verification artifact。"""
    from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel
    from app.core.constants import WorkflowMode, WorkflowStatus
    from app.domain.runtime import ResearchMessage

    recorded = _Artifacts()
    monkeypatch.setattr(
        "app.infrastructure.eval_repository.eval_repository.upsert_artifact",
        recorded.upsert_artifact,
    )
    monkeypatch.setattr(
        "app.infrastructure.eval_repository.eval_repository.replace_claim_manifest",
        recorded.replace_claim_manifest,
    )
    monkeypatch.setattr(
        "app.infrastructure.eval_repository.eval_repository.load_source_catalog",
        recorded.load_source_catalog,
    )

    # ClaimVerifier 返回全部 verified，避免报告被改写（便于断言 report 不变）
    class FakeClient:
        async def run_agent(self, request):
            return SimpleNamespace(
                token_usage=None,
                ai_message=SimpleNamespace(text=json.dumps({"verdict": "verified", "scores": {"support": 0.9}})),
            )

    monkeypatch.setattr("app.application.agents.model_handler.get_chat_client", lambda _rid: FakeClient())
    monkeypatch.setattr("app.application.agents.event_publisher.publish_event", _noop_event)

    state = DeepResearchState(
        research_id="research-cv",
        chat_history=[ResearchMessage.user("x")],
        status=WorkflowStatus.IN_REPORT,
        workflow_mode=WorkflowMode.ULTRA_DYNAMIC,
        dynamic_round_no=1,
        trace_metadata_model=TraceMetadataModel(
            research_id="research-cv",
            user_id=1,
            model_id="mimo",
            budget_level="ULTRA",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=6, max_search_count=4, max_concurrent_units=3),
        budget_name="ULTRA",
    )
    state.run_id = "run-cv"
    state.supervisor_notes = ["证据：某事实成立"]

    report = "某公司 2025 年收入同比增长 18%[1]。这是带引用的声明。"
    agent = ReportAgent()
    result = await agent.verify_report_claims(state, report)

    # 全 verified → 报告不改写
    assert result == report
    cv = [c for c in recorded.calls if c.get("artifact_type") == "claim_verification"]
    # claims_to_verify[:8]，这里句子数 <= 8
    assert len(cv) >= 1
    assert all(c["stage_name"] == "ClaimVerifier" for c in cv)
    assert all(c["outcome"] == "verified" for c in cv)
