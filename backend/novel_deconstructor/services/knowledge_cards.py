from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path
import hashlib
import json
import math
import re
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from ..models import KnowledgeBase, KnowledgeCard, WritingMemory
from ..services.knowledge_base import knowledge_base_storage_dir
from ..services.path_safety import secure_slug


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
AUTO_MERGE_THRESHOLD = 0.88
REVIEW_MERGE_THRESHOLD = 0.72
RAG_SEARCH_MAX_TOP_K = 200
RAG_COMPACT_MIN_GROUP_CARDS = 6
RAG_COMPACT_GROUP_SIZE = 8
RAG_COMPACT_ITEM_MAX_CHARS = 220
RAG_COMPACT_CONTENT_MAX_CHARS = 1800
SEMANTIC_MERGE_CARD_TYPES = {
    "writing_rule",
    "emotion_module",
    "conflict_pattern",
    "anti_pattern",
    "style_pattern",
    "information_pattern",
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
        "WorldbuildingFact": "worldbuilding",
    }
    if cleaned in aliases:
        return aliases[cleaned]
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", cleaned).lower()
    return CARD_COLLECTIONS.get(cleaned, CARD_COLLECTIONS.get(snake, snake))


def normalize_scope_level(value: str | None, default: str = "global") -> str:
    cleaned = (value or default or "global").strip().lower()
    return cleaned if cleaned in VALID_SCOPE_LEVELS else default


def select_preferred_card_types(stage: str) -> list[str]:
    mapping = {
        "outline": ["writing_rule", "conflict_pattern", "emotion_module", "chapter_analysis"],
        "draft": ["writing_rule", "emotion_module", "style_pattern", "anti_pattern", "memory"],
        "revision": ["anti_pattern", "style_pattern", "writing_rule", "memory"],
        "continue": ["memory", "chapter_analysis", "writing_rule", "emotion_module"],
        "continuation": ["memory", "chapter_analysis", "writing_rule", "emotion_module"],
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


def knowledge_docs_root(knowledge_base: KnowledgeBase) -> Path:
    return knowledge_base_storage_dir(knowledge_base) / "knowledge_docs"


def import_knowledge_package(
    db: Session,
    knowledge_base: KnowledgeBase,
    package: dict[str, Any],
    *,
    library_type: str = "writing_guide",
    status: str = "approved",
    merge_mode: str = "safe",
    auto_merge_threshold: float = AUTO_MERGE_THRESHOLD,
    review_threshold: float = REVIEW_MERGE_THRESHOLD,
    generate_markdown: bool = True,
) -> dict[str, Any]:
    normalized_library = normalize_library_type(library_type, "writing_guide")
    normalized_status = normalize_status(status, "approved")
    markdown_root = knowledge_docs_root(knowledge_base)
    package_id = str(package.get("package_id") or "")
    if not _is_demo_package_id(package_id):
        purge_demo_knowledge_cards(db, knowledge_base)
    counters: Counter[str] = Counter()
    card_types: Counter[str] = Counter()
    imported = 0
    skipped = 0
    generated_markdown = 0
    exact_duplicates = 0
    seen_ids: set[str] = set()
    seen_fingerprints: set[tuple[str, str, str]] = set()

    for source_key, raw_card in _iter_package_cards(package):
        default_card_type = CARD_COLLECTIONS.get(source_key) or raw_card.get("card_type") or raw_card.get("type") or "writing_rule"
        card_type = normalize_card_type(raw_card.get("card_type") or raw_card.get("type") or default_card_type)
        card_library = normalize_library_type(str(raw_card.get("library_type") or raw_card.get("layer") or normalized_library), normalized_library)
        card_status = normalize_status(str(raw_card.get("status") or normalized_status), normalized_status)
        is_canonical = _default_is_canonical(raw_card, card_status)
        counters[card_type] += 1
        card_id = _card_id(raw_card, card_type, counters[card_type])
        explicit_card_id = _has_explicit_card_id(raw_card)
        title = _card_title(raw_card, card_type, card_id)
        content = _card_content(raw_card, card_type)
        tags = _tags(raw_card, card_type)
        avoid = _avoid_text(raw_card)
        fingerprint = content_fingerprint(title, content, avoid, tags)
        if card_id in seen_ids:
            if explicit_card_id:
                skipped += 1
                continue
            card_id = _next_available_card_id(db, knowledge_base, card_type, seen_ids)
            title = _card_title(raw_card, card_type, card_id)
            fingerprint = content_fingerprint(title, content, avoid, tags)
        exists = (
            db.query(KnowledgeCard)
            .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == card_id)
            .first()
        )
        if exists:
            if (
                exists.library_type == card_library
                and exists.card_type == card_type
                and exists.content_fingerprint == fingerprint
            ):
                skipped += 1
                continue
            if explicit_card_id:
                skipped += 1
                continue
            card_id = _next_available_card_id(db, knowledge_base, card_type, seen_ids)
            title = _card_title(raw_card, card_type, card_id)
            fingerprint = content_fingerprint(title, content, avoid, tags)
        seen_ids.add(card_id)
        fingerprint_key = (card_library, card_type, fingerprint)
        if fingerprint in {item[2] for item in seen_fingerprints if item[:2] == fingerprint_key[:2]}:
            exact_duplicates += 1
        seen_fingerprints.add(fingerprint_key)
        source_ref = _source_ref(package, raw_card, source_key)
        scope = _scope_values(raw_card, source_ref, card_library, card_type)
        card = KnowledgeCard(
            knowledge_base_id=knowledge_base.id,
            card_id=card_id,
            library_type=card_library,
            card_type=card_type,
            title=title,
            content=content,
            summary=_summary(raw_card, content),
            tags_json=_json(tags),
            source_ref_json=_json(source_ref),
            use_when_json=_json(_as_list(raw_card.get("use_when"))),
            avoid=avoid,
            confidence=_confidence(raw_card),
            status=card_status,
            source_kind="knowledge_package",
            package_id=package_id,
            is_canonical=is_canonical,
            merged_from_ids_json=_json([card_id]),
            evidence_count=1,
            content_fingerprint=fingerprint,
            scope_level=scope["scope_level"],
            volume_index=scope["volume_index"],
            volume_title=scope["volume_title"],
            chapter_index=scope["chapter_index"],
            chapter_title=scope["chapter_title"],
            valid_from_volume_index=scope["valid_from_volume_index"],
            valid_from_chapter_index=scope["valid_from_chapter_index"],
            valid_until_volume_index=scope["valid_until_volume_index"],
            valid_until_chapter_index=scope["valid_until_chapter_index"],
            reveal_at_volume_index=scope["reveal_at_volume_index"],
            reveal_at_chapter_index=scope["reveal_at_chapter_index"],
            retrievable=_default_retrievable(raw_card, card_library, card_status, is_canonical),
            priority=_int_or_none(raw_card.get("priority")) or 0,
        )
        card.markdown_path = str(card_markdown_path(knowledge_base, card))
        db.add(card)
        db.flush()
        if generate_markdown and card.is_canonical:
            write_card_markdown(knowledge_base, card)
            generated_markdown += 1
        imported += 1
        card_types[card_type] += 1

    merge_preview: dict[str, Any] = {"groups": [], "review_required_count": 0, "exact_duplicate_count": 0}
    merged_count = 0
    compacted_card_count = 0
    compacted_evidence_count = 0
    if merge_mode == "safe":
        applied = apply_knowledge_card_merges(
            db,
            knowledge_base,
            merge_mode=merge_mode,
            auto_merge_threshold=auto_merge_threshold,
            review_threshold=review_threshold,
        )
        merged_count = int(applied["merged_card_count"])
        compacted_card_count = int(applied.get("compacted_card_count", 0))
        compacted_evidence_count = int(applied.get("compacted_evidence_count", 0))
        generated_markdown += int(applied["generated_markdown_count"])
        merge_preview = preview_knowledge_card_merges(
            db,
            knowledge_base,
            merge_mode="preview",
            auto_merge_threshold=auto_merge_threshold,
            review_threshold=review_threshold,
        )
    elif merge_mode == "preview":
        merge_preview = preview_knowledge_card_merges(
            db,
            knowledge_base,
            merge_mode=merge_mode,
            auto_merge_threshold=auto_merge_threshold,
            review_threshold=review_threshold,
        )
    db.commit()
    stats = knowledge_card_merge_stats(db, knowledge_base)
    return {
        "imported_count": imported,
        "generated_markdown_count": generated_markdown,
        "skipped_count": skipped,
        "raw_card_count": stats["raw_card_count"],
        "canonical_card_count": stats["canonical_card_count"],
        "exact_duplicate_count": exact_duplicates + int(merge_preview.get("exact_duplicate_count", 0)),
        "merged_card_count": merged_count,
        "compacted_card_count": compacted_card_count,
        "compacted_evidence_count": compacted_evidence_count,
        "review_required_count": int(merge_preview.get("review_required_count", 0)),
        "reduction_rate": stats["reduction_rate"],
        "card_types": dict(card_types),
        "markdown_root": str(markdown_root),
        "message": f"已导入 {imported} 张知识卡，生成 {generated_markdown} 个 Markdown 文档，跳过 {skipped} 项。",
    }


