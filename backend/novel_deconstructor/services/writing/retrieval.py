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
    BLOCKED_STATUSES,
    RETRIEVABLE_STATUSES,
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
from .common import *

__all__ = [
    "_augment_results_with_priority_context",
    "_build_card_agent_prompt",
    "_build_structured_card_agent_prompt",
    "_card_agent_prompt",
    "_card_scope_label",
    "_cards_for_search_results",
    "_format_card_context",
    "_format_handoff_context",
    "_format_used_knowledge",
    "_is_broad_outline_request",
    "_is_current_chapter_card",
    "_merge_retrieval_debug",
    "_merge_used_knowledge",
    "_normalized_scope_level",
    "_outline_output_rule",
    "_outline_scope_block",
    "_outline_scope_kind",
    "_position_after",
    "_position_before",
    "_priority_context_buckets",
    "_priority_context_sort_key",
    "_prompt_card_filter_reason",
    "_prompt_cards_for_results",
    "_prompt_safe_cards",
    "_prompt_scope_filter_reason",
    "_result_from_card",
    "_results_for_prompt_cards",
    "_retrieval_queries",
    "_retrieve_for_agent_task",
    "_retrieve_for_card_agent",
]

def _retrieve_for_card_agent(
    db: Session,
    knowledge_base: KnowledgeBase,
    payload: WritingGenerateRequest,
    *,
    stage: str,
    query: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    settings = get_settings()
    try:
        retrieval = retrieve_for_writing(
            db,
            workspace_id=knowledge_base.workspace_id,
            knowledge_base_ids=[knowledge_base.id],
            query=query,
            phase=stage,
            target_volume_index=payload.current_volume_index,
            target_chapter_index=payload.current_chapter_index,
            top_k=payload.top_k or settings.retrieval_top_k,
            include_future=payload.include_future_knowledge,
            include_raw=payload.include_raw_knowledge,
        )
        debug = retrieval["retrieval_debug"]
        card_results = [hit for hit in retrieval["hits"] if hit.get("source_type") == "card"]
        non_card_count = len(retrieval["hits"]) - len(card_results)
        if non_card_count:
            debug.setdefault("warnings", []).append(f"non_card_hits_available:{non_card_count}")
        return card_results, debug
    except Exception as exc:  # noqa: BLE001 - keep writing agent available if the new service regresses.
        results, debug = search_rag_cards(
            db,
            [knowledge_base.id],
            stage=stage,
            query=query,
            top_k=payload.top_k or settings.retrieval_top_k,
            current_volume_index=payload.current_volume_index,
            current_chapter_index=payload.current_chapter_index,
            include_future=payload.include_future_knowledge,
            include_raw=payload.include_raw_knowledge,
        )
        debug["mode"] = "keyword"
        debug["effective_mode"] = "keyword"
        debug["fallback"] = f"retrieval_service_error:{type(exc).__name__}:{exc}"
        debug.setdefault("warnings", []).append("new_retrieval_service_failed")
        return results, debug

def _augment_results_with_priority_context(
    db: Session,
    knowledge_base_id: int,
    results: list[dict[str, Any]],
    payload: WritingGenerateRequest,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    warnings = debug.setdefault("warnings", [])
    if payload.current_volume_index is None or payload.current_chapter_index is None:
        warning = "missing_current_writing_position: only global writing_guide is safe; fill Volume and Chapter for scoped memory"
        if warning not in warnings:
            warnings.append(warning)
        return results

    existing_ids = {item["id"] for item in results}
    cards = (
        db.query(KnowledgeCard)
        .filter(
            KnowledgeCard.knowledge_base_id == knowledge_base_id,
            KnowledgeCard.library_type == "memory",
            KnowledgeCard.card_type.in_(FORCED_CONTEXT_CARD_TYPES),
        )
        .all()
    )
    safe_cards = [card for card in cards if _prompt_card_filter_reason(card, payload) is None]
    buckets = _priority_context_buckets(safe_cards, payload)
    ordered_cards = [
        *buckets["current_outline"][:3],
        *buckets["previous_handoff"][:6],
        *buckets["character_state"][:6],
        *buckets["relationship_state"][:6],
        *buckets["foreshadowing"][:6],
        *buckets["volume_summary"][:3],
    ]

    forced_results: list[dict[str, Any]] = []
    forced_ids: list[str] = []
    for index, card in enumerate(ordered_cards):
        if card.card_id in existing_ids:
            continue
        forced_results.append(_result_from_card(card, 120 - index))
        forced_ids.append(card.card_id)
        existing_ids.add(card.card_id)

    if forced_ids:
        selected_ids = [*forced_ids, *debug.get("selected_card_ids", [])]
        debug["selected_card_ids"] = list(dict.fromkeys(selected_ids))
        selected_scope = dict(debug.get("selected_card_scope", {}))
        selected_scope.update({card.card_id: _card_scope_label(card) for card in ordered_cards if card.card_id in forced_ids})
        debug["selected_card_scope"] = selected_scope
        pinned = [*forced_ids, *debug.get("selected_pinned_context", [])]
        debug["selected_pinned_context"] = list(dict.fromkeys(pinned))
        debug["selected_count"] = len(debug["selected_card_ids"])
        warning = f"forced_priority_context:{','.join(forced_ids)}"
        if warning not in warnings:
            warnings.append(warning)
    return [*forced_results, *results]

def _priority_context_buckets(cards: list[KnowledgeCard], payload: WritingGenerateRequest) -> dict[str, list[KnowledgeCard]]:
    buckets = {
        "current_outline": [],
        "previous_handoff": [],
        "character_state": [],
        "relationship_state": [],
        "foreshadowing": [],
        "volume_summary": [],
    }
    for card in cards:
        if card.card_type == "ChapterOutline":
            if _is_current_chapter_card(card, payload):
                buckets["current_outline"].append(card)
            continue
        if card.card_type == "ChapterHandoff":
            buckets["previous_handoff"].append(card)
            continue
        if card.card_type in buckets:
            buckets[card.card_type].append(card)

    for key, value in buckets.items():
        reverse = key != "current_outline"
        value.sort(key=_priority_context_sort_key, reverse=reverse)
    return buckets

def _priority_context_sort_key(card: KnowledgeCard) -> tuple[int, int, int, datetime]:
    return (
        card.volume_index or 0,
        card.chapter_index or 0,
        card.priority or 0,
        card.updated_at or card.created_at or datetime.min,
    )

def _result_from_card(card: KnowledgeCard, score: float) -> dict[str, Any]:
    return {
        "id": card.card_id,
        "library_type": card.library_type,
        "card_type": card.card_type,
        "title": card.title,
        "score": round(score, 4),
        "source_ref": _json_dict_text(card.source_ref_json),
        "content_preview": _clip(card.content, 320),
        "tags": _json_list_text(card.tags_json),
        "status": card.status,
        "retrieval_level": getattr(card, "retrieval_level", "primary") or "primary",
        "context_role": getattr(card, "context_role", "auxiliary") or "auxiliary",
        "scope_level": card.scope_level or "global",
        "volume_index": card.volume_index,
        "chapter_index": card.chapter_index,
    }

def _card_scope_label(card: KnowledgeCard) -> str:
    scope_level = _normalized_scope_level(card)
    if scope_level == "global":
        return "global"
    if scope_level == "volume":
        return f"volume:{card.volume_index}" if card.volume_index is not None else "volume:unknown"
    volume = card.volume_index if card.volume_index is not None else "unknown"
    chapter = card.chapter_index if card.chapter_index is not None else "unknown"
    return f"chapter:{volume}/{chapter}"

def _prompt_cards_for_results(
    db: Session,
    knowledge_base_id: int,
    results: list[dict[str, Any]],
    *,
    payload: WritingGenerateRequest | None = None,
    debug: dict[str, Any] | None = None,
) -> tuple[list[KnowledgeCard], list[dict[str, Any]]]:
    prompt_results = results[:RAG_PROMPT_CARD_LIMIT]
    cards = _cards_for_search_results(db, knowledge_base_id, prompt_results)
    if payload is not None:
        cards, prompt_results = _prompt_safe_cards(cards, prompt_results, payload, debug)
    return cards, _results_for_prompt_cards(prompt_results, cards)

def _prompt_safe_cards(
    cards: list[KnowledgeCard],
    prompt_results: list[dict[str, Any]],
    payload: WritingGenerateRequest,
    debug: dict[str, Any] | None,
) -> tuple[list[KnowledgeCard], list[dict[str, Any]]]:
    results_by_id = {item["id"]: item for item in prompt_results}
    safe_cards: list[KnowledgeCard] = []
    warnings: list[str] = []
    for card in cards:
        reason = _prompt_card_filter_reason(card, payload)
        if reason:
            warnings.append(f"prompt_dropped:{card.card_id}:{reason}")
            continue
        safe_cards.append(card)

    safe_ids = {card.card_id for card in safe_cards}
    safe_results = [results_by_id[card.card_id] for card in safe_cards if card.card_id in results_by_id]
    if debug is not None:
        debug["selected_card_ids"] = [card.card_id for card in safe_cards]
        debug["selected_card_scope"] = {
            card_id: scope
            for card_id, scope in debug.get("selected_card_scope", {}).items()
            if card_id in safe_ids
        }
        debug["selected_count"] = len(safe_cards)
        if warnings:
            existing_warnings = debug.setdefault("warnings", [])
            for warning in warnings:
                if warning not in existing_warnings:
                    existing_warnings.append(warning)
    return safe_cards, safe_results

def _prompt_card_filter_reason(card: KnowledgeCard, payload: WritingGenerateRequest) -> str | None:
    if card.status in BLOCKED_STATUSES:
        return "blocked_status"
    if card.status == "raw_extracted":
        if not (payload.include_raw_knowledge and payload.dry_run):
            return "raw_debug_only"
    elif not bool(card.retrievable):
        return "not_retrievable"
    elif card.status not in RETRIEVABLE_STATUSES:
        return "inactive_status"
    if not bool(card.is_canonical) and not (card.status == "raw_extracted" and payload.include_raw_knowledge and payload.dry_run):
        return "not_canonical"

    current_volume = payload.current_volume_index
    current_chapter = payload.current_chapter_index
    if current_volume is None or current_chapter is None:
        if card.library_type == "writing_guide" and _normalized_scope_level(card) == "global":
            return None
        return "missing_position_scope"

    return _prompt_scope_filter_reason(card, current_volume, current_chapter)

def _prompt_scope_filter_reason(card: KnowledgeCard, current_volume: int, current_chapter: int) -> str | None:
    if _position_after(card.reveal_at_volume_index, card.reveal_at_chapter_index, current_volume, current_chapter):
        return "future_reveal"
    if _position_after(card.valid_from_volume_index, card.valid_from_chapter_index, current_volume, current_chapter):
        return "future_valid_from"
    if _position_before(card.valid_until_volume_index, card.valid_until_chapter_index, current_volume, current_chapter):
        return "expired_scope"
    if _position_after(card.volume_index, card.chapter_index, current_volume, current_chapter):
        return "future_position"

    scope_level = _normalized_scope_level(card)
    if scope_level == "global":
        return None
    if scope_level == "volume":
        if card.volume_index is None:
            return "unknown_volume_scope"
        if card.volume_index > current_volume:
            return "future_volume"
        return None if card.volume_index == current_volume else "past_volume_scope"
    if card.volume_index is None or card.chapter_index is None:
        return "unknown_chapter_scope"
    if card.library_type == "memory":
        if card.volume_index < current_volume:
            return None
        if card.volume_index == current_volume and card.chapter_index <= current_chapter:
            return None
        return "future_chapter"
    if card.volume_index == current_volume:
        if card.chapter_index > current_chapter:
            return "future_chapter"
        return None if card.chapter_index == current_chapter else "past_chapter_scope"
    return "future_chapter"

def _position_after(
    volume_index: int | None,
    chapter_index: int | None,
    current_volume: int,
    current_chapter: int,
) -> bool:
    if volume_index is None and chapter_index is None:
        return False
    compare_volume = current_volume if volume_index is None else volume_index
    compare_chapter = 0 if chapter_index is None else chapter_index
    return (compare_volume, compare_chapter) > (current_volume, current_chapter)

def _position_before(
    volume_index: int | None,
    chapter_index: int | None,
    current_volume: int,
    current_chapter: int,
) -> bool:
    if volume_index is None and chapter_index is None:
        return False
    compare_volume = current_volume if volume_index is None else volume_index
    compare_chapter = 999999 if chapter_index is None else chapter_index
    return (compare_volume, compare_chapter) < (current_volume, current_chapter)

def _normalized_scope_level(card: KnowledgeCard) -> str:
    value = (card.scope_level or "global").strip().lower()
    if value == "book":
        return "global"
    return value if value in {"global", "volume", "chapter"} else "global"

def _cards_for_search_results(db: Session, knowledge_base_id: int, results: list[dict[str, Any]]) -> list[KnowledgeCard]:
    ids = [item["id"] for item in results]
    if not ids:
        return []
    cards = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == knowledge_base_id, KnowledgeCard.card_id.in_(ids))
        .all()
    )
    by_id = {card.card_id: card for card in cards}
    return [by_id[card_id] for card_id in ids if card_id in by_id]

