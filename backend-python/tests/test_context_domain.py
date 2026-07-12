from __future__ import annotations

import pytest

from app.domain.context import (
    ContextNodeType,
    ResearchContextPath,
    TypedQuery,
    estimate_tokens,
    stable_source_key,
)


def test_research_context_path_builds_stable_source_layers() -> None:
    base = ResearchContextPath.source(
        research_id="research-1",
        branch_index=2,
        source_key="src-abc",
    )

    assert base.raw == "research://research-1/branches/branch-002/sources/src-abc"
    assert base.child("abstract.md").raw == (
        "research://research-1/branches/branch-002/sources/src-abc/abstract.md"
    )


def test_stable_source_key_uses_url_hash() -> None:
    assert stable_source_key("https://example.com/a?x=1") == stable_source_key("https://example.com/a?x=1")
    assert stable_source_key("https://example.com/a?x=1") != stable_source_key("https://example.com/a?x=2")


def test_typed_query_rejects_invalid_priority() -> None:
    with pytest.raises(ValueError):
        TypedQuery(
            query="market size",
            intent="find market data",
            context_type=ContextNodeType.EVIDENCE,
            priority=9,
            section_hint="市场规模",
        )


def test_estimate_tokens_uses_conservative_char_ratio() -> None:
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2
