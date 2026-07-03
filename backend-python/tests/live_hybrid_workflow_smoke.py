from __future__ import annotations

import asyncio
import os
import time
import uuid

import httpx
import pymysql


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8080")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "2"))
TIMEOUT_SECONDS = float(os.getenv("WORKFLOW_TIMEOUT_SECONDS", "1200"))
VERIFY_REVISE = os.getenv("VERIFY_REVISE", "true").lower() == "true"


def assert_ok(response: httpx.Response):
    response.raise_for_status()
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


async def wait_for_status(client, headers, research_id, expected: set[str]):
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last = None
    while time.monotonic() < deadline:
        last = assert_ok(await client.get(f"/api/v1/research/{research_id}/messages", headers=headers))
        if last["status"] in expected:
            return last
        await asyncio.sleep(POLL_SECONDS)
    raise AssertionError(f"workflow timeout: {last}")


async def main() -> None:
    username = "hybrid_live_" + uuid.uuid4().hex[:10]
    password = "test-password"
    research_id = ""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        token = assert_ok(
            await client.post("/api/v1/user/register", json={"username": username, "password": password}),
        )["token"]
        headers = {"Authorization": f"Bearer {token}"}
        models = assert_ok(await client.get("/api/v1/models", headers=headers))
        mimo = next((item for item in models if "mimo" in (item.get("name", "") + item.get("model", "")).lower()), None)
        assert mimo is not None, "database model 'mimo' was not found"
        research_id = assert_ok(await client.get("/api/v1/research/create?num=1", headers=headers))["researchIds"][0]
        assert_ok(
            await client.post(
                f"/api/v1/research/{research_id}/messages",
                headers=headers,
                json={
                    "content": "研究小型软件项目如何设计高质量自动化测试策略，给出可执行建议和来源。",
                    "modelId": mimo["id"],
                    "budget": "MEDIUM",
                    "hitlMode": "DIRECTION_ONLY",
                },
            ),
        )

        awaiting = await wait_for_status(
            client,
            headers,
            research_id,
            {"NEED_CLARIFICATION", "AWAITING_DIRECTION_CONFIRM", "FAILED"},
        )
        if awaiting["status"] == "NEED_CLARIFICATION":
            assert_ok(
                await client.post(
                    f"/api/v1/research/{research_id}/messages",
                    headers=headers,
                    json={
                        "content": (
                            "聚焦 Python FastAPI 小型 Web 项目，覆盖单元测试、集成测试、"
                            "端到端测试和 GitHub Actions CI，面向 3 到 5 人团队。"
                        ),
                    },
                ),
            )
            awaiting = await wait_for_status(client, headers, research_id, {"AWAITING_DIRECTION_CONFIRM", "FAILED"})
        assert awaiting["status"] == "AWAITING_DIRECTION_CONFIRM", awaiting
        assert any(event["type"] == "AGENT_RUNTIME" for event in awaiting["events"])

        if VERIFY_REVISE:
            assert_ok(
                await client.post(
                    f"/api/v1/research/{research_id}/direction-action",
                    headers=headers,
                    json={"action": "REVISE", "feedback": "重点覆盖 Python Web 项目，并加入 CI 流水线测试分层。"},
                ),
            )
            revised = await wait_for_status(client, headers, research_id, {"AWAITING_DIRECTION_CONFIRM", "FAILED"})
            assert revised["status"] == "AWAITING_DIRECTION_CONFIRM", revised
            assert "Python" in "\n".join(event.get("content") or "" for event in revised["events"])

        assert_ok(
            await client.post(
                f"/api/v1/research/{research_id}/direction-action",
                headers=headers,
                json={"action": "APPROVE", "feedback": ""},
            ),
        )
        completed = await wait_for_status(client, headers, research_id, {"COMPLETED", "FAILED", "CANCELLED"})
        assert completed["status"] == "COMPLETED", completed
        assistant_messages = [item for item in completed["messages"] if item["role"] == "assistant"]
        assert assistant_messages and len(assistant_messages[-1]["content"]) > 500
        runtime_events = [event for event in completed["events"] if event["type"] == "AGENT_RUNTIME"]
        task_events = [event for event in runtime_events if event.get("runtimeMetadata", {}).get("kind") == "team_task"]
        assert runtime_events
        assert task_events
        assert any(event["runtimeMetadata"].get("status") == "completed" for event in task_events)
        assert (completed.get("totalInputTokens") or 0) > 0
        assert (completed.get("totalOutputTokens") or 0) > 0
        print(
            "live-hybrid-workflow: passed",
            research_id,
            "events=",
            len(completed["events"]),
            "runtime_events=",
            len(runtime_events),
            "tokens=",
            completed.get("totalInputTokens"),
            completed.get("totalOutputTokens"),
        )

    connection = pymysql.connect(host="127.0.0.1", user="root", password="12345678", database="db_deep_research")
    try:
        with connection.cursor() as cursor:
            if research_id:
                cursor.execute("DELETE FROM workflow_event WHERE research_id = %s", (research_id,))
                cursor.execute("DELETE FROM chat_message WHERE research_id = %s", (research_id,))
                cursor.execute("DELETE FROM research_session WHERE id = %s", (research_id,))
            cursor.execute("DELETE FROM user WHERE username = %s", (username,))
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    asyncio.run(main())
