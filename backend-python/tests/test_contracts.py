from __future__ import annotations

import asyncio
import json
import uuid

import pymysql
import pytest
import redis as redis_sync
from fastapi.testclient import TestClient

from app.infrastructure.cache import get_cache, sequence_util
from app.core.config import get_settings
from app.core.constants import WorkflowStatus
from app.main import app
from app.infrastructure.observability import export_headers, resolved_endpoint, summarize
from app.application import agents as agents_module
from app.application import services as services_module
from app.application.agents import ReportAgent, ResearcherAgent, ResearchTask, ScopeAgent, SupervisorAgent
from app.application.services import ResearchService, model_service
from app.application.pipeline import should_rebuild_scope_from_latest_user, ResearchTaskQueue
from app.infrastructure.sse import sse_hub
from app.domain.models import ResearchSession
from app.domain.runtime import ResearchAgentRequest, ResearchChatResponse, ResearchMemory, ResearchMessage
from app.domain.state import BudgetSnapshot, DeepResearchState, TraceMetadataModel


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


def test_queue_recovery_mode_for_direction_actions() -> None:
    assert should_rebuild_scope_from_latest_user("修改意见: 缩小范围") is True
    assert should_rebuild_scope_from_latest_user("请重新调整研究方向") is True
    assert should_rebuild_scope_from_latest_user("确认研究方向，开始执行研究") is False
    assert should_rebuild_scope_from_latest_user("普通研究问题") is False


def test_queue_recovery_builds_state_from_history() -> None:
    session_obj = ResearchSession(
        id=uuid.uuid4().hex,
        user_id=123,
        status=WorkflowStatus.QUEUE,
        model_id="model-1",
        budget="MEDIUM",
        total_input_tokens=7,
        total_output_tokens=11,
    )
    settings = get_settings()
    budget_level = settings.budget_levels()["MEDIUM"]
    state = ResearchTaskQueue()._new_state_from_history(
        session_obj,
        [ResearchMessage.user("研究问题")],
        "MEDIUM",
        budget_level,
    )

    assert state.research_id == session_obj.id
    assert state.status == WorkflowStatus.QUEUE
    assert state.chat_history[-1].text == "研究问题"
    assert state.trace_context()["user.id"] == 123
    assert state.trace_context()["model.id"] == "model-1"
    assert state.budget.max_conduct_count == budget_level.max_conduct_count
    assert state.total_input_tokens == 7
    assert state.total_output_tokens == 11


@pytest.mark.asyncio
async def test_scope_agent_injects_hitl_revision_as_hard_prompt_constraint(monkeypatch: pytest.MonkeyPatch) -> None:
    captured_prompts: list[str] = []

    class FakeClient:
        async def run_agent(self, request: ResearchAgentRequest) -> ResearchChatResponse:
            captured_prompts.append(request.messages[0].text)
            payload = {"researchBrief": "我想研究指定主题，用户约束为 2020-2022，不扩展到其他年份。"}
            return ResearchChatResponse(ResearchMessage.assistant(json.dumps(payload, ensure_ascii=False)))

    async def fake_publish_event(*_args, **_kwargs) -> int:
        return 1

    monkeypatch.setattr(agents_module.model_handler, "get_chat_client", lambda _research_id: FakeClient())
    monkeypatch.setattr(agents_module.event_publisher, "publish_event", fake_publish_event)

    state = DeepResearchState(
        research_id=uuid.uuid4().hex,
        chat_history=[],
        status=WorkflowStatus.IN_SCOPE,
        trace_metadata_model=TraceMetadataModel(
            research_id="rid",
            user_id=1,
            model_id="mid",
            budget_level="MEDIUM",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=2, max_search_count=2, max_concurrent_units=1),
        budget_name="MEDIUM",
        hitl_mode="DIRECTION_ONLY",
        hitl_feedback="时间范围必须改为 2020-2022，不要包含 2023-2026。",
    )
    memory = ResearchMemory(10)
    memory.add(ResearchMessage.user("研究这个行业在 2023-2026 年的发展。"))

    await ScopeAgent()._write_research_brief(memory, state)

    assert captured_prompts
    prompt = captured_prompts[0]
    assert '<HumanRevision priority="highest">' in prompt
    assert "时间范围必须改为 2020-2022" in prompt
    assert "覆盖历史消息、旧研究简报或旧确认消息" in prompt
    assert "不得扩展、近似或改写" in prompt
    assert "近2-3年" in prompt
    assert state.research_brief == "我想研究指定主题，用户约束为 2020-2022，不扩展到其他年份。"


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


