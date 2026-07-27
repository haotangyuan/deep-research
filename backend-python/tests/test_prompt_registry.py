"""prompt_registry 单测。

纯逻辑：prompt sha 稳定；改文本变 sha；VersionSnapshot 扁平列 round-trip；
template_sha256 规范化后稳定。
"""
from __future__ import annotations

from app.core.prompt_registry import (
    PROMPT_VERSIONS,
    freeze_for_state,
    freeze_version_snapshot,
    snapshot,
)
from app.application.workflow_template import template_sha256


def test_snapshot_covers_all_families() -> None:
    snap = snapshot()
    for family in PROMPT_VERSIONS:
        assert family in snap
        entry = snap[family]
        assert entry.version == PROMPT_VERSIONS[family]
        assert len(entry.sha256) == 64
        assert entry.text_len >= 0


def test_snapshot_is_cached_and_stable() -> None:
    snap1 = snapshot()
    snap2 = snapshot()
    # lru_cache：同一对象
    assert snap1 is snap2
    # sha 稳定
    assert snap1["scope"].sha256 == snap2["scope"].sha256


def test_version_snapshot_to_run_columns_round_trip() -> None:
    snap = freeze_version_snapshot(
        workflow_commit_sha="abc123",
        workflow_dirty=1,
        template_version="1",
        template_sha256="thash",
        request_model="mimo",
    )
    cols = snap.to_run_columns()
    assert cols["workflow_commit_sha"] == "abc123"
    assert cols["workflow_dirty"] == 1
    assert cols["template_version"] == "1"
    assert cols["request_model"] == "mimo"
    assert "scope" in cols["prompt_versions"]
    assert "scope" in cols["prompt_hashes"]
    assert cols["prompt_versions"]["scope"] == PROMPT_VERSIONS["scope"]


def test_template_sha256_is_stable_and_normalizes() -> None:
    # 等价模板（旧扁平字段 vs 嵌套）规范化后应同 hash
    t1 = {"version": 1, "type": "general", "mode": "ultra_dynamic", "reviewerCount": 3}
    t2 = {"version": 1, "type": "general", "mode": "ultra_dynamic", "reviewer": {"count": 3}}
    h1 = template_sha256(t1)
    h2 = template_sha256(t2)
    assert h1 == h2
    assert len(h1) == 64
    # 空模板
    assert template_sha256(None) == template_sha256({})


class _FakeState:
    workflow_template = {"version": 1, "type": "general", "mode": "ultra_dynamic"}

    class _meta:
        model_id = "mimo"

    trace_metadata_model = _meta()


def test_freeze_for_state_extracts_model_and_template() -> None:
    state = _FakeState()
    cols = freeze_for_state(state)
    assert cols["request_model"] == "mimo"
    assert cols["template_sha256"] is not None
    assert len(cols["template_sha256"]) == 64
    assert cols["template_version"] == "1"