def import_markdown_knowledge_source(
    db: Session,
    knowledge_base: KnowledgeBase,
    markdown: str,
    *,
    source_name: str = "external_knowledge.md",
    library_type: str = "writing_guide",
    status: str = "raw_extracted",
) -> dict[str, Any]:
    normalized_library = normalize_library_type(library_type, "writing_guide")
    normalized_status = normalize_status(status, "raw_extracted")
    purge_demo_knowledge_cards(db, knowledge_base)
    frontmatter, body = parse_frontmatter(markdown)
    source_name = source_name or str(frontmatter.get("source_name") or "external_knowledge.md")
    archived_source = _archive_import_markdown(knowledge_base, source_name, markdown)
    sections = _split_markdown_sections(body, source_name)
    card_types: Counter[str] = Counter()
    imported = 0
    skipped = 0
    generated_markdown = 0
    seen_ids: set[str] = set()

    for index, section in enumerate(sections, start=1):
        section_title = str(section["title"])
        section_body = str(section["content"]).strip()
        if not section_body:
            skipped += 1
            continue
        card_type = _infer_markdown_card_type(
            section_title,
            section_body,
            normalized_library,
            explicit=str(frontmatter.get("card_type") or frontmatter.get("type") or ""),
        )
        explicit_id = str(frontmatter.get("card_id") or "") if len(sections) == 1 else ""
        card_id = _markdown_card_id(source_name, section_title, card_type, index, explicit_id)
        if card_id in seen_ids:
            skipped += 1
            continue
        seen_ids.add(card_id)
        exists = (
            db.query(KnowledgeCard)
            .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == card_id)
            .first()
        )
        if exists:
            skipped += 1
            continue

        tags = _markdown_tags(frontmatter, section_title, section_body, normalized_library, card_type, source_name)
        source_ref = {
            "source": source_name,
            "source_kind": "markdown_import",
            "source_path": str(archived_source),
            "heading_path": section.get("heading_path", []),
            "section_index": index,
        }
        raw_scope = {**frontmatter, "title": section_title}
        scope = _scope_values(raw_scope, source_ref, normalized_library, card_type)
        is_canonical = _default_is_canonical(raw_scope, normalized_status)
        card = KnowledgeCard(
            knowledge_base_id=knowledge_base.id,
            card_id=card_id,
            library_type=normalized_library,
            card_type=card_type,
            title=_clip(section_title, 120),
            content=section_body,
            summary=_clip(re.sub(r"#+\s*", "", section_body), 240),
            tags_json=_json(tags),
            source_ref_json=_json(source_ref),
            use_when_json=_json(_markdown_use_when(normalized_library, card_type)),
            avoid=section_body if card_type == "anti_pattern" else "",
            confidence=0.72,
            status=normalized_status,
            source_kind="markdown_import",
            package_id="",
            is_canonical=is_canonical,
            merged_from_ids_json=_json([card_id]),
            evidence_count=1,
            content_fingerprint=content_fingerprint(section_title, section_body, section_body if card_type == "anti_pattern" else "", tags),
            scope_level=scope["scope_level"],
            volume_index=scope["volume_index"],
            volume_title=scope["volume_title"],
            chapter_index=scope["chapter_index"],
            chapter_title=scope["chapter_title"],
            valid_from_volume_index=scope["valid_from_volume_index"],
            valid_from_chapter_index=scope["valid_from_chapter_index"],
            valid_until_volume_index=scope["valid_until_volume_index"],
            valid_until_chapter_index=scope["valid_until_chapter_index"],
            reveal_at_volume_index=scope["reveal_at_volume_index"],
            reveal_at_chapter_index=scope["reveal_at_chapter_index"],
            retrievable=_default_retrievable(raw_scope, normalized_library, normalized_status, is_canonical),
            priority=_int_or_none(frontmatter.get("priority")) or 0,
        )
        card.markdown_path = str(card_markdown_path(knowledge_base, card))
        db.add(card)
        db.flush()
        write_card_markdown(knowledge_base, card)
        imported += 1
        generated_markdown += 1
        card_types[card_type] += 1

    compacted = apply_knowledge_card_merges(db, knowledge_base)
    generated_markdown += int(compacted.get("generated_markdown_count", 0))
    db.commit()
    return {
        "imported_count": imported,
        "generated_markdown_count": generated_markdown,
        "skipped_count": skipped,
        "compacted_card_count": int(compacted.get("compacted_card_count", 0)),
        "compacted_evidence_count": int(compacted.get("compacted_evidence_count", 0)),
        "card_types": dict(card_types),
        "markdown_root": str(knowledge_docs_root(knowledge_base)),
        "source_name": source_name,
        "message": f"已从 Markdown 自动拆分 {imported} 张知识卡，归档 {generated_markdown} 个 Markdown 文档，跳过 {skipped} 项。",
    }


def sync_memory_card(db: Session, knowledge_base: KnowledgeBase, memory: WritingMemory) -> KnowledgeCard:
    card_id = f"MEM-{memory.id:03d}"
    card = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == card_id)
        .first()
    )
    if not card:
        card = KnowledgeCard(knowledge_base_id=knowledge_base.id, card_id=card_id)
        db.add(card)
    memory_type = normalize_card_type(memory.memory_type, "memory")
    card.library_type = "memory"
    card.card_type = memory_type
    card.title = memory.title
    card.content = memory.content
    card.summary = _clip(memory.content, 240)
    tags = [memory_type, memory.source, *memory.tags]
    card.tags_json = _json(list(dict.fromkeys(tag for tag in tags if tag)))
    card.source_ref_json = _json({"memory_id": memory.id, "source": memory.source, **memory.source_ref})
    card.use_when_json = _json(["draft", "continue", "revision"])
    card.avoid = ""
    card.confidence = 1.0
    card.status = "approved"
    card.source_kind = "memory"
    card.package_id = ""
    card.is_canonical = True
    card.merged_into_card_id = None
    card.merged_from_ids_json = _json([card_id])
    card.evidence_count = 1
    card.content_fingerprint = content_fingerprint(card.title, card.content, card.avoid, tags)
    card.scope_level = normalize_scope_level(memory.scope_level, "chapter")
    card.volume_index = memory.volume_index
    card.volume_title = memory.volume_title
    card.chapter_index = memory.chapter_index
    card.chapter_title = memory.chapter_title
    card.valid_from_volume_index = memory.valid_from_volume_index
    card.valid_from_chapter_index = memory.valid_from_chapter_index
    card.valid_until_volume_index = memory.valid_until_volume_index
    card.valid_until_chapter_index = memory.valid_until_chapter_index
    card.reveal_at_volume_index = memory.reveal_at_volume_index
    card.reveal_at_chapter_index = memory.reveal_at_chapter_index
    card.retrievable = bool(memory.retrievable)
    card.priority = memory.priority or 0
    card.markdown_path = str(card_markdown_path(knowledge_base, card))
    db.flush()
    write_card_markdown(knowledge_base, card)
    db.commit()
    db.refresh(card)
    return card


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


def card_markdown_path(knowledge_base: KnowledgeBase, card: KnowledgeCard) -> Path:
    library = secure_slug(card.library_type or "writing_guide", "writing_guide")
    card_type = secure_slug(card.card_type or "card", "card")
    filename = f"{secure_slug(card.card_id or card.title, 'card')}.md"
    scope_dir = _scope_markdown_dir(card)
    return knowledge_docs_root(knowledge_base) / library / scope_dir / card_type / filename


def write_card_markdown(knowledge_base: KnowledgeBase, card: KnowledgeCard) -> Path:
    path = Path(card.markdown_path) if card.markdown_path else card_markdown_path(knowledge_base, card)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_card_markdown(card), encoding="utf-8")
    card.markdown_path = str(path)
    return path


def render_card_markdown(card: KnowledgeCard) -> str:
    tags = _json_list(card.tags_json)
    use_when = _json_list(card.use_when_json)
    source_ref = _json_dict(card.source_ref_json)
    frontmatter = _frontmatter(
        {
            "card_id": card.card_id,
            "library_type": card.library_type,
            "card_type": card.card_type,
            "title": card.title,
            "status": card.status,
            "is_canonical": bool(card.is_canonical),
            "evidence_count": card.evidence_count or 1,
            "merged_from": _json_list(card.merged_from_ids_json),
            "confidence": card.confidence,
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
            "tags": tags,
            "use_when": use_when,
            "source_ref": source_ref,
        }
    )
    sections = [
        frontmatter,
        f"# {card.title}",
        "",
        "## Content",
        "",
        card.content.strip(),
    ]
    if card.avoid.strip():
        sections.extend(["", "## Avoid", "", card.avoid.strip()])
    sections.extend(
        [
            "",
            "## Notes",
            "",
            f"该知识卡由 {card.evidence_count or 1} 条证据沉淀而来。若来自拆书结果，只能作为写法参考，不能照搬来源作品的人物、地名、桥段或世界观。",
            "",
        ]
    )
    return "\n".join(sections)


def list_markdown_docs(db: Session, knowledge_base: KnowledgeBase) -> list[dict[str, Any]]:
    cards = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.is_canonical.is_(True))
        .order_by(KnowledgeCard.library_type, KnowledgeCard.card_type, KnowledgeCard.card_id)
        .all()
    )
    docs: list[dict[str, Any]] = []
    for card in cards:
        path = Path(card.markdown_path or "")
        docs.append(
            {
                "doc_id": card.card_id,
                "card_id": card.card_id,
                "library_type": card.library_type,
                "card_type": card.card_type,
                "title": card.title,
                "status": card.status,
                "path": card.markdown_path,
                "exists": path.exists(),
                "updated_at": card.updated_at,
            }
        )
    return docs


