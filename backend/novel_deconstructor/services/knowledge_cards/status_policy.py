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
from .common import *

__all__ = [
    "ACTIVE_STATUSES",
    "ALWAYS_ON_QUERY_TERMS",
    "AUTO_MERGE_THRESHOLD",
    "BLOCKED_STATUSES",
    "CARD_COLLECTIONS",
    "CARD_PREFIXES",
    "CHAPTER_HEADING_RE",
    "CONTEXT_ROLE_BY_CARD_TYPE",
    "DEMO_PACKAGE_IDS",
    "PINNED_CONTEXT_CARD_TYPES",
    "RAG_COMPACT_CONTENT_MAX_CHARS",
    "RAG_COMPACT_EXCLUDED_CARD_TYPES",
    "RAG_COMPACT_GROUP_SIZE",
    "RAG_COMPACT_ITEM_MAX_CHARS",
    "RAG_COMPACT_MIN_GROUP_CARDS",
    "RAG_COMPACT_SAMPLE_REF_LIMIT",
    "RAG_COMPACT_SOURCE_GROUP_LIMIT",
    "RAG_COMPACT_SOURCE_HEADING_LIMIT",
    "RAG_SEARCH_MAX_TOP_K",
    "RAG_SECONDARY_MIN_TOP_K",
    "RAG_SOURCE_CAP_PER_SOURCE",
    "RETRIEVABLE_STATUSES",
    "REVIEW_MERGE_THRESHOLD",
    "SCOPE_ALIASES",
    "SECONDARY_CARD_TYPES",
    "SEMANTIC_MERGE_CARD_TYPES",
    "STAGE_QUERY_EXPANSIONS",
    "VALID_CONTEXT_ROLES",
    "VALID_LIBRARY_TYPES",
    "VALID_RETRIEVAL_LEVELS",
    "VALID_SCOPE_LEVELS",
    "VALID_STATUSES",
    "VOLUME_HEADING_RE",
    "WORD_RE",
    "_apply_card_db_scope_filter",
    "_apply_card_db_status_filter",
    "_card_scope_filter_reason",
    "_card_status_filter_reason",
    "_count_db_future_position_cards",
    "_default_context_role",
    "_default_is_canonical",
    "_default_retrievable",
    "_default_retrieval_level",
    "_effective_retrieval_level",
    "_normalized_allowed_scope_levels",
    "_refresh_card_retrieval_metadata",
    "_scope_allowed",
    "_scope_level_column_values",
    "canonical_group_id",
    "card_to_read",
    "is_after",
    "is_before",
    "is_card_visible_for_position",
    "normalize_card_type",
    "normalize_context_role",
    "normalize_library_type",
    "normalize_retrieval_level",
    "normalize_scope_level",
    "normalize_status",
    "select_preferred_card_types",
]

CARD_COLLECTIONS = {
    "chapter_analysis": "chapter_analysis",
    "chapter_analyses": "chapter_analysis",
    "writing_rules": "writing_rule",
    "writing_rule": "writing_rule",
    "emotion_modules": "emotion_module",
    "emotion_module": "emotion_module",
    "conflict_patterns": "conflict_pattern",
    "conflict_pattern": "conflict_pattern",
    "anti_patterns": "anti_pattern",
    "anti_pattern": "anti_pattern",
    "style_patterns": "style_pattern",
    "style_pattern": "style_pattern",
    "information_patterns": "information_pattern",
    "information_pattern": "information_pattern",
}

CARD_PREFIXES = {
    "chapter_analysis": "CA",
    "writing_rule": "WR",
    "emotion_module": "EM",
    "conflict_pattern": "CP",
    "anti_pattern": "AP",
    "style_pattern": "SP",
    "information_pattern": "IP",
    "memory": "MEM",
    "outline": "MEM",
    "draft": "MEM",
    "ChapterOutline": "CHO",
    "ChapterHandoff": "CHH",
    "book_outline": "BO",
    "volume_outline": "VO",
    "character_state": "MEM",
    "foreshadowing": "MEM",
    "continuity_note": "MEM",
    "worldbuilding": "WB",
    "character": "CH",
    "location": "LC",
    "faction": "FC",
    "rule": "RL",
    "timeline": "TL",
    "item": "IT",
}

