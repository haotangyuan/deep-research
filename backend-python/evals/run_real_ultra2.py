"""真实跑 ULTRA 研究（v2）：用 model owner user_id=3 的 token，避免 model 归属不匹配。"""
from __future__ import annotations
import asyncio, sys, time
import httpx

BASE = "http://127.0.0.1:8080"
MODEL_ID = "bda582c2d9824a3ab1486b7eb6169f09"  # 属于 user_id=3
QUERY = "对比 RAG 与 Fine-tuning 在企业知识问答场景的优劣，并给出选型建议。"
TIMEOUT = 2400  # 40 分钟，ULTRA 4 轮 + 报告 + claim verification


async def main():
    from app.core.auth import generate_token
    uid = 3
    token = generate_token(uid)
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url=BASE, timeout=30.0) as client:
        r = await client.get("/api/v1/research/create", params={"num": 1}, headers=headers)
        r.raise_for_status()
        rd = r.json()["data"]
        research_id = (rd.get("researchIds") or [None])[0] or rd.get("id")
        print(f"[ok] research_id={research_id}", flush=True)

        r = await client.post(
            f"/api/v1/research/{research_id}/messages",
            headers={**headers, "Content-Type": "application/json"},
            json={"content": QUERY, "modelId": MODEL_ID, "budget": "ULTRA", "hitlMode": "NONE"},
        )
        if r.status_code != 200:
            print(f"[error] send_message {r.status_code}: {r.text[:500]}", file=sys.stderr)
            return None
        print(f"[ok] message accepted", flush=True)

        start = time.time()
        last = None
        while time.time() - start < TIMEOUT:
            r = await client.get(f"/api/v1/research/{research_id}/messages", headers=headers)
            if r.status_code == 200:
                d = r.json().get("data") or {}
                status = d.get("status")
                if status != last:
                    print(f"[..] status={status} elapsed={int(time.time()-start)}s", flush=True)
                    last = status
                if status == "COMPLETED":
                    print(f"[ok] COMPLETED in {int(time.time()-start)}s", flush=True)
                    print(f"[ok] in={d.get('totalInputTokens')} out={d.get('totalOutputTokens')}", flush=True)
                    msgs = d.get("messages") or []
                    for m in reversed(msgs):
                        if m.get("role") == "assistant" and m.get("content"):
                            print("[report]", m["content"][:500], flush=True)
                            break
                    print(f"RESEARCH_ID={research_id}", flush=True)
                    return research_id
                if status in ("FAILED", "ERROR", "ABORTED", "FAILED_TOO_MANY_STEPS"):
                    print(f"[error] terminal {status}", file=sys.stderr)
                    print(str(d)[:800], file=sys.stderr)
                    return None
            await asyncio.sleep(6)
        print("[error] timeout", file=sys.stderr)
        return None


if __name__ == "__main__":
    rid = asyncio.run(main())
    sys.exit(0 if rid else 1)