def _results_for_prompt_cards(results: list[dict[str, Any]], cards: list[KnowledgeCard]) -> list[dict[str, Any]]:
    prompt_card_ids = {card.card_id for card in cards}
    return [item for item in results if item["id"] in prompt_card_ids]

def _card_agent_prompt(
    stage: str,
    payload: WritingGenerateRequest,
    cards: list[KnowledgeCard],
    confirmed_outline: str,
) -> str:
    worldbuilding = [card for card in cards if card.library_type == "worldbuilding"]
    memory = [card for card in cards if card.library_type == "memory"]
    anti_patterns = [card for card in cards if card.card_type == "anti_pattern"]
    writing_guide = [card for card in cards if card.library_type == "writing_guide" and card.card_type != "anti_pattern"]
    output_rule = (
        "只输出章节提纲，不要写正文。提纲要能直接进入下一步正文生成。"
        if stage == "outline"
        else "只输出小说正文，不要输出提纲、表格、写作说明或引用编号。"
    )
    return f"""[STORY FACTS / WORLDBUILDING]
这里放用户确认的原创世界观、人物、地点、规则。这是硬约束，不允许随意改写。
{_format_card_context(worldbuilding) or "未检索到用户确认的 worldbuilding。不要沿用拆书来源作品的世界观、人物、势力、地名或专名。"}

[PROJECT MEMORY]
这里放已确认提纲、上一章结尾、人物状态、伏笔、连续性备注。这是当前作品连续性约束。
{_format_card_context(memory) or "暂无可用 memory。"}

[WRITING GUIDE]
这里放拆书提取出的写作技巧、结构、冲突、情绪链、节奏、语言规则。这些只指导写法，不是故事事实。
{_format_card_context(writing_guide) or "未检索到 writing_guide。"}

[ANTI PATTERNS]
这里放不建议模仿的写法，例如 AI 味、解释腔、机械对白、硬讲设定。
{_format_card_context(anti_patterns) or "暂无 anti_pattern。"}

[CONFIRMED OUTLINE]
{confirmed_outline or "（空）"}

[CURRENT CONTEXT]
{payload.current_content or "（空）"}

[USER REQUEST]
{payload.task}

[OUTPUT RULES]
- {output_rule}
- writing_guide 只能作为写法参考，不能复制来源作品的人名、地名、专名、势力、世界观和标志性桥段。
- worldbuilding 和 memory 的优先级高于 writing_guide。
- 如果 writing_guide 与当前 worldbuilding / memory 冲突，以当前 worldbuilding / memory 为准。
- 生成结果应尽量体现召回知识中的结构、冲突、情绪链和反模式约束。
"""