def read_markdown_doc(db: Session, knowledge_base: KnowledgeBase, doc_id: str) -> dict[str, Any]:
    card = get_card_or_404(db, knowledge_base, doc_id)
    path = Path(card.markdown_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Markdown 文档不存在")
    return {"doc_id": card.card_id, "card_id": card.card_id, "content": path.read_text(encoding="utf-8"), "path": str(path)}


def save_markdown_doc(db: Session, knowledge_base: KnowledgeBase, doc_id: str, content: str) -> dict[str, Any]:
    card = get_card_or_404(db, knowledge_base, doc_id)
    path = Path(card.markdown_path or card_markdown_path(knowledge_base, card))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    card.markdown_path = str(path)
    db.commit()
    return {"doc_id": card.card_id, "card_id": card.card_id, "content": content, "path": str(path)}


def delete_markdown_doc(db: Session, knowledge_base: KnowledgeBase, doc_id: str) -> dict[str, Any]:
    card = get_card_or_404(db, knowledge_base, doc_id)
    path = Path(card.markdown_path or "")
    if path.exists() and path.is_file():
        path.unlink()
    card.status = "deleted"
    db.commit()
    db.refresh(card)
    return {"card_id": card.card_id, "status": "deleted", "updated_fields": ["markdown_path", "status"]}


def sync_card_from_markdown(db: Session, knowledge_base: KnowledgeBase, doc_id: str) -> dict[str, Any]:
    card = get_card_or_404(db, knowledge_base, doc_id)
    path = Path(card.markdown_path or "")
    if not path.exists():
        raise HTTPException(status_code=404, detail="Markdown 文档不存在")
    frontmatter, body = parse_frontmatter(path.read_text(encoding="utf-8"))
    updated: list[str] = []
    field_map = {
        "title": "title",
        "library_type": "library_type",
        "card_type": "card_type",
        "status": "status",
        "confidence": "confidence",
        "scope_level": "scope_level",
        "volume_index": "volume_index",
        "volume_title": "volume_title",
        "chapter_index": "chapter_index",
        "chapter_title": "chapter_title",
        "valid_from_volume_index": "valid_from_volume_index",
        "valid_from_chapter_index": "valid_from_chapter_index",
        "valid_until_volume_index": "valid_until_volume_index",
        "valid_until_chapter_index": "valid_until_chapter_index",
        "reveal_at_volume_index": "reveal_at_volume_index",
        "reveal_at_chapter_index": "reveal_at_chapter_index",
        "retrievable": "retrievable",
        "priority": "priority",
    }
    for source_key, attr in field_map.items():
        if source_key not in frontmatter:
            continue
        value = frontmatter[source_key]
        if attr == "library_type":
            value = normalize_library_type(str(value), card.library_type)
        elif attr == "status":
            value = normalize_status(str(value), card.status)
        elif attr == "card_type":
            value = normalize_card_type(str(value), card.card_type)
        elif attr == "confidence":
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue
        elif attr == "scope_level":
            value = normalize_scope_level(str(value), card.scope_level)
        elif attr == "retrievable":
            value = _bool_value(value, bool(card.retrievable))
        elif attr in {
            "volume_index",
            "chapter_index",
            "valid_from_volume_index",
            "valid_from_chapter_index",
            "valid_until_volume_index",
            "valid_until_chapter_index",
            "reveal_at_volume_index",
            "reveal_at_chapter_index",
            "priority",
        }:
            value = _int_or_none(value)
            if attr == "priority" and value is None:
                value = 0
        if getattr(card, attr) != value:
            setattr(card, attr, value)
            updated.append(attr)

    for key, attr in [("tags", "tags_json"), ("use_when", "use_when_json"), ("source_ref", "source_ref_json")]:
        if key not in frontmatter:
            continue
        value = frontmatter[key]
        serialized = _json(value if isinstance(value, (list, dict)) else [str(value)])
        if attr == "source_ref_json" and not isinstance(value, dict):
            serialized = _json({"value": str(value)})
        if getattr(card, attr) != serialized:
            setattr(card, attr, serialized)
            updated.append(key)

    content = _strip_markdown_title(body, card.title).strip()
    if content and content != card.content:
        card.content = content
        card.summary = _clip(content, 240)
        updated.extend(["content", "summary"])
    if "is_canonical" in frontmatter:
        value = bool(frontmatter["is_canonical"])
        if card.is_canonical != value:
            card.is_canonical = value
            updated.append("is_canonical")
    if "evidence_count" in frontmatter:
        try:
            evidence_count = max(1, int(frontmatter["evidence_count"]))
        except (TypeError, ValueError):
            evidence_count = card.evidence_count or 1
        if card.evidence_count != evidence_count:
            card.evidence_count = evidence_count
            updated.append("evidence_count")
    if "merged_from" in frontmatter:
        value = frontmatter["merged_from"]
        merged_from = value if isinstance(value, list) else [str(value)]
        serialized = _json([str(item) for item in merged_from if str(item).strip()])
        if card.merged_from_ids_json != serialized:
            card.merged_from_ids_json = serialized
            updated.append("merged_from")
    card.content_fingerprint = content_fingerprint(card.title, card.content, card.avoid, _json_list(card.tags_json))
    card.markdown_path = str(card_markdown_path(knowledge_base, card))
    db.commit()
    db.refresh(card)
    write_card_markdown(knowledge_base, card)
    db.commit()
    return {"card_id": card.card_id, "status": "updated", "updated_fields": list(dict.fromkeys(updated))}


def export_card_markdown(db: Session, knowledge_base: KnowledgeBase, card_id: str) -> dict[str, Any]:
    card = get_card_or_404(db, knowledge_base, card_id)
    card.is_canonical = True
    if card.status == "merged":
        card.status = "approved"
    card.merged_into_card_id = None
    if not _json_list(card.merged_from_ids_json):
        card.merged_from_ids_json = _json([card.card_id])
    card.evidence_count = max(1, card.evidence_count or 1)
    card.content_fingerprint = card.content_fingerprint or content_fingerprint(card.title, card.content, card.avoid, _json_list(card.tags_json))
    card.markdown_path = str(card_markdown_path(knowledge_base, card))
    path = write_card_markdown(knowledge_base, card)
    db.commit()
    return {"doc_id": card.card_id, "card_id": card.card_id, "content": path.read_text(encoding="utf-8"), "path": str(path)}


def sync_deleted_markdown(db: Session, knowledge_base: KnowledgeBase) -> dict[str, Any]:
    cards = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id == knowledge_base.id).all()
    deleted = 0
    for card in cards:
        if card.markdown_path and not Path(card.markdown_path).exists() and card.status != "deleted":
            card.status = "deleted"
            deleted += 1
    db.commit()
    return {"card_id": "*", "status": "updated", "updated_fields": [f"deleted:{deleted}"]}


def preview_knowledge_card_merges(
    db: Session,
    knowledge_base: KnowledgeBase,
    *,
    merge_mode: str = "preview",
    auto_merge_threshold: float = AUTO_MERGE_THRESHOLD,
    review_threshold: float = REVIEW_MERGE_THRESHOLD,
) -> dict[str, Any]:
    cards = _merge_candidate_cards(db, knowledge_base)
    groups = _merge_groups(cards, auto_merge_threshold=auto_merge_threshold, review_threshold=review_threshold)
    return {
        "groups": groups,
        "auto_merge_count": sum(len(group["candidate_card_ids"]) for group in groups if group["action"] == "auto_merge"),
        "review_required_count": sum(1 for group in groups if group["action"] == "review"),
        "exact_duplicate_count": sum(len(group["candidate_card_ids"]) for group in groups if group["reason"] == "exact_duplicate"),
    }


def apply_knowledge_card_merges(
    db: Session,
    knowledge_base: KnowledgeBase,
    *,
    merge_mode: str = "safe",
    auto_merge_threshold: float = AUTO_MERGE_THRESHOLD,
    review_threshold: float = REVIEW_MERGE_THRESHOLD,
) -> dict[str, Any]:
    preview = preview_knowledge_card_merges(
        db,
        knowledge_base,
        merge_mode=merge_mode,
        auto_merge_threshold=auto_merge_threshold,
        review_threshold=review_threshold,
    )
    if merge_mode == "preview":
        return {"merged_card_count": 0, "generated_markdown_count": 0, "groups": preview["groups"], "message": "预览模式未修改知识卡。"}

    merged_count = 0
    generated_markdown = 0
    applied_groups: list[dict[str, Any]] = []
    for group in preview["groups"]:
        if group["action"] != "auto_merge":
            continue
        primary = get_card_or_404(db, knowledge_base, group["primary_card_id"])
        changed = False
        for candidate_id in group["candidate_card_ids"]:
            candidate = get_card_or_404(db, knowledge_base, candidate_id)
            if candidate.card_id == primary.card_id or candidate.status == "merged":
                continue
            _merge_card_into(primary, candidate)
            merged_count += 1
            changed = True
        if changed:
            primary.is_canonical = True
            if primary.status not in ACTIVE_STATUSES:
                primary.status = "approved"
            primary.content_fingerprint = content_fingerprint(primary.title, primary.content, primary.avoid, _json_list(primary.tags_json))
            write_card_markdown(knowledge_base, primary)
            generated_markdown += 1
            applied_groups.append(group)
    compacted = compact_knowledge_cards_for_rag(db, knowledge_base)
    generated_markdown += int(compacted["generated_markdown_count"])
    db.commit()
    return {
        "merged_card_count": merged_count,
        "generated_markdown_count": generated_markdown,
        "compacted_card_count": int(compacted["compacted_card_count"]),
        "compacted_evidence_count": int(compacted["compacted_evidence_count"]),
        "groups": applied_groups,
        "message": f"已安全合并 {merged_count} 张重复或高度相似知识卡。",
    }


