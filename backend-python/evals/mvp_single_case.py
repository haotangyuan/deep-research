"""Deep Research Eval 单题端到端 MVP — CLI 入口。

按规格 docs/deep-research-eval-mvp-single-case.md 第 4 节运行命令：

    python -m evals.mvp_single_case \
      --fixture evals/fixtures/mvp_single_case.json \
      --output evals/mvp_output \
      --model-id <DB model 表主键>

主流程：读 Fixture → build_context → check_completeness → 5 evaluator（固定顺序）
→ aggregate → write_json + write_markdown。

模型配置从 DB ``model`` 表读（``--model-id``），构造 OpenAI 兼容 chat_fn。
不碰 agentscope / model_handler。取不到 model 记录或 api_key 为空 → 报错退出。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from evals.evaluators.base import ChatFn
from evals.mvp_context import MvpEvalContext, build_context, load_fixture
from evals.mvp_evaluators import (
    evaluate_claim_verifier,
    evaluate_claims,
    evaluate_consistency,
    evaluate_intent,
    evaluate_review,
)
from evals.mvp_report import aggregate, write_json, write_markdown


# ============================================================
# DB model 表读取
# ============================================================

async def _load_model_record(model_id: str) -> dict[str, Any] | None:
    """连 MySQL 读 model 表指定 id 的记录，返回 {model, base_url, api_key}。"""
    from sqlalchemy import select
    from app.domain.models import Model
    from app.infrastructure.db import SessionLocal

    async with SessionLocal() as session:
        row = (await session.execute(select(Model).where(Model.id == model_id))).scalar_one_or_none()
        if row is None:
            return None
        return {
            "model": row.model,
            "base_url": row.base_url,
            "api_key": row.api_key,
            "name": row.name,
        }


# ============================================================
# OpenAI 兼容 chat_fn 构造
# ============================================================

def build_chat_fn(model_record: dict[str, Any]) -> ChatFn:
    """用 httpx 构造 OpenAI 兼容的 async chat_fn(system, user) -> str。"""
    import httpx

    base_url = (model_record["base_url"] or "").rstrip("/")
    api_key = model_record["api_key"] or ""
    model = model_record["model"]
    if not base_url or not api_key:
        raise RuntimeError(
            f"model 记录缺少 base_url/api_key（name={model_record.get('name')}, "
            f"model={model}, base_url={'有' if base_url else '无'}, api_key={'有' if api_key else '无'}）"
        )
    endpoint = f"{base_url}/chat/completions"

    async def chat_fn(system_prompt: str, user_prompt: str) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError(f"LLM 返回无 choices：{json.dumps(data, ensure_ascii=False)[:300]}")
        return choices[0].get("message", {}).get("content", "") or ""

    return chat_fn


# ============================================================
# 主流程
# ============================================================

async def run(
    fixture: str,
    output: str,
    model_id: str | None,
    chat_fn_override: ChatFn | None = None,
) -> dict[str, Any]:
    """跑完整单题 Eval。chat_fn_override 供测试注入，绕过 DB/真实 LLM。"""
    raw = load_fixture(fixture)
    ctx: MvpEvalContext = build_context(raw)

    if not ctx.completeness.get("evaluable"):
        # 不默认通过；继续跑可评估部分，但标记 context 不完整
        print(f"[warn] EvalContext 不完整，missing={ctx.completeness.get('missing')}", file=sys.stderr)

    # 构造 chat_fn：测试可注入；否则从 DB 读 model 配置
    chat_fn: ChatFn | None = chat_fn_override
    if chat_fn is None:
        if not model_id:
            raise SystemExit(
                "Claim evaluator 需要真实 LLM：请通过 --model-id 指向 DB model 表的有效记录。"
            )
        record = await _load_model_record(model_id)
        if record is None:
            raise SystemExit(f"DB model 表未找到 id={model_id} 的记录。")
        if not record.get("api_key"):
            raise SystemExit(f"model 记录 id={model_id} 的 api_key 为空，无法调用 LLM。")
        chat_fn = build_chat_fn(record)

    # 固定顺序执行（规格第 4 节）
    intent = await evaluate_intent(ctx)
    review = await evaluate_review(ctx)
    claims = await evaluate_claims(ctx, chat_fn=chat_fn)
    consistency = await evaluate_consistency(ctx)
    verifier = await evaluate_claim_verifier(ctx)

    result = aggregate(ctx, intent, review, claims, consistency, verifier)
    json_path = write_json(result, output)
    md_path = write_markdown(result, ctx, output)
    print(f"[ok] JSON: {json_path}")
    print(f"[ok] Markdown: {md_path}")
    print(f"[ok] hard_gate={result['result_eval']['hard_gate']}  case_id={result.get('case_id')}")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="evals.mvp_single_case",
        description="Deep Research Eval 单题端到端 MVP（离线 Fixture + 真实 LLM 判 claim）",
    )
    parser.add_argument("--fixture", required=True, help="Fixture JSON 路径")
    parser.add_argument("--output", default="evals/mvp_output", help="输出目录")
    parser.add_argument(
        "--model-id",
        default=None,
        help="DB model 表主键 id，用于读取 LLM 的 base_url/api_key/model（Claim 判定用）",
    )
    args = parser.parse_args(argv)

    if not Path(args.fixture).exists():
        print(f"[error] fixture 不存在：{args.fixture}", file=sys.stderr)
        return 2

    try:
        asyncio.run(run(args.fixture, args.output, args.model_id))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"[error] 运行失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
