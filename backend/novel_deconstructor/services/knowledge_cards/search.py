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
    "_card_sort_time",
    "_card_type_label",
    "_card_type_search_cap",
    "_dedupe_terms",
    "_max_cards_per_type",
    "_query_phrases",
    "_scope_label",
    "_score_card",
    "_search_fingerprint",
    "_search_result",
    "_select_diverse_scored_cards",
    "_selected_scope_distribution",
    "_source_cap_key",
    "_stage_label",
    "_tokens",
    "build_expanded_rag_query",
    "search_knowledge_cards",
    "used_knowledge_from_results",
]

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
    total_candidates = cards_query.count()
    raw_cards_total = cards_query.filter(KnowledgeCard.status == "raw_extracted").count()
    status_query = _apply_card_db_status_filter(cards_query, include_inactive=include_inactive, include_raw=include_raw)
    status_candidate_count = status_query.count()
    include_secondary = limit >= RAG_SECONDARY_MIN_TOP_K or include_raw or include_inactive
    secondary_cards_excluded_count = 0
    if not include_secondary:
        secondary_cards_excluded_count = status_query.filter(KnowledgeCard.retrieval_level == "secondary").count()
        status_query = status_query.filter(or_(KnowledgeCard.retrieval_level.is_(None), KnowledgeCard.retrieval_level != "secondary"))
    after_retrieval_level_count = status_query.count()
    db_future_count = _count_db_future_position_cards(
        status_query,
        current_volume_index,
        current_chapter_index,
        include_future=include_future,
    )
    scoped_query = _apply_card_db_scope_filter(
        status_query,
        current_volume_index,
        current_chapter_index,
        include_future=include_future,
        allowed_scope_levels=allowed_scope_levels,
    )
    scoped_candidate_count = scoped_query.count()
    base_candidates = (
        scoped_query.order_by(
            KnowledgeCard.priority.desc(),
            KnowledgeCard.updated_at.desc(),
            KnowledgeCard.id.desc(),
        )
        .all()
    )
    status_candidates: list[KnowledgeCard] = []
    filtered_by_status_count = max(0, total_candidates - status_candidate_count)
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
    filtered_by_scope_count = max(0, after_retrieval_level_count - scoped_candidate_count - db_future_count)
    filtered_by_future_count = db_future_count
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
        score = _score_card(
            card,
            expanded_query["raw_query"],
            expanded_query["query"],
            stage,
            preferred_card_types,
            expanded_query["expanded_terms"],
        )
        if card.priority:
            score += min(max(card.priority, 0), 100) / 100
        if score > 0:
            scored.append((score, card))
    scored.sort(key=lambda item: (item[0], _card_sort_time(item[1])), reverse=True)
    selected, filtered_duplicate_count, source_cap_excluded_count, diversity_buckets = _select_diverse_scored_cards(
        scored,
        limit,
        preferred_card_types,
    )
    results = [_search_result(card, score) for score, card in selected]
    selected_scope_distribution = _selected_scope_distribution([card for _, card in selected])
    debug = {
        "query": expanded_query["query"],
        "raw_query": expanded_query["raw_query"],
        "expanded_terms": expanded_query["expanded_terms"],
        "preferred_card_types": preferred_card_types,
        "total_candidates": total_candidates,
        "candidate_count_total": total_candidates,
        "candidate_count_after_db_filter": len(base_candidates),
        "candidate_count_after_status_filter": status_candidate_count,
        "candidate_count_after_retrieval_level_filter": after_retrieval_level_count,
        "candidate_count_after_visibility_filter": len(visible_candidates),
        "current_volume_index": current_volume_index,
        "current_chapter_index": current_chapter_index,
        "candidate_count_before_scope_filter": len(status_candidates),
        "candidate_count_after_scope_filter": len(visible_candidates),
        "filtered_by_status_count": filtered_by_status_count,
        "filtered_by_scope_count": filtered_by_scope_count,
        "filtered_by_future_count": filtered_by_future_count,
        "raw_cards_excluded_count": 0 if include_raw else raw_cards_total,
        "secondary_cards_excluded_count": secondary_cards_excluded_count,
        "future_cards_excluded_count": filtered_by_future_count,
        "duplicate_group_excluded_count": filtered_duplicate_count,
        "source_cap_excluded_count": source_cap_excluded_count,
        "selected_card_ids": [card.card_id for _, card in selected],
        "selected_card_scope": {card.card_id: _scope_label(card) for _, card in selected},
        "selected_card_type_distribution": diversity_buckets,
        "selected_scope_distribution": selected_scope_distribution,
        "selected_pinned_context": [card.card_id for _, card in selected if _effective_retrieval_level(card) == "pinned"],
        "selected_top_k_cards": [
            {
                "id": card.card_id,
                "card_type": card.card_type,
                "scope": _scope_label(card),
                "score": round(score, 4),
                "retrieval_level": _effective_retrieval_level(card),
            }
            for score, card in selected
        ],
        "selected_count": len(results),
        "filtered_duplicate_count": filtered_duplicate_count,
        "diversity_buckets": diversity_buckets,
        "stage": stage,
        "top_k": limit,
        "warnings": [],
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

def _select_diverse_scored_cards(
    scored: list[tuple[float, KnowledgeCard]],
    limit: int,
    preferred_card_types: list[str],
) -> tuple[list[tuple[float, KnowledgeCard]], int, int, dict[str, int]]:
    selected: list[tuple[float, KnowledgeCard]] = []
    selected_ids: set[int] = set()
    seen_fingerprints: set[str] = set()
    card_type_counts: Counter[str] = Counter()
    source_counts: Counter[str] = Counter()
    capped_backlog: list[tuple[float, KnowledgeCard, str]] = []
    filtered_duplicate_count = 0
    source_cap_excluded_count = 0
    max_per_type = _max_cards_per_type(limit, preferred_card_types)

    for score, card in scored:
        fingerprint = _search_fingerprint(card)
        if fingerprint and fingerprint in seen_fingerprints:
            filtered_duplicate_count += 1
            continue
        source_key = _source_cap_key(card)
        if source_key and source_counts[source_key] >= RAG_SOURCE_CAP_PER_SOURCE:
            source_cap_excluded_count += 1
            continue
        type_cap = _card_type_search_cap(card, max_per_type)
        if card_type_counts[card.card_type] >= type_cap:
            capped_backlog.append((score, card, fingerprint))
            continue
        selected.append((score, card))
        selected_ids.add(card.id)
        card_type_counts[card.card_type] += 1
        if source_key:
            source_counts[source_key] += 1
        if fingerprint:
            seen_fingerprints.add(fingerprint)
        if len(selected) >= limit:
            return selected, filtered_duplicate_count, source_cap_excluded_count, dict(card_type_counts)

    for score, card, fingerprint in capped_backlog:
        if len(selected) >= limit:
            break
        if card.id in selected_ids:
            continue
        if fingerprint and fingerprint in seen_fingerprints:
            filtered_duplicate_count += 1
            continue
        source_key = _source_cap_key(card)
        if source_key and source_counts[source_key] >= RAG_SOURCE_CAP_PER_SOURCE:
            source_cap_excluded_count += 1
            continue
        selected.append((score, card))
        selected_ids.add(card.id)
        card_type_counts[card.card_type] += 1
        if source_key:
            source_counts[source_key] += 1
        if fingerprint:
            seen_fingerprints.add(fingerprint)

    return selected, filtered_duplicate_count, source_cap_excluded_count, dict(card_type_counts)

def _max_cards_per_type(limit: int, preferred_card_types: list[str]) -> int:
    diversity_slots = max(2, min(4, len(preferred_card_types) or 2))
    return max(2, math.ceil(limit / diversity_slots) + 1)

def _card_type_search_cap(card: KnowledgeCard, max_per_type: int) -> int:
    if card.library_type in {"worldbuilding", "memory"}:
        return max_per_type + 1
    if card.card_type in {"ChapterOutline", "ChapterHandoff", "memory", "character", "location", "faction", "rule", "world_rule"}:
        return max_per_type + 1
    return max_per_type

def _search_fingerprint(card: KnowledgeCard) -> str:
    if card.content_fingerprint:
        return card.content_fingerprint
    return content_fingerprint(card.title, card.content, card.avoid, _json_list(card.tags_json))

def _source_cap_key(card: KnowledgeCard) -> str:
    refs = _json_list_of_dicts(card.source_refs_json)
    if not refs:
        source_ref = _json_dict(card.source_ref_json)
        refs = [source_ref] if source_ref else []
    if not refs:
        return ""
    ref = refs[0]
    source = (
        ref.get("source_path")
        or ref.get("source_file")
        or ref.get("source")
        or ref.get("package_id")
        or card.package_id
        or ""
    )
    source = str(source).strip()
    return f"{card.library_type}:{source}" if source else ""

def _card_sort_time(card: KnowledgeCard) -> datetime:
    return card.updated_at or card.created_at or datetime.min

def _score_card(
    card: KnowledgeCard,
    raw_query: str,
    query: str,
    stage: str,
    preferred_card_types: list[str],
    expanded_terms: list[str] | None = None,
) -> float:
    raw_terms = _tokens(raw_query, limit=96)
    expanded_tokens = _tokens(" ".join(expanded_terms or []), limit=32)
    expanded_only = [term for term in expanded_tokens if term not in set(raw_terms)]
    tags = [tag.lower() for tag in _json_list(card.tags_json)]
    use_when_items = [item.lower() for item in _json_list(card.use_when_json)]
    source_ref = _json_dict(card.source_ref_json)
    source_refs = _json_list_of_dicts(card.source_refs_json)
    source_text = json.dumps({"source_ref": source_ref, "source_refs": source_refs}, ensure_ascii=False).lower()
    title_text = "\n".join([card.title or "", card.chapter_title or "", card.volume_title or ""]).lower()
    meta_text = "\n".join(
        [
            card.card_type or "",
            card.library_type or "",
            " ".join(tags),
            " ".join(use_when_items),
            source_text,
        ]
    ).lower()
    body_text = "\n".join([card.summary or "", card.content or "", card.avoid or ""]).lower()
    haystack = "\n".join([title_text, meta_text, body_text])
    score = 0.0
    raw_match_count = 0
    for term in raw_terms:
        if not term:
            continue
        matched = False
        if term in title_text:
            score += 4.0
            matched = True
        if term in meta_text:
            score += 3.0
            matched = True
        if term in body_text:
            score += 2.0
            matched = True
        if any(term == tag or term in tag for tag in tags):
            score += 2.0
            matched = True
        if matched:
            raw_match_count += 1

    for phrase in _query_phrases(raw_query):
        if phrase in title_text:
            score += 5.0
        elif phrase in meta_text:
            score += 4.0
        elif phrase in body_text:
            score += 3.0

    for term in expanded_only:
        if term and term in haystack:
            score += 0.4
        if any(term == tag or term in tag for tag in tags):
            score += 0.6

    if card.card_type in preferred_card_types:
        score += 1.5
    use_when = " ".join(use_when_items)
    if stage and (stage.lower() in use_when or _stage_label(stage) in use_when):
        score += 1.0
    if stage == "worldbuilding_check" and card.library_type == "worldbuilding":
        score += 5.0
    elif card.library_type == "worldbuilding":
        score += 1.5
    if stage in {"draft", "continue", "continuation"} and card.library_type == "memory":
        score += 3.0
    elif stage == "revision" and card.library_type == "memory":
        score += 2.0
    if stage in {"draft", "revision"} and card.card_type == "anti_pattern":
        score += 2.0
    if stage in {"draft", "revision"} and card.card_type == "style_pattern":
        score += 1.5
    if card.library_type == "memory":
        score += 1.0 / math.sqrt(max(1, (datetime.utcnow() - card.updated_at).days + 1)) if card.updated_at else 0.5
    if card.source_kind == "rag_compact" and raw_terms:
        if raw_match_count < min(3, max(1, len(raw_terms) // 3)):
            score -= 2.0
        else:
            score -= 0.5
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
        "retrieval_level": _effective_retrieval_level(card),
        "context_role": normalize_context_role(card.context_role, "auxiliary"),
        "scope_level": card.scope_level or "global",
        "volume_index": card.volume_index,
        "chapter_index": card.chapter_index,
    }

def _selected_scope_distribution(cards: list[KnowledgeCard]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for card in cards:
        counter[normalize_scope_level(card.scope_level, "global")] += 1
    return dict(counter)

def _scope_label(card: KnowledgeCard) -> str:
    scope_level = normalize_scope_level(card.scope_level, "global")
    if scope_level == "global":
        return "global"
    if scope_level == "volume":
        return f"volume:{card.volume_index}" if card.volume_index is not None else "volume:unknown"
    volume = card.volume_index if card.volume_index is not None else "unknown"
    chapter = card.chapter_index if card.chapter_index is not None else "unknown"
    return f"chapter:{volume}/{chapter}"

def _tokens(value: str, *, limit: int = 64) -> list[str]:
    lowered = (value or "").lower()
    words = WORD_RE.findall(lowered)
    if words:
        tokens: list[str] = []
        for word in words:
            if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 4:
                tokens.extend(word[index : index + 2] for index in range(len(word) - 1))
                tokens.extend(word[index : index + 3] for index in range(len(word) - 2))
                tokens.extend(word[index : index + 4] for index in range(len(word) - 3))
            tokens.append(word)
        return list(dict.fromkeys(token for token in tokens if len(token) >= 2 or token.isdigit()))[:limit]
    compact = re.sub(r"\s+", "", lowered)
    return [compact[index : index + 2] for index in range(max(0, len(compact) - 1))][:limit]

def _query_phrases(value: str) -> list[str]:
    phrases: list[str] = []
    for part in re.split(r"[\s,，。；;：:\n\r\t\"'“”‘’（）()\[\]【】<>《》]+", value or ""):
        text = part.strip().lower()
        if len(text) >= 3 and len(text) <= 24:
            phrases.append(text)
    return list(dict.fromkeys(phrases))[:24]

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
        "ChapterOutline": "章节提纲记忆",
        "ChapterHandoff": "章节接力卡",
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

