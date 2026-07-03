from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pymysql


BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8080")


def assert_ok(response: httpx.Response):
    response.raise_for_status()
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


async def wait_for_status(client: httpx.AsyncClient, auth: dict[str, str], research_id: str, expected: str) -> None:
    for _ in range(120):
        status = assert_ok(await client.get(f"/api/v1/research/{research_id}", headers=auth))["status"]
        if status == expected:
            return
        await asyncio.sleep(0.25)
    raise AssertionError(f"research {research_id} did not reach {expected}")


async def wait_until_active(client: httpx.AsyncClient, auth: dict[str, str], research_id: str) -> None:
    for _ in range(120):
        status = assert_ok(await client.get(f"/api/v1/research/{research_id}", headers=auth))["status"]
        if status in {"START", "IN_SCOPE", "IN_RESEARCH", "IN_REPORT"}:
            return
        await asyncio.sleep(0.1)
    raise AssertionError(f"research {research_id} did not become active")


async def main() -> None:
    username = "hybrid_sse_" + uuid.uuid4().hex[:10]
    password = "test-password"
    research_id = ""
    cancel_research_id = ""
    model_id = ""
    lines: list[str] = []
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        token = assert_ok(
            await client.post("/api/v1/user/register", json={"username": username, "password": password}),
        )["token"]
        auth = {"Authorization": f"Bearer {token}"}
        model_id = assert_ok(
            await client.post(
                "/api/v1/models",
                headers=auth,
                json={
                    "name": "unreachable-smoke-model",
                    "model": "unreachable",
                    "baseUrl": "http://127.0.0.1:9/v1",
                    "apiKey": "test",
                },
            ),
        )
        research_id = assert_ok(await client.get("/api/v1/research/create?num=1", headers=auth))["researchIds"][0]

        async def consume(target_id: str, target_lines: list[str], client_id: str) -> None:
            headers = {
                **auth,
                "X-Research-Id": target_id,
                "X-Client-Id": client_id,
            }
            async with client.stream("GET", "/api/v1/research/sse", headers=headers, timeout=60) as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")
                async for line in response.aiter_lines():
                    if line:
                        target_lines.append(line)
                    if line.startswith("data: [DONE]"):
                        return

        consumer = asyncio.create_task(consume(research_id, lines, "sse-smoke"))
        await asyncio.sleep(0.2)
        initial_question = "验证首次研究问题超过二十个字符时标题仍然能够完整保存和展示"
        assert_ok(
            await client.post(
                f"/api/v1/research/{research_id}/messages",
                headers=auth,
                json={"content": initial_question, "modelId": model_id, "budget": "MEDIUM", "hitlMode": "NONE"},
            ),
        )
        assert assert_ok(await client.get(f"/api/v1/research/{research_id}", headers=auth))["title"] == initial_question
        await asyncio.wait_for(consumer, timeout=60)
        assert any(line == "event: event" for line in lines)
        assert any("AGENT_RUNTIME" in line for line in lines)
        assert any(line == "data: [DONE] FAILED" for line in lines)
        assert_ok(
            await client.post(
                f"/api/v1/research/{research_id}/messages",
                headers=auth,
                json={"content": "继续", "hitlMode": "NONE"},
            ),
        )
        await wait_for_status(client, auth, research_id, "FAILED")

        cancel_research_id = assert_ok(await client.get("/api/v1/research/create?num=1", headers=auth))["researchIds"][0]
        cancel_lines: list[str] = []
        cancel_consumer = asyncio.create_task(consume(cancel_research_id, cancel_lines, "cancel-smoke"))
        await asyncio.sleep(0.2)
        assert_ok(
            await client.post(
                f"/api/v1/research/{cancel_research_id}/messages",
                headers=auth,
                json={"content": "Cancel smoke", "modelId": model_id, "budget": "MEDIUM", "hitlMode": "NONE"},
            ),
        )
        await wait_until_active(client, auth, cancel_research_id)
        assert_ok(await client.post(f"/api/v1/research/{cancel_research_id}/cancel", headers=auth))
        await asyncio.wait_for(cancel_consumer, timeout=10)
        assert any(line == "data: [DONE] CANCELLED" for line in cancel_lines)
        timeline = assert_ok(await client.get(f"/api/v1/research/{cancel_research_id}/messages", headers=auth))
        timeline_size = len(timeline["messages"]) + len(timeline["events"])
        await asyncio.sleep(1)
        stable_timeline = assert_ok(await client.get(f"/api/v1/research/{cancel_research_id}/messages", headers=auth))
        assert len(stable_timeline["messages"]) + len(stable_timeline["events"]) == timeline_size

        assert_ok(await client.delete(f"/api/v1/models/{model_id}", headers=auth))
        assert_ok(await client.delete(f"/api/v1/research/{cancel_research_id}", headers=auth))
        assert_ok(await client.delete(f"/api/v1/research/{research_id}", headers=auth))

    connection = pymysql.connect(host="127.0.0.1", user="root", password="12345678", database="db_deep_research")
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM user WHERE username = %s", (username,))
        connection.commit()
    finally:
        connection.close()
    print("sse-smoke: passed", len(lines), "lines")


if __name__ == "__main__":
    asyncio.run(main())
