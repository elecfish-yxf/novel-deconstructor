from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import math
import re
import uuid

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ...config import PROJECT_ROOT
from ...config import get_settings
from ...database import SessionLocal
from ...models import DeconstructionSkill, KnowledgeBase, KnowledgeCard, Outline, WritingDraftJob, WritingMemory
from ...schemas import (
    KnowledgeMarkdownImportRequest,
    KnowledgePackageImportRequest,
    WorldbuildingDraftRequest,
    WritingDraftJobRead,
    WritingDraftRequest,
    WritingGenerateRequest,
    WritingGenerateResponse,
    WritingMemoryConfirmRequest,
    WritingOutlineRequest,
    WritingRevisionRequest,
)
from ..knowledge_base import search_knowledge
from ..knowledge_cards import (
    canonical_group_id,
    normalized_title_hash,
    sync_memory_card,
    used_knowledge_from_results,
)
from ..llm_provider import DoubaoResponsesProvider, LLMProvider, LLMRequest, OpenAICompatibleProvider, is_doubao_base_url
from ..rag_retrieval import search_rag_cards
from ..retrieval_service import (
    delete_card_vector,
    delete_memory_vector,
    index_knowledge_card,
    index_writing_memory,
    rebuild_knowledge_base_vectors,
    retrieve_for_writing,
)

__all__ = [
    "AGENT_RETRIEVAL_PROTOCOL",
    "AUTO_BOOK_OUTLINE_SOURCE",
    "AUTO_NOVEL_OUTLINE_SOURCE",
    "AUTO_VOLUME_CONTINUITY_SOURCE",
    "AUTO_VOLUME_OUTLINE_SOURCE",
    "DEFAULT_LONG_SECTION_CHARS",
    "DRAFT_TERMINAL_STATUSES",
    "FORCED_CONTEXT_CARD_TYPES",
    "LONG_GENERATION_TOLERANCE",
    "MAX_SECTION_SUPPLEMENTS",
    "OUTLINE_CARD_TYPE_BOOK",
    "OUTLINE_CARD_TYPE_CHAPTER",
    "OUTLINE_CARD_TYPE_VOLUME",
    "RAG_PROMPT_CARD_LIMIT",
    "SECTION_MIN_COMPLETION_RATIO",
    "SINGLE_CALL_SOFT_LIMIT_CHARS",
    "_char_stats",
    "_clip",
    "_content_lines",
    "_display_char_count",
    "_ensure_workspace_kb",
    "_first_text_block",
    "_format_handoff_list",
    "_format_handoff_position",
    "_json_dict_text",
    "_json_list_text",
    "_json_list_values",
    "_json_object_text",
    "_json_scalar_text",
    "_keyword_excerpt",
    "_keyword_lines",
    "_last_paragraphs",
    "_last_sentence",
    "_list_candidates",
    "_position_value",
    "_recent_memories",
    "_safe_delete_card_vector",
    "_safe_delete_memory_vector",
    "_safe_index_card",
    "_safe_index_memory",
    "_safe_rebuild_kb_vectors",
    "_tail_clip",
    "_tail_excerpt",
    "_unique_texts",
    "_workspace_kb_ids",
    "count_cjk_chars",
    "count_non_space_chars",
    "estimate_output_tokens",
]

AGENT_RETRIEVAL_PROTOCOL = {
    "outline": ["structure_pattern", "conflict_pattern", "emotion_module", "worldbuilding", "memory"],
    "draft": ["style_pattern", "dialogue_rule", "emotion_module", "anti_pattern", "worldbuilding", "memory"],
    "worldbuilding_draft": ["writing_guide", "structure_pattern", "conflict_pattern", "emotion_module"],
    "worldbuilding_check": ["worldbuilding", "memory"],
    "revision": ["language_style", "anti_pattern", "user_preference", "memory"],
    "continuation": ["memory", "previous_ending", "character_state", "foreshadowing", "writing_guide"],
}

SINGLE_CALL_SOFT_LIMIT_CHARS = 2500

DEFAULT_LONG_SECTION_CHARS = 2000

