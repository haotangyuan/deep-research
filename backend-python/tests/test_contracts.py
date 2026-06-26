from __future__ import annotations

import asyncio
import json
import uuid

import pymysql
import pytest
import redis as redis_sync
from fastapi.testclient import TestClient

from app.cache import get_cache, sequence_util
from app.config import get_settings
from app.constants import WorkflowStatus
from app.main import app
from app.observability import export_headers, resolved_endpoint, summarize
from app.agents import ReportAgent
from app.sse import sse_hub
from app.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel


def _mysql_conn():
    settings = get_settings()
    return pymysql.connect(
        host="127.0.0.1",
        port=3306,
        user=settings.db_username,
        password=settings.db_password,
        database="db_deep_research",
        autocommit=True,
        charset="utf8mb4",
    )


def _require_mysql_and_redis() -> None:
    try:
        with _mysql_conn():
            pass
        settings = get_settings()
        redis_sync.Redis(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password or None,
            db=settings.redis_database,
        ).ping()
    except Exception as exc:
        pytest.skip(f"local MySQL/Redis unavailable: {exc}")


def _cleanup(username: str | None = None, research_ids: list[str] | None = None) -> None:
    research_ids = research_ids or []
    user_ids: list[int] = []
    with _mysql_conn() as conn:
        with conn.cursor() as cur:
            if username:
                cur.execute("SELECT id FROM user WHERE username=%s", (username,))
                user_ids = [int(row[0]) for row in cur.fetchall()]
            for research_id in research_ids:
                cur.execute("DELETE FROM chat_message WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM workflow_event WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM research_session WHERE id=%s", (research_id,))
            for user_id in user_ids:
                cur.execute("SELECT id FROM research_session WHERE user_id=%s", (user_id,))
                owned_research_ids = [row[0] for row in cur.fetchall()]
                for research_id in owned_research_ids:
                    cur.execute("DELETE FROM chat_message WHERE research_id=%s", (research_id,))
                    cur.execute("DELETE FROM workflow_event WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM research_session WHERE user_id=%s", (user_id,))
                cur.execute("DELETE FROM model WHERE user_id=%s AND type='USER'", (user_id,))
                cur.execute("DELETE FROM user WHERE id=%s", (user_id,))


def test_rest_contract_without_llm() -> None:
    _require_mysql_and_redis()
    username = "pytest_py_" + uuid.uuid4().hex[:12]
    research_ids: list[str] = []
    try:
        with TestClient(app) as client:
            registered = client.post(
                "/api/v1/user/register",
                json={"username": username, "password": "pw"},
            ).json()
            assert registered["code"] == 0
            token = registered["data"]["token"]
            headers = {"Authorization": "Bearer " + token}

            logged_in = client.post(
                "/api/v1/user/login",
                json={"username": username, "password": "pw"},
            ).json()
            assert logged_in["code"] == 0
            assert logged_in["data"]["token"]

            me = client.get("/api/v1/user/me", headers=headers).json()
            assert me["code"] == 0
            assert "avatarUrl" in me["data"]

            model_id = client.post(
                "/api/v1/models",
                headers=headers,
                json={
                    "name": "pytest-model",
                    "model": "pytest-model",
                    "baseUrl": "https://example.invalid/v1",
                    "apiKey": "sk-test",
                },
            ).json()["data"]
            models = client.get("/api/v1/models", headers=headers).json()
            assert models["code"] == 0
            assert any(item["id"] == model_id for item in models["data"])
            assert all("apiKey" not in item for item in models["data"])
            deleted = client.delete(f"/api/v1/models/{model_id}", headers=headers).json()
            assert deleted["code"] == 0

            created = client.get("/api/v1/research/create?num=1", headers=headers).json()
            assert created["code"] == 0
            research_id = created["data"]["researchIds"][0]
            research_ids.append(research_id)

            status = client.get(f"/api/v1/research/{research_id}", headers=headers).json()
            assert status["code"] == 0
            assert status["data"]["status"] == WorkflowStatus.NEW

            messages = client.get(f"/api/v1/research/{research_id}/messages", headers=headers).json()
            assert messages["code"] == 0
            assert messages["data"]["id"] == research_id
            assert messages["data"]["messages"] == []
            assert messages["data"]["events"] == []

            cancelled = client.post(f"/api/v1/research/{research_id}/cancel", headers=headers).json()
            assert cancelled["code"] == 0
            after_cancel = client.get(f"/api/v1/research/{research_id}/messages", headers=headers).json()
            assert after_cancel["data"]["status"] == WorkflowStatus.CANCELLED
            assert [item["role"] for item in after_cancel["data"]["messages"]] == ["user", "assistant"]
    finally:
        _cleanup(username, research_ids)


