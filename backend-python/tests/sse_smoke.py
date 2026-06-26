from __future__ import annotations

import asyncio
import os
import uuid

import httpx
import pymysql


BASE = os.getenv("DEEP_RESEARCH_BASE_URL", "http://127.0.0.1:8080")


class SmokeContext:
    def __init__(self) -> None:
        self.username = "py_sse_" + uuid.uuid4().hex[:10]
        self.research_id: str | None = None

    def cleanup(self) -> None:
        conn = pymysql.connect(
            host="127.0.0.1",
            port=3306,
            user="root",
            password="12345678",
            database="db_deep_research",
            autocommit=True,
            charset="utf8mb4",
        )
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM user WHERE username=%s", (self.username,))
                user_ids = [row[0] for row in cur.fetchall()]
                if self.research_id:
                    cur.execute("DELETE FROM chat_message WHERE research_id=%s", (self.research_id,))
                    cur.execute("DELETE FROM workflow_event WHERE research_id=%s", (self.research_id,))
                    cur.execute("DELETE FROM research_session WHERE id=%s", (self.research_id,))
                for user_id in user_ids:
                    cur.execute("DELETE FROM model WHERE user_id=%s AND type='USER'", (user_id,))
                    cur.execute("DELETE FROM user WHERE id=%s", (user_id,))
        finally:
            conn.close()


async def main() -> None:
    ctx = SmokeContext()
    ctx.cleanup()
    timeout = httpx.Timeout(20.0, read=None)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            registered = (
                await client.post(
                    f"{BASE}/api/v1/user/register",
                    json={"username": ctx.username, "password": "pw"},
                )
            ).json()
            token = registered["data"]["token"]
            headers = {"Authorization": "Bearer " + token}
            model_id = (
                await client.post(
                    f"{BASE}/api/v1/models",
                    headers=headers,
                    json={
                        "name": "sse-fast-fail",
                        "model": "sse-fast-fail",
                        "baseUrl": "http://127.0.0.1:1/v1",
                        "apiKey": "sk-test",
                    },
                )
            ).json()["data"]
            created = (await client.get(f"{BASE}/api/v1/research/create?num=1", headers=headers)).json()
            ctx.research_id = created["data"]["researchIds"][0]
            sse_headers = dict(headers)
            sse_headers.update({"X-Research-Id": ctx.research_id, "X-Client-Id": "sse-smoke-client"})
            seen: list[str] = []

            async def reader() -> None:
                async with client.stream("GET", f"{BASE}/api/v1/research/sse", headers=sse_headers) as response:
                    print("sse_status", response.status_code, response.headers.get("content-type"), flush=True)
                    async for line in response.aiter_lines():
                        if not line:
                            continue
                        print("sse_line", line[:180], flush=True)
                        seen.append(line)
                        if "[DONE]" in line or len(seen) >= 12:
                            break

            async def writer() -> None:
                await asyncio.sleep(0.5)
                sent = await client.post(
                    f"{BASE}/api/v1/research/{ctx.research_id}/messages",
                    headers=headers,
                    json={
                        "content": "SSE 测试任务",
                        "modelId": model_id,
                        "budget": "MEDIUM",
                        "hitlMode": "NONE",
                    },
                )
                print("send_code", sent.json().get("code"), flush=True)

            await asyncio.wait_for(asyncio.gather(reader(), writer()), timeout=20)
            if not any("event: event" in item for item in seen):
                raise RuntimeError("SSE event payload not observed")
            if not any("[DONE] FAILED" in item for item in seen):
                raise RuntimeError("SSE completion payload not observed")
    finally:
        ctx.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
