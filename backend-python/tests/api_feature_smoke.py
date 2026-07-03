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


def assert_failure(response: httpx.Response, message: str) -> None:
    response.raise_for_status()
    payload = response.json()
    assert payload["code"] == -1, payload
    assert message in payload["message"]


async def main() -> None:
    username = "hybrid_api_" + uuid.uuid4().hex[:10]
    password = "test-password"
    research_ids: list[str] = []
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30) as client:
        registered = assert_ok(await client.post("/api/v1/user/register", json={"username": username, "password": password}))
        token = registered["token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert assert_ok(await client.post("/api/v1/user/login", json={"username": username, "password": password}))["token"]
        user_info = assert_ok(await client.get("/api/v1/user/me", headers=headers))
        assert user_info["avatarUrl"]
        assert user_info["username"] == username

        models = assert_ok(await client.get("/api/v1/models", headers=headers))
        assert isinstance(models, list) and models
        custom_id = assert_ok(
            await client.post(
                "/api/v1/models",
                headers=headers,
                json={
                    "name": "temporary-model",
                    "model": "temporary-model",
                    "baseUrl": "http://127.0.0.1:9/v1",
                    "apiKey": "temporary-key",
                },
            ),
        )
        assert any(item["id"] == custom_id for item in assert_ok(await client.get("/api/v1/models", headers=headers)))
        assert_ok(await client.delete(f"/api/v1/models/{custom_id}", headers=headers))

        research_ids = assert_ok(await client.get("/api/v1/research/create?num=2", headers=headers))["researchIds"]
        assert len(research_ids) == 2
        assert len(assert_ok(await client.get("/api/v1/research/list", headers=headers))) >= 2
        first = research_ids[0]
        assert assert_ok(await client.get(f"/api/v1/research/{first}", headers=headers))["status"] == "NEW"
        renamed = assert_ok(
            await client.patch(
                f"/api/v1/research/{first}/title",
                headers=headers,
                json={"title": "  Updated research title  "},
            ),
        )
        assert renamed["content"] == "Updated research title"
        assert assert_ok(await client.get(f"/api/v1/research/{first}", headers=headers))["title"] == renamed["content"]
        assert_failure(
            await client.patch(f"/api/v1/research/{first}/title", headers=headers, json={"title": "   "}),
            "标题不能为空",
        )
        assert_failure(
            await client.patch(f"/api/v1/research/{first}/title", headers=headers, json={"title": "x" * 201}),
            "标题不能超过",
        )
        assert_ok(await client.post(f"/api/v1/research/{first}/archive", headers=headers))
        assert_ok(await client.delete(f"/api/v1/research/{first}", headers=headers))
        assert_ok(await client.post(f"/api/v1/research/{research_ids[1]}/cancel", headers=headers))
        assert_ok(await client.delete(f"/api/v1/research/{research_ids[1]}", headers=headers))

    connection = pymysql.connect(host="127.0.0.1", user="root", password="12345678", database="db_deep_research")
    try:
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM user WHERE username = %s", (username,))
        connection.commit()
    finally:
        connection.close()
    print("api-feature-smoke: passed", username)


if __name__ == "__main__":
    asyncio.run(main())