@pytest.mark.asyncio
async def test_sse_replay_uses_timeline_contract() -> None:
    _require_mysql_and_redis()
    research_id = uuid.uuid4().hex
    cache = get_cache()
    try:
        await cache.redis.delete(cache.timeline_key(research_id))
        item = await cache.save_message(research_id, "user", "sse replay message")
        queue: asyncio.Queue[dict | None] = asyncio.Queue()

        await sse_hub._replay_if_needed(research_id, queue, "0")

        payload = await asyncio.wait_for(queue.get(), timeout=1)
        assert payload is not None
        assert payload["id"] == str(item.sequence_no)
        assert payload["event"] == "message"
        data = json.loads(payload["data"])
        assert data["kind"] == "message"
        assert data["message"]["content"] == "sse replay message"
    finally:
        await cache.redis.delete(cache.timeline_key(research_id))
        sequence_util.reset(research_id)
        _cleanup(research_ids=[research_id])


def test_state_checkpoint_round_trip() -> None:
    state = DeepResearchState(
        research_id=uuid.uuid4().hex,
        chat_history=[],
        status=WorkflowStatus.QUEUE,
        trace_metadata_model=TraceMetadataModel(
            research_id="rid",
            user_id=1,
            model_id="mid",
            budget_level="MEDIUM",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=2, max_search_count=2, max_concurrent_units=1),
        budget_name="MEDIUM",
        supervisor_notes=["note"],
        researcher_notes=[],
        search_results={},
        search_notes=[],
        hitl_mode="DIRECTION_ONLY",
    )

    restored = DeepResearchState.model_validate(state.model_dump(mode="json"))

    assert restored.research_id == state.research_id
    assert restored.trace_context()["agent.framework"] == "agentscope-python"
    assert restored.supervisor_notes == ["note"]


def test_observability_langfuse_config_and_sanitization(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "research_observability_provider", "langfuse")
    monkeypatch.setattr(settings, "research_observability_endpoint", "")
    monkeypatch.setattr(settings, "langfuse_public_key", "pk-test")
    monkeypatch.setattr(settings, "langfuse_secret_key", "sk-test")
    monkeypatch.setattr(settings, "langfuse_ingestion_version", "4")
    monkeypatch.setattr(settings, "research_observability_capture_io", True)
    monkeypatch.setattr(settings, "research_observability_io_max_chars", 200)

    assert resolved_endpoint() == "https://cloud.langfuse.com/api/public/otel/v1/traces"
    headers = export_headers()
    assert headers["Authorization"].startswith("Basic ")
    assert headers["x-langfuse-ingestion-version"] == "4"
    summary = summarize("authorization: Bearer abc\napi_key=secret-value\nnormal=value")
    assert summary is not None
    assert "abc" not in summary
    assert "secret-value" not in summary
    assert "normal=value" in summary


def test_report_findings_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "research_report_findings_max_chars", 1200)

    findings = ReportAgent._bounded_findings(["a" * 1000, "b" * 1000])

    assert len(findings) < 1400
    assert "部分研究材料因长度限制已截断" in findings
