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
from .status_policy import *
from .markdown import *
from .merge import *

__all__ = [
    "_best_keyword_type",
    "_card_content",
    "_card_id",
    "_card_title",
    "_has_explicit_card_id",
    "_infer_markdown_card_type",
    "_is_demo_package_id",
    "_iter_package_cards",
    "_markdown_card_id",
    "_markdown_scope_tags",
    "_markdown_tags",
    "_markdown_use_when",
    "_next_available_card_id",
    "_scope_values",
    "_source_ref",
    "_summary",
    "_tags",
    "_value_markdown",
    "import_knowledge_package",
    "import_markdown_knowledge_source",
    "purge_demo_knowledge_cards",
    "sync_memory_card",
]

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
        retrievable = _default_retrievable(raw_card, card_library, card_status, is_canonical)
        title_hash = normalized_title_hash(title)
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
            source_refs_json=_json(_card_source_refs(source_ref)),
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
            normalized_title_hash=title_hash,
            canonical_group_id=canonical_group_id(card_library, card_type, scope, title_hash),
            retrieval_level=_default_retrieval_level(raw_card, card_library, card_type, card_status, is_canonical, retrievable),
            context_role=_default_context_role(raw_card, card_library, card_type, card_status),
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
            retrievable=retrievable,
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
        chapter_scope = _infer_markdown_chapter_scope(
            section_title,
            section_body,
            section.get("heading_path", []),
            source_name,
        )
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
        if chapter_scope:
            source_ref.update({key: value for key, value in chapter_scope.items() if value is not None})
            if normalized_library == "memory" and not (frontmatter.get("card_type") or frontmatter.get("type")):
                card_type = "ChapterOutline"
        raw_scope = {**frontmatter, "title": section_title}
        if chapter_scope:
            raw_scope.update(chapter_scope)
        scope = _scope_values(raw_scope, source_ref, normalized_library, card_type)
        tags = _merge_lists(
            _markdown_tags(frontmatter, section_title, section_body, normalized_library, card_type, source_name),
            _markdown_scope_tags(scope),
        )
        is_canonical = _default_is_canonical(raw_scope, normalized_status)
        retrievable = _default_retrievable(raw_scope, normalized_library, normalized_status, is_canonical)
        title_hash = normalized_title_hash(section_title)
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
            source_refs_json=_json(_card_source_refs(source_ref)),
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
            normalized_title_hash=title_hash,
            canonical_group_id=canonical_group_id(normalized_library, card_type, scope, title_hash),
            retrieval_level=_default_retrieval_level(raw_scope, normalized_library, card_type, normalized_status, is_canonical, retrievable),
            context_role=_default_context_role(raw_scope, normalized_library, card_type, normalized_status),
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
            retrievable=retrievable,
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
    source_ref = {"memory_id": memory.id, "source": memory.source, **memory.source_ref}
    card.source_ref_json = _json(source_ref)
    card.source_refs_json = _json(_card_source_refs(source_ref))
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
    title_hash = normalized_title_hash(card.title)
    card.normalized_title_hash = title_hash
    card.canonical_group_id = canonical_group_id(
        card.library_type,
        card.card_type,
        {"scope_level": card.scope_level, "volume_index": card.volume_index, "chapter_index": card.chapter_index},
        title_hash,
    )
    card.retrieval_level = _default_retrieval_level({}, card.library_type, card.card_type, card.status, card.is_canonical, card.retrievable)
    card.context_role = _default_context_role({}, card.library_type, card.card_type, card.status)
    card.markdown_path = str(card_markdown_path(knowledge_base, card))
    db.flush()
    write_card_markdown(knowledge_base, card)
    db.commit()
    db.refresh(card)
    return card

def _infer_markdown_card_type(title: str, content: str, library_type: str, *, explicit: str = "") -> str:
    if explicit:
        return normalize_card_type(explicit)
    if _extract_chapter_index(title) is not None:
        return "ChapterOutline" if library_type == "memory" else "chapter_analysis"
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

def _markdown_scope_tags(scope: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    scope_level = normalize_scope_level(str(scope.get("scope_level") or "global"), "global")
    volume_index = scope.get("volume_index")
    chapter_index = scope.get("chapter_index")
    if scope_level in {"volume", "chapter"} and volume_index is not None:
        tags.extend([f"volume:{volume_index}", f"volume_{int(volume_index):03d}"])
    if scope_level == "chapter" and chapter_index is not None:
        tags.extend([f"chapter:{chapter_index}", f"chapter_{int(chapter_index):03d}"])
    return tags

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

