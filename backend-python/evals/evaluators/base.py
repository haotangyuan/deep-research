"""Eval MVP v2 — Evaluator 公共基类与评估上下文。

每个 evaluator 声明自己的 ``evaluator_version``，便于同一报告被不同版本重评且不互相
覆盖（v2 §6.11 / eval_score 唯一键含 evaluator_version）。

Judge 类 evaluator 通过注入的 ``chat_fn`` 调用 LLM，便于测试时 monkeypatch；
生产由 runner 注入真实 model_handler。绝不直接 import pipeline，保持离线可测。
"""
from __future__ import annotations

import abc
import hashlib
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from evals.schemas import MetricResult

# Chat 函数契约：(system_prompt, user_prompt) -> str（异步）
ChatFn = Callable[[str, str], Awaitable[str]]


@dataclass
class EvalContext:
    """单次 case_run 的评估输入。runner 装配，evaluator 只读。"""

    case_run_id: str
    report: str  # 最终报告 Markdown
    dataset_item: dict[str, Any] = field(default_factory=dict)
    # claim-citation manifest（claim_id -> {citations, importance, ...}）
    claim_manifest: list[dict[str, Any]] = field(default_factory=list)
    # 来源快照（每个含 url/title/score 等元数据，来自 research_artifact(type=source_snapshot)）
    sources: list[dict[str, Any]] = field(default_factory=list)
    # section team 产物：{section_id: {"draft": str, "revision": str|None}}
    section_artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    # merged 报告正文（区别于最终 report_final，来自 report_merged artifact）
    merged_report: str = ""
    # HIGH 双 draft + synthesis：[{angle, content, score?}]（来自 report_draft/report_synthesis artifact）
    report_drafts: list[dict[str, Any]] = field(default_factory=list)
    report_synthesis: str = ""
    # research_run 行的关键字段（tokens / duration / counts）
    run: dict[str, Any] = field(default_factory=dict)
    # artifacts 汇总（type -> count）
    artifact_counts: dict[str, int] = field(default_factory=dict)
    # 机制维度（可选）
    round_no: int | None = None
    reviewer_lenses: list[str] = field(default_factory=list)
    # trace 标量本地落地（research_span_attribute）读取：
    # {round_no: {attr_key: value}}，含 review 投票/consensus/各维度分/gaps/next_action。
    # 由 runner 读 research_span_attribute(span_scope=UltraDynamicReview) 装配。
    review_attributes: dict[int, dict[str, Any]] = field(default_factory=dict)
    # report quality 摘要（research_span_attribute(span_scope=UltraReportGate)）：
    # {status / weak_sections / blocking_gaps}
    report_quality: dict[str, Any] = field(default_factory=dict)
    # HardGate 后置聚合用：其他 evaluator 已产出的结果（metric_name -> MetricResult）。
    # 由 runner 在两阶段跑完后填充，HardGate 只读。
    prior_results: dict[str, Any] = field(default_factory=dict)


class BaseEvaluator(abc.ABC):
    """所有 evaluator 的基类。子类实现 ``evaluate(ctx) -> list[MetricResult]``。"""

    name: str = "base"
    version: str = "0.1.0"
    judge_model: str | None = None

    def __init__(self, *, chat_fn: ChatFn | None = None, judge_model: str | None = None) -> None:
        self._chat_fn = chat_fn
        if judge_model is not None:
            self.judge_model = judge_model

    async def chat(self, system_prompt: str, user_prompt: str) -> str:
        if self._chat_fn is None:
            raise RuntimeError(f"{self.name}: judge requires chat_fn, none injected")
        return await self._chat_fn(system_prompt, user_prompt)

    @abc.abstractmethod
    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        """返回该 evaluator 产出的全部分数。"""


def judge_prompt_hash(system_prompt: str) -> str:
    """judge prompt sha256，用于 evaluator_version 派生（v2 §6.11）。"""
    return hashlib.sha256(system_prompt.encode("utf-8")).hexdigest()


def parse_json_safe(text: str) -> Any:
    """从可能含 markdown fence 的 LLM 输出里取 JSON。失败返回 None。"""
    from app.core.json_utils import extract_json

    try:
        return extract_json(text)
    except Exception:  # noqa: BLE001
        return None