def compact_knowledge_cards_for_rag(
    db: Session,
    knowledge_base: KnowledgeBase,
    *,
    min_group_cards: int = RAG_COMPACT_MIN_GROUP_CARDS,
    group_size: int = RAG_COMPACT_GROUP_SIZE,
) -> dict[str, Any]:
    candidates = _rag_compact_candidate_cards(db, knowledge_base)
    buckets: dict[tuple[Any, ...], list[KnowledgeCard]] = {}
    for card in candidates:
        buckets.setdefault(_rag_compact_bucket(card), []).append(card)

    compacted_card_count = 0
    compacted_evidence_count = 0
    generated_markdown_count = 0
    for cards in buckets.values():
        if len(cards) < min_group_cards:
            continue
        ordered = sorted(cards, key=_rag_compact_sort_key)
        for batch in _rag_compact_batches(ordered, min_group_cards=min_group_cards, group_size=group_size):
            compact = _create_rag_compact_card(db, knowledge_base, batch)
            write_card_markdown(knowledge_base, compact)
            compacted_card_count += 1
            compacted_evidence_count += len(batch)
            generated_markdown_count += 1
    return {
        "compacted_card_count": compacted_card_count,
        "compacted_evidence_count": compacted_evidence_count,
        "generated_markdown_count": generated_markdown_count,
    }


def knowledge_card_merge_stats(db: Session, knowledge_base: KnowledgeBase) -> dict[str, Any]:
    cards = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id == knowledge_base.id).all()
    raw_count = sum(1 for card in cards if not card.is_canonical)
    canonical_count = sum(1 for card in cards if card.is_canonical and card.status != "deleted")
    merged_count = sum(1 for card in cards if card.status == "merged")
    disabled_count = sum(1 for card in cards if card.status == "disabled")
    deleted_count = sum(1 for card in cards if card.status == "deleted")
    preview = preview_knowledge_card_merges(db, knowledge_base)
    total_signal = canonical_count + merged_count
    return {
        "raw_card_count": raw_count,
        "canonical_card_count": canonical_count,
        "merged_card_count": merged_count,
        "disabled_card_count": disabled_count,
        "deleted_card_count": deleted_count,
        "review_required_count": preview["review_required_count"],
        "reduction_rate": round(merged_count / total_signal, 4) if total_signal else 0,
    }


def unmerge_knowledge_card(db: Session, knowledge_base: KnowledgeBase, card_id: str) -> KnowledgeCard:
    card = get_card_or_404(db, knowledge_base, card_id)
    previous_parent_id = card.merged_into_card_id
    card.is_canonical = True
    card.status = "approved" if card.status == "merged" else card.status
    card.merged_into_card_id = None
    card.merged_from_ids_json = _json([card.card_id])
    card.evidence_count = 1
    card.content_fingerprint = content_fingerprint(card.title, card.content, card.avoid, _json_list(card.tags_json))
    write_card_markdown(knowledge_base, card)
    if previous_parent_id:
        parent = (
            db.query(KnowledgeCard)
            .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == previous_parent_id)
            .first()
        )
        if parent:
            merged_from = [item for item in _json_list(parent.merged_from_ids_json) if item != card.card_id]
            parent.merged_from_ids_json = _json(merged_from or [parent.card_id])
            parent.evidence_count = max(1, (parent.evidence_count or 1) - 1)
            write_card_markdown(knowledge_base, parent)
    db.commit()
    db.refresh(card)
    return card


def get_card_or_404(db: Session, knowledge_base: KnowledgeBase, card_id: str) -> KnowledgeCard:
    card = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == card_id)
        .first()
    )
    if not card:
        raise HTTPException(status_code=404, detail="知识卡不存在")
    return card


def search_knowledge_cards(
    db: Session,
    knowledge_base_ids: list[int],
    *,
    stage: str,
    query: str,
    top_k: int = 8,
    library_type: str | None = None,
    include_inactive: bool = False,
    current_volume_index: int | None = None,
    current_chapter_index: int | None = None,
    include_future: bool = False,
    include_raw: bool = False,
    allowed_scope_levels: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    limit = max(1, min(top_k or 8, RAG_SEARCH_MAX_TOP_K))
    preferred_card_types = select_preferred_card_types(stage)
    expanded_query = build_expanded_rag_query(stage=stage, query=query, preferred_card_types=preferred_card_types)
    cards_query = db.query(KnowledgeCard)
    if knowledge_base_ids:
        cards_query = cards_query.filter(KnowledgeCard.knowledge_base_id.in_(knowledge_base_ids))
    if library_type:
        cards_query = cards_query.filter(KnowledgeCard.library_type == library_type)
    base_candidates = cards_query.all()
    status_candidates: list[KnowledgeCard] = []
    filtered_by_status_count = 0
    for card in base_candidates:
        reason = _card_status_filter_reason(card, include_raw=include_raw)
        if reason and not include_inactive:
            filtered_by_status_count += 1
            continue
        if reason in {"blocked_status", "not_retrievable"}:
            filtered_by_status_count += 1
            continue
        status_candidates.append(card)

    visible_candidates: list[KnowledgeCard] = []
    filtered_by_scope_count = 0
    filtered_by_future_count = 0
    for card in status_candidates:
        reason = _card_scope_filter_reason(
            card,
            current_volume_index,
            current_chapter_index,
            include_future=include_future,
            allowed_scope_levels=allowed_scope_levels,
        )
        if reason is None:
            visible_candidates.append(card)
            continue
        if reason == "future":
            filtered_by_future_count += 1
        else:
            filtered_by_scope_count += 1

    scored: list[tuple[float, KnowledgeCard]] = []
    for card in visible_candidates:
        score = _score_card(card, expanded_query["query"], stage, preferred_card_types, expanded_query["expanded_terms"])
        if card.priority:
            score += min(max(card.priority, 0), 100) / 100
        if score > 0:
            scored.append((score, card))
    scored.sort(key=lambda item: (item[0], _card_sort_time(item[1])), reverse=True)
    selected, filtered_duplicate_count, diversity_buckets = _select_diverse_scored_cards(scored, limit, preferred_card_types)
    results = [_search_result(card, score) for score, card in selected]
    debug = {
        "query": expanded_query["query"],
        "raw_query": expanded_query["raw_query"],
        "expanded_terms": expanded_query["expanded_terms"],
        "preferred_card_types": preferred_card_types,
        "total_candidates": len(base_candidates),
        "current_volume_index": current_volume_index,
        "current_chapter_index": current_chapter_index,
        "candidate_count_before_scope_filter": len(status_candidates),
        "candidate_count_after_scope_filter": len(visible_candidates),
        "filtered_by_status_count": filtered_by_status_count,
        "filtered_by_scope_count": filtered_by_scope_count,
        "filtered_by_future_count": filtered_by_future_count,
        "selected_card_ids": [card.card_id for _, card in selected],
        "selected_card_scope": {card.card_id: _scope_label(card) for _, card in selected},
        "selected_count": len(results),
        "filtered_duplicate_count": filtered_duplicate_count,
        "diversity_buckets": diversity_buckets,
        "stage": stage,
        "top_k": limit,
    }
    return results, debug


def used_knowledge_from_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": item["id"],
            "library_type": item["library_type"],
            "card_type": item["card_type"],
            "title": item["title"],
            "score": item["score"],
            "source_ref": item.get("source_ref", {}),
            "content_preview": item.get("content_preview", ""),
            "tags": item.get("tags", []),
            "status": item.get("status"),
            "scope_level": item.get("scope_level"),
            "volume_index": item.get("volume_index"),
            "chapter_index": item.get("chapter_index"),
        }
        for item in results
    ]


def build_expanded_rag_query(
    *,
    stage: str,
    query: str,
    preferred_card_types: list[str] | None = None,
) -> dict[str, Any]:
    normalized_stage = (stage or "").strip() or "draft"
    raw_query = (query or "").strip()
    preferred = preferred_card_types if preferred_card_types is not None else select_preferred_card_types(normalized_stage)
    expanded_terms = _dedupe_terms(
        [
            normalized_stage,
            _stage_label(normalized_stage),
            *STAGE_QUERY_EXPANSIONS.get(normalized_stage, []),
            *ALWAYS_ON_QUERY_TERMS,
            *preferred,
            *(_card_type_label(card_type) for card_type in preferred),
        ]
    )
    expanded_query = "\n".join(part for part in [raw_query, " ".join(expanded_terms)] if part)
    return {
        "query": expanded_query,
        "raw_query": raw_query,
        "expanded_terms": expanded_terms,
    }


def parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end == -1:
        return {}, text
    raw = text[4:end].strip("\n")
    body = text[end + 4 :].lstrip("\n")
    return _parse_simple_yaml(raw), body


def _archive_import_markdown(knowledge_base: KnowledgeBase, source_name: str, markdown: str) -> Path:
    source_path = Path(source_name)
    suffix = source_path.suffix if source_path.suffix.lower() in {".md", ".markdown"} else ".md"
    stem = secure_slug(source_path.stem or "external_knowledge", "external_knowledge")
    digest = hashlib.sha1(markdown.encode("utf-8", errors="ignore")).hexdigest()[:8]
    path = knowledge_docs_root(knowledge_base) / "_imports" / f"{stem}-{digest}{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    return path