LONG_GENERATION_TOLERANCE = 0.1

SECTION_MIN_COMPLETION_RATIO = 0.8

MAX_SECTION_SUPPLEMENTS = 2

RAG_PROMPT_CARD_LIMIT = 60

DRAFT_TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

AUTO_VOLUME_CONTINUITY_SOURCE = "auto_volume_continuity"

FORCED_CONTEXT_CARD_TYPES = {
    "ChapterOutline",
    "ChapterHandoff",
    "book_outline",
    "volume_outline",
    "character_state",
    "relationship_state",
    "foreshadowing",
    "volume_summary",
}

AUTO_VOLUME_OUTLINE_SOURCE = "auto_volume_outline"

AUTO_NOVEL_OUTLINE_SOURCE = "auto_novel_outline"

AUTO_BOOK_OUTLINE_SOURCE = "auto_book_outline"

OUTLINE_CARD_TYPE_BOOK = "book_outline"

OUTLINE_CARD_TYPE_VOLUME = "volume_outline"

OUTLINE_CARD_TYPE_CHAPTER = "chapter_outline"

def _json_list_values(value: Any, *, limit: int, max_chars: int) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif value:
        raw_items = [value]
    else:
        raw_items = []
    items: list[str] = []
    for item in raw_items:
        text = _json_scalar_text(item)
        if text:
            items.append(_clip(text, max_chars))
    return _unique_texts(items)[:limit]

def _content_lines(content: str) -> list[str]:
    return [line.strip(" \t-*>#。；;") for line in (content or "").splitlines() if line.strip(" \t-*>#。；;")]

def _first_text_block(lines: list[str], fallback: str) -> str:
    for line in lines:
        if len(line) >= 8:
            return line
    return fallback.strip()

def _keyword_lines(lines: list[str], keywords: list[str]) -> list[str]:
    return [line for line in lines if any(keyword.lower() in line.lower() for keyword in keywords)]

def _keyword_excerpt(lines: list[str], keywords: list[str]) -> str:
    matches = _keyword_lines(lines, keywords)
    return _clip("；".join(matches[:3]), 500) if matches else ""

def _list_candidates(lines: list[str], *, fallback: str, limit: int) -> list[str]:
    items = [_clip(line, 220) for line in lines if line]
    if not items and fallback:
        items = [_clip(part, 220) for part in re.split(r"[。！？!?\n]+", fallback) if part.strip()]
    return _unique_texts(items)[:limit]

def _tail_excerpt(content: str, max_chars: int) -> str:
    compact = "\n".join(_content_lines(content))
    if len(compact) <= max_chars:
        return compact
    return compact[-max_chars:].strip()

def _unique_texts(items: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = re.sub(r"\s+", " ", (item or "").strip())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(normalized)
    return unique

def _json_list_text(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []

def _json_dict_text(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def _position_value(value: int | None) -> str:
    return str(value) if value is not None else "UNKNOWN"

def _json_object_text(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}

def _json_scalar_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        parts = []
        for key, item in value.items():
            text = _json_scalar_text(item)
            if text:
                parts.append(f"{key}: {text}")
        return "；".join(parts)
    if isinstance(value, list):
        parts = []
        for item in value:
            text = _json_scalar_text(item)
            if text:
                parts.append(text)
        return "；".join(parts)
    return str(value).strip()

def _format_handoff_position(value: Any) -> str:
    if not isinstance(value, dict):
        return "UNKNOWN"
    volume = value.get("volume_index")
    chapter = value.get("chapter_index")
    volume_text = f"Volume {volume}" if volume is not None else "Volume UNKNOWN"
    chapter_text = f"Chapter {chapter}" if chapter is not None else "Chapter UNKNOWN"
    title = _json_scalar_text(value.get("chapter_title"))
    return f"{volume_text} {chapter_text}{f' ({title})' if title else ''}"

def _format_handoff_list(label: str, value: Any, *, limit: int) -> str:
    if isinstance(value, list):
        items = [_json_scalar_text(item) for item in value]
    else:
        items = [_json_scalar_text(value)]
    items = _unique_texts([item for item in items if item])[:limit]
    if not items:
        return ""
    return f"{label}:\n" + "\n".join(f"- {item}" for item in items)

def _last_paragraphs(text: str, *, count: int = 3, max_chars: int = 1600) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n|\r?\n", text or "") if part.strip()]
    if not paragraphs:
        return ""
    return _tail_clip("\n\n".join(paragraphs[-count:]), max_chars)

def _last_sentence(text: str, max_chars: int = 260) -> str:
    tail = _tail_clip(text or "", max(max_chars * 4, 900))
    if not tail:
        return ""
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?；;])\s*", tail) if part.strip()]
    if sentences:
        return _tail_clip(sentences[-1], max_chars)
    paragraphs = [part.strip() for part in tail.splitlines() if part.strip()]
    return _tail_clip(paragraphs[-1], max_chars) if paragraphs else _tail_clip(tail, max_chars)

def count_cjk_chars(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text or ""))

