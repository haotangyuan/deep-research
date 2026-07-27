r"""Eval MVP v2 — Section Team Revision/Merge Information Loss（§9.3）。

对应 v2 §9.3「Section Team」指标：

- ``merge_information_loss``         : merged 报告相对各 section 正文的信息丢失比例
                                       （section 里的 claim/citation 在 merged 里未保留）
- ``claim_retention_after_revision`` : revision 相对 draft 保留的 claim 比例
- ``citation_retention_after_revision``: revision 相对 draft 保留的 citation 比例

确定性实现，不需要 LLM。以「claim（含数字/百分比/URL 的句子）」和「citation
（markdown 链接 + [n] 数字标记）」为载体算保留率：

- retention = 子集内容在后续版本里仍出现的比例（按文本块归一化匹配）
- merge_information_loss = 1 - claim_retention_in_merge

无 section artifact 时返回 None 分数（不参与 gate），不报失败。
"""
from __future__ import annotations

import re

from evals.evaluators.base import BaseEvaluator, EvalContext
from evals.schemas import MetricResult

# claim 载体：含数字/百分比/URL 的句子
_CLAIM_RE = re.compile(r"\d|[%％]|https?://")
# citation 载体：markdown 链接 + [n] 数字标记
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
_NUMERIC_CITE_RE = re.compile(r"\[(\d+)\]")
_SENT_SPLIT_RE = re.compile(r"(?<=[。.!?])\s*")


def _mask_urls(text: str, store: list[str]) -> str:
    """把 URL 替换为占位符，避免 URL 里的 . 被当句末。"""
    def _repl(m: re.Match) -> str:
        store.append(m.group(0))
        return f"__URL{len(store) - 1}__"

    return re.sub(r"https?://[^\s)]+", _repl, text)


def _normalize(text: str) -> str:
    """归一化：去全部空白 + 小写，使跨版本子串匹配不受空格/换行干扰。

    中文报告里空白是排版噪声（删 citation 标记后常留空格），去空白后
    ``市场 5000 亿 。`` 与 ``市场5000亿。`` 才能匹配上。
    """
    return re.sub(r"\s+", "", text or "").lower()


def _strip_citations(text: str) -> str:
    """剥离 citation 标记，使 claim 句子纯净，跨版本可子串匹配。

    md 链接 ``[锚文本](url)`` 整体删除（锚文本如「来源」「见报告」是引用说明，
    非事实内容，保留会污染 claim 文本）；``[n]`` 数字标记整删。
    """
    # md 链接 [text](url) → 整删
    text = re.sub(r"\[[^\]]*\]\(https?://[^)]+\)", "", text or "")
    # [n] 数字标记 → 删除
    text = _NUMERIC_CITE_RE.sub("", text)
    return text


def _claims(text: str) -> list[str]:
    """从文本抽出 claim 载体（含数字/百分比/URL 的句子，归一化去空白小写）。

    先剥离 citation 标记，避免 ``市场 5000 亿 [来源](url)。`` 里的 citation
    污染 claim 文本导致跨版本子串匹配失败。归一化时去全部空白，使
    ``市场 5000 亿 。`` 与 ``市场5000亿。`` 能匹配上。
    """
    urls: list[str] = []
    stripped = _strip_citations(text)
    masked = _mask_urls(stripped, urls)
    sents = [s.strip() for s in _SENT_SPLIT_RE.split(masked) if s.strip()]
    return [_normalize(s) for s in sents if _CLAIM_RE.search(s)]


def _citations(text: str) -> set[str]:
    """抽出 citation 载体（md 链接 url + [n] 标记），归一化集合。"""
    cits: set[str] = set()
    for m in _MD_LINK_RE.finditer(text or ""):
        cits.add(m.group(2).strip().lower())
    for m in _NUMERIC_CITE_RE.finditer(text or ""):
        cits.add(f"[{m.group(1)}]")
    return cits


def _retention(prior: list[str] | set[str], later_text: str, *, is_claim: bool) -> float:
    """prior 里的内容在 later_text 里仍出现的比例。"""
    if not prior:
        return 1.0  # 无 prior 内容不算丢失
    if is_claim:
        # claim 载体已剥离 citation，对比时 later_text 也要同口径剥离+归一化，
        # 否则 ``市场5000亿。`` 在 ``市场5000亿[来源](url)。`` 里子串匹配失败
        later_norm = _normalize(_strip_citations(later_text))
        kept = sum(1 for c in prior if c and c in later_norm)
        return kept / len(prior)
    later_lower = (later_text or "").lower()
    kept = sum(1 for c in prior if c and c in later_lower)
    return kept / len(prior)