VALID_LIBRARY_TYPES = {"writing_guide", "worldbuilding", "memory"}

VALID_STATUSES = {"raw_extracted", "reviewed", "approved", "merged", "disabled", "deleted", "deprecated", "superseded"}

RETRIEVABLE_STATUSES = {"reviewed", "approved"}

BLOCKED_STATUSES = {"deleted", "deprecated", "superseded", "merged", "disabled"}

ACTIVE_STATUSES = RETRIEVABLE_STATUSES

VALID_SCOPE_LEVELS = {"global", "volume", "chapter"}

SCOPE_ALIASES = {"book": "global"}

VALID_RETRIEVAL_LEVELS = {"pinned", "primary", "secondary", "evidence"}

VALID_CONTEXT_ROLES = {"fact", "memory", "guide", "style", "anti_pattern", "evidence", "auxiliary"}

AUTO_MERGE_THRESHOLD = 0.88

REVIEW_MERGE_THRESHOLD = 0.72

RAG_SEARCH_MAX_TOP_K = 200

RAG_SECONDARY_MIN_TOP_K = 20

RAG_SOURCE_CAP_PER_SOURCE = 2

RAG_COMPACT_MIN_GROUP_CARDS = 6

RAG_COMPACT_GROUP_SIZE = 8

RAG_COMPACT_ITEM_MAX_CHARS = 220

RAG_COMPACT_CONTENT_MAX_CHARS = 1800

RAG_COMPACT_SAMPLE_REF_LIMIT = 12

RAG_COMPACT_SOURCE_GROUP_LIMIT = 24

RAG_COMPACT_SOURCE_HEADING_LIMIT = 8

RAG_COMPACT_EXCLUDED_CARD_TYPES = {"ChapterOutline", "ChapterHandoff", "character", "location", "faction", "item", "timeline"}

CHAPTER_HEADING_RE = re.compile(r"第\s*([0-9０-９〇零一二两三四五六七八九十百千]+)\s*[章节回]")

VOLUME_HEADING_RE = re.compile(r"第\s*([0-9０-９〇零一二两三四五六七八九十百千]+)\s*卷")

SEMANTIC_MERGE_CARD_TYPES = {
    "writing_rule",
    "emotion_module",
    "conflict_pattern",
    "anti_pattern",
    "style_pattern",
    "information_pattern",
}

PINNED_CONTEXT_CARD_TYPES = {
    "ChapterOutline",
    "ChapterHandoff",
    "VolumeSummary",
    "BookWorldRules",
    "BookCharacterRegistry",
    "character_state",
    "relationship_state",
    "foreshadowing",
    "volume_summary",
}

SECONDARY_CARD_TYPES = {"chapter_analysis", "information_pattern"}

CONTEXT_ROLE_BY_CARD_TYPE = {
    "anti_pattern": "anti_pattern",
    "AntiPattern": "anti_pattern",
    "style_pattern": "style",
    "StylePattern": "style",
    "ChapterOutline": "memory",
    "ChapterHandoff": "memory",
    "character_state": "memory",
    "relationship_state": "memory",
    "foreshadowing": "memory",
    "volume_summary": "memory",
}

DEMO_PACKAGE_IDS = {"demo_rain_lamp_street", "demo_rain_lamp_street_canonical_cards"}

WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]+")

STAGE_QUERY_EXPANSIONS = {
    "outline": [
        "outline",
        "chapter outline",
        "story structure",
        "conflict escalation",
        "turning point",
        "hook",
        "章节提纲",
        "结构",
        "冲突",
        "目标",
        "阻力",
        "章尾钩子",
    ],
    "draft": [
        "draft",
        "scene",
        "style",
        "emotion",
        "conflict",
        "dialogue",
        "正文",
        "场景",
        "动作",
        "对话",
        "情绪",
        "节奏",
    ],
    "revision": [
        "revision",
        "polish",
        "anti pattern",
        "style",
        "consistency",
        "润色",
        "改写",
        "反模式",
        "文风",
        "一致性",
    ],
    "continue": [
        "continue",
        "continuity",
        "previous ending",
        "character state",
        "foreshadowing",
        "续写",
        "承接",
        "上一章结尾",
        "人物状态",
        "伏笔",
    ],
    "continuation": [
        "continue",
        "continuity",
        "previous ending",
        "character state",
        "foreshadowing",
        "续写",
        "承接",
        "上一章结尾",
        "人物状态",
        "伏笔",
    ],
    "worldbuilding_check": [
        "worldbuilding",
        "setting",
        "character",
        "location",
        "faction",
        "rule",
        "世界观",
        "设定",
        "人物",
        "地点",
        "势力",
        "规则",
    ],
}