def _build_card_agent_prompt(
    stage: str,
    payload: WritingGenerateRequest,
    cards: list[KnowledgeCard],
    confirmed_outline: str,
) -> str:
    return _build_structured_card_agent_prompt(stage, payload, cards, confirmed_outline)

def _outline_scope_kind(payload: WritingGenerateRequest) -> str:
    scope = (payload.scope_level or "chapter").strip().lower()
    if scope in {"global", "book"}:
        return "global"
    if scope == "volume":
        return "volume"
    return "global" if _is_broad_outline_request(payload) else "chapter"

def _is_broad_outline_request(payload: WritingGenerateRequest) -> bool:
    text = f"{payload.task}\n{payload.current_content}".lower()
    broad_keywords = [
        "全书",
        "整本",
        "整部",
        "整个作品",
        "多卷",
        "三卷",
        "3卷",
        "卷末",
        "每卷",
        "每章",
        "章节列表",
        "章节目录",
        "分卷",
        "volume",
        "volumes",
        "full novel",
        "novel outline",
        "chapter list",
    ]
    if any(keyword in text for keyword in broad_keywords):
        return True
    return bool(re.search(r"长篇.{0,12}(?:大纲|提纲|结构|规划|章节目录|章节列表)", text))

def _outline_output_rule(payload: WritingGenerateRequest) -> str:
    scope = _outline_scope_kind(payload)
    if scope == "global":
        return (
            "Output the complete novel outline requested by the user, not just the current chapter. "
            "Do not title the response as a single chapter outline such as '# ...第1章...大纲'. "
            "If the request asks for multi-volume structure, include the volume architecture, each volume's theme/conflict/relationship progress/worldbuilding progress/end hook, "
            "and per-chapter entries with function, summary, conflict, relationship progress, worldbuilding keywords, state-change cause-effect chain, and ending hook. "
            "Do not write prose; make the outline directly usable for later chapter-by-chapter draft generation."
        )
    if scope == "volume":
        return (
            "Only output the current-volume outline. Include the volume's theme, main conflict, relationship progress, "
            "worldbuilding progress, ending hook, and per-chapter entries. Do not write prose yet."
        )
    return "Only output a current-chapter outline. Do not write prose yet. The outline must be directly usable for draft generation."

