from __future__ import annotations

import time
import uuid
import os

import httpx
import pymysql


BASE = os.getenv("DEEP_RESEARCH_BASE_URL", "http://127.0.0.1:8080")
FIRST_PHASE_POLLS = int(os.getenv("LIVE_FIRST_PHASE_POLLS", "120"))
FINAL_PHASE_POLLS = int(os.getenv("LIVE_FINAL_PHASE_POLLS", "360"))


def copy_mimo_model_for_user(username: str) -> str:
    model_id = uuid.uuid4().hex
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
            cur.execute("SELECT id FROM user WHERE username=%s", (username,))
            user_id = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO model(id,type,user_id,name,model,base_url,api_key,create_time,update_time)
                SELECT %s,'USER',%s,name,model,base_url,api_key,NOW(),NOW()
                FROM model
                WHERE name LIKE '%%mimo%%' OR model LIKE '%%mimo%%'
                LIMIT 1
                """,
                (model_id, user_id),
            )
    finally:
        conn.close()
    return model_id


def poll_messages(client: httpx.Client, headers: dict[str, str], research_id: str) -> dict:
    response = client.get(f"{BASE}/api/v1/research/{research_id}/messages", headers=headers)
    response.raise_for_status()
    payload = response.json()
    if payload["code"] != 0:
        raise RuntimeError(payload)
    return payload["data"]


def log(*args) -> None:
    print(*args, flush=True)


def main() -> None:
    username = f"py_live_{int(time.time())}"
    with httpx.Client(timeout=30) as client:
        response = client.post(
            f"{BASE}/api/v1/user/register",
            json={"username": username, "password": "pw"},
        )
        log("register", response.status_code, response.json().get("code"))
        token = response.json()["data"]["token"]
        headers = {"Authorization": "Bearer " + token}
        model_id = copy_mimo_model_for_user(username)

        models = client.get(f"{BASE}/api/v1/models", headers=headers).json()
        log("models", models.get("code"), len(models.get("data") or []), model_id in [m["id"] for m in models.get("data") or []])

        created = client.get(f"{BASE}/api/v1/research/create?num=1", headers=headers).json()
        log("create", created.get("code"), created.get("data"))
        research_id = created["data"]["researchIds"][0]

        payload = {
            "content": "请用中文简要研究 FastAPI 与 Spring Boot 在小型项目中的差异，最终报告控制在 300 字以内。",
            "modelId": model_id,
            "budget": "MEDIUM",
            "hitlMode": "DIRECTION_ONLY",
        }
        sent = client.post(
            f"{BASE}/api/v1/research/{research_id}/messages",
            headers=headers,
            json=payload,
        ).json()
        log("send", sent)

        status = ""
        for idx in range(FIRST_PHASE_POLLS):
            time.sleep(2)
            data = poll_messages(client, headers, research_id)
            status = data["status"]
            log("poll1", idx, status, len(data.get("messages") or []), len(data.get("events") or []))
            if status in {"AWAITING_DIRECTION_CONFIRM", "FAILED", "NEED_CLARIFICATION", "COMPLETED", "CANCELLED"}:
                break

        if status == "AWAITING_DIRECTION_CONFIRM":
            approved = client.post(
                f"{BASE}/api/v1/research/{research_id}/direction-action",
                headers=headers,
                json={"action": "APPROVE"},
            ).json()
            log("approve", approved)
            for idx in range(FINAL_PHASE_POLLS):
                time.sleep(2)
                data = poll_messages(client, headers, research_id)
                status = data["status"]
                log(
                    "poll2",
                    idx,
                    status,
                    len(data.get("messages") or []),
                    len(data.get("events") or []),
                    data.get("totalInputTokens"),
                    data.get("totalOutputTokens"),
                )
                if status in {"FAILED", "COMPLETED", "CANCELLED", "NEED_CLARIFICATION", "AWAITING_DIRECTION_CONFIRM"}:
                    break

        final = poll_messages(client, headers, research_id)
        log(
            "final",
            final["status"],
            "messages",
            len(final["messages"]),
            "events",
            len(final["events"]),
            "tokens",
            final.get("totalInputTokens"),
            final.get("totalOutputTokens"),
        )
        if final["messages"]:
            log("last_role", final["messages"][-1]["role"], "last_len", len(final["messages"][-1]["content"]))
        if final["status"] != "COMPLETED":
            raise SystemExit(f"workflow did not complete: status={final['status']} research_id={research_id}")
        if not final["messages"] or final["messages"][-1]["role"] != "assistant":
            raise SystemExit(f"missing final assistant report: research_id={research_id}")


if __name__ == "__main__":
    main()