ALWAYS_ON_QUERY_TERMS = ["worldbuilding", "memory", "世界观", "设定", "记忆", "连续性"]

def normalize_library_type(value: str | None, default: str = "writing_guide") -> str:
    return value if value in VALID_LIBRARY_TYPES else default

def normalize_status(value: str | None, default: str = "raw_extracted") -> str:
    return value if value in VALID_STATUSES else default

def normalize_card_type(value: str | None, fallback: str = "writing_rule") -> str:
    cleaned = (value or fallback).strip()
    aliases = {
        "WritingRule": "writing_rule",
        "EmotionModule": "emotion_module",
        "ConflictPattern": "conflict_pattern",
        "AntiPattern": "anti_pattern",
        "StylePattern": "style_pattern",
        "InformationPattern": "information_pattern",
        "ChapterAnalysis": "chapter_analysis",
        "Memory": "memory",
        "ChapterOutline": "ChapterOutline",
        "ChapterHandoff": "ChapterHandoff",
        "WorldbuildingFact": "worldbuilding",
    }
    if cleaned in aliases:
        return aliases[cleaned]
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cleaned).lower()
    return CARD_COLLECTIONS.get(cleaned, CARD_COLLECTIONS.get(snake, snake))

def normalize_scope_level(value: str | None, default: str = "global") -> str:
    cleaned = (value or default or "global").strip().lower()
    cleaned = SCOPE_ALIASES.get(cleaned, cleaned)
    return cleaned if cleaned in VALID_SCOPE_LEVELS else default

def normalize_retrieval_level(value: str | None, default: str = "evidence") -> str:
    cleaned = (value or default or "evidence").strip().lower()
    return cleaned if cleaned in VALID_RETRIEVAL_LEVELS else default

def normalize_context_role(value: str | None, default: str = "auxiliary") -> str:
    cleaned = (value or default or "auxiliary").strip().lower()
    return cleaned if cleaned in VALID_CONTEXT_ROLES else default

def select_preferred_card_types(stage: str) -> list[str]:
    mapping = {
        "outline": ["writing_rule", "conflict_pattern", "emotion_module", "chapter_analysis", "ChapterHandoff", "ChapterOutline"],
        "draft": ["writing_rule", "emotion_module", "style_pattern", "anti_pattern", "memory", "ChapterHandoff", "ChapterOutline"],
        "revision": ["anti_pattern", "style_pattern", "writing_rule", "memory", "ChapterHandoff", "ChapterOutline"],
        "continue": ["memory", "chapter_analysis", "writing_rule", "emotion_module", "ChapterHandoff", "ChapterOutline"],
        "continuation": ["memory", "chapter_analysis", "writing_rule", "emotion_module", "ChapterHandoff", "ChapterOutline"],
        "worldbuilding_check": ["worldbuilding", "memory", "character", "location", "faction", "rule"],
    }
    return mapping.get((stage or "").strip(), ["writing_rule", "emotion_module", "anti_pattern", "memory"])

def is_after(
    volume_a: int | None,
    chapter_a: int | None,
    volume_b: int | None,
    chapter_b: int | None,
) -> bool:
    if volume_a is None or volume_b is None:
        return False
    if volume_a > volume_b:
        return True
    if volume_a == volume_b and chapter_a is not None and chapter_b is not None:
        return chapter_a > chapter_b
    return False

def is_before(
    volume_a: int | None,
    chapter_a: int | None,
    volume_b: int | None,
    chapter_b: int | None,
) -> bool:
    if volume_a is None or volume_b is None:
        return False
    if volume_a < volume_b:
        return True
    if volume_a == volume_b and chapter_a is not None and chapter_b is not None:
        return chapter_a < chapter_b
    return False