class RevisionMergeLossEvaluator(BaseEvaluator):
    """Section Team 信息保留/丢失评估器。产 §9.3 三个指标。"""

    name = "section_team_loss"
    version = "1.0.0"
    metric_group = "mechanism"

    async def evaluate(self, ctx: EvalContext) -> list[MetricResult]:
        sections = ctx.section_artifacts or {}
        merged = ctx.merged_report or ctx.report or ""
        results: list[MetricResult] = []

        # 无 section artifact → 三指标 None，不参与 gate
        if not sections:
            for name in ("merge_information_loss", "claim_retention_after_revision", "citation_retention_after_revision"):
                results.append(
                    MetricResult(
                        metric_name=name,
                        metric_group=self.metric_group,
                        evaluator_name=self.name,
                        evaluator_version=self.version,
                        score_value=None,
                        passed=None,
                        judge_model=None,
                        reason="无 section artifact（非 Section Team 路径），跳过",
                        details={},
                    )
                )
            return results

        # revision vs draft：claim/citation 保留率
        claim_retentions: list[float] = []
        cite_retentions: list[float] = []
        all_draft_claims: list[str] = []
        all_draft_cites: set[str] = set()
        for sid, parts in sections.items():
            draft = parts.get("draft") or ""
            revision = parts.get("revision")
            d_claims = _claims(draft)
            d_cites = _citations(draft)
            all_draft_claims.extend(d_claims)
            all_draft_cites |= d_cites
            if revision is not None:
                cr = _retention(d_claims, revision, is_claim=True)
                ctr = _retention(d_cites, revision, is_claim=False)
                claim_retentions.append(cr)
                cite_retentions.append(ctr)

        if claim_retentions:
            claim_retention = round(sum(claim_retentions) / len(claim_retentions), 4)
            results.append(
                MetricResult(
                    metric_name="claim_retention_after_revision",
                    metric_group=self.metric_group,
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=claim_retention,
                    passed=1 if claim_retention >= 0.8 else 0,
                    judge_model=None,
                    reason=f"revision 相对 draft 平均 claim 保留率={claim_retention}",
                    details={"section_count": len(claim_retentions)},
                )
            )
            cite_retention = round(sum(cite_retentions) / len(cite_retentions), 4)
            results.append(
                MetricResult(
                    metric_name="citation_retention_after_revision",
                    metric_group=self.metric_group,
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=cite_retention,
                    passed=1 if cite_retention >= 0.8 else 0,
                    judge_model=None,
                    reason=f"revision 相对 draft 平均 citation 保留率={cite_retention}",
                    details={"section_count": len(cite_retentions)},
                )
            )
        else:
            # 有 draft 无 revision（未走修订）
            for name in ("claim_retention_after_revision", "citation_retention_after_revision"):
                results.append(
                    MetricResult(
                        metric_name=name,
                        metric_group=self.metric_group,
                        evaluator_name=self.name,
                        evaluator_version=self.version,
                        score_value=None,
                        passed=None,
                        judge_model=None,
                        reason="有 section draft 但无 revision（未走修订链路）",
                        details={},
                    )
                )

        # merge information loss：draft 的 claim/citation 在 merged 里保留的比例，loss = 1 - retention
        if all_draft_claims or all_draft_cites:
            claim_in_merge = _retention(all_draft_claims, merged, is_claim=True)
            cite_in_merge = _retention(all_draft_cites, merged, is_claim=False)
            retention = (claim_in_merge + cite_in_merge) / 2
            loss = round(1 - retention, 4)
            results.append(
                MetricResult(
                    metric_name="merge_information_loss",
                    metric_group=self.metric_group,
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=loss,
                    passed=1 if loss <= 0.3 else 0,
                    judge_model=None,
                    reason=f"merged 相对 section draft 信息丢失={loss}（claim_retain={claim_in_merge:.2f}, cite_retain={cite_in_merge:.2f}）",
                    details={
                        "claim_retention_in_merge": round(claim_in_merge, 4),
                        "citation_retention_in_merge": round(cite_in_merge, 4),
                        "draft_claim_count": len(all_draft_claims),
                        "draft_citation_count": len(all_draft_cites),
                    },
                )
            )
        else:
            results.append(
                MetricResult(
                    metric_name="merge_information_loss",
                    metric_group=self.metric_group,
                    evaluator_name=self.name,
                    evaluator_version=self.version,
                    score_value=None,
                    passed=None,
                    judge_model=None,
                    reason="section draft 无 claim/citation 载体，无法算丢失",
                    details={},
                )
            )
        return results
