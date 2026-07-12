from __future__ import annotations

from app.application.report_context import enforce_report_context_budget, has_selected_context, render_report_context, should_expand_raw
from app.domain.context import ContextLevel, ContextNodeType, ReportContext, SelectedContextItem


def test_render_report_context_groups_sections_and_sources() -> None:
    context = ReportContext(
        research_id="research-1",
        research_brief="研究 AI 搜索",
        section_contexts={
            "市场格局": [
                SelectedContextItem(
                    path="research://research-1/branches/branch-001/evidence/evidence-001.json",
                    node_type=ContextNodeType.EVIDENCE,
                    level=ContextLevel.DERIVED,
                    title="市场增长",
                    content='{"claim":"市场增长","evidence_text":"用户增加"}',
                    source_url="https://example.com/report",
                    score=2.0,
                    reason="matched section",
                )
            ]
        },
        total_estimated_tokens=100,
    )

    rendered = render_report_context(context)

    assert "## 市场格局" in rendered
    assert "https://example.com/report" in rendered
    assert "research://research-1" in rendered


def test_should_expand_raw_only_for_thin_or_specific_sections() -> None:
    assert should_expand_raw(section="关键证据", selected_count=0, needs_numbers=False) is True
    assert should_expand_raw(section="市场规模", selected_count=2, needs_numbers=True) is True
    assert should_expand_raw(section="背景与现状", selected_count=4, needs_numbers=False) is False


def test_has_selected_context_detects_empty_context() -> None:
    empty = ReportContext(research_id="research-1", research_brief="")
    non_empty = ReportContext(
        research_id="research-1",
        research_brief="brief",
        section_contexts={
            "核心结论": [
                SelectedContextItem(
                    path="p",
                    node_type=ContextNodeType.EVIDENCE,
                    level=ContextLevel.DERIVED,
                    content="evidence",
                )
            ]
        },
    )

    assert has_selected_context(empty) is False
    assert has_selected_context(non_empty) is True


def test_enforce_report_context_budget_drops_later_items() -> None:
    context = ReportContext(
        research_id="research-1",
        research_brief="brief",
        section_contexts={
            "核心结论": [
                SelectedContextItem(
                    path="a",
                    node_type=ContextNodeType.EVIDENCE,
                    level=ContextLevel.DERIVED,
                    content="a" * 10,
                ),
                SelectedContextItem(
                    path="b",
                    node_type=ContextNodeType.EVIDENCE,
                    level=ContextLevel.DERIVED,
                    content="b" * 100,
                ),
            ]
        },
    )

    enforce_report_context_budget(context, max_chars=60)

    assert [item.path for item in context.section_contexts["核心结论"]] == ["a"]
    assert context.dropped[-1]["path"] == "b"