def _outline_scope_block(payload: WritingGenerateRequest) -> str:
    scope = _outline_scope_kind(payload)
    if scope == "global":
        return """[OUTLINE SCOPE OVERRIDE]
Scope: FULL_NOVEL_OR_MULTI_VOLUME.
- The user's request is for full-story planning, not the current chapter.
- Current volume/chapter metadata is only UI context and must not restrict the output.
- Start with the full novel architecture: at least three volumes, then chapter entries under each volume.
- Include the requested golden three chapters as explicit early chapter entries.
- A single-chapter outline is invalid for this request."""
    if scope == "volume":
        return """[OUTLINE SCOPE]
Scope: CURRENT_VOLUME.
- The user's request is for the current volume outline.
- Use the current volume metadata as the target range.
- Do not expand into a full-novel outline unless the user changes the outline scope to full book."""
    return """[OUTLINE SCOPE]
Scope: CURRENT_CHAPTER.
- The user's request is for the current chapter outline.
- Do not expand into full-story, multi-volume, or chapter-list planning just because the task references a long-form writing guide."""

def _build_structured_card_agent_prompt(
    stage: str,
    payload: WritingGenerateRequest,
    cards: list[KnowledgeCard],
    confirmed_outline: str,
) -> str:
    worldbuilding = [card for card in cards if card.library_type == "worldbuilding"]
    memory = [card for card in cards if card.library_type == "memory"]
    book_outlines = [card for card in memory if card.card_type == OUTLINE_CARD_TYPE_BOOK]
    volume_outlines = [card for card in memory if card.card_type == OUTLINE_CARD_TYPE_VOLUME]
    previous_handoff = [card for card in memory if card.card_type == "ChapterHandoff"]
    current_outline = [card for card in memory if card.card_type == "ChapterOutline" and _is_current_chapter_card(card, payload)]
    character_states = [card for card in memory if card.card_type == "character_state"]
    relationship_states = [card for card in memory if card.card_type == "relationship_state"]
    foreshadowing = [card for card in memory if card.card_type == "foreshadowing"]
    volume_summaries = [card for card in memory if card.card_type == "volume_summary"]
    classified_memory_ids = {
        card.card_id
        for card in [*book_outlines, *volume_outlines, *previous_handoff, *current_outline, *character_states, *relationship_states, *foreshadowing, *volume_summaries]
    }
    other_memory = [card for card in memory if card.card_id not in classified_memory_ids]
    anti_patterns = [card for card in cards if card.card_type == "anti_pattern"]
    writing_guide = [card for card in cards if card.library_type == "writing_guide" and card.card_type != "anti_pattern"]
    output_rule = {
        "outline": _outline_output_rule(payload),
        "draft": "Only output novel prose. Do not output outlines, tables, writing notes, retrieval notes, or citation IDs.",
        "revision": "Only output the revised prose. Do not output revision notes, lists, tables, or citation IDs.",
    }.get(stage, "Only output the content requested by the current task. Do not output retrieval notes, writing notes, or citation IDs.")
    target_chars = payload.target_chars if payload.target_chars else "UNSPECIFIED"
    raw_policy = "enabled for explicit debug mode" if payload.include_raw_knowledge else "disabled"
    future_policy = "explicitly requested, but prompt input is still safety-filtered" if payload.include_future_knowledge else "disabled"
    return f"""[CURRENT WRITING POSITION]
Current volume: {_position_value(payload.current_volume_index)}
Current chapter: {_position_value(payload.current_chapter_index)}

{_outline_scope_block(payload) if stage == "outline" else ""}

[RETRIEVAL POLICY]
- Use only global knowledge, current/prior volume knowledge, and chapters up to the current writing position.
- Do not use future volume or future chapter knowledge.
- Raw Evidence is {raw_policy}; future knowledge is {future_policy}.
- Treat writing_guide as technique, not story fact. Story facts and memory override writing_guide.

[STORY FACTS / WORLDBUILDING]
User-confirmed original characters, places, factions, rules, and worldbuilding. These are hard constraints.
{_format_card_context(worldbuilding) or "No user-confirmed worldbuilding was retrieved. Do not borrow names, places, factions, or unique settings from source works."}

[PREVIOUS CHAPTER HANDOFF]
Continuity cards from already confirmed chapters. Treat every HANDOFF CONTINUITY LOCK as a hard next-chapter constraint, not optional inspiration.
{_format_handoff_context(previous_handoff) or "No previous chapter handoff was retrieved."}

[CURRENT CHAPTER OUTLINE]
The approved outline memory for the current chapter, when available.
{_format_card_context(current_outline) or "No approved ChapterOutline card matched the current chapter."}

[ACTIVE CHARACTER STATES]
Current character state memory that is visible at this writing position.
{_format_card_context(character_states) or "No character_state memory was retrieved."}

[ACTIVE RELATIONSHIP STATES]
Current relationship state memory that is visible at this writing position.
{_format_card_context(relationship_states) or "No relationship_state memory was retrieved."}

[ACTIVE FORESHADOWING]
Visible foreshadowing and unresolved setup that should be preserved or paid off.
{_format_card_context(foreshadowing) or "No foreshadowing memory was retrieved."}

[CURRENT VOLUME SUMMARY]
Approved cumulative continuity memory for the current volume and prior visible volume context. Use it to preserve the work's running cause-effect chain, not just the immediately previous chapter.
{_format_card_context(volume_summaries) or "No volume_summary memory was retrieved."}

[BOOK OUTLINE]
The auto-generated full-novel outline based on all imported knowledge cards. Use this as the high-level structural framework for the entire work.
{_format_card_context(book_outlines) or "No book outline card exists yet. Import knowledge cards to auto-generate one."}

[VOLUME OUTLINES]
Auto-generated per-volume outlines based on knowledge cards scoped to each volume.
{_format_card_context(volume_outlines) or "No volume outline cards exist yet. Import knowledge cards to auto-generate them."}

[PROJECT MEMORY]
Other confirmed continuity memory for this work.
{_format_card_context(other_memory) or "No additional project memory was retrieved."}

[WRITING GUIDE]
Technique, structure, pacing, conflict, emotion chain, language, and style guidance. These guide execution only.
{_format_card_context(writing_guide) or "No writing_guide cards were retrieved."}

[ANTI PATTERNS]
Problems to avoid in this generation.
{_format_card_context(anti_patterns) or "No anti_pattern cards were retrieved."}

[CURRENT TASK]
Stage: {stage}
Target chars: {target_chars}
User request:
{payload.task}

Confirmed outline:
{confirmed_outline or "(empty)"}

Current context:
{payload.current_content or "(empty)"}

[OUTPUT REQUIREMENTS]
- {output_rule}
- Worldbuilding and memory take precedence over writing_guide if there is a conflict.
- If a HANDOFF CONTINUITY LOCK is present, the opening must directly continue its last_sentence or ending_snapshot before introducing a new scene.
- Preserve the handoff's character state, relationship state, unresolved hooks, props, injuries, promises, and emotional aftertaste.
- Preserve the CURRENT VOLUME SUMMARY continuity chain so later chapters do not forget earlier confirmed events, relationships, foreshadowing, and worldbuilding.
- Do not copy source-work names, places, factions, worldbuilding, or signature passages from writing_guide cards.
- Do not expose card names, retrieval process, scores, or citation IDs in the prose.
- Internalize the retrieved rules naturally; do not mechanically restate them."""