def _split_markdown_sections(markdown: str, source_name: str, max_chars: int = 2800) -> list[dict[str, Any]]:
    text = markdown.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []
    sections: list[dict[str, Any]] = []
    stack: list[tuple[int, str]] = []
    current_title = Path(source_name).stem or "Markdown Knowledge"
    current_level = 0
    current_lines: list[str] = []
    current_path: list[str] = []

    def flush() -> None:
        content = "\n".join(current_lines).strip()
        if not content:
            return
        sections.extend(_split_long_section(current_title, content, current_path, max_chars))

    for line in text.splitlines():
        match = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if match:
            flush()
            current_level = len(match.group(1))
            current_title = _clean_heading(match.group(2)) or current_title
            stack[:] = [(level, title) for level, title in stack if level < current_level]
            stack.append((current_level, current_title))
            current_path = [title for _, title in stack]
            current_lines = []
            continue
        current_lines.append(line)
    flush()
    if sections:
        return sections
    fallback_title = _clean_heading(Path(source_name).stem) or "Markdown Knowledge"
    return _split_long_section(fallback_title, text, [fallback_title], max_chars)


def _split_long_section(title: str, content: str, heading_path: list[str], max_chars: int) -> list[dict[str, Any]]:
    if len(content) <= max_chars:
        return [{"title": title, "content": content, "heading_path": heading_path}]
    paragraphs = [item.strip() for item in re.split(r"\n{2,}", content) if item.strip()]
    if not paragraphs:
        return [{"title": title, "content": content, "heading_path": heading_path}]
    chunks: list[dict[str, Any]] = []
    buffer: list[str] = []
    size = 0
    part = 1
    for paragraph in paragraphs:
        paragraph_size = len(paragraph)
        if buffer and size + paragraph_size + 2 > max_chars:
            chunks.append(
                {
                    "title": f"{title} Part {part}",
                    "content": "\n\n".join(buffer),
                    "heading_path": [*heading_path, f"Part {part}"],
                }
            )
            buffer = []
            size = 0
            part += 1
        buffer.append(paragraph)
        size += paragraph_size + 2
    if buffer:
        chunks.append(
            {
                "title": f"{title} Part {part}" if part > 1 else title,
                "content": "\n\n".join(buffer),
                "heading_path": [*heading_path, f"Part {part}"] if part > 1 else heading_path,
            }
        )
    return chunks


def _clean_heading(value: str) -> str:
    text = re.sub(r"\s+#*$", "", value or "").strip()
    return re.sub(r"^\d+[\.)、]\s*", "", text)


def _infer_markdown_card_type(title: str, content: str, library_type: str, *, explicit: str = "") -> str:
    if explicit:
        return normalize_card_type(explicit)
    haystack = f"{title}\n{content}".lower()
    if library_type == "worldbuilding":
        worldbuilding_rules = [
            ("character", ["角色", "人物", "主角", "配角", "character", "protagonist"]),
            ("location", ["地点", "城市", "区域", "地图", "location", "city", "place"]),
            ("faction", ["组织", "势力", "门派", "公司", "faction", "guild", "group"]),
            ("rule", ["规则", "体系", "能力", "法则", "system", "rule", "power"]),
            ("timeline", ["时间线", "历史", "年表", "timeline", "history"]),
            ("item", ["道具", "物品", "装备", "artifact", "item"]),
        ]
        return _best_keyword_type(haystack, worldbuilding_rules, "worldbuilding")
    writing_rules = [
        ("anti_pattern", ["反模式", "风险", "禁忌", "避免", "不要", "问题", "anti", "pitfall", "avoid"]),
        ("conflict_pattern", ["冲突", "阻力", "对抗", "升级", "压迫", "conflict", "obstacle", "escalation"]),
        ("emotion_module", ["情绪", "爽点", "期待", "释放", "触发", "emotion", "payoff", "tension"]),
        ("style_pattern", ["风格", "句式", "语言", "对白", "动作", "style", "voice", "dialogue"]),
        ("information_pattern", ["信息", "伏笔", "悬念", "揭示", "铺垫", "foreshadow", "reveal"]),
        ("chapter_analysis", ["章节", "结构", "节奏", "提纲", "开头", "结尾", "chapter", "structure", "outline"]),
    ]
    return _best_keyword_type(haystack, writing_rules, "writing_rule")


def _best_keyword_type(haystack: str, rules: list[tuple[str, list[str]]], fallback: str) -> str:
    best_type = fallback
    best_score = 0
    for card_type, keywords in rules:
        score = sum(1 for keyword in keywords if keyword.lower() in haystack)
        if score > best_score:
            best_type = card_type
            best_score = score
    return best_type


def _markdown_card_id(source_name: str, title: str, card_type: str, index: int, explicit_id: str = "") -> str:
    if explicit_id:
        cleaned = re.sub(r"[^A-Za-z0-9_\-\u4e00-\u9fff]+", "-", explicit_id).strip("-_")
        if cleaned:
            return cleaned[:80]
    prefix = CARD_PREFIXES.get(card_type, "KC")
    source_slug = secure_slug(Path(source_name).stem or "markdown", "markdown")
    digest = hashlib.sha1(f"{source_name}:{index}:{title}:{card_type}".encode("utf-8", errors="ignore")).hexdigest()[:8]
    return f"{prefix}-{source_slug}-{index:03d}-{digest}"[:80]


def _markdown_tags(
    frontmatter: dict[str, Any],
    title: str,
    content: str,
    library_type: str,
    card_type: str,
    source_name: str,
) -> list[str]:
    tags = _as_list(frontmatter.get("tags"))
    candidates = [library_type, card_type, secure_slug(Path(source_name).stem or "markdown", "markdown")]
    text = f"{title}\n{content}"
    for keyword in ["黄金三章", "冲突", "情绪", "伏笔", "人物", "设定", "风格"]:
        if keyword in text:
            candidates.append(keyword)
    return list(dict.fromkeys(tag for tag in [*tags, *candidates] if tag))


def _markdown_use_when(library_type: str, card_type: str) -> list[str]:
    if library_type == "worldbuilding":
        return ["outline", "draft", "worldbuilding_check"]
    mapping = {
        "anti_pattern": ["draft", "revision"],
        "style_pattern": ["draft", "revision"],
        "information_pattern": ["outline", "draft", "revision"],
        "conflict_pattern": ["outline", "draft"],
        "emotion_module": ["outline", "draft"],
        "chapter_analysis": ["outline", "continue"],
    }
    return mapping.get(card_type, ["outline", "draft", "revision"])


def _iter_package_cards(package: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    cards: list[tuple[str, dict[str, Any]]] = []
    for key, card_type in CARD_COLLECTIONS.items():
        value = package.get(key)
        if isinstance(value, list):
            cards.extend((key, item) for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            item = dict(value)
            item.setdefault("type", card_type)
            cards.append((key, item))
    canonical_cards = package.get("canonical_cards")
    if isinstance(canonical_cards, list):
        cards.extend(("canonical_cards", item) for item in canonical_cards if isinstance(item, dict))
    return cards


def _card_id(raw: dict[str, Any], card_type: str, index: int) -> str:
    explicit = raw.get("card_id") or raw.get("id")
    if explicit:
        return re.sub(r"[^A-Za-z0-9_-]+", "-", str(explicit)).strip("-_")[:80] or f"{CARD_PREFIXES.get(card_type, 'KC')}-{index:03d}"
    return f"{CARD_PREFIXES.get(card_type, 'KC')}-{index:03d}"


def _has_explicit_card_id(raw: dict[str, Any]) -> bool:
    return bool(str(raw.get("card_id") or raw.get("id") or "").strip())


def _next_available_card_id(db: Session, knowledge_base: KnowledgeBase, card_type: str, seen_ids: set[str]) -> str:
    prefix = CARD_PREFIXES.get(card_type, "KC")
    existing_ids = {
        item.card_id
        for item in db.query(KnowledgeCard.card_id).filter(
            KnowledgeCard.knowledge_base_id == knowledge_base.id,
            KnowledgeCard.card_id.like(f"{prefix}-%"),
        )
    }
    index = 1
    while True:
        candidate = f"{prefix}-{index:03d}"
        if candidate not in existing_ids and candidate not in seen_ids:
            return candidate
        index += 1


def _is_demo_package_id(package_id: str) -> bool:
    return package_id in DEMO_PACKAGE_IDS


def purge_demo_knowledge_cards(db: Session, knowledge_base: KnowledgeBase) -> int:
    cards = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.package_id.in_(DEMO_PACKAGE_IDS))
        .all()
    )
    root = knowledge_docs_root(knowledge_base).resolve()
    removed = 0
    for card in cards:
        if card.markdown_path:
            try:
                path = Path(card.markdown_path).resolve()
                if path.is_file() and (path == root or root in path.parents):
                    path.unlink()
            except OSError:
                pass
        db.delete(card)
        removed += 1
    if removed:
        db.flush()
    return removed


