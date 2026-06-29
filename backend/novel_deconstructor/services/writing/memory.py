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
    delete_card_physical,
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
from .common import *

__all__ = [
    "_auto_volume_continuity_memory",
    "_chapter_handoff_memory_content",
    "_chapter_handoff_title",
    "_chapter_outline_memory_content",
    "_chapter_outline_title",
    "_create_memory_record",
    "_delete_memories_and_cards",
    "_latest_volume_handoff_memories",
    "_matches_writing_scope",
    "_memory_source_ref",
    "_next_chapter_position",
    "_refresh_volume_continuity_memory",
    "_require_chapter_position",
    "_volume_continuity_memory_content",
    "_volume_continuity_title",
]

def _create_memory_record(
    db: Session,
    knowledge_base: KnowledgeBase,
    *,
    workspace_id: str,
    memory_type: str,
    title: str,
    content: str,
    tags: list[str],
    source_ref: dict[str, Any],
    source: str,
    scope_level: str = "chapter",
    volume_index: int | None = None,
    volume_title: str | None = None,
    chapter_index: int | None = None,
    chapter_title: str | None = None,
    valid_from_volume_index: int | None = None,
    valid_from_chapter_index: int | None = None,
    valid_until_volume_index: int | None = None,
    valid_until_chapter_index: int | None = None,
    reveal_at_volume_index: int | None = None,
    reveal_at_chapter_index: int | None = None,
    retrievable: bool = True,
    priority: int = 0,
) -> WritingMemory:
    memory = WritingMemory(
        knowledge_base_id=knowledge_base.id,
        workspace_id=workspace_id,
        memory_type=memory_type,
        title=title,
        content=content,
        tags_json=json.dumps(tags, ensure_ascii=False),
        source_ref_json=json.dumps(source_ref, ensure_ascii=False),
        source=source,
        scope_level=scope_level,
        volume_index=volume_index,
        volume_title=volume_title,
        chapter_index=chapter_index,
        chapter_title=chapter_title,
        valid_from_volume_index=valid_from_volume_index,
        valid_from_chapter_index=valid_from_chapter_index,
        valid_until_volume_index=valid_until_volume_index,
        valid_until_chapter_index=valid_until_chapter_index,
        reveal_at_volume_index=reveal_at_volume_index,
        reveal_at_chapter_index=reveal_at_chapter_index,
        retrievable=retrievable,
        priority=priority,
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    card = sync_memory_card(db, knowledge_base, memory)
    _safe_index_memory(db, memory)
    _safe_index_card(db, card)
    db.refresh(memory)
    return memory

def _require_chapter_position(volume_index: int | None, chapter_index: int | None) -> None:
    if not volume_index or not chapter_index:
        raise HTTPException(status_code=400, detail="确认章节 Memory 前必须提供 current_volume_index / current_chapter_index")

def _next_chapter_position(volume_index: int | None, chapter_index: int | None) -> tuple[int | None, int | None]:
    if not volume_index or not chapter_index:
        return volume_index, chapter_index
    return volume_index, chapter_index + 1

def _chapter_outline_title(payload: WritingMemoryConfirmRequest) -> str:
    if payload.volume_index and payload.chapter_index:
        return f"Volume {payload.volume_index} Chapter {payload.chapter_index} Outline"
    return payload.title

def _chapter_handoff_title(payload: WritingMemoryConfirmRequest, *, next_volume: int | None, next_chapter: int | None) -> str:
    if payload.volume_index and payload.chapter_index and next_volume and next_chapter:
        return f"Handoff from Volume {payload.volume_index} Chapter {payload.chapter_index} to Chapter {next_chapter}"
    return payload.title

def _memory_source_ref(payload: WritingMemoryConfirmRequest, *, raw_content_chars: int) -> dict[str, Any]:
    return {
        **payload.source_ref,
        "raw_content_chars": raw_content_chars,
        "volume_index": payload.volume_index,
        "chapter_index": payload.chapter_index,
    }

def _chapter_outline_memory_content(payload: WritingMemoryConfirmRequest) -> str:
    lines = _content_lines(payload.content)
    planned_events = _list_candidates(lines, fallback=payload.content, limit=8)
    data = {
        "chapter_goal": _clip(_first_text_block(lines, payload.content), 600),
        "planned_events": planned_events,
        "expected_conflict": _keyword_excerpt(lines, ["冲突", "阻力", "压力", "对抗", "危机"]) or "待从确认提纲中承接。",
        "expected_emotion_chain": _keyword_excerpt(lines, ["情绪", "爽点", "期待", "释放", "余波"]) or "待从确认提纲中承接。",
        "required_worldbuilding": _list_candidates(_keyword_lines(lines, ["设定", "世界观", "规则", "地点", "势力", "人物"]), fallback="", limit=6),
        "continuity_requirements": _list_candidates(_keyword_lines(lines, ["承接", "连续", "伏笔", "章尾", "下一章", "状态"]), fallback="", limit=6),
        "confirmed_outline_excerpt": _clip(payload.content, 1200),
    }
    return json.dumps(data, ensure_ascii=False, indent=2)

def _chapter_handoff_memory_content(
    payload: WritingMemoryConfirmRequest,
    *,
    next_volume: int | None,
    next_chapter: int | None,
) -> str:
    lines = _content_lines(payload.content)
    ending = _last_paragraphs(payload.content, count=3, max_chars=650) or _tail_excerpt(payload.content, 600)
    last_sentence = _last_sentence(payload.content, max_chars=220)
    open_threads = _unique_texts(
        [
            *_list_candidates(_keyword_lines(lines, ["伏笔", "悬念", "秘密", "异常", "疑问", "尚未", "未解", "线索"]), fallback="", limit=6),
            *_list_candidates(_keyword_lines(lines, ["下一章", "章尾", "钩子", "继续", "必须", "将要", "转折"]), fallback="", limit=6),
        ]
    )[:8]
    scene_anchor = {
        "where_when": _clip(_keyword_excerpt(lines, ["地点", "城市", "房间", "门", "夜", "天", "现场", "走廊", "街", "archive"]), 180)
        or "从 ending_snapshot 的最后场景继续判断。",
        "pov_or_focus": _clip(_keyword_excerpt(lines, ["视角", "主角", "他", "她", "我", "他们", "人物"]), 180) or "延续上一章结尾正在行动或承压的人物焦点。",
        "immediate_pressure": _clip(_keyword_excerpt(lines, ["危机", "压力", "阻力", "冲突", "追", "逃", "威胁", "选择", "决定"]), 180)
        or (last_sentence or "承接上一章结尾的直接后果。"),
    }
    character_state = _list_candidates(_keyword_lines(lines, ["他", "她", "主角", "人物", "状态", "选择", "决定", "意识到", "受伤", "拿到", "失去"]), fallback="", limit=8)
    relationship_state = _list_candidates(_keyword_lines(lines, ["关系", "信任", "误解", "同盟", "敌意", "靠近", "背叛", "保护"]), fallback="", limit=6)
    worldbuilding_facts = _list_candidates(_keyword_lines(lines, ["规则", "设定", "城市", "组织", "地点", "世界", "制度", "能力", "物品"]), fallback="", limit=6)
    continuation_requirements = _unique_texts(
        [
            f"Next visible position: Volume {next_volume} Chapter {next_chapter}" if next_volume and next_chapter else "",
            f"下一章开头必须直接承接上一章最后一句：{last_sentence}" if last_sentence else "下一章开头必须承接上一章结尾的直接后果。",
            "延续上一章结尾的时间、地点、人物目标、情绪余波和风险压力；如需跳时空，先给出清楚过渡。",
            "先处理 ending_snapshot 中尚未完成的动作或反应，再推进新事件。",
            *_list_candidates(_keyword_lines(lines, ["不要忘", "记住", "承接", "连续", "伏笔", "状态", "下一章"]), fallback="", limit=6),
            *open_threads[:4],
        ]
    )
    data = {
        "card_purpose": "ChapterHandoff",
        "source_position": {
            "volume_index": payload.volume_index,
            "volume_title": payload.volume_title,
            "chapter_index": payload.chapter_index,
            "chapter_title": payload.chapter_title,
        },
        "target_position": {
            "volume_index": next_volume,
            "chapter_index": next_chapter,
        },
        "chapter_summary": _clip(_first_text_block(lines, payload.content), 420),
        "ending_snapshot": ending or "待从已确认正文结尾承接。",
        "last_sentence": last_sentence,
        "scene_anchor": scene_anchor,
        "ending_state": {
            "visible_situation": "见 ending_snapshot。" if ending else "待从已确认正文结尾承接。",
            "immediate_pressure": scene_anchor["immediate_pressure"],
            "emotional_aftertaste": _clip(_keyword_excerpt(lines, ["情绪", "恐惧", "愤怒", "期待", "爽点", "余波", "沉默", "震惊"]), 180)
            or "延续上一章章尾情绪，不要重置为平静开场。",
        },
        "character_state_delta": character_state,
        "relationship_delta": relationship_state,
        "new_worldbuilding_facts": worldbuilding_facts,
        "active_foreshadowing": _list_candidates(_keyword_lines(lines, ["伏笔", "悬念", "秘密", "异常", "疑问", "尚未", "未解"]), fallback="", limit=6),
        "open_threads": open_threads,
        "resolved_items": _list_candidates(_keyword_lines(lines, ["解决", "完成", "确认", "明白", "结束"]), fallback="", limit=5),
        "next_chapter_hooks": _list_candidates(_keyword_lines(lines, ["下一章", "章尾", "钩子", "继续", "必须", "将要", "转折"]), fallback=_clip(last_sentence or ending, 180), limit=6),
        "must_continue": continuation_requirements[:6],
        "do_not_reset": [
            "不得把下一章写成全新的无关开头。",
            "不得重新介绍已经在上一章完成交代的人物、地点或目标。",
            "不得无解释跳过上一章最后一句造成的动作后果、情绪余波或危险压力。",
            "不得让已受伤、已获得、已失去、已暴露或已承诺的状态凭空消失。",
        ],
        "continuity_requirements": continuation_requirements[:8],
        "do_not_forget": _unique_texts(
            [
                *continuation_requirements[:4],
                *character_state[:4],
                *relationship_state[:3],
                *worldbuilding_facts[:3],
            ]
        ),
        "handoff_prompt": _clip(
            "下一章必须从上一章章尾的直接后果写起。"
            f"上一章最后一句：{last_sentence or '见 ending_snapshot'}。"
            "先回应人物反应、风险变化和未解线索，再开启新的场景推进。",
            450,
        ),
    }
    return json.dumps(data, ensure_ascii=False, indent=2)

def _refresh_volume_continuity_memory(
    db: Session,
    knowledge_base: KnowledgeBase,
    workspace_id: str,
    volume_index: int | None,
) -> WritingMemory | None:
    if not volume_index:
        return None
    existing = _auto_volume_continuity_memory(db, knowledge_base.id, workspace_id, volume_index)
    handoffs = _latest_volume_handoff_memories(db, knowledge_base.id, workspace_id, volume_index)
    if not handoffs:
        if existing:
            card = (
                db.query(KnowledgeCard)
                .filter(KnowledgeCard.knowledge_base_id == knowledge_base.id, KnowledgeCard.card_id == f"MEM-{existing.id:03d}")
                .first()
            )
            if card:
                _safe_delete_card_vector(card)
                delete_card_physical(db, knowledge_base, card)
            _safe_delete_memory_vector(existing)
            db.delete(existing)
            db.commit()
        return None

    latest_chapter = max((memory.chapter_index or 0) for memory in handoffs)
    source_ref = {
        "source": AUTO_VOLUME_CONTINUITY_SOURCE,
        "volume_index": volume_index,
        "latest_chapter_index": latest_chapter,
        "handoff_memory_ids": [memory.id for memory in handoffs],
    }
    content = _volume_continuity_memory_content(handoffs, volume_index=volume_index)
    tags = _unique_texts(["volume_summary", "volume_continuity", "continuity", "auto", "approved"])
    volume_title = next((memory.volume_title for memory in handoffs if memory.volume_title), None)
    if existing:
        existing.title = _volume_continuity_title(volume_index)
        existing.content = content
        existing.tags_json = json.dumps(tags, ensure_ascii=False)
        existing.source_ref_json = json.dumps(source_ref, ensure_ascii=False)
        existing.source = AUTO_VOLUME_CONTINUITY_SOURCE
        existing.scope_level = "volume"
        existing.volume_index = volume_index
        existing.volume_title = volume_title or existing.volume_title
        existing.chapter_index = None
        existing.chapter_title = None
        existing.valid_from_volume_index = volume_index
        existing.valid_from_chapter_index = latest_chapter + 1
        existing.valid_until_volume_index = None
        existing.valid_until_chapter_index = None
        existing.reveal_at_volume_index = volume_index
        existing.reveal_at_chapter_index = latest_chapter + 1
        existing.retrievable = True
        existing.priority = max(existing.priority or 0, 95)
        db.commit()
        db.refresh(existing)
        card = sync_memory_card(db, knowledge_base, existing)
        _safe_index_memory(db, existing)
        _safe_index_card(db, card)
        db.refresh(existing)
        return existing

    return _create_memory_record(
        db,
        knowledge_base,
        workspace_id=workspace_id,
        memory_type="volume_summary",
        title=_volume_continuity_title(volume_index),
        content=content,
        tags=tags,
        source_ref=source_ref,
        source=AUTO_VOLUME_CONTINUITY_SOURCE,
        scope_level="volume",
        volume_index=volume_index,
        volume_title=volume_title,
        chapter_index=None,
        valid_from_volume_index=volume_index,
        valid_from_chapter_index=latest_chapter + 1,
        reveal_at_volume_index=volume_index,
        reveal_at_chapter_index=latest_chapter + 1,
        retrievable=True,
        priority=95,
    )

def _auto_volume_continuity_memory(db: Session, knowledge_base_id: int, workspace_id: str, volume_index: int) -> WritingMemory | None:
    return (
        db.query(WritingMemory)
        .filter(
            WritingMemory.workspace_id == workspace_id,
            WritingMemory.knowledge_base_id == knowledge_base_id,
            WritingMemory.memory_type == "volume_summary",
            WritingMemory.source == AUTO_VOLUME_CONTINUITY_SOURCE,
            WritingMemory.volume_index == volume_index,
        )
        .first()
    )

def _latest_volume_handoff_memories(db: Session, knowledge_base_id: int, workspace_id: str, volume_index: int) -> list[WritingMemory]:
    memories = (
        db.query(WritingMemory)
        .filter(
            WritingMemory.workspace_id == workspace_id,
            WritingMemory.knowledge_base_id == knowledge_base_id,
            WritingMemory.memory_type == "ChapterHandoff",
            WritingMemory.volume_index == volume_index,
        )
        .order_by(WritingMemory.updated_at.desc(), WritingMemory.id.desc())
        .all()
    )
    latest_by_chapter: dict[int, WritingMemory] = {}
    for memory in memories:
        if not memory.chapter_index:
            continue
        latest_by_chapter.setdefault(memory.chapter_index, memory)
    return sorted(latest_by_chapter.values(), key=lambda item: (item.chapter_index or 0, item.id))

def _volume_continuity_title(volume_index: int) -> str:
    return f"Volume {volume_index} Continuity"

def _volume_continuity_memory_content(handoffs: list[WritingMemory], *, volume_index: int) -> str:
    chain: list[dict[str, Any]] = []
    open_threads: list[str] = []
    character_state: list[str] = []
    relationship_state: list[str] = []
    worldbuilding_facts: list[str] = []
    continuity_requirements: list[str] = []
    for memory in handoffs:
        data = _json_object_text(memory.content)
        chain.append(
            {
                "chapter_index": memory.chapter_index,
                "chapter_title": memory.chapter_title,
                "handoff_memory_id": memory.id,
                "last_sentence": _clip(_json_scalar_text(data.get("last_sentence")), 180),
                "ending_snapshot": _clip(_json_scalar_text(data.get("ending_snapshot")), 260),
                "must_continue": _json_list_values(data.get("must_continue") or data.get("continuity_requirements"), limit=3, max_chars=180),
                "open_threads": _json_list_values(data.get("open_threads") or data.get("active_foreshadowing"), limit=3, max_chars=160),
            }
        )
        open_threads.extend(_json_list_values(data.get("open_threads") or data.get("active_foreshadowing"), limit=6, max_chars=180))
        character_state.extend(_json_list_values(data.get("character_state_delta"), limit=6, max_chars=180))
        relationship_state.extend(_json_list_values(data.get("relationship_delta"), limit=5, max_chars=180))
        worldbuilding_facts.extend(_json_list_values(data.get("new_worldbuilding_facts"), limit=5, max_chars=180))
        continuity_requirements.extend(_json_list_values(data.get("continuity_requirements") or data.get("must_continue"), limit=5, max_chars=200))

    latest_chapter = max((memory.chapter_index or 0) for memory in handoffs)
    data = {
        "card_purpose": "VolumeContinuity",
        "volume_index": volume_index,
        "updated_through_chapter_index": latest_chapter,
        "chapter_handoff_count": len(handoffs),
        "continuity_chain": chain,
        "active_open_threads": _unique_texts(open_threads)[:30],
        "character_state_rollup": _unique_texts(character_state)[:30],
        "relationship_state_rollup": _unique_texts(relationship_state)[:24],
        "worldbuilding_rollup": _unique_texts(worldbuilding_facts)[:24],
        "volume_continuity_requirements": _unique_texts(
            [
                f"本卷后续章节必须承接第 1 章到第 {latest_chapter} 章已经确认的因果链、人物状态、伏笔和情绪余波。",
                "不得只承接上一章而忽略本卷早前已经建立的承诺、伤势、物品、关系变化和未解问题。",
                "如果要跨场景或跳时间，必须交代从已确认章节链到新场景之间的因果过渡。",
                *_unique_texts(continuity_requirements)[:24],
            ]
        )[:30],
        "do_not_reset": [
            "不得让本卷早前已经确认的状态在后续章节中无解释消失。",
            "不得把后续章节写成与本卷前文因果链无关的独立开头。",
            "不得重复介绍已经完成铺垫的核心人物、地点、规则和目标。",
        ],
    }
    return json.dumps(data, ensure_ascii=False, indent=2)

def _matches_writing_scope(
    volume_index: int | None,
    chapter_index: int | None,
    volume_indices: set[int],
    chapter_refs: set[tuple[int, int]],
) -> bool:
    if volume_index is None:
        return False
    if volume_index in volume_indices:
        return True
    if chapter_index is None:
        return False
    return (volume_index, chapter_index) in chapter_refs

def _delete_memories_and_cards(db: Session, workspace_id: str, memories: list[WritingMemory]) -> dict[str, int]:
    deleted_memories = 0
    deleted_cards = 0
    deleted_files = 0
    kb_cache: dict[int, KnowledgeBase] = {}
    for memory in memories:
        kb = kb_cache.get(memory.knowledge_base_id)
        if not kb:
            kb = _ensure_workspace_kb(db, workspace_id, memory.knowledge_base_id)
            kb_cache[memory.knowledge_base_id] = kb
        card = (
            db.query(KnowledgeCard)
            .filter(KnowledgeCard.knowledge_base_id == memory.knowledge_base_id, KnowledgeCard.card_id == f"MEM-{memory.id:03d}")
            .first()
        )
        if card:
            _safe_delete_card_vector(card)
            if delete_card_physical(db, kb, card):
                deleted_files += 1
            deleted_cards += 1
        _safe_delete_memory_vector(memory)
        db.delete(memory)
        deleted_memories += 1
    return {"memories": deleted_memories, "cards": deleted_cards, "files": deleted_files}

