from __future__ import annotations

import json
from typing import Any


def extract_object(text: str) -> str:
    if not text:
        raise ValueError("empty json text")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("json object not found")
    return cleaned[start : end + 1]


def extract_json(text: str) -> dict[str, Any]:
    return json.loads(extract_object(text))


def truncate(value: str | None, max_chars: int) -> str:
    if not value:
        return ""
    return value if len(value) <= max_chars else value[:max_chars]