def _is_current_chapter_card(card: KnowledgeCard, payload: WritingGenerateRequest) -> bool:
    if payload.current_volume_index is None or payload.current_chapter_index is None:
        return False
    if card.volume_index is not None and card.volume_index != payload.current_volume_index:
        return False
    if card.chapter_index is not None and card.chapter_index != payload.current_chapter_index:
        return False
    return True

def _format_card_context(cards: list[KnowledgeCard]) -> str:
    return "\n\n".join(
        f"[{card.card_id}] {card.library_type}/{card.card_type} | {card.title}\n{_clip(card.content, 1400)}"
        for card in cards
    )

def _format_handoff_context(cards: list[KnowledgeCard]) -> str:
    formatted: list[str] = []
    for card in cards:
        data = _json_object_text(card.content)
        if not data:
            formatted.append(f"[HANDOFF CONTINUITY LOCK] {card.card_id} | {card.title}\n{_clip(card.content, 1400)}")
            continue
        source = _format_handoff_position(data.get("source_position"))
        target = _format_handoff_position(data.get("target_position"))
        formatted.append(
            "\n".join(
                line
                for line in [
                    f"[HANDOFF CONTINUITY LOCK] {card.card_id} | {card.title}",
                    f"Source -> Target: {source} -> {target}",
                    f"Last sentence to continue: {_json_scalar_text(data.get('last_sentence')) or 'See ending snapshot.'}",
                    f"Ending snapshot: {_clip(_json_scalar_text(data.get('ending_snapshot')) or _json_scalar_text(data.get('ending_state')), 1100)}",
                    _format_handoff_list("Must continue", data.get("must_continue") or data.get("continuity_requirements"), limit=8),
                    _format_handoff_list("Do not reset", data.get("do_not_reset"), limit=6),
                    _format_handoff_list("Open threads", data.get("open_threads") or data.get("active_foreshadowing"), limit=6),
                    _format_handoff_list("Character state", data.get("character_state_delta"), limit=6),
                    _format_handoff_list("Relationship state", data.get("relationship_delta"), limit=5),
                    f"Handoff instruction: {_clip(_json_scalar_text(data.get('handoff_prompt')), 700)}" if data.get("handoff_prompt") else "",
                ]
                if line
            )
        )
    return "\n\n".join(formatted)

