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
    RETRIEVABLE_STATUSES,
    card_markdown_path,
    canonical_group_id,
    normalized_title_hash,
    sync_memory_card,
    used_knowledge_from_results,
    write_card_markdown,
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
from .common import *

__all__ = [
    "_build_book_outline_from_cards",
    "_build_volume_outline_from_cards",
    "_chinese_to_int",
    "_extract_volume_number",
    "_flush_volume",
    "_outline_card_id",
    "_save_outline_layers_as_cards",
    "_split_generated_outline_by_layers",
    "_upsert_outline_card",
    "sync_book_volume_outlines_from_cards",
]

def _split_generated_outline_by_layers(content: str) -> dict[str, Any]:
    """将 LLM 生成的大纲 Markdown 拆分为书/卷/章三层。

    返回:
        {
            "book_outline": str | None,       # # 全书大纲 内容
            "volume_outlines": dict[int, str], # {volume_index: "## 第X卷 ..."}
            "chapter_content": str,            # 仅章节层内容（给用户展示）
        }
    """
    lines = content.splitlines()
    result: dict[str, Any] = {
        "book_outline": None,
        "volume_outlines": {},
        "chapter_content": "",
    }

    # 状态机提取
    current_book_lines: list[str] = []
    current_volume_lines: list[str] = []
    current_volume_index: int | None = None
    chapter_lines: list[str] = []
    in_book = False
    in_volume = False

    book_header_pattern = re.compile(
        r"^#{1,2}\s*(?:全书|全本|整部|整体|novel|book|作品)\s*(?:大纲|纲要|结构|框架|概览)?",
        re.IGNORECASE,
    )
    volume_header_pattern = re.compile(
        r"^#{1,3}\s*(?:第\s*[一二三四五六七八九十百千万\d]+\s*卷|volume\s*\d+|vol\.?\s*\d+)",
        re.IGNORECASE,
    )
    chapter_header_pattern = re.compile(
        r"^#{1,4}\s*(?:第\s*[一二三四五六七八九十百千万\d]+\s*章|chapter\s*\d+|ch\.?\s*\d+)",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()

        if book_header_pattern.match(stripped):
            # 进入书层 — 先保存前一段书层内容
            if current_book_lines:
                book_text = "\n".join(current_book_lines).strip()
                if len(book_text) > 20:
                    result["book_outline"] = book_text
            _flush_volume(current_volume_lines, current_volume_index, result)
            in_book = True
            in_volume = False
            current_book_lines = [line]
            continue

        if volume_header_pattern.match(stripped):
            _flush_volume(current_volume_lines, current_volume_index, result)
            if in_book:
                current_book_lines.append(line)
            in_book = False
            in_volume = True
            current_volume_index = _extract_volume_number(stripped)
            current_volume_lines = [line]
            continue

        if chapter_header_pattern.match(stripped):
            _flush_volume(current_volume_lines, current_volume_index, result)
            in_book = False
            in_volume = False
            current_volume_index = None
            chapter_lines.append(line)
            continue

        if in_book:
            current_book_lines.append(line)
        elif in_volume:
            current_volume_lines.append(line)
        else:
            chapter_lines.append(line)

    _flush_volume(current_volume_lines, current_volume_index, result)

    if current_book_lines:
        book_text = "\n".join(current_book_lines).strip()
        if len(book_text) > 20:
            result["book_outline"] = book_text

    result["chapter_content"] = "\n".join(chapter_lines).strip()
    if not result["chapter_content"] and content.strip():
        # 如果没有识别到章节层，返回原始内容
        result["chapter_content"] = content.strip()

    return result

def _extract_volume_number(line: str) -> int | None:
    """从行中提取卷号。"""
    match = re.search(r"第\s*([一二三四五六七八九十百千万\d]+)\s*卷", line)
    if match:
        return _chinese_to_int(match.group(1))
    match = re.search(r"volume\s*(\d+)", line, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None

def _chinese_to_int(text: str) -> int:
    """中文数字转整数。"""
    mapping = {
        "零": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
        "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
        "百": 100, "千": 1000, "万": 10000,
    }
    if text.isdigit():
        return int(text)
    # 标准中文数字解析：从高位到低位
    result = 0
    current = 0
    for char in text:
        if char in mapping:
            val = mapping[char]
            if val >= 10:
                if current == 0:
                    current = 1
                result += current * val
                current = 0
            else:
                current = val
        else:
            try:
                return int(text)
            except ValueError:
                return 0
    result += current  # 加上最后的个位数
    return result if result > 0 else 0

def _flush_volume(lines: list[str], volume_index: int | None, result: dict[str, Any]) -> None:
    if not lines or volume_index is None:
        lines.clear()
        return
    text = "\n".join(lines).strip()
    if len(text) > 10:
        result["volume_outlines"][volume_index] = text
    lines.clear()

def _save_outline_layers_as_cards(
    db: Session,
    kb: KnowledgeBase,
    workspace_id: str,
    layers: dict[str, Any],
) -> dict[str, Any]:
    """将书层和卷层大纲保存为知识卡。返回创建的 card_id 列表。"""
    saved: dict[str, Any] = {"book_card_id": None, "volume_card_ids": {}}

    # 保存全书大纲卡
    if layers.get("book_outline"):
        book_content = str(layers["book_outline"])
        book_card = _upsert_outline_card(
            db, kb, workspace_id,
            card_type=OUTLINE_CARD_TYPE_BOOK,
            title="全书大纲",
            content=book_content,
            scope_level="global",
            volume_index=None,
            chapter_index=None,
            priority=98,
        )
        if book_card:
            saved["book_card_id"] = book_card.card_id

    # 保存各卷大纲卡
    volume_outlines: dict[int, str] = layers.get("volume_outlines", {})
    for volume_index, vol_content in sorted(volume_outlines.items()):
        vol_card = _upsert_outline_card(
            db, kb, workspace_id,
            card_type=OUTLINE_CARD_TYPE_VOLUME,
            title=f"第{volume_index}卷大纲",
            content=vol_content,
            scope_level="volume",
            volume_index=volume_index,
            chapter_index=None,
            priority=97,
        )
        if vol_card:
            saved["volume_card_ids"][volume_index] = vol_card.card_id

    db.commit()
    return saved

def _upsert_outline_card(
    db: Session,
    kb: KnowledgeBase,
    workspace_id: str,
    *,
    card_type: str,
    title: str,
    content: str,
    scope_level: str,
    volume_index: int | None = None,
    chapter_index: int | None = None,
    priority: int = 95,
) -> KnowledgeCard | None:
    """创建或更新大纲类知识卡。通过 card_type + volume_index 定位已有卡片。"""
    import hashlib

    content_fp = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    source = AUTO_BOOK_OUTLINE_SOURCE if card_type == OUTLINE_CARD_TYPE_BOOK else AUTO_VOLUME_OUTLINE_SOURCE

    query = db.query(KnowledgeCard).filter(
        KnowledgeCard.knowledge_base_id == kb.id,
        KnowledgeCard.card_type == card_type,
        KnowledgeCard.source_kind == source,
    )
    if volume_index is not None:
        query = query.filter(KnowledgeCard.volume_index == volume_index)
    else:
        query = query.filter(KnowledgeCard.scope_level == "global")

    existing = query.first()
    if existing and existing.content_fingerprint == content_fp:
        return existing  # 内容未变化

    if existing:
        title_hash = normalized_title_hash(title)
        existing.title = title
        existing.content = content
        existing.summary = _clip(content, 240)
        existing.content_fingerprint = content_fp
        existing.normalized_title_hash = title_hash
        existing.canonical_group_id = canonical_group_id(
            "memory",
            card_type,
            {"scope_level": scope_level, "volume_index": volume_index, "chapter_index": chapter_index},
            title_hash,
        )
        existing.retrieval_level = "pinned"
        existing.context_role = "memory"
        existing.status = "approved"
        existing.is_canonical = True
        existing.retrievable = True
        existing.priority = max(existing.priority or 0, priority)
        existing.updated_at = datetime.utcnow()
        db.flush()
        write_card_markdown(kb, existing)
        _safe_index_card(db, existing)
        return existing

    # 新建卡片
    card_id = _outline_card_id(db, kb, card_type, volume_index)
    source_ref = {"source": source, "generated_at": datetime.utcnow().isoformat()}
    title_hash = normalized_title_hash(title)
    card = KnowledgeCard(
        knowledge_base_id=kb.id,
        card_id=card_id,
        library_type="memory",
        card_type=card_type,
        title=title,
        content=content,
        summary=_clip(content, 240),
        tags_json=json.dumps([card_type, "auto_generated", "approved"], ensure_ascii=False),
        source_ref_json=json.dumps(source_ref, ensure_ascii=False),
        source_refs_json=json.dumps([source_ref], ensure_ascii=False),
        use_when_json=json.dumps(["draft", "outline", "continue", "revision"], ensure_ascii=False),
        avoid="",
        confidence=1.0,
        status="approved",
        source_kind=source,
        package_id="",
        is_canonical=True,
        merged_from_ids_json=json.dumps([card_id], ensure_ascii=False),
        evidence_count=1,
        content_fingerprint=content_fp,
        normalized_title_hash=title_hash,
        canonical_group_id=canonical_group_id(
            "memory",
            card_type,
            {"scope_level": scope_level, "volume_index": volume_index, "chapter_index": chapter_index},
            title_hash,
        ),
        retrieval_level="pinned",
        context_role="memory",
        scope_level=scope_level,
        volume_index=volume_index,
        chapter_index=chapter_index,
        retrievable=True,
        priority=priority,
    )
    card.markdown_path = str(card_markdown_path(kb, card))
    db.add(card)
    db.flush()
    write_card_markdown(kb, card)
    _safe_index_card(db, card)
    return card

def _outline_card_id(db: Session, kb: KnowledgeBase, card_type: str, volume_index: int | None) -> str:
    """生成大纲卡的唯一 ID。"""
    existing = (
        db.query(KnowledgeCard)
        .filter(
            KnowledgeCard.knowledge_base_id == kb.id,
            KnowledgeCard.card_type == card_type,
        )
        .count()
    )
    if card_type == OUTLINE_CARD_TYPE_BOOK:
        return f"BO-{existing + 1:03d}"
    if volume_index is not None:
        return f"VO-{volume_index:02d}-{existing + 1:03d}"
    return f"AO-{existing + 1:03d}"

def sync_book_volume_outlines_from_cards(
    db: Session,
    kb: KnowledgeBase,
    workspace_id: str,
) -> dict[str, Any]:
    """根据现有知识卡内容，自动生成/更新书层和卷层大纲卡。

    当知识卡被导入、修改或合并后调用此函数，以保持书卷大纲与知识卡内容同步。
    """
    cards = (
        db.query(KnowledgeCard)
        .filter(
            KnowledgeCard.knowledge_base_id == kb.id,
            KnowledgeCard.is_canonical.is_(True),
            KnowledgeCard.status.in_(RETRIEVABLE_STATUSES),
            KnowledgeCard.retrievable.is_(True),
        )
        .order_by(KnowledgeCard.library_type, KnowledgeCard.card_type)
        .all()
    )

    if not cards:
        return {"book_card_id": None, "volume_card_ids": {}, "message": "无可用知识卡，跳过书卷大纲生成。"}

    # 分类汇总知识卡
    worldbuilding_cards = [c for c in cards if c.library_type == "worldbuilding"]
    writing_guide_cards = [c for c in cards if c.library_type == "writing_guide"]
    memory_cards = [c for c in cards if c.library_type == "memory"]

    # 按卷分组
    volume_groups: dict[int, list[KnowledgeCard]] = {}
    global_cards: list[KnowledgeCard] = []
    for card in cards:
        if card.scope_level == "global":
            global_cards.append(card)
        elif card.volume_index is not None:
            volume_groups.setdefault(card.volume_index, []).append(card)

    saved: dict[str, Any] = {"book_card_id": None, "volume_card_ids": {}}

    # 生成全书大纲
    book_outline = _build_book_outline_from_cards(
        worldbuilding_cards, writing_guide_cards, memory_cards,
        global_cards, volume_groups,
    )
    if book_outline:
        book_card = _upsert_outline_card(
            db, kb, workspace_id,
            card_type=OUTLINE_CARD_TYPE_BOOK,
            title="全书大纲（自动同步）",
            content=book_outline,
            scope_level="global",
            priority=98,
        )
        if book_card:
            saved["book_card_id"] = book_card.card_id

    # 生成各卷大纲
    for volume_index in sorted(volume_groups.keys()):
        vol_cards = volume_groups[volume_index]
        vol_outline = _build_volume_outline_from_cards(
            volume_index, vol_cards, global_cards,
            worldbuilding_cards, writing_guide_cards,
        )
        if vol_outline:
            vol_card = _upsert_outline_card(
                db, kb, workspace_id,
                card_type=OUTLINE_CARD_TYPE_VOLUME,
                title=f"第{volume_index}卷大纲（自动同步）",
                content=vol_outline,
                scope_level="volume",
                volume_index=volume_index,
                priority=97,
            )
            if vol_card:
                saved["volume_card_ids"][volume_index] = vol_card.card_id

    db.commit()
    saved["message"] = f"书层大纲：{'已更新' if saved['book_card_id'] else '无变化'}；卷层大纲：{len(saved['volume_card_ids'])} 卷已同步。"
    return saved

def _build_book_outline_from_cards(
    worldbuilding_cards: list[KnowledgeCard],
    writing_guide_cards: list[KnowledgeCard],
    memory_cards: list[KnowledgeCard],
    global_cards: list[KnowledgeCard],
    volume_groups: dict[int, list[KnowledgeCard]],
) -> str:
    """根据知识卡构建全书大纲文本。"""
    lines: list[str] = []
    lines.append("# 全书大纲")
    lines.append("")
    lines.append("> 本大纲由知识卡自动生成，随知识卡新增/修改同步更新。")
    lines.append("")

    # 世界观概览
    wb_titles = [c.title for c in worldbuilding_cards[:10]]
    if wb_titles:
        lines.append("## 世界观设定概览")
        for title in wb_titles:
            lines.append(f"- {title}")
        lines.append("")

    # 写作技法概览
    wg_types: dict[str, int] = {}
    for c in writing_guide_cards:
        wg_types[c.card_type] = wg_types.get(c.card_type, 0) + 1
    if wg_types:
        lines.append("## 写作技法概览")
        lines.append(f"- 共 {sum(wg_types.values())} 条技法指南")
        for ct, count in sorted(wg_types.items()):
            lines.append(f"  - {ct}: {count} 条")
        lines.append("")

    # 全局设定卡
    global_titles = [c.title for c in global_cards[:15]]
    if global_titles:
        lines.append("## 全局设定与规则")
        for title in global_titles:
            lines.append(f"- {title}")
        lines.append("")

    # 卷结构概览
    if volume_groups:
        lines.append("## 卷结构概览")
        for vi in sorted(volume_groups.keys()):
            vol_card_count = len(volume_groups[vi])
            vol_titles = [c.title for c in volume_groups[vi][:5]]
            lines.append(f"### 第{vi}卷")
            lines.append(f"- 知识卡数量: {vol_card_count}")
            for title in vol_titles:
                lines.append(f"  - {title}")
        lines.append("")

    # Memory 关键信息
    outline_memories = [c for c in memory_cards if c.card_type in ("ChapterOutline", "volume_summary")]
    if outline_memories:
        lines.append("## 已确认写作进展")
        for mem in outline_memories[:10]:
            pos = f"V{mem.volume_index}C{mem.chapter_index}" if mem.volume_index and mem.chapter_index else "全局"
            lines.append(f"- [{pos}] {mem.title}")
        lines.append("")

    return "\n".join(lines)

def _build_volume_outline_from_cards(
    volume_index: int,
    vol_cards: list[KnowledgeCard],
    global_cards: list[KnowledgeCard],
    worldbuilding_cards: list[KnowledgeCard],
    writing_guide_cards: list[KnowledgeCard],
) -> str:
    """根据知识卡构建某一卷的大纲文本。"""
    lines: list[str] = []
    lines.append(f"## 第{volume_index}卷大纲")
    lines.append("")
    lines.append(f"> 本卷大纲由知识卡自动生成，随知识卡新增/修改同步更新。")
    lines.append("")

    # 卷内卡分类
    chapter_cards: dict[int, list[KnowledgeCard]] = {}
    vol_global: list[KnowledgeCard] = []
    for card in vol_cards:
        if card.chapter_index is not None:
            chapter_cards.setdefault(card.chapter_index, []).append(card)
        else:
            vol_global.append(card)

    # 卷级设定
    if vol_global:
        lines.append("### 本卷级设定与规则")
        for card in vol_global[:10]:
            lines.append(f"- [{card.card_type}] {card.title}")
        lines.append("")

    # 相关全局设定
    relevant_global = [c for c in global_cards if c.library_type == "worldbuilding"][:5]
    if relevant_global:
        lines.append("### 适用本卷的全局设定")
        for card in relevant_global:
            lines.append(f"- {card.title}")
        lines.append("")

    # 章节结构
    if chapter_cards:
        lines.append("### 章节结构")
        for ci in sorted(chapter_cards.keys()):
            ch_cards = chapter_cards[ci]
            ch_titles = [c.title for c in ch_cards[:5]]
            lines.append(f"- 第{ci}章: {', '.join(ch_titles) if ch_titles else '（无关键卡）'}")
        lines.append("")

    return "\n".join(lines)

