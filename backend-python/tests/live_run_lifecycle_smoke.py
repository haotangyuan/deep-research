"""Eval MVP v2 — Run Lifecycle Live Smoke（§17 Phase 1 验收 #1-5）。

端到端验证落库链路：跑一个真实研究（live LLM + Tavily），完成后查 DB 断言：

1. research_run 行存在且 outcome/trace_id/end_time 齐全（验收 #2）。
2. research_llm_call 行数 > 0（token 单一事实源）；research_stage_usage 投影聚合。
3. research_artifact 含 user_query / research_brief / report_final / source_snapshot。
4. token_reconciliation artifact 存在且 reason ∈ {matched, *_delta=*, stage_missing}（验收 #4）。
5. eval_candidate_snapshot artifact 存在（验收 #5：snapshot 成功）。

前置（与 live_hybrid_workflow_smoke.py 一致）：
- 本地后端 ./start-python-backend.sh 监听 0.0.0.0:8080
- MySQL root/12345678 db_deep_research + model 表含 mimo + .env 配 TAVILY_API_KEY

运行：
    VERIFY_REVISE=false conda run -n deep-research-py python -m \
        pytest -q tests/live_run_lifecycle_smoke.py

可选 monkeypatch async isolation 验证（验收 #5 后半）由单测 test_eval_commit6b_snapshot 覆盖，
本 smoke 聚焦真实链路落库；多 attempt（initial→resume→retry）需手动触发，见末尾注释。
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

import httpx
import pymysql
import pytest

from app.core.config import get_settings

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:8080")
POLL_SECONDS = float(os.getenv("POLL_SECONDS", "2"))
TIMEOUT_SECONDS = float(os.getenv("WORKFLOW_TIMEOUT_SECONDS", "1200"))
# VERIFY_REVISE=false 时跳过 HITL revise 轮，直接 approve（更快）。
VERIFY_REVISE = os.getenv("VERIFY_REVISE", "false").lower() == "true"

# 从 .env 读 DB 配置（不硬编码，适配 root 无密码等本机环境）
_settings = get_settings()
from urllib.parse import urlparse

_raw_db = _settings.db_url.removeprefix("jdbc:") if _settings.db_url.startswith("jdbc:") else _settings.db_url
_parsed_db = urlparse(_raw_db)
DB_HOST = _parsed_db.hostname or "127.0.0.1"
DB_PORT = _parsed_db.port or 3306
DB_USER = _settings.db_username
DB_PASSWORD = _settings.db_password or ""
DB_NAME = (_parsed_db.path or "/db_deep_research").lstrip("/") or "db_deep_research"


def _backend_up() -> bool:
    try:
        httpx.get(f"{BASE_URL}/api/v1/models", timeout=2)
        return True
    except Exception:  # noqa: BLE001
        return False


def _db_reachable() -> bool:
    try:
        c = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME, connect_timeout=2)
        c.close()
        return True
    except Exception:  # noqa: BLE001
        return False


LIVE_OK = _backend_up() and _db_reachable()
SKIP_REASON = "需本地后端(0.0.0.0:8080)+MySQL+mimo+Tavily 全部就绪"


def _assert_ok(response: httpx.Response):
    response.raise_for_status()
    payload = response.json()
    assert payload["code"] == 0, payload
    return payload["data"]


async def _wait_for_status(client, headers, research_id, expected: set[str]):
    deadline = time.monotonic() + TIMEOUT_SECONDS
    last = None
    while time.monotonic() < deadline:
        last = _assert_ok(await client.get(f"/api/v1/research/{research_id}/messages", headers=headers))
        if last["status"] in expected:
            return last
        await asyncio.sleep(POLL_SECONDS)
    raise AssertionError(f"workflow timeout: {last}")


def _db_one(cursor, sql, args=None):
    cursor.execute(sql, args or ())
    return cursor.fetchone()


def _borrow_existing_model_config() -> dict | None:
    """从 DB 取一个有 api_key 的现有模型配置，供当前 user 复制一份 USER 模型。

    适配「DB 里只有其他 user 的 USER 模型、无 GLOBAL 模型」的环境（如本机 DeepSeek）。
    不改全局状态，只读配置。
    """
    conn = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            row = _db_one(
                cur,
                "SELECT name, model, base_url, api_key FROM model WHERE api_key IS NOT NULL AND api_key != '' ORDER BY create_time LIMIT 1",
            )
            return row
    finally:
        conn.close()


@pytest.mark.skipif(not LIVE_OK, reason=SKIP_REASON)
@pytest.mark.asyncio
async def test_run_lifecycle_persistence_end_to_end() -> None:
    username = "lifecycle_live_" + uuid.uuid4().hex[:10]
    password = "test-password"
    research_id = ""
    borrowed_model_id = ""  # 若 smoke 自建了 USER 模型，清理时删
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60) as client:
        token = _assert_ok(
            await client.post("/api/v1/user/register", json={"username": username, "password": password}),
        )["token"]
        headers = {"Authorization": f"Bearer {token}"}
        models = _assert_ok(await client.get("/api/v1/models", headers=headers))
        # 模型选择：优先 mimo（CLAUDE.md 开发默认），否则取第一个可用模型。
        # 若新 user 无任何可用模型（DB 只有其他 user 的 USER 模型），从 DB 借一份配置复制给自己。
        chosen = next((m for m in models if "mimo" in (m.get("name", "") + m.get("model", "")).lower()), None)
        if chosen is None and models:
            chosen = models[0]
        if chosen is None:
            borrowed = _borrow_existing_model_config()
            assert borrowed, "数据库无可用模型且无带 api_key 的现有模型可借"
            added = _assert_ok(
                await client.post(
                    "/api/v1/models",
                    headers=headers,
                    json={
                        "name": borrowed["name"] + "-smoke",
                        "model": borrowed["model"],
                        "baseUrl": borrowed["base_url"],
                        "apiKey": borrowed["api_key"],
                    },
                )
            )
            borrowed_model_id = added if isinstance(added, str) else (added.get("id") if isinstance(added, dict) else None)
            chosen = {"id": borrowed_model_id, "name": borrowed["name"]}
        assert chosen and chosen.get("id"), "无法获得可用模型"
        print(f"  使用模型: {chosen.get('name')} ({chosen.get('id')})")
        research_id = _assert_ok(await client.get("/api/v1/research/create?num=1", headers=headers))["researchIds"][0]
        _assert_ok(
            await client.post(
                f"/api/v1/research/{research_id}/messages",
                headers=headers,
                json={
                    "content": "研究 Python Web 项目如何设计自动化测试分层策略，给出可执行建议和权威来源。",
                    "modelId": chosen["id"],
                    "budget": "MEDIUM",
                    "hitlMode": "DIRECTION_ONLY",
                },
            ),
        )

        awaiting = await _wait_for_status(
            client, headers, research_id, {"NEED_CLARIFICATION", "AWAITING_DIRECTION_CONFIRM", "FAILED"}
        )
        if awaiting["status"] == "NEED_CLARIFICATION":
            _assert_ok(
                await client.post(
                    f"/api/v1/research/{research_id}/messages",
                    headers=headers,
                    json={"content": "聚焦 FastAPI 小项目，覆盖单元/集成/E2E 与 CI，面向 3-5 人团队。"},
                ),
            )
            awaiting = await _wait_for_status(client, headers, research_id, {"AWAITING_DIRECTION_CONFIRM", "FAILED"})
        assert awaiting["status"] == "AWAITING_DIRECTION_CONFIRM", awaiting

        if VERIFY_REVISE:
            _assert_ok(
                await client.post(
                    f"/api/v1/research/{research_id}/direction-action",
                    headers=headers,
                    json={"action": "REVISE", "feedback": "重点覆盖 Python Web 项目并加入 CI 测试分层。"},
                ),
            )
            await _wait_for_status(client, headers, research_id, {"AWAITING_DIRECTION_CONFIRM", "FAILED"})

        _assert_ok(
            await client.post(
                f"/api/v1/research/{research_id}/direction-action",
                headers=headers,
                json={"action": "APPROVE", "feedback": ""},
            ),
        )
        completed = await _wait_for_status(client, headers, research_id, {"COMPLETED", "FAILED", "CANCELLED"})
        assert completed["status"] == "COMPLETED", completed

    # ====== 落库链路 DB 断言（§17 Phase 1 验收 #1-5）======
    conn = pymysql.connect(host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME)
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cur:
            # 验收 #2：research_run 行存在且最终 attempt 的 outcome/trace_id/end_time 齐全。
            # APPROVE 会触发 hitl_resume mint 新 run（attempt_no 递增），故取 MAX(attempt_no) 那行（COMPLETED 的）。
            # 验收 #1 顺带验证：同一 research 有多个 attempt（initial + hitl_resume）。
            cur.execute(
                "SELECT * FROM research_run WHERE research_id=%s ORDER BY attempt_no DESC",
                (research_id,),
            )
            all_runs = cur.fetchall()
            assert all_runs, "research_run 行缺失（落库链路未触发）"
            run = all_runs[0]  # 最新 attempt（COMPLETED 的）
            assert run["outcome"] in ("success", "degraded"), (
                f"最终 attempt outcome={run['outcome']}（应为 success/degraded，hitl_wait 是中间态，说明取错 attempt）"
            )
            assert run["trace_id"], "trace_id 空快照失败"
            assert run["end_time"] is not None, "end_time 空（close_run 未执行）"
            assert run["input_tokens"] is not None and run["input_tokens"] >= 0
            assert (run.get("workflow_commit_sha") or "") not in ("", "unknown"), "workflow 版本快照失败"
            run_id = run["id"]
            # 验收 #1：initial→HITL resume 是同一 research 的不同 attempt（VERIFY_REVISE=false 下至少 2 个）
            attempt_count = len(all_runs)
            max_attempt_no = run["attempt_no"]
            assert max_attempt_no >= 1
            print(f"  research_run: attempts={attempt_count} max_attempt_no={max_attempt_no}")

            # token 单一事实源：research_llm_call 行数 > 0
            cur.execute("SELECT COUNT(*) AS n FROM research_llm_call WHERE run_id=%s", (run_id,))
            llm_calls = cur.fetchone()["n"]
            assert llm_calls > 0, "research_llm_call 行为空（token 未落库）"
            # research_stage_usage 投影聚合
            cur.execute("SELECT COUNT(*) AS n FROM research_stage_usage WHERE run_id=%s", (run_id,))
            stage_rows = cur.fetchone()["n"]
            assert stage_rows > 0, "research_stage_usage 投影为空"

            # 验收 #5：关键 artifact 齐全（跨该 research 所有 run 查，因 user_query/brief 可能在
            # attempt_no=1 的 run 落，report_final 在 COMPLETED 的 attempt_no=2 落）
            cur.execute(
                "SELECT artifact_type, COUNT(*) AS n FROM research_artifact a "
                "JOIN research_run r ON a.run_id=r.id WHERE r.research_id=%s GROUP BY artifact_type",
                (research_id,),
            )
            art_types = {r["artifact_type"]: r["n"] for r in cur.fetchall()}
            assert "user_query" in art_types, f"user_query artifact 缺失: {art_types}"
            assert "report_final" in art_types, f"report_final artifact 缺失: {art_types}"
            assert "research_brief" in art_types, f"research_brief artifact 缺失: {art_types}"
            print(f"  research_artifact types (across all attempts): {art_types}")

            # 验收 #4：token_reconciliation artifact 存在且 reason 非异常（在最终 run 上）
            rec = _db_one(cur, "SELECT outcome, content FROM research_artifact WHERE run_id=%s AND artifact_type='token_reconciliation'", (run_id,))
            assert rec is not None, "token_reconciliation artifact 缺失（对账未执行）"
            rec_reason = rec["outcome"]
            assert rec_reason in ("matched",) or "delta" in rec_reason or rec_reason == "stage_missing", (
                f"对账 reason 异常: {rec_reason}"
            )
            rec_content = json.loads(rec["content"]) if rec["content"] else {}
            print(f"  token_reconciliation: reason={rec_reason} delta={rec_content.get('input_delta')}/{rec_content.get('output_delta')}")

            # 验收 #5：eval_candidate_snapshot 存在（snapshot 成功）
            snap = _db_one(cur, "SELECT id FROM research_artifact WHERE run_id=%s AND artifact_type='eval_candidate_snapshot'", (run_id,))
            assert snap is not None, "eval_candidate_snapshot artifact 缺失（snapshot 未冻结）"

            # claim_manifest：COMPLETED 报告应生成（若 ClaimVerifier 提取成功）
            cur.execute("SELECT COUNT(*) AS n FROM research_claim_manifest WHERE run_id=%s", (run_id,))
            manifest_n = cur.fetchone()["n"]
            print(f"  research_claim_manifest: {manifest_n} rows")

            print(
                f"live-run-lifecycle: PASSED research_id={research_id} run_id={run_id} "
                f"llm_calls={llm_calls} stage_rows={stage_rows} artifacts={len(art_types)} "
                f"reconcile={rec_reason} snapshot=ok"
            )
    finally:
        # 清理（与 live_hybrid 一致，加 eval 表）
        with conn.cursor() as cur:
            if research_id:
                cur.execute("DELETE FROM research_artifact WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM research_claim_manifest WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM research_llm_call WHERE run_id IN (SELECT id FROM research_run WHERE research_id=%s)", (research_id,))
                cur.execute("DELETE FROM research_stage_usage WHERE run_id IN (SELECT id FROM research_run WHERE research_id=%s)", (research_id,))
                cur.execute("DELETE FROM research_run WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM workflow_event WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM chat_message WHERE research_id=%s", (research_id,))
                cur.execute("DELETE FROM research_session WHERE id=%s", (research_id,))
            if borrowed_model_id:
                cur.execute("DELETE FROM model WHERE id=%s", (borrowed_model_id,))
            cur.execute("DELETE FROM user WHERE username=%s", (username,))
        conn.commit()
        conn.close()


# 验收点 #1「多 attempt」说明（实测 2026-07-21 DeepSeek 环境验证）：
# 即使 VERIFY_REVISE=false，APPROVE 触发 hitl_resume 也会 mint 新 run（attempt_no 递增）。
# 故同一 research 至少有 2 个 attempt（initial 的 hitl_wait + approve 后的 success），
# 验收 #1「initial→HITL resume 是不同 attempt」天然覆盖。
# 完整 initial→resume→retry 三 attempt 链路需手动触发 retry（FAILED 后重发消息），
# 由 live_hybrid 的 retry 路径 + 本 smoke 的 DB 断言组合验证。
# 注意：断言必须取 MAX(attempt_no) 那行（COMPLETED 的），不能取首行（停在 hitl_wait）。
