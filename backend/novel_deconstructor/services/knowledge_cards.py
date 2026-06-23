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
VALID_STATUSES = {"raw_extracted", "approved", "disabled", "deleted", "deprecated"}
ACTIVE_STATUSES = {"raw_extracted", "approved"}
WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]+")


def normalize_library_type(value: str | None, default: str = "writing_guide") -> str:
    return value if value in VALID_LIBRARY_TYPES else default


def normalize_status(value: str | None, default: str = "raw_extracted") -> str:
    return value if value in VALID_STATUSES else default


def normalize_card_type(value: str | None, fallback: str = "writing_rule") -> str:
    cleaned = (value or fallback).strip()
    return CARD_COLLECTIONS.get(cleaned, cleaned)


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


def knowledge_docs_root(knowledge_base: KnowledgeBase) -> Path:
    return knowledge_base_storage_dir(knowledge_base) / "knowledge_docs"


def import_knowledge_package(
    db: Session,
    knowledge_base: KnowledgeBase,
    package: dict[str, Any],
    *,
    library_type: str = "writing_guide",
    status: str = "approved",
) -> dict[str, Any]:
    normalized_library = normalize_library_type(library_type, "writing_guide")
    normalized_status = normalize_status(status, "approved")
    markdown_root = knowledge_docs_root(knowledge_base)
    counters: Counter[str] = Counter()
    card_types: Counter[str] = Counter()
    imported = 0
    skipped = 0
    generated_markdown = 0
    seen_ids: set[str] = set()

    for source_key, raw_card in _iter_package_cards(package):
        card_type = normalize_card_type(raw_card.get("card_type") or raw_card.get("type") or CARD_COLLECTIONS[source_key])
        counters[card_type] += 1
        card_id = _card_id(raw_card, card_type, counters[card_type])
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
        title = _card_title(raw_card, card_type, card_id)
        content = _card_content(raw_card, card_type)
        source_ref = _source_ref(package, raw_card, source_key)
        card = KnowledgeCard(
            knowledge_base_id=knowledge_base.id,
            card_id=card_id,
            library_type=normalized_library,
            card_type=card_type,
            title=title,
            content=content,
            summary=_summary(raw_card, content),
            tags_json=_json(_tags(raw_card, card_type)),
            source_ref_json=_json(source_ref),
            use_when_json=_json(_as_list(raw_card.get("use_when"))),
            avoid=_avoid_text(raw_card),
            confidence=_confidence(raw_card),
            status=normalized_status,
            source_kind="knowledge_package",
            package_id=str(package.get("package_id") or ""),
        )
        card.markdown_path = str(card_markdown_path(knowledge_base, card))
        db.add(card)
        db.flush()
        write_card_markdown(knowledge_base, card)
        imported += 1
        generated_markdown += 1
        card_types[card_type] += 1

    db.commit()
    return {
        "imported_count": imported,
        "generated_markdown_count": generated_markdown,
        "skipped_count": skipped,
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
        )
        card.markdown_path = str(card_markdown_path(knowledge_base, card))
        db.add(card)
        db.flush()
        write_card_markdown(knowledge_base, card)
        imported += 1
        generated_markdown += 1
        card_types[card_type] += 1

    db.commit()
    return {
        "imported_count": imported,
        "generated_markdown_count": generated_markdown,
        "skipped_count": skipped,
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
        "created_at": card.created_at,
        "updated_at": card.updated_at,
    }


def card_markdown_path(knowledge_base: KnowledgeBase, card: KnowledgeCard) -> Path:
    library = secure_slug(card.library_type or "writing_guide", "writing_guide")
    card_type = secure_slug(card.card_type or "card", "card")
    filename = f"{secure_slug(card.card_id or card.title, 'card')}.md"
    return knowledge_docs_root(knowledge_base) / library / card_type / filename


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
            "confidence": card.confidence,
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
            "这张知识卡可供写作 Agent 检索使用。若来自拆书结果，只能作为写法参考，不能照搬来源作品的人物、地名、桥段或世界观。",
            "",
        ]
    )
    return "\n".join(sections)


def list_markdown_docs(db: Session, knowledge_base: KnowledgeBase) -> list[dict[str, Any]]:
    cards = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id)
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
    card.markdown_path = str(card_markdown_path(knowledge_base, card))
    db.commit()
    db.refresh(card)
    write_card_markdown(knowledge_base, card)
    db.commit()
    return {"card_id": card.card_id, "status": "updated", "updated_fields": list(dict.fromkeys(updated))}


def export_card_markdown(db: Session, knowledge_base: KnowledgeBase, card_id: str) -> dict[str, Any]:
    card = get_card_or_404(db, knowledge_base, card_id)
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
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    limit = max(1, min(top_k or 8, 30))
    preferred_card_types = select_preferred_card_types(stage)
    cards_query = db.query(KnowledgeCard)
    if knowledge_base_ids:
        cards_query = cards_query.filter(KnowledgeCard.knowledge_base_id.in_(knowledge_base_ids))
    if library_type:
        cards_query = cards_query.filter(KnowledgeCard.library_type == library_type)
    if not include_inactive:
        cards_query = cards_query.filter(KnowledgeCard.status.in_(ACTIVE_STATUSES))
    candidates = cards_query.all()
    scored: list[tuple[float, KnowledgeCard]] = []
    for card in candidates:
        score = _score_card(card, query, stage, preferred_card_types)
        if score > 0:
            scored.append((score, card))
    scored.sort(key=lambda item: (item[0], item[1].updated_at or item[1].created_at), reverse=True)
    selected = scored[:limit]
    results = [_search_result(card, score) for score, card in selected]
    debug = {
        "query": query,
        "preferred_card_types": preferred_card_types,
        "total_candidates": len(candidates),
        "selected_count": len(results),
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
        }
        for item in results
    ]


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
    return cards


def _card_id(raw: dict[str, Any], card_type: str, index: int) -> str:
    explicit = raw.get("card_id") or raw.get("id")
    if explicit:
        return re.sub(r"[^A-Za-z0-9_-]+", "-", str(explicit)).strip("-_")[:80] or f"{CARD_PREFIXES.get(card_type, 'KC')}-{index:03d}"
    return f"{CARD_PREFIXES.get(card_type, 'KC')}-{index:03d}"


def _card_title(raw: dict[str, Any], card_type: str, card_id: str) -> str:
    for key in ("title", "name", "chapter_title", "summary"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return _clip(value, 120)
    return f"{card_type} {card_id}"


def _card_content(raw: dict[str, Any], card_type: str) -> str:
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
        if field not in raw:
            continue
        text = _value_markdown(field, raw[field])
        if text:
            lines.append(text)
    if lines:
        return "\n\n".join(lines)
    return json.dumps(raw, ensure_ascii=False, indent=2)


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
    return source_ref


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


def _score_card(card: KnowledgeCard, query: str, stage: str, preferred_card_types: list[str]) -> float:
    terms = _tokens(query)
    haystack = "\n".join(
        [
            card.title or "",
            card.summary or "",
            card.content or "",
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
    if stage in {"draft", "continue", "continuation"} and card.library_type == "memory":
        score += 4.0
    if stage in {"draft", "revision"} and card.card_type == "anti_pattern":
        score += 3.0
    if card.library_type == "memory":
        score += 1.0 / math.sqrt(max(1, (datetime.utcnow() - card.updated_at).days + 1)) if card.updated_at else 0.5
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
    }


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