def _format_used_knowledge(items: list[dict[str, Any]]) -> str:
    return "\n".join(f"- [{item['card_type']}] {item['title']} ({item['id']}, score {item['score']})" for item in items)

def _merge_used_knowledge(target: dict[str, dict[str, Any]], items: list[dict[str, Any]]) -> None:
    for item in items:
        existing = target.get(item["id"])
        if not existing or item.get("score", 0) > existing.get("score", 0):
            target[item["id"]] = item

def _merge_retrieval_debug(target: dict[str, Any], debug: dict[str, Any]) -> None:
    target["total_candidates"] = int(target.get("total_candidates", 0)) + int(debug.get("total_candidates", 0))
    for key in [
        "candidate_count_before_scope_filter",
        "candidate_count_after_scope_filter",
        "candidate_count_after_db_filter",
        "candidate_count_after_status_filter",
        "candidate_count_after_retrieval_level_filter",
        "candidate_count_after_visibility_filter",
        "filtered_by_status_count",
        "filtered_by_scope_count",
        "filtered_by_future_count",
        "raw_cards_excluded_count",
        "secondary_cards_excluded_count",
        "future_cards_excluded_count",
        "duplicate_group_excluded_count",
        "source_cap_excluded_count",
    ]:
        target[key] = int(target.get(key, 0)) + int(debug.get(key, 0))
    target["current_volume_index"] = debug.get("current_volume_index", target.get("current_volume_index"))
    target["current_chapter_index"] = debug.get("current_chapter_index", target.get("current_chapter_index"))
    preferred = [*target.get("preferred_card_types", []), *debug.get("preferred_card_types", [])]
    target["preferred_card_types"] = list(dict.fromkeys(preferred))
    expanded_terms = [*target.get("expanded_terms", []), *debug.get("expanded_terms", [])]
    target["expanded_terms"] = list(dict.fromkeys(expanded_terms))
    selected_ids = [*target.get("selected_card_ids", []), *debug.get("selected_card_ids", [])]
    target["selected_card_ids"] = list(dict.fromkeys(selected_ids))
    warnings = [*target.get("warnings", []), *debug.get("warnings", [])]
    target["warnings"] = list(dict.fromkeys(warnings))
    selected_scope = dict(target.get("selected_card_scope", {}))
    selected_scope.update(debug.get("selected_card_scope", {}))
    target["selected_card_scope"] = selected_scope
    selected_top_k = [*target.get("selected_top_k_cards", []), *debug.get("selected_top_k_cards", [])]
    target["selected_top_k_cards"] = selected_top_k[:RAG_PROMPT_CARD_LIMIT]
    pinned = [*target.get("selected_pinned_context", []), *debug.get("selected_pinned_context", [])]
    target["selected_pinned_context"] = list(dict.fromkeys(pinned))
    target["filtered_duplicate_count"] = int(target.get("filtered_duplicate_count", 0)) + int(debug.get("filtered_duplicate_count", 0))
    buckets = dict(target.get("diversity_buckets", {}))
    for card_type, count in debug.get("diversity_buckets", {}).items():
        buckets[card_type] = int(buckets.get(card_type, 0)) + int(count)
    target["diversity_buckets"] = buckets
    selected_types = dict(target.get("selected_card_type_distribution", {}))
    for card_type, count in debug.get("selected_card_type_distribution", {}).items():
        selected_types[card_type] = int(selected_types.get(card_type, 0)) + int(count)
    target["selected_card_type_distribution"] = selected_types
    selected_scopes = dict(target.get("selected_scope_distribution", {}))
    for scope, count in debug.get("selected_scope_distribution", {}).items():
        selected_scopes[scope] = int(selected_scopes.get(scope, 0)) + int(count)
    target["selected_scope_distribution"] = selected_scopes