def _card_title(raw: dict[str, Any], card_type: str, card_id: str) -> str:
    for key in ("title", "name", "chapter_title", "summary"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return _clip(value, 120)
    return f"{card_type} {card_id}"


def _card_content(raw: dict[str, Any], card_type: str) -> str:
    raw_values = dict(raw)
    if isinstance(raw.get("content"), dict):
        raw_values.update(raw["content"])
    field_groups = {
        "chapter_analysis": [
            "summary",
            "opening_state",
            "ending_state",
            "state_change",
            "chapter_function",
            "conflict_units",
            "emotion_chain",
            "information_delivery",
            "character_changes",
            "ending_hook",
            "reusable_patterns",
            "anti_patterns",
        ],
        "writing_rule": ["rule", "use_when", "avoid"],
        "emotion_module": ["emotion_chain", "scene_function", "reusable_steps", "do_not_copy"],
        "conflict_pattern": ["conflict_type", "trigger", "escalation", "payoff", "next_hook"],
        "anti_pattern": ["problem", "why_bad", "fix_strategy"],
        "style_pattern": ["pattern", "style", "example", "use_when", "avoid"],
        "information_pattern": ["pattern", "information_delivery", "use_when", "avoid"],
    }
    fields = field_groups.get(card_type)
    if not fields:
        fields = [key for key in raw if key not in {"id", "card_id", "type", "title", "name", "tags", "source", "source_ref", "status", "confidence"}]
    lines: list[str] = []
    for field in fields:
        if field not in raw_values:
            continue
        text = _value_markdown(field, raw_values[field])
        if text:
            lines.append(text)
    if lines:
        return "\n\n".join(lines)
    return json.dumps(raw_values, ensure_ascii=False, indent=2)


def _value_markdown(label: str, value: Any) -> str:
    title = label.replace("_", " ").title()
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
        if not items:
            return ""
        return f"## {title}\n" + "\n".join(f"- {item}" for item in items)
    if isinstance(value, dict):
        return f"## {title}\n```json\n{json.dumps(value, ensure_ascii=False, indent=2)}\n```"
    text = str(value).strip()
    return f"## {title}\n{text}" if text else ""


def _summary(raw: dict[str, Any], content: str) -> str:
    value = raw.get("summary") or raw.get("chapter_function") or raw.get("problem") or raw.get("rule")
    if isinstance(value, str) and value.strip():
        return _clip(value, 240)
    return _clip(re.sub(r"#+\s*", "", content), 240)


def _tags(raw: dict[str, Any], card_type: str) -> list[str]:
    tags = _as_list(raw.get("tags"))
    if card_type not in tags:
        tags.insert(0, card_type)
    return tags


def _source_ref(package: dict[str, Any], raw: dict[str, Any], source_key: str) -> dict[str, Any]:
    source_ref: dict[str, Any] = {
        "package_id": package.get("package_id", ""),
        "collection": source_key,
    }
    for container_key in ("project", "source", "job"):
        value = package.get(container_key)
        if isinstance(value, dict):
            source_ref[container_key] = value
    for key in ("source_ref", "source"):
        value = raw.get(key)
        if isinstance(value, dict):
            source_ref.update(value)
    source_refs = raw.get("source_refs")
    if isinstance(source_refs, list):
        source_ref["source_refs"] = [item for item in source_refs if isinstance(item, dict)]
    return source_ref


def _scope_values(
    raw: dict[str, Any],
    source_ref: dict[str, Any],
    library_type: str,
    card_type: str,
) -> dict[str, Any]:
    volume_index = _first_int(raw, source_ref, "volume_index")
    chapter_index = _first_int(raw, source_ref, "chapter_index")
    scope_default = "global"
    if chapter_index is not None:
        scope_default = "chapter"
    elif volume_index is not None:
        scope_default = "volume"
    if library_type == "writing_guide":
        scope_default = "global"
    if card_type == "chapter_analysis":
        scope_default = "chapter"
    scope_level = normalize_scope_level(str(raw.get("scope_level") or raw.get("scope") or scope_default), scope_default)
    return {
        "scope_level": scope_level,
        "volume_index": volume_index,
        "volume_title": _first_text(raw, source_ref, "volume_title"),
        "chapter_index": chapter_index,
        "chapter_title": _first_text(raw, source_ref, "chapter_title") or _first_text(raw, source_ref, "chapter"),
        "valid_from_volume_index": _first_int(raw, source_ref, "valid_from_volume_index"),
        "valid_from_chapter_index": _first_int(raw, source_ref, "valid_from_chapter_index"),
        "valid_until_volume_index": _first_int(raw, source_ref, "valid_until_volume_index"),
        "valid_until_chapter_index": _first_int(raw, source_ref, "valid_until_chapter_index"),
        "reveal_at_volume_index": _first_int(raw, source_ref, "reveal_at_volume_index"),
        "reveal_at_chapter_index": _first_int(raw, source_ref, "reveal_at_chapter_index"),
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
        return library_type in {"writing_guide", "worldbuilding"}
    if not is_canonical or status not in RETRIEVABLE_STATUSES:
        return False
    return True


def _scope_markdown_dir(card: KnowledgeCard) -> Path:
    scope_level = normalize_scope_level(card.scope_level, "global")
    if scope_level == "global":
        return Path("global")
    if scope_level == "volume":
        if card.volume_index is None:
            return Path("volume_unknown")
        return Path(f"volume_{card.volume_index:03d}")
    volume_dir = f"volume_{card.volume_index:03d}" if card.volume_index is not None else "volume_unknown"
    chapter_dir = f"chapter_{card.chapter_index:03d}" if card.chapter_index is not None else "chapter_unknown"
    return Path(volume_dir) / "chapters" / chapter_dir


def _card_status_filter_reason(card: KnowledgeCard, *, include_raw: bool = False) -> str | None:
    if not bool(card.retrievable):
        return "not_retrievable"
    if card.status in BLOCKED_STATUSES:
        return "blocked_status"
    if card.status == "raw_extracted":
        return None if include_raw else "raw_hidden"
    if card.status not in RETRIEVABLE_STATUSES:
        return "inactive_status"
    if not bool(card.is_canonical) and not include_raw:
        return "not_canonical"
    return None


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

    if scope_level == "global":
        return None
    if scope_level == "volume":
        if card.volume_index is None:
            return "scope"
        return None if card.volume_index <= current_volume_index else "future"
    if card.volume_index is None or card.chapter_index is None:
        return "scope"
    if card.volume_index < current_volume_index:
        return None
    if card.volume_index == current_volume_index:
        return None if card.chapter_index <= current_chapter_index else "future"
    return "future"


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


def _merge_candidate_cards(db: Session, knowledge_base: KnowledgeBase) -> list[KnowledgeCard]:
    cards = (
        db.query(KnowledgeCard)
        .filter(
            KnowledgeCard.knowledge_base_id == knowledge_base.id,
            KnowledgeCard.is_canonical.is_(True),
            KnowledgeCard.status.in_(ACTIVE_STATUSES),
        )
        .order_by(KnowledgeCard.library_type, KnowledgeCard.card_type, KnowledgeCard.card_id)
        .all()
    )
    changed = False
    for card in cards:
        if not card.content_fingerprint:
            card.content_fingerprint = content_fingerprint(card.title, card.content, card.avoid, _json_list(card.tags_json))
            changed = True
        if not card.merged_from_ids_json or card.merged_from_ids_json == "[]":
            card.merged_from_ids_json = _json([card.card_id])
            changed = True
        if not card.evidence_count:
            card.evidence_count = 1
            changed = True
    if changed:
        db.flush()
    return cards


def _merge_groups(cards: list[KnowledgeCard], *, auto_merge_threshold: float, review_threshold: float) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    consumed: set[str] = set()
    buckets: dict[tuple[str, str, str], list[KnowledgeCard]] = {}
    for card in cards:
        buckets.setdefault((card.library_type, card.card_type, card.content_fingerprint), []).append(card)
    for (_, _, fingerprint), bucket in buckets.items():
        if len(bucket) < 2:
            continue
        ordered = sorted(bucket, key=lambda item: (item.confidence, item.evidence_count or 1, item.updated_at or item.created_at), reverse=True)
        primary = ordered[0]
        candidates = [card for card in ordered[1:] if card.card_id not in consumed]
        if not candidates:
            continue
        consumed.update(card.card_id for card in candidates)
        groups.append(_merge_group_dict(primary, candidates, "auto_merge", "exact_duplicate", 1.0, fingerprint))

    for index, left in enumerate(cards):
        if left.card_id in consumed:
            continue
        candidates: list[tuple[float, KnowledgeCard]] = []
        for right in cards[index + 1 :]:
            if right.card_id in consumed or right.card_id == left.card_id:
                continue
            if not _can_semantic_merge(left, right):
                continue
            score = _similarity_score(left, right)
            if score >= review_threshold:
                candidates.append((score, right))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        auto_cards = [card for score, card in candidates if score >= auto_merge_threshold]
        review_cards = [card for score, card in candidates if review_threshold <= score < auto_merge_threshold]
        if auto_cards:
            best_score = max(score for score, _ in candidates if score >= auto_merge_threshold)
            consumed.update(card.card_id for card in auto_cards)
            groups.append(_merge_group_dict(left, auto_cards, "auto_merge", "similarity", best_score, f"sim-{left.card_id}"))
        elif review_cards:
            best_score = max(score for score, _ in candidates if review_threshold <= score < auto_merge_threshold)
            groups.append(_merge_group_dict(left, review_cards[:5], "review", "similarity", best_score, f"review-{left.card_id}"))
    return groups


def _merge_group_dict(primary: KnowledgeCard, candidates: list[KnowledgeCard], action: str, reason: str, score: float, suffix: str) -> dict[str, Any]:
    cards = [primary, *candidates]
    return {
        "group_id": f"{reason}:{primary.card_id}:{suffix}",
        "action": action,
        "reason": reason,
        "similarity": round(score, 4),
        "primary_card_id": primary.card_id,
        "candidate_card_ids": [card.card_id for card in candidates],
        "cards": [_merge_card_summary(card) for card in cards],
    }


def _merge_card_summary(card: KnowledgeCard) -> dict[str, Any]:
    return {
        "card_id": card.card_id,
        "title": card.title,
        "library_type": card.library_type,
        "card_type": card.card_type,
        "status": card.status,
        "is_canonical": bool(card.is_canonical),
        "evidence_count": card.evidence_count or 1,
    }


def _can_semantic_merge(left: KnowledgeCard, right: KnowledgeCard) -> bool:
    if left.library_type != right.library_type or left.card_type != right.card_type:
        return False
    if left.library_type != "writing_guide":
        return False
    return left.card_type in SEMANTIC_MERGE_CARD_TYPES


def _similarity_score(left: KnowledgeCard, right: KnowledgeCard) -> float:
    content_similarity = _ngram_similarity(left.content, right.content)
    title_similarity = _ngram_similarity(left.title, right.title)
    tag_similarity = _set_similarity(_json_list(left.tags_json), _json_list(right.tags_json))
    use_when_similarity = _set_similarity(_json_list(left.use_when_json), _json_list(right.use_when_json))
    avoid_similarity = _ngram_similarity(left.avoid, right.avoid) if left.avoid and right.avoid else 0.0
    return round(
        content_similarity * 0.45
        + title_similarity * 0.20
        + tag_similarity * 0.15
        + use_when_similarity * 0.10
        + avoid_similarity * 0.10,
        4,
    )


def _ngram_similarity(left: str, right: str, n: int = 2) -> float:
    left_text = _normalize_for_fingerprint(left)
    right_text = _normalize_for_fingerprint(right)
    if not left_text or not right_text:
        return 0.0
    if left_text == right_text:
        return 1.0
    left_grams = {left_text[index : index + n] for index in range(max(1, len(left_text) - n + 1))}
    right_grams = {right_text[index : index + n] for index in range(max(1, len(right_text) - n + 1))}
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def _set_similarity(left: list[str], right: list[str]) -> float:
    left_set = {item.lower() for item in left if item}
    right_set = {item.lower() for item in right if item}
    if not left_set and not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def _merge_card_into(primary: KnowledgeCard, candidate: KnowledgeCard) -> None:
    primary.tags_json = _json(_merge_lists(_json_list(primary.tags_json), _json_list(candidate.tags_json)))
    primary.use_when_json = _json(_merge_lists(_json_list(primary.use_when_json), _json_list(candidate.use_when_json)))
    primary.source_ref_json = _json(_merge_source_refs(_json_dict(primary.source_ref_json), _json_dict(candidate.source_ref_json)))
    if candidate.avoid and candidate.avoid not in primary.avoid:
        primary.avoid = "\n".join(item for item in [primary.avoid.strip(), candidate.avoid.strip()] if item)
    primary.confidence = max(primary.confidence or 0, candidate.confidence or 0)
    merged_from = _merge_lists(_json_list(primary.merged_from_ids_json) or [primary.card_id], _json_list(candidate.merged_from_ids_json) or [candidate.card_id])
    primary.merged_from_ids_json = _json(merged_from)
    primary.evidence_count = max(1, len(merged_from), (primary.evidence_count or 1) + (candidate.evidence_count or 1))
    candidate.is_canonical = False
    candidate.status = "merged"
    candidate.merged_into_card_id = primary.card_id
    candidate.markdown_path = candidate.markdown_path or str(card_markdown_path(primary.knowledge_base, candidate))


def _merge_lists(left: list[str], right: list[str]) -> list[str]:
    return list(dict.fromkeys([*(item for item in left if item), *(item for item in right if item)]))


def _merge_source_refs(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    refs: list[dict[str, Any]] = []
    for value in (left, right):
        if not value:
            continue
        if isinstance(value.get("source_refs"), list):
            refs.extend(item for item in value["source_refs"] if isinstance(item, dict))
        else:
            refs.append(value)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        unique.append(ref)
        seen.add(key)
    if len(unique) == 1:
        return unique[0]
    return {"source_refs": unique}


def _rag_compact_candidate_cards(db: Session, knowledge_base: KnowledgeBase) -> list[KnowledgeCard]:
    return (
        db.query(KnowledgeCard)
        .filter(
            KnowledgeCard.knowledge_base_id == knowledge_base.id,
            KnowledgeCard.status.in_({"raw_extracted", "reviewed", "approved"}),
            KnowledgeCard.retrievable.is_(True),
            KnowledgeCard.library_type != "memory",
            KnowledgeCard.source_kind != "rag_compact",
        )
        .order_by(KnowledgeCard.library_type, KnowledgeCard.card_type, KnowledgeCard.card_id)
        .all()
    )


def _rag_compact_bucket(card: KnowledgeCard) -> tuple[Any, ...]:
    scope = normalize_scope_level(card.scope_level, "global")
    volume = card.volume_index if scope in {"volume", "chapter"} else None
    chapter = card.chapter_index if scope == "chapter" else None
    reveal = (card.reveal_at_volume_index, card.reveal_at_chapter_index)
    valid_from = (card.valid_from_volume_index, card.valid_from_chapter_index)
    valid_until = (card.valid_until_volume_index, card.valid_until_chapter_index)
    return (card.library_type, card.card_type, scope, volume, chapter, reveal, valid_from, valid_until)


def _rag_compact_sort_key(card: KnowledgeCard) -> tuple[Any, ...]:
    source_ref = _json_dict(card.source_ref_json)
    heading = source_ref.get("heading_path")
    heading_key = " / ".join(str(item) for item in heading) if isinstance(heading, list) else ""
    return (
        str(source_ref.get("source") or source_ref.get("source_path") or ""),
        _int_or_none(source_ref.get("section_index")) or 0,
        heading_key,
        card.card_id,
    )


def _rag_compact_batches(
    cards: list[KnowledgeCard],
    *,
    min_group_cards: int,
    group_size: int,
) -> list[list[KnowledgeCard]]:
    batches = [cards[index : index + group_size] for index in range(0, len(cards), group_size)]
    if len(batches) > 1 and len(batches[-1]) < min_group_cards:
        batches[-2].extend(batches.pop())
    return [batch for batch in batches if len(batch) >= min_group_cards]


def _create_rag_compact_card(db: Session, knowledge_base: KnowledgeBase, cards: list[KnowledgeCard]) -> KnowledgeCard:
    first = cards[0]
    card_ids = [card.card_id for card in cards]
    digest = hashlib.sha1("|".join(card_ids).encode("utf-8", errors="ignore")).hexdigest()[:10]
    prefix = CARD_PREFIXES.get(first.card_type, "KC")
    card_id = _unique_compact_card_id(db, knowledge_base, f"{prefix}-CMP-{digest}")
    tags = _merge_lists(["rag_compact", first.library_type, first.card_type], [tag for card in cards for tag in _json_list(card.tags_json)])
    use_when = _merge_lists([], [item for card in cards for item in _json_list(card.use_when_json)])
    content = _compact_card_content(cards)
    source_ref = _merge_compact_source_refs(cards)
    avoid = _compact_avoid_text(cards)
    compact = KnowledgeCard(
        knowledge_base_id=knowledge_base.id,
        card_id=card_id,
        library_type=first.library_type,
        card_type=first.card_type,
        title=f"RAG compact {first.library_type}/{first.card_type} ({len(cards)} items)",
        content=content,
        summary=_clip(content, 240),
        tags_json=_json(tags),
        source_ref_json=_json(source_ref),
        use_when_json=_json(use_when),
        avoid=avoid,
        confidence=max(card.confidence or 0 for card in cards),
        status="approved",
        source_kind="rag_compact",
        package_id="",
        is_canonical=True,
        merged_from_ids_json=_json(card_ids),
        evidence_count=sum(max(1, card.evidence_count or 1) for card in cards),
        content_fingerprint=content_fingerprint(card_id, content, avoid, tags),
        scope_level=first.scope_level,
        volume_index=first.volume_index,
        volume_title=first.volume_title,
        chapter_index=first.chapter_index,
        chapter_title=first.chapter_title,
        valid_from_volume_index=first.valid_from_volume_index,
        valid_from_chapter_index=first.valid_from_chapter_index,
        valid_until_volume_index=first.valid_until_volume_index,
        valid_until_chapter_index=first.valid_until_chapter_index,
        reveal_at_volume_index=first.reveal_at_volume_index,
        reveal_at_chapter_index=first.reveal_at_chapter_index,
        retrievable=True,
        priority=max(card.priority or 0 for card in cards),
    )
    compact.markdown_path = str(card_markdown_path(knowledge_base, compact))
    db.add(compact)
    db.flush()
    for card in cards:
        card.is_canonical = False
        card.status = "merged"
        card.retrievable = False
        card.merged_into_card_id = compact.card_id
        card.markdown_path = card.markdown_path or str(card_markdown_path(knowledge_base, card))
    return compact


def _unique_compact_card_id(db: Session, knowledge_base: KnowledgeBase, base_id: str) -> str:
    card_id = base_id[:80]
    suffix = 2
    while (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == card_id)
        .first()
    ):
        tail = f"-{suffix}"
        card_id = f"{base_id[: 80 - len(tail)]}{tail}"
        suffix += 1
    return card_id


def _compact_card_content(cards: list[KnowledgeCard]) -> str:
    lines = [
        "## RAG Compact Evidence",
        "",
        f"Condensed from {len(cards)} imported knowledge cards. Use this card as the retrieval surface; source cards remain linked as evidence.",
        "",
        "## Key Items",
        "",
    ]
    for card in cards:
        lines.append(f"- {card.title}: {_compact_card_excerpt(card)}")
    return _clip("\n".join(lines), RAG_COMPACT_CONTENT_MAX_CHARS)


def _compact_card_excerpt(card: KnowledgeCard) -> str:
    source = card.summary or card.content or card.avoid
    cleaned = re.sub(r"#+\s*", "", source)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _clip(cleaned, RAG_COMPACT_ITEM_MAX_CHARS)


def _compact_avoid_text(cards: list[KnowledgeCard]) -> str:
    avoid_items = [_compact_card_excerpt(card) for card in cards if card.avoid.strip()]
    return _clip("\n".join(f"- {item}" for item in avoid_items), 1000) if avoid_items else ""


def _merge_compact_source_refs(cards: list[KnowledgeCard]) -> dict[str, Any]:
    refs = [_json_dict(card.source_ref_json) for card in cards]
    merged = _merge_source_refs({}, {"source_refs": refs})
    if isinstance(merged, dict):
        merged["compact_source_card_ids"] = [card.card_id for card in cards]
    return merged


def _frontmatter(values: dict[str, Any]) -> str:
    lines = ["---"]
    for key, value in values.items():
        if isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {_yaml_scalar(item)}" for item in value)
        elif isinstance(value, dict):
            lines.append(f"{key}:")
            for sub_key, sub_value in value.items():
                lines.append(f"  {sub_key}: {_yaml_scalar(sub_value)}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _yaml_scalar(value: Any) -> str:
    if value is None:
        return '""'
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def _parse_simple_yaml(raw: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    current_key: str | None = None
    current_mode: str | None = None
    for line in raw.splitlines():
        if not line.strip():
            continue
        if not line.startswith(" "):
            key, _, value = line.partition(":")
            current_key = key.strip()
            value = value.strip()
            if value:
                result[current_key] = _parse_scalar(value)
                current_mode = None
            else:
                result[current_key] = []
                current_mode = "block"
            continue
        if current_key is None or current_mode != "block":
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            if not isinstance(result[current_key], list):
                result[current_key] = []
            result[current_key].append(_parse_scalar(stripped[2:].strip()))
        elif ":" in stripped:
            if not isinstance(result[current_key], dict):
                result[current_key] = {}
            sub_key, _, sub_value = stripped.partition(":")
            result[current_key][sub_key.strip()] = _parse_scalar(sub_value.strip())
    return result


def _parse_scalar(value: str) -> Any:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] == '"':
        return text[1:-1].replace('\\"', '"')
    if text in {"true", "false"}:
        return text == "true"
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def _strip_markdown_title(body: str, title: str) -> str:
    lines = body.lstrip().splitlines()
    if lines and lines[0].strip().startswith("# "):
        lines = lines[1:]
        if lines and not lines[0].strip():
            lines = lines[1:]
    return "\n".join(lines).strip() or body.strip()


def _select_diverse_scored_cards(
    scored: list[tuple[float, KnowledgeCard]],
    limit: int,
    preferred_card_types: list[str],
) -> tuple[list[tuple[float, KnowledgeCard]], int, dict[str, int]]:
    selected: list[tuple[float, KnowledgeCard]] = []
    selected_ids: set[int] = set()
    seen_fingerprints: set[str] = set()
    card_type_counts: Counter[str] = Counter()
    capped_backlog: list[tuple[float, KnowledgeCard, str]] = []
    filtered_duplicate_count = 0
    max_per_type = _max_cards_per_type(limit, preferred_card_types)

    for score, card in scored:
        fingerprint = _search_fingerprint(card)
        if fingerprint and fingerprint in seen_fingerprints:
            filtered_duplicate_count += 1
            continue
        type_cap = _card_type_search_cap(card, max_per_type)
        if card_type_counts[card.card_type] >= type_cap:
            capped_backlog.append((score, card, fingerprint))
            continue
        selected.append((score, card))
        selected_ids.add(card.id)
        card_type_counts[card.card_type] += 1
        if fingerprint:
            seen_fingerprints.add(fingerprint)
        if len(selected) >= limit:
            return selected, filtered_duplicate_count, dict(card_type_counts)

    for score, card, fingerprint in capped_backlog:
        if len(selected) >= limit:
            break
        if card.id in selected_ids:
            continue
        if fingerprint and fingerprint in seen_fingerprints:
            filtered_duplicate_count += 1
            continue
        selected.append((score, card))
        selected_ids.add(card.id)
        card_type_counts[card.card_type] += 1
        if fingerprint:
            seen_fingerprints.add(fingerprint)

    return selected, filtered_duplicate_count, dict(card_type_counts)


def _max_cards_per_type(limit: int, preferred_card_types: list[str]) -> int:
    diversity_slots = max(2, min(4, len(preferred_card_types) or 2))
    return max(2, math.ceil(limit / diversity_slots) + 1)


def _card_type_search_cap(card: KnowledgeCard, max_per_type: int) -> int:
    if card.library_type in {"worldbuilding", "memory"}:
        return max_per_type + 1
    if card.card_type in {"memory", "character", "location", "faction", "rule", "world_rule"}:
        return max_per_type + 1
    return max_per_type


def _search_fingerprint(card: KnowledgeCard) -> str:
    if card.content_fingerprint:
        return card.content_fingerprint
    return content_fingerprint(card.title, card.content, card.avoid, _json_list(card.tags_json))


def _card_sort_time(card: KnowledgeCard) -> datetime:
    return card.updated_at or card.created_at or datetime.min


def _score_card(
    card: KnowledgeCard,
    query: str,
    stage: str,
    preferred_card_types: list[str],
    expanded_terms: list[str] | None = None,
) -> float:
    terms = _tokens(query)
    expanded_tokens = _tokens(" ".join(expanded_terms or []))
    terms = list(dict.fromkeys([*terms, *expanded_tokens]))[:32]
    haystack = "\n".join(
        [
            card.title or "",
            card.summary or "",
            card.content or "",
            card.avoid or "",
            card.card_type or "",
            card.library_type or "",
            " ".join(_json_list(card.tags_json)),
            " ".join(_json_list(card.use_when_json)),
        ]
    ).lower()
    score = 0.0
    for term in terms:
        if term and term in haystack:
            score += 1.0
    tags = [tag.lower() for tag in _json_list(card.tags_json)]
    for term in terms:
        if any(term == tag or term in tag for tag in tags):
            score += 2.0
    if card.card_type in preferred_card_types:
        score += 3.0
    use_when = " ".join(_json_list(card.use_when_json)).lower()
    if stage and (stage.lower() in use_when or _stage_label(stage) in use_when):
        score += 2.0
    if stage == "worldbuilding_check" and card.library_type == "worldbuilding":
        score += 5.0
    elif card.library_type == "worldbuilding":
        score += 2.0
    if stage in {"draft", "continue", "continuation"} and card.library_type == "memory":
        score += 4.0
    elif stage == "revision" and card.library_type == "memory":
        score += 3.0
    if stage in {"draft", "revision"} and card.card_type == "anti_pattern":
        score += 3.0
    if stage in {"draft", "revision"} and card.card_type == "style_pattern":
        score += 2.0
    if card.library_type == "memory":
        score += 1.0 / math.sqrt(max(1, (datetime.utcnow() - card.updated_at).days + 1)) if card.updated_at else 0.5
    if score > 0:
        score += min(math.log2(max(0, card.evidence_count or 0) + 1), 2.0)
    return round(score, 4)


def _search_result(card: KnowledgeCard, score: float) -> dict[str, Any]:
    return {
        "id": card.card_id,
        "library_type": card.library_type,
        "card_type": card.card_type,
        "title": card.title,
        "score": round(score, 4),
        "source_ref": _json_dict(card.source_ref_json),
        "content_preview": _clip(card.content, 320),
        "tags": _json_list(card.tags_json),
        "status": card.status,
        "scope_level": card.scope_level or "global",
        "volume_index": card.volume_index,
        "chapter_index": card.chapter_index,
    }


def _scope_label(card: KnowledgeCard) -> str:
    scope_level = normalize_scope_level(card.scope_level, "global")
    if scope_level == "global":
        return "global"
    if scope_level == "volume":
        return f"volume:{card.volume_index}" if card.volume_index is not None else "volume:unknown"
    volume = card.volume_index if card.volume_index is not None else "unknown"
    chapter = card.chapter_index if card.chapter_index is not None else "unknown"
    return f"chapter:{volume}/{chapter}"


def _tokens(value: str) -> list[str]:
    lowered = (value or "").lower()
    words = WORD_RE.findall(lowered)
    if words:
        tokens: list[str] = []
        for word in words:
            if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 4:
                tokens.extend(word[index : index + 2] for index in range(len(word) - 1))
            tokens.append(word)
        return list(dict.fromkeys(token for token in tokens if len(token) >= 2))[:16]
    compact = re.sub(r"\s+", "", lowered)
    return [compact[index : index + 2] for index in range(max(0, len(compact) - 1))][:16]


def _dedupe_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        term = re.sub(r"\s+", " ", (value or "").strip())
        if not term:
            continue
        key = term.lower()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms[:36]


def _card_type_label(card_type: str) -> str:
    return {
        "chapter_analysis": "章节分析",
        "writing_rule": "写作规则",
        "emotion_module": "情绪模块",
        "conflict_pattern": "冲突模式",
        "anti_pattern": "反模式",
        "style_pattern": "文风模式",
        "information_pattern": "信息投放",
        "memory": "长期记忆",
        "outline": "提纲记忆",
        "draft": "正文记忆",
        "character_state": "人物状态",
        "foreshadowing": "伏笔",
        "continuity_note": "连续性",
        "worldbuilding": "世界观",
        "character": "人物",
        "location": "地点",
        "faction": "势力",
        "rule": "规则",
        "world_rule": "世界规则",
        "timeline": "时间线",
        "item": "物件",
    }.get(card_type, card_type)


def _stage_label(stage: str) -> str:
    return {
        "outline": "提纲",
        "draft": "正文",
        "revision": "润色",
        "continue": "续写",
        "continuation": "续写",
        "worldbuilding_check": "设定",
    }.get(stage, stage).lower()


def _clip(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