def count_non_space_chars(text: str) -> int:
    return len(re.sub(r"\s+", "", text or ""))

def estimate_output_tokens(text: str) -> int:
    cjk = count_cjk_chars(text)
    non_space = count_non_space_chars(text)
    ascii_like = max(0, non_space - cjk)
    return max(1, math.ceil(cjk * 1.15 + ascii_like / 4))

def _char_stats(text: str) -> dict[str, int]:
    cjk = count_cjk_chars(text)
    non_space = count_non_space_chars(text)
    return {
        "actual_chars": max(cjk, non_space),
        "cjk_chars": cjk,
        "non_space_chars": non_space,
        "estimated_tokens": estimate_output_tokens(text),
    }

def _display_char_count(text: str) -> int:
    return _char_stats(text)["actual_chars"]

def _safe_index_card(db: Session, card: KnowledgeCard | None) -> None:
    if not card:
        return
    try:
        index_knowledge_card(db, card)
    except Exception:
        pass

def _safe_delete_card_vector(card: KnowledgeCard | str | None) -> None:
    if not card:
        return
    try:
        delete_card_vector(card)
    except Exception:
        pass

def _safe_index_memory(db: Session, memory: WritingMemory | None) -> None:
    if not memory:
        return
    try:
        index_writing_memory(db, memory)
    except Exception:
        pass

def _safe_delete_memory_vector(memory: WritingMemory | int | None) -> None:
    if not memory:
        return
    try:
        delete_memory_vector(memory)
    except Exception:
        pass

def _safe_rebuild_kb_vectors(db: Session, knowledge_base: KnowledgeBase) -> None:
    try:
        rebuild_knowledge_base_vectors(db, knowledge_base)
    except Exception:
        pass

def _ensure_workspace_kb(db: Session, workspace_id: str, knowledge_base_id: int) -> KnowledgeBase:
    kb = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == knowledge_base_id, KnowledgeBase.workspace_id == workspace_id)
        .first()
    )
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb

def _workspace_kb_ids(db: Session, workspace_id: str, requested_ids: list[int]) -> list[int]:
    query = db.query(KnowledgeBase.id).filter(KnowledgeBase.workspace_id == workspace_id)
    if requested_ids:
        query = query.filter(KnowledgeBase.id.in_(requested_ids))
    return [item.id for item in query.all()]

def _recent_memories(db: Session, workspace_id: str, kb_ids: list[int], limit: int = 8) -> list[WritingMemory]:
    if not kb_ids:
        return []
    return (
        db.query(WritingMemory)
        .filter(WritingMemory.workspace_id == workspace_id, WritingMemory.knowledge_base_id.in_(kb_ids))
        .order_by(WritingMemory.updated_at.desc())
        .limit(limit)
        .all()
    )

def _clip(text: str, max_chars: int) -> str:
    compact = text.strip()
    if len(compact) <= max_chars:
        return compact
    return f"{compact[:max_chars].rstrip()}..."

def _tail_clip(text: str, max_chars: int) -> str:
    compact = text.strip()
    if len(compact) <= max_chars:
        return compact
    return f"...{compact[-max_chars:].lstrip()}"