def _retrieve_for_agent_task(db: Session, kb_ids: list[int], task_type: str, base_query: str, top_k: int) -> list[dict]:
    queries = _retrieval_queries(task_type, base_query)
    if not queries:
        return search_knowledge(db, kb_ids, base_query, top_k)
    limit = max(1, top_k)
    per_query_limit = max(1, min(4, limit // len(queries) + 1))
    hits: list[dict] = []
    seen: set[str] = set()
    for priority, query in enumerate(queries, start=1):
        for hit in search_knowledge(db, kb_ids, query, per_query_limit):
            chunk_id = hit.get("chunk_id")
            if not chunk_id or chunk_id in seen:
                continue
            enriched = dict(hit)
            enriched["retrieval_task"] = task_type
            enriched["retrieval_priority"] = priority
            hits.append(enriched)
            seen.add(chunk_id)
            if len(hits) >= limit:
                return hits
    return hits

def _retrieval_queries(task_type: str, base_query: str) -> list[str]:
    query = (base_query or "").strip()
    if not query:
        return []
    protocol = {
        "outline": [
            "章节结构 状态变化 章尾钩子 structure pattern",
            "冲突推进 冲突升级 conflict pattern",
            "情绪链 爽点循环 emotion module",
            "世界观 设定 人物 地点 规则 worldbuilding",
            "长期 Memory 已确认提纲 人物状态 伏笔",
        ],
        "draft": [
            "语言风格 句式 对话 动作 心理描写 style pattern dialogue rule",
            "情绪链 爽点循环 可复现模块 emotion module",
            "不建议模仿 AI味 反模式 anti pattern",
            "世界观 设定 人物 地点 规则 worldbuilding",
            "长期 Memory 上一章结尾 人物状态 伏笔",
        ],
        "worldbuilding_draft": [
            "写作技巧指南 黄金三章 结构 规则 writing guide",
            "冲突推进 信息投放 情绪链 可复现模块",
            "不建议照搬 专名 世界观 独特设定 反模式",
        ],
        "worldbuilding_check": [
            "世界观 设定 人物 地点 规则 worldbuilding",
            "长期 Memory 已确认事实 连续性 伏笔",
        ],
        "revision": [
            "语言风格 句式 对话 节奏 润色",
            "AI味 不建议模仿 反模式 anti pattern",
            "用户偏好 Memory 已确认要求",
        ],
        "continuation": [
            "长期 Memory 上一章结尾 人物状态 伏笔",
            "章节结构 章尾牵引 续写",
            "写作技巧指南 冲突推进 情绪链",
        ],
    }
    suffixes = protocol.get(task_type, [])
    return [f"{query}\n{suffix}" for suffix in suffixes] or [query]