@pytest.mark.asyncio
async def test_supervisor_branch_failure_is_returned_as_result(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str | None, int | None]] = []
    settings = get_settings()
    monkeypatch.setattr(settings, "research_observability_capture_io", True)
    monkeypatch.setattr(settings, "research_observability_io_max_chars", 500)

    async def fake_publish_event(
        _research_id: str,
        _event_type: str,
        title: str,
        content: str | None,
        parent_event_id: int | None = None,
    ) -> int:
        events.append((title, content, parent_event_id))
        return 1

    monkeypatch.setattr(agents_module.event_publisher, "publish_event", fake_publish_event)

    class FailingResearcher:
        async def run(self, _state: DeepResearchState) -> str:
            raise RuntimeError("branch boom")

    state = DeepResearchState(
        research_id=uuid.uuid4().hex,
        chat_history=[],
        status=WorkflowStatus.IN_RESEARCH,
        trace_metadata_model=TraceMetadataModel(
            research_id="rid",
            user_id=1,
            model_id="mid",
            budget_level="MEDIUM",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=2, max_search_count=2, max_concurrent_units=2),
        budget_name="MEDIUM",
        current_supervisor_event_id=99,
    )
    tasks = [ResearchTask(0, "失败分支", "研究主题")]

    results = await SupervisorAgent(FailingResearcher())._execute_research_tasks(tasks, state)

    assert len(results) == 1
    assert results[0].index == 0
    assert results[0].branch_state is None
    assert "该研究分支执行失败" in (results[0].findings or "")
    assert "branch boom" in (results[0].findings or "")
    assert any(title == "研究分支失败: 失败分支" and content and "branch boom" in content for title, content, _ in events)


@pytest.mark.asyncio
async def test_research_compress_timeout_falls_back_to_raw_materials(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str, str | None]] = []
    settings = get_settings()
    monkeypatch.setattr(settings, "research_observability_capture_io", True)

    async def fake_publish_event(
        _research_id: str,
        event_type: str,
        title: str,
        content: str | None,
        _parent_event_id: int | None = None,
    ) -> int:
        events.append((event_type, title, content))
        return 1

    class TimeoutClient:
        async def run_agent(self, _request: ResearchAgentRequest) -> ResearchChatResponse:
            raise TimeoutError()

    monkeypatch.setattr(agents_module.event_publisher, "publish_event", fake_publish_event)
    monkeypatch.setattr(agents_module.model_handler, "get_chat_client", lambda _research_id: TimeoutClient())

    state = DeepResearchState(
        research_id=uuid.uuid4().hex,
        chat_history=[],
        status=WorkflowStatus.IN_RESEARCH,
        trace_metadata_model=TraceMetadataModel(
            research_id="rid",
            user_id=1,
            model_id="mid",
            budget_level="MEDIUM",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=2, max_search_count=2, max_concurrent_units=1),
        budget_name="MEDIUM",
        research_topic="营养 RAG",
        search_notes=["[source]\nURL: https://example.test\nraw finding"],
        researcher_notes=["[thinkTool] useful note"],
    )
    memory = ResearchMemory(10)
    memory.add(ResearchMessage.system("sys"))
    memory.add(ResearchMessage.user("topic"))

    compressed = await ResearcherAgent(search_agent=None)._compress_research(memory, state)  # type: ignore[arg-type]

    assert "研究材料压缩阶段失败" in compressed
    assert "raw finding" in compressed
    assert state.compressed_research == compressed
    assert any(title == "研究材料压缩失败，使用原始材料" for _event_type, title, _content in events)
    assert any(title == "已完成该主题研究" for _event_type, title, _content in events)