def is_card_visible_for_position(
    card: KnowledgeCard,
    current_volume_index: int | None,
    current_chapter_index: int | None,
    *,
    include_future: bool = False,
    include_raw: bool = False,
    allowed_scope_levels: list[str] | None = None,
) -> bool:
    if _card_status_filter_reason(card, include_raw=include_raw):
        return False
    return _card_scope_filter_reason(
        card,
        current_volume_index,
        current_chapter_index,
        include_future=include_future,
        allowed_scope_levels=allowed_scope_levels,
    ) is None

def card_to_read(card: KnowledgeCard) -> dict[str, Any]:
    return {
        "id": card.id,
        "knowledge_base_id": card.knowledge_base_id,
        "card_id": card.card_id,
        "library_type": card.library_type,
        "card_type": card.card_type,
        "title": card.title,
        "content": card.content,
        "summary": card.summary,
        "tags": _json_list(card.tags_json),
        "source_ref": _json_dict(card.source_ref_json),
        "source_refs": _json_list_of_dicts(card.source_refs_json),
        "use_when": _json_list(card.use_when_json),
        "avoid": card.avoid,
        "confidence": card.confidence,
        "status": card.status,
        "source_kind": card.source_kind,
        "package_id": card.package_id,
        "markdown_path": card.markdown_path,
        "is_canonical": bool(card.is_canonical),
        "merged_into_card_id": card.merged_into_card_id,
        "merged_from_ids": _json_list(card.merged_from_ids_json),
        "evidence_count": card.evidence_count or 1,
        "content_fingerprint": card.content_fingerprint or "",
        "normalized_title_hash": card.normalized_title_hash or "",
        "canonical_group_id": card.canonical_group_id or "",
        "retrieval_level": _effective_retrieval_level(card),
        "context_role": normalize_context_role(card.context_role, "auxiliary"),
        "scope_level": card.scope_level or "global",
        "volume_index": card.volume_index,
        "volume_title": card.volume_title,
        "chapter_index": card.chapter_index,
        "chapter_title": card.chapter_title,
        "valid_from_volume_index": card.valid_from_volume_index,
        "valid_from_chapter_index": card.valid_from_chapter_index,
        "valid_until_volume_index": card.valid_until_volume_index,
        "valid_until_chapter_index": card.valid_until_chapter_index,
        "reveal_at_volume_index": card.reveal_at_volume_index,
        "reveal_at_chapter_index": card.reveal_at_chapter_index,
        "retrievable": bool(card.retrievable),
        "priority": card.priority or 0,
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }

def _default_is_canonical(raw: dict[str, Any], status: str) -> bool:
    if "is_canonical" in raw:
        return _bool_value(raw.get("is_canonical"), False)
    return status in RETRIEVABLE_STATUSES

def _default_retrievable(raw: dict[str, Any], library_type: str, status: str, is_canonical: bool) -> bool:
    if "retrievable" in raw:
        return _bool_value(raw.get("retrievable"), False)
    if library_type not in {"writing_guide", "worldbuilding", "memory"}:
        return False
    if status == "raw_extracted":
        return False
    if not is_canonical or status not in RETRIEVABLE_STATUSES:
        return False
    return True

def _default_retrieval_level(raw: dict[str, Any], library_type: str, card_type: str, status: str, is_canonical: bool, retrievable: bool) -> str:
    if "retrieval_level" in raw:
        return normalize_retrieval_level(str(raw.get("retrieval_level")), "evidence")
    if status == "raw_extracted" or not is_canonical or not retrievable:
        return "evidence"
    if library_type == "memory" or card_type in PINNED_CONTEXT_CARD_TYPES:
        return "pinned"
    if card_type in SECONDARY_CARD_TYPES:
        return "secondary"
    return "primary"

def _default_context_role(raw: dict[str, Any], library_type: str, card_type: str, status: str) -> str:
    if "context_role" in raw:
        return normalize_context_role(str(raw.get("context_role")), "auxiliary")
    if status == "raw_extracted":
        return "evidence"
    if card_type in CONTEXT_ROLE_BY_CARD_TYPE:
        return CONTEXT_ROLE_BY_CARD_TYPE[card_type]
    if library_type == "memory":
        return "memory"
    if library_type == "worldbuilding":
        return "fact"
    if library_type == "writing_guide":
        return "guide"
    return "auxiliary"

