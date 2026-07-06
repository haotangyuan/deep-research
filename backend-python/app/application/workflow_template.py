from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.config import get_settings


# 支持的研究类型枚举（与 ScopeAgent 输出对应）
RESEARCH_TYPES = {
    "tech_comparison",
    "market_analysis",
    "academic_review",
    "fact_lookup",
    "trend_forecast",
    "general",
}


def _template_dir() -> Path:
    return Path(get_settings().research_ultra_template_dir)


def _read(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_template(research_type: str | None) -> dict[str, Any]:
    """加载指定类型的模板，不存在则 fallback 到 default。"""
    base = _template_dir()
    if research_type and research_type in RESEARCH_TYPES and research_type != "general":
        path = base / f"ultra_{research_type}.json"
        if path.exists():
            return _read(path)
    return _read(base / "ultra_default.json")


def select_template(research_type: str | None, confidence: float) -> dict[str, Any]:
    """按意图识别结果选模板：置信度 >= 0.7 且有对应模板才用类型模板，否则 default。

    借鉴点 E：意图识别 + 模板分配，零额外 LLM 调用（复用 ScopeAgent 输出）。
    """
    if (
        research_type
        and research_type in RESEARCH_TYPES
        and research_type != "general"
        and confidence >= 0.7
    ):
        base = _template_dir()
        path = base / f"ultra_{research_type}.json"
        if path.exists():
            return _read(path)
    return load_template("general")
