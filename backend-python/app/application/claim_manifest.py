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
from difflib import SequenceMatcher
from typing import Any

__all__ = [
    "extract_claims_from_report",
    "extract_reference_map",
    "normalize_report_citations",
]

# 句子切分：与 verify_report_claims 保持一致（句末标点 + 换行）
_SENTENCE_SPLIT = re.compile(r"(?<=[。.!?])\s*")
# [n] 数字引用标记
_NUMERIC_CITATION = re.compile(r"\[(\d+)\](?!\()")
# Markdown 链接引用 [text](url)
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_REFERENCE_TABLE_ROW = re.compile(r"^\s*\|\s*\[(\d+)\]\s*\|\s*(.*)$")
_REFERENCE_LINE = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")
_HEADING = re.compile(r"^\s*(#{1,6})\s+(.+?)\s*$")
_SOURCE_SECTION_NAME = re.compile(
    r"(?:^来源$|来源列表|来源清单|参考来源|参考文献|references|sources)",
    re.IGNORECASE,
)
_BARE_URL = re.compile(r"https?://[^\s|)）>]+")


def _clean_url(value: str) -> str:
    return value.rstrip(".,;:，。；：")


def _source_catalog_items(source_catalog: list[dict[str, Any]] | None) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for source in source_catalog or []:
        url = _clean_url(str(source.get("url") or "").strip())
        if not url:
            continue
        items.append(
            {
                "url": url,
                "title": str(source.get("title") or "").strip(),
                "evidence_id": str(source.get("evidence_id") or "").strip(),
            }
        )
    return items


def _match_catalog_source(
    title: str,
    source_catalog: list[dict[str, Any]] | None,
) -> dict[str, str] | None:
    """仅在标题高度相似且最佳候选明显胜出时回填 URL，避免凭编号猜来源。"""
    normalized = re.sub(r"\s+", " ", title).strip(" -*:：|")
    if len(normalized) < 6:
        return None
    ranked: list[tuple[float, dict[str, str]]] = []
    for source in _source_catalog_items(source_catalog):
        candidate = re.sub(r"\s+", " ", source["title"]).strip()
        if not candidate:
            continue
        score = SequenceMatcher(None, normalized.casefold(), candidate.casefold()).ratio()
        ranked.append((score, source))
    ranked.sort(key=lambda item: item[0], reverse=True)
    if not ranked or ranked[0][0] < 0.82:
        return None
    if len(ranked) > 1 and ranked[0][0] - ranked[1][0] < 0.08:
        return None
    return ranked[0][1]


def _reference_region(report: str) -> tuple[str, str]:
    """返回正文与全部来源区，支持来源清单位于报告中间或末尾。"""
    body_lines: list[str] = []
    reference_lines: list[str] = []
    in_reference = False
    reference_level = 7
    found_reference_section = False
    for line in report.splitlines():
        heading = _HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            title = re.sub(
                r"^\s*\d+(?:\.\d+)*[.、]?\s*",
                "",
                heading.group(2),
            ).strip()
            if in_reference and level <= reference_level:
                in_reference = False
            if _SOURCE_SECTION_NAME.search(title):
                in_reference = True
                reference_level = level
                found_reference_section = True
                continue
        if in_reference:
            reference_lines.append(line)
        else:
            body_lines.append(line)
    if not found_reference_section:
        return report, report
    return "\n".join(body_lines), "\n".join(reference_lines)


def extract_reference_map(
    report: str | None,
    *,
    source_catalog: list[dict[str, Any]] | None = None,
) -> dict[str, dict[str, str]]:
    """解析常见来源列表格式，建立 ``引用编号 → URL`` 映射。

    支持 Markdown 链接、表格、同一行裸 URL，以及标题下一行单独 URL。
    没有 URL 的条目只在能与 source_snapshot 标题高置信匹配时回填。
    """
    if not report:
        return {}
    _, region = _reference_region(report)
    references: dict[str, dict[str, str]] = {}
    pending_number: str | None = None
    pending_title = ""

    for raw_line in region.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        table_match = _REFERENCE_TABLE_ROW.match(line)
        line_match = _REFERENCE_LINE.match(line)
        match = table_match or line_match
        if match:
            number = match.group(1)
            tail = match.group(2).strip()
            link = _MD_LINK.search(tail)
            bare = _BARE_URL.search(tail)
            url = _clean_url((link.group(2) if link else bare.group(0) if bare else "").strip())
            title_text = tail.split("|", 1)[0] if table_match else tail
            title = (
                link.group(1) if link else _BARE_URL.sub("", title_text)
            ).strip(" |:-：")
            entry = {"citation_marker": f"[{number}]", "title": title}
            if url:
                entry["citation_url"] = url
            else:
                matched = _match_catalog_source(title, source_catalog)
                if matched:
                    entry["citation_url"] = matched["url"]
                    if matched.get("evidence_id"):
                        entry["evidence_id"] = matched["evidence_id"]
            references[number] = entry
            pending_number = number if not entry.get("citation_url") else None
            pending_title = title
            continue

        if pending_number:
            bare = _BARE_URL.search(line)
            if bare:
                references[pending_number]["citation_url"] = _clean_url(bare.group(0))
                pending_number = None
                pending_title = ""
            elif line.startswith("#") or line.startswith("|"):
                pending_number = None
                pending_title = ""

    if pending_number and not references[pending_number].get("citation_url"):
        matched = _match_catalog_source(pending_title, source_catalog)
        if matched:
            references[pending_number]["citation_url"] = matched["url"]
            if matched.get("evidence_id"):
                references[pending_number]["evidence_id"] = matched["evidence_id"]
    return references


def normalize_report_citations(
    report: str | None,
    *,
    source_catalog: list[dict[str, Any]] | None = None,
) -> tuple[str, dict[str, Any]]:
    """审计报告正文引用；不伪造 URL，也不改变用户可见的引用格式。"""
    text = report or ""
    body, _ = _reference_region(text)
    references = extract_reference_map(text, source_catalog=source_catalog)
    marker_ids = sorted(set(_NUMERIC_CITATION.findall(body)), key=int)
    resolved = [marker for marker in marker_ids if (references.get(marker) or {}).get("citation_url")]
    unresolved = [marker for marker in marker_ids if marker not in resolved]
    return text, {
        "marker_ids": marker_ids,
        "resolved_marker_ids": resolved,
        "unresolved_marker_ids": unresolved,
        "reference_count": len(references),
        "traceability": (len(resolved) / len(marker_ids)) if marker_ids else None,
    }


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


def _citations_for_sentence(
    sentence: str,
    references: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
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
        number = match.group(1)
        marker = f"[{number}]"
        reference = (references or {}).get(number) or {}
        item = {
            "citation_id": f"marker-{number}",
            "citation_marker": marker,
            "excerpt": reference.get("title") or None,
        }
        if reference.get("citation_url"):
            item["citation_url"] = reference["citation_url"]
        if reference.get("evidence_id"):
            item["evidence_id"] = reference["evidence_id"]
        cites.append(item)
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


def extract_claims_from_report(
    report: str | None,
    *,
    section_id: str | None = None,
    source_catalog: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
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
    body, _ = _reference_region(report)
    references = extract_reference_map(report, source_catalog=source_catalog)
    masked, url_map = _mask_urls(body)
    claims: list[dict[str, Any]] = []
    idx = 0
    for raw_sentence in _SENTENCE_SPLIT.split(masked):
        sentence = _restore(raw_sentence.strip(), url_map)
        if len(sentence) <= 15:
            continue
        cites = _citations_for_sentence(sentence, references)
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