def canonical_group_id(library_type: str, card_type: str, scope: dict[str, Any], title_hash: str) -> str:
    scope_level = normalize_scope_level(str(scope.get("scope_level") or "global"), "global")
    volume = scope.get("volume_index") if scope_level in {"volume", "chapter"} else "*"
    chapter = scope.get("chapter_index") if scope_level == "chapter" else "*"
    return f"{library_type}:{card_type}:{scope_level}:{volume}:{chapter}:{title_hash[:16]}"[:96]

def _refresh_card_retrieval_metadata(card: KnowledgeCard) -> None:
    source_ref = _json_dict(card.source_ref_json)
    if not card.source_refs_json or card.source_refs_json == "[]":
        card.source_refs_json = _json(_card_source_refs(source_ref))
    title_hash = normalized_title_hash(card.title)
    card.normalized_title_hash = title_hash
    card.canonical_group_id = canonical_group_id(
        card.library_type,
        card.card_type,
        {
            "scope_level": card.scope_level,
            "volume_index": card.volume_index,
            "chapter_index": card.chapter_index,
        },
        title_hash,
    )
    card.retrieval_level = _effective_retrieval_level(card)
    if not card.context_role or card.context_role == "auxiliary":
        card.context_role = _default_context_role({}, card.library_type, card.card_type, card.status)
    else:
        card.context_role = normalize_context_role(card.context_role, "auxiliary")

def _card_status_filter_reason(card: KnowledgeCard, *, include_raw: bool = False) -> str | None:
    if card.status in BLOCKED_STATUSES:
        return "blocked_status"
    if card.status == "raw_extracted":
        return None if include_raw else "raw_hidden"
    if not bool(card.retrievable):
        return "not_retrievable"
    if card.status not in RETRIEVABLE_STATUSES:
        return "inactive_status"
    if not bool(card.is_canonical) and not include_raw:
        return "not_canonical"
    return None

def _effective_retrieval_level(card: KnowledgeCard) -> str:
    level = normalize_retrieval_level(card.retrieval_level, "evidence")
    if level == "evidence" and card.status in RETRIEVABLE_STATUSES and bool(card.retrievable) and bool(card.is_canonical):
        return _default_retrieval_level({}, card.library_type, card.card_type, card.status, bool(card.is_canonical), bool(card.retrievable))
    return level

def _apply_card_db_status_filter(query: Any, *, include_inactive: bool, include_raw: bool) -> Any:
    if include_inactive:
        filtered = query.filter(~KnowledgeCard.status.in_(tuple(BLOCKED_STATUSES)))
        if not include_raw:
            filtered = filtered.filter(KnowledgeCard.status != "raw_extracted")
        return filtered
    retrievable_clause = and_(
        KnowledgeCard.status.in_(tuple(RETRIEVABLE_STATUSES)),
        KnowledgeCard.retrievable.is_(True),
        KnowledgeCard.is_canonical.is_(True),
    )
    if include_raw:
        return query.filter(or_(KnowledgeCard.status == "raw_extracted", retrievable_clause))
    return query.filter(retrievable_clause)

def _normalized_allowed_scope_levels(allowed_scope_levels: list[str] | None) -> set[str]:
    return {normalize_scope_level(item, item) for item in (allowed_scope_levels or []) if item}

def _scope_level_column_values(scope_level: str) -> list[str]:
    if scope_level == "global":
        return ["global", "book"]
    return [scope_level]

def _scope_allowed(scope_level: str, allowed_scope_levels: set[str]) -> bool:
    return not allowed_scope_levels or scope_level in allowed_scope_levels

