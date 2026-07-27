r"""Eval MVP v2 Commit 5 — Claim-Citation Manifest 提取器。

从最终报告 Markdown 提取「原子 Claim + 引用」对，结构化为
``eval_repository.write_claim_manifest`` 所需的 claims list。

设计权衡（与 v2 §6.4 一致）：
- MVP 由「Eval Claim Extractor 从最终 Markdown 生成」，不依赖报告 Agent 同步输出；
  长期由 ReportAgent 直接输出 Manifest，Eval 再独立验证，避免「自己生成、自己证明」。
- 提取口径与 ``ReportAgent.verify_report_claims`` 的 claim 抽取一致：
  以「带 ``[\d+]`` 标记或 Markdown 链接 ``[text](url)`` 的句子」为一个 claim 单元，
  使 manifest 与被验证的 claim 对齐，便于后续 ``claim_factuality`` / ``citation_completeness``。
- 没有引用的句子不进 manifest（manifest 关注「需要被审计的事实声明」）。
- 一行一个 Claim-Citation Pair；无 URL 的 marker 仍保留一行，citation_url 为空。
"""
from __future__ import annotations

import hashlib
import re
from typing import Any

__all__ = ["extract_claims_from_report"]

# 句子切分：与 verify_report_claims 保持一致（句末标点 + 换行）
_SENTENCE_SPLIT = re.compile(r"(?<=[。.!?])\s*")
# [n] 数字引用标记
_NUMERIC_CITATION = re.compile(r"\[(\d+)\]")
# Markdown 链接引用 [text](url)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def _claim_id(claim_text: str, idx: int) -> str:
    raw = f"{idx}:{claim_text[:64]}"
    return "claim-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _derive_importance(claim_text: str, has_url: bool) -> str:
    """粗粒度重要性：含具体数值或 URL 的视为 critical，其余 minor。

    非精确判定，仅给 manifest 提供可分组维度；真正 importance 判定留给
    离线 claim_factuality judge。
    """
    if re.search(r"\d+(?:\.\d+)?\s*[%％]|\d{4}\s*年|\$\s*\d", claim_text) or has_url:
        return "critical"
    return "minor"


def _citations_for_sentence(sentence: str) -> list[dict[str, Any]]:
    """从单句提取所有引用对：优先 Markdown 链接（带 URL），再补 [n] 标记。"""
    cites: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for match in _MD_LINK.finditer(sentence):
        url = match.group(2).strip()
        if url and url not in seen_urls:
            seen_urls.add(url)
            cites.append(
                {
                    "citation_id": "cite-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:10],
                    "citation_url": url,
                    "excerpt": match.group(1)[:200],
                }
            )
    for match in _NUMERIC_CITATION.finditer(sentence):
        marker = f"[{match.group(1)}]"
        cites.append({"citation_id": f"marker-{match.group(1)}", "citation_marker": marker})
    return cites


# URL 占位：句切分前先把 URL 内的 ``.`` 屏蔽，避免 ``https://x.com`` 里的 ``.`` 被当成句末。
_URL_PATTERN = re.compile(r"https?://[^\s)）]+")


def _mask_urls(report: str) -> tuple[str, dict[str, str]]:
    """把 URL 替换为占位符，返回 (masked_report, placeholder->url)。切分后再还原。"""
    mapping: dict[str, str] = {}

    def _repl(m: re.Match) -> str:
        url = m.group(0)
        token = f"URL{len(mapping)}END"
        mapping[token] = url
        return token

    return _URL_PATTERN.sub(_repl, report), mapping


def _restore(sentence: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return sentence
    for token, url in mapping.items():
        sentence = sentence.replace(token, url)
    return sentence


def extract_claims_from_report(report: str | None, *, section_id: str | None = None) -> list[dict[str, Any]]:
    """从报告 Markdown 抽取 claim-citation 对。

    返回结构匹配 ``EvalRepository.write_claim_manifest`` 的 ``claims`` 入参：

    .. code-block:: python

        [
            {
                "claim_id": "claim-<sha>",
                "claim_text": "<句子>",
                "section_id": "<传入或 None>",
                "importance": "critical" | "minor",
                "requires_citation": True,
                "citations": [
                    {"citation_id": "...", "citation_url": "https://...", "excerpt": "..."},
                    {"citation_id": "marker-1", "citation_marker": "[1]"},
                ],
            },
            ...
        ]

    没有任何引用标记的句子不进 manifest。空报告返回空列表。
    句切分前会先把 URL 屏蔽为占位符，避免 ``https://x.com`` 里的 ``.`` 被当成句末。
    """
    if not report:
        return []
    masked, url_map = _mask_urls(report)
    claims: list[dict[str, Any]] = []
    idx = 0
    for raw_sentence in _SENTENCE_SPLIT.split(masked):
        sentence = _restore(raw_sentence.strip(), url_map)
        if len(sentence) <= 15:
            continue
        cites = _citations_for_sentence(sentence)
        if not cites:
            continue
        idx += 1
        has_url = any(c.get("citation_url") for c in cites)
        claims.append(
            {
                "claim_id": _claim_id(sentence, idx),
                "claim_text": sentence,
                "section_id": section_id,
                "importance": _derive_importance(sentence, has_url),
                "requires_citation": True,
                "citations": cites,
            }
        )
    return claims
