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

__all__ = [
    "_archive_import_markdown",
    "_clean_heading",
    "_extract_chapter_index",
    "_extract_volume_index",
    "_frontmatter",
    "_infer_markdown_chapter_scope",
    "_parse_scalar",
    "_parse_simple_yaml",
    "_parse_zh_number",
    "_scope_markdown_dir",
    "_split_long_section",
    "_split_markdown_sections",
    "_strip_markdown_title",
    "_yaml_scalar",
    "card_markdown_path",
    "delete_card_physical",
    "delete_markdown_doc",
    "export_card_markdown",
    "knowledge_docs_root",
    "list_markdown_docs",
    "parse_frontmatter",
    "read_markdown_doc",
    "render_card_markdown",
    "save_markdown_doc",
    "sync_card_from_markdown",
    "sync_deleted_markdown",
    "write_card_markdown",
]

def knowledge_docs_root(knowledge_base: KnowledgeBase) -> Path:
    return knowledge_base_storage_dir(knowledge_base) / "knowledge_docs"

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

def delete_card_physical(db: Session, knowledge_base: KnowledgeBase, card: KnowledgeCard) -> bool:
    paths = []
    if card.markdown_path:
        paths.append(Path(card.markdown_path))
    paths.append(card_markdown_path(knowledge_base, card))
    deleted_file = False
    for path in dict.fromkeys(paths):
        if path.exists() and path.is_file():
            path.unlink()
            deleted_file = True
    db.delete(card)
    return deleted_file

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
            "tags": tags,
            "use_when": use_when,
            "source_ref": source_ref,
            "source_refs": _json_list_of_dicts(card.source_refs_json),
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
    deleted_file = delete_card_physical(db, knowledge_base, card)
    db.commit()
    return {
        "card_id": doc_id,
        "status": "deleted",
        "updated_fields": ["markdown_path", "status", "physical_delete", f"files:{1 if deleted_file else 0}"],
    }

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
        "retrieval_level": "retrieval_level",
        "context_role": "context_role",
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
        elif attr == "retrieval_level":
            value = normalize_retrieval_level(str(value), card.retrieval_level)
        elif attr == "context_role":
            value = normalize_context_role(str(value), card.context_role)
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

    for key, attr in [("tags", "tags_json"), ("use_when", "use_when_json"), ("source_ref", "source_ref_json"), ("source_refs", "source_refs_json")]:
        if key not in frontmatter:
            continue
        value = frontmatter[key]
        serialized = _json(value if isinstance(value, (list, dict)) else [str(value)])
        if attr == "source_ref_json" and not isinstance(value, dict):
            serialized = _json({"value": str(value)})
        if attr == "source_refs_json":
            source_refs = value if isinstance(value, list) else [value]
            serialized = _json([item for item in source_refs if isinstance(item, dict)])
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
    _refresh_card_retrieval_metadata(card)
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
    _refresh_card_retrieval_metadata(card)
    card.markdown_path = str(card_markdown_path(knowledge_base, card))
    path = write_card_markdown(knowledge_base, card)
    db.commit()
    return {"doc_id": card.card_id, "card_id": card.card_id, "content": path.read_text(encoding="utf-8"), "path": str(path)}

def sync_deleted_markdown(db: Session, knowledge_base: KnowledgeBase) -> dict[str, Any]:
    cards = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id == knowledge_base.id).all()
    deleted = 0
    deleted_files = 0
    for card in cards:
        if card.markdown_path and not Path(card.markdown_path).exists():
            if delete_card_physical(db, knowledge_base, card):
                deleted_files += 1
            deleted += 1
    db.commit()
    return {"card_id": "*", "status": "updated", "updated_fields": [f"deleted:{deleted}", f"files:{deleted_files}"]}

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
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
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

def _infer_markdown_chapter_scope(
    title: str,
    content: str,
    heading_path: list[str],
    source_name: str,
) -> dict[str, Any]:
    chapter_index = _extract_chapter_index(title)
    if chapter_index is None:
        for heading in reversed(heading_path):
            chapter_index = _extract_chapter_index(heading)
            if chapter_index is not None:
                break
    if chapter_index is None:
        chapter_index = _extract_chapter_index(content[:1200])
    if chapter_index is None:
        return {}

    volume_index = None
    for value in [*heading_path, source_name, content[:1200]]:
        volume_index = _extract_volume_index(str(value))
        if volume_index is not None:
            break
    if volume_index is None:
        volume_index = 1

    return {
        "scope_level": "chapter",
        "volume_index": volume_index,
        "chapter_index": chapter_index,
        "chapter_title": _clip(_clean_heading(title), 120),
        "reveal_at_volume_index": volume_index,
        "reveal_at_chapter_index": chapter_index,
    }

def _extract_chapter_index(value: str) -> int | None:
    match = CHAPTER_HEADING_RE.search(value or "")
    if not match:
        return None
    return _parse_zh_number(match.group(1))

def _extract_volume_index(value: str) -> int | None:
    match = VOLUME_HEADING_RE.search(value or "")
    if not match:
        return None
    return _parse_zh_number(match.group(1))

def _parse_zh_number(value: str) -> int | None:
    text = (value or "").strip().translate(str.maketrans("０１２３４５６７８９", "0123456789"))
    if not text:
        return None
    if text.isdigit():
        return int(text)
    digit_map = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    unit_map = {"十": 10, "百": 100, "千": 1000}
    total = 0
    section = 0
    number = 0
    seen = False
    for char in text:
        if char in digit_map:
            number = digit_map[char]
            seen = True
            continue
        if char in unit_map:
            unit = unit_map[char]
            if number == 0:
                number = 1
            section += number * unit
            number = 0
            seen = True
            continue
        return None
    total += section + number
    return total if seen and total > 0 else None

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