def _apply_card_db_scope_filter(
    query: Any,
    current_volume_index: int | None,
    current_chapter_index: int | None,
    *,
    include_future: bool,
    allowed_scope_levels: list[str] | None,
) -> Any:
    allowed = _normalized_allowed_scope_levels(allowed_scope_levels)
    clauses = []
    if _scope_allowed("global", allowed):
        clauses.append(KnowledgeCard.scope_level.in_(_scope_level_column_values("global")))

    if current_volume_index is None or current_chapter_index is None:
        if clauses:
            return query.filter(KnowledgeCard.library_type == "writing_guide").filter(or_(*clauses))
        return query.filter(False)

    if _scope_allowed("volume", allowed):
        if include_future:
            clauses.append(KnowledgeCard.scope_level == "volume")
        else:
            clauses.append(and_(KnowledgeCard.scope_level == "volume", KnowledgeCard.volume_index == current_volume_index))

    if _scope_allowed("chapter", allowed):
        if include_future:
            clauses.append(KnowledgeCard.scope_level == "chapter")
        else:
            current_chapter_clause = and_(
                KnowledgeCard.scope_level == "chapter",
                KnowledgeCard.volume_index == current_volume_index,
                KnowledgeCard.chapter_index == current_chapter_index,
                KnowledgeCard.library_type != "memory",
            )
            memory_history_clause = and_(
                KnowledgeCard.scope_level == "chapter",
                KnowledgeCard.library_type == "memory",
                or_(
                    KnowledgeCard.volume_index < current_volume_index,
                    and_(KnowledgeCard.volume_index == current_volume_index, KnowledgeCard.chapter_index <= current_chapter_index),
                ),
            )
            clauses.extend([current_chapter_clause, memory_history_clause])

    if not clauses:
        return query.filter(False)
    return query.filter(or_(*clauses))

def _count_db_future_position_cards(
    query: Any,
    current_volume_index: int | None,
    current_chapter_index: int | None,
    *,
    include_future: bool,
) -> int:
    if include_future or current_volume_index is None or current_chapter_index is None:
        return 0
    future_clause = or_(
        and_(KnowledgeCard.scope_level == "volume", KnowledgeCard.volume_index > current_volume_index),
        and_(
            KnowledgeCard.scope_level == "chapter",
            or_(
                KnowledgeCard.volume_index > current_volume_index,
                and_(KnowledgeCard.volume_index == current_volume_index, KnowledgeCard.chapter_index > current_chapter_index),
            ),
        ),
    )
    return query.filter(future_clause).count()

def _card_scope_filter_reason(
    card: KnowledgeCard,
    current_volume_index: int | None,
    current_chapter_index: int | None,
    *,
    include_future: bool = False,
    allowed_scope_levels: list[str] | None = None,
) -> str | None:
    scope_level = normalize_scope_level(card.scope_level, "global")
    allowed = {normalize_scope_level(item, item) for item in (allowed_scope_levels or []) if item}
    if allowed and scope_level not in allowed:
        return "scope"

    if current_volume_index is None or current_chapter_index is None:
        if card.library_type == "writing_guide" and scope_level == "global":
            return None
        return "scope"

    if not include_future:
        if card.reveal_at_volume_index is not None and is_after(
            card.reveal_at_volume_index,
            card.reveal_at_chapter_index,
            current_volume_index,
            current_chapter_index,
        ):
            return "future"
        if card.valid_from_volume_index is not None and is_after(
            card.valid_from_volume_index,
            card.valid_from_chapter_index,
            current_volume_index,
            current_chapter_index,
        ):
            return "future"

    if card.valid_until_volume_index is not None and is_before(
        card.valid_until_volume_index,
        card.valid_until_chapter_index,
        current_volume_index,
        current_chapter_index,
    ):
        return "scope"

    if card.volume_index is not None and is_after(
        card.volume_index,
        card.chapter_index,
        current_volume_index,
        current_chapter_index,
    ):
        return "future"

    if scope_level == "global":
        return None
    if scope_level == "volume":
        if card.volume_index is None:
            return "scope"
        if card.volume_index > current_volume_index:
            return "future"
        return None if card.volume_index == current_volume_index else "scope"
    if card.volume_index is None or card.chapter_index is None:
        return "scope"
    if card.library_type == "memory":
        if card.volume_index < current_volume_index:
            return None
        if card.volume_index == current_volume_index:
            return None if card.chapter_index <= current_chapter_index else "future"
        return "future"
    if card.volume_index == current_volume_index:
        if card.chapter_index > current_chapter_index:
            return "future"
        return None if card.chapter_index == current_chapter_index else "scope"
    return "future"