@pytest.mark.asyncio
async def test_report_timeout_falls_back_to_material_report(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[tuple[str, str, str | None]] = []
    messages: list[tuple[str, str]] = []
    settings = get_settings()
    monkeypatch.setattr(settings, "research_observability_capture_io", True)

    async def fake_publish_event(
        _research_id: str,
        event_type: str,
        title: str,
        content: str | None,
        _parent_event_id: int | None = None,
    ) -> int:
        events.append((event_type, title, content))
        return 1

    async def fake_publish_message(_research_id: str, role: str, content: str):
        messages.append((role, content))
        return None

    class TimeoutClient:
        async def run_agent(self, _request: ResearchAgentRequest) -> ResearchChatResponse:
            raise TimeoutError()

    monkeypatch.setattr(agents_module.event_publisher, "publish_event", fake_publish_event)
    monkeypatch.setattr(agents_module.event_publisher, "publish_message", fake_publish_message)
    monkeypatch.setattr(agents_module.model_handler, "get_chat_client", lambda _research_id: TimeoutClient())

    state = DeepResearchState(
        research_id=uuid.uuid4().hex,
        chat_history=[],
        status=WorkflowStatus.IN_REPORT,
        trace_metadata_model=TraceMetadataModel(
            research_id="rid",
            user_id=1,
            model_id="mid",
            budget_level="MEDIUM",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=2, max_search_count=2, max_concurrent_units=1),
        budget_name="MEDIUM",
        research_brief="研究营养 RAG",
        supervisor_notes=["## 已完成分支\n有价值的研究材料"],
    )

    report = await ReportAgent().run(state)

    assert "# 研究报告（降级生成）" in report
    assert "有价值的研究材料" in report
    assert state.report == report
    assert messages and messages[-1] == ("assistant", report)
    assert any(title == "报告生成模型失败，使用兜底报告" for _event_type, title, _content in events)
    assert any(title == "研究报告已完成（降级）" for _event_type, title, _content in events)


@pytest.mark.asyncio
async def test_resume_checkpoint_keeps_failed_stage_for_report_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_save_message(_research_id: str, _role: str, _content: str):
        return None

    checkpoint_state = DeepResearchState(
        research_id="rid",
        chat_history=[],
        status=WorkflowStatus.IN_RESEARCH,
        trace_metadata_model=TraceMetadataModel(
            research_id="rid",
            user_id=1,
            model_id="mid",
            budget_level="MEDIUM",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=2, max_search_count=2, max_concurrent_units=1),
        budget_name="MEDIUM",
        research_brief="研究简报",
        supervisor_notes=["## 已完成分支\n材料"],
    )

    async def fake_load_checkpoint(_research_id: str):
        return checkpoint_state.model_dump(mode="json")

    monkeypatch.setattr(services_module.get_cache(), "load_checkpoint", fake_load_checkpoint)
    monkeypatch.setattr(services_module.get_cache(), "save_message", fake_save_message)

    state = await ResearchService(model_service)._build_resume_state(
        1,
        "rid",
        "mid",
        "MEDIUM",
        get_settings().budget_levels()["MEDIUM"],
        "继续",
        "DIRECTION_ONLY",
    )

    assert state.skip_scope_phase is True
    assert state.status == WorkflowStatus.IN_REPORT
    assert state.supervisor_notes == ["## 已完成分支\n材料"]


@pytest.mark.asyncio
async def test_hydrate_resume_state_infers_report_stage_from_events() -> None:
    _require_mysql_and_redis()
    research_id = uuid.uuid4().hex
    service = ResearchService(model_service)
    state = DeepResearchState(
        research_id=research_id,
        chat_history=[],
        status=WorkflowStatus.QUEUE,
        trace_metadata_model=TraceMetadataModel(
            research_id=research_id,
            user_id=1,
            model_id="mid",
            budget_level="MEDIUM",
            agent_framework="agentscope-python",
        ),
        budget=BudgetSnapshot(max_conduct_count=2, max_search_count=2, max_concurrent_units=1),
        budget_name="MEDIUM",
    )
    try:
        cache = get_cache()
        await cache.save_event(research_id, "SCOPE", "已制定研究计划", "研究简报")
        await cache.save_event(research_id, "RESEARCH", "已完成该主题研究", "研究材料")
        await cache.save_event(research_id, "REPORT", "正在生成研究报告...", None)

        await service._hydrate_resume_state_from_events(state)

        assert state.research_brief == "研究简报"
        assert "研究材料" in state.supervisor_notes
        assert state.status == WorkflowStatus.IN_REPORT
    finally:
        sequence_util.reset(research_id)
        _cleanup(research_ids=[research_id])
