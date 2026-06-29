from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any
import hashlib
import json
import math
import re

from fastapi import HTTPException
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ...models import KnowledgeBase, KnowledgeCard, WritingMemory
from ..knowledge_base import knowledge_base_storage_dir
from ..path_safety import secure_slug

__all__ = [
    "_as_list",
    "_avoid_text",
    "_bool_value",
    "_card_source_refs",
    "_clip",
    "_confidence",
    "_first_int",
    "_first_text",
    "_int_or_none",
    "_json",
    "_json_dict",
    "_json_list",
    "_json_list_of_dicts",
    "_merge_lists",
    "_normalize_for_fingerprint",
    "content_fingerprint",
    "get_card_or_404",
    "normalized_title_hash",
]

def get_card_or_404(db: Session, knowledge_base: KnowledgeBase, card_id: str) -> KnowledgeCard:
    card = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == card_id)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="知识卡不存在")
    return card

def _card_source_refs(source_ref: dict[str, Any]) -> list[dict[str, Any]]:
    refs = source_ref.get("source_refs")
    if isinstance(refs, list):
        clean_refs = [item for item in refs if isinstance(item, dict)]
        if clean_refs:
            return clean_refs
    return [source_ref] if source_ref else []

def normalized_title_hash(title: str) -> str:
    normalized = re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", (title or "").lower())
    if not normalized:
        normalized = "untitled"
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()

def _first_int(raw: dict[str, Any], source_ref: dict[str, Any], key: str) -> int | None:
    for values in (raw, source_ref):
        value = _int_or_none(values.get(key))
        if value is not None:
            return value
    return None

def _first_text(raw: dict[str, Any], source_ref: dict[str, Any], key: str) -> str | None:
    for values in (raw, source_ref):
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None

def _int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default

def _avoid_text(raw: dict[str, Any]) -> str:
    for key in ("avoid", "do_not_copy", "why_bad"):
        value = raw.get(key)
        if isinstance(value, list):
            return "\n".join(f"- {item}" for item in value)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

def _confidence(raw: dict[str, Any]) -> float:
    try:
        return float(raw.get("confidence", 0.75))
    except (TypeError, ValueError):
        return 0.75

def _as_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []

def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)

def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []

def _json_dict(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def _json_list_of_dicts(value: str | None) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []

def content_fingerprint(title: str, content: str, avoid: str = "", tags: list[str] | None = None) -> str:
    normalized = _normalize_for_fingerprint("\n".join([title or "", content or "", avoid or "", " ".join(sorted(tags or []))]))
    return hashlib.sha256(normalized.encode("utf-8", errors="ignore")).hexdigest()

def _normalize_for_fingerprint(value: str) -> str:
    text = (value or "").lower()
    full_width = "，。！？；：（）【】“”‘’、　"
    half_width = ",.!?;:()[]\"\"''  "
    text = text.translate(str.maketrans(full_width, half_width))
    text = re.sub(r"#+\s*", "", text)
    text = re.sub(r"\b(rule|content|avoid|summary|use when|notes)\b", "", text)
    text = re.sub(r"\s+", "", text)
    return text

def _merge_lists(left: list[str], right: list[str]) -> list[str]:
    return list(dict.fromkeys([*(item for item in left if item), *(item for item in right if item)]))

def _clip(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."

