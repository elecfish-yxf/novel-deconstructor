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

__all__ = [
    "_can_semantic_merge",
    "_compact_avoid_text",
    "_compact_card_content",
    "_compact_card_excerpt",
    "_create_rag_compact_card",
    "_merge_candidate_cards",
    "_merge_card_into",
    "_merge_card_summary",
    "_merge_compact_source_refs",
    "_merge_group_dict",
    "_merge_groups",
    "_merge_source_ref_lists",
    "_merge_source_refs",
    "_ngram_similarity",
    "_rag_compact_batches",
    "_rag_compact_bucket",
    "_rag_compact_candidate_cards",
    "_rag_compact_sort_key",
    "_set_similarity",
    "_similarity_score",
    "_unique_compact_card_id",
    "apply_knowledge_card_merges",
    "compact_knowledge_cards_for_rag",
    "knowledge_card_merge_stats",
    "preview_knowledge_card_merges",
    "unmerge_knowledge_card",
]

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
        previous_metadata = (
            card.source_refs_json,
            card.normalized_title_hash,
            card.canonical_group_id,
            card.retrieval_level,
            card.context_role,
        )
        _refresh_card_retrieval_metadata(card)
        if previous_metadata != (
            card.source_refs_json,
            card.normalized_title_hash,
            card.canonical_group_id,
            card.retrieval_level,
            card.context_role,
        ):
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

    title_buckets: dict[tuple[str, str, str], list[KnowledgeCard]] = {}
    for card in cards:
        if card.card_id in consumed or not card.canonical_group_id:
            continue
        title_buckets.setdefault((card.library_type, card.card_type, card.canonical_group_id), []).append(card)
    for (_, _, group_id), bucket in title_buckets.items():
        candidates = [card for card in bucket if card.card_id not in consumed]
        if len(candidates) < 2:
            continue
        ordered = sorted(candidates, key=lambda item: (item.confidence, item.evidence_count or 1, item.updated_at or item.created_at), reverse=True)
        primary = ordered[0]
        merge_candidates = ordered[1:]
        consumed.update(card.card_id for card in merge_candidates)
        groups.append(_merge_group_dict(primary, merge_candidates, "auto_merge", "title_scope_duplicate", 0.95, group_id))

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
    primary.source_refs_json = _json(_merge_source_ref_lists(_json_list_of_dicts(primary.source_refs_json), _json_list_of_dicts(candidate.source_refs_json), _json_dict(primary.source_ref_json)))
    if candidate.avoid and candidate.avoid not in primary.avoid:
        primary.avoid = "\n".join(item for item in [primary.avoid.strip(), candidate.avoid.strip()] if item)
    primary.confidence = max(primary.confidence or 0, candidate.confidence or 0)
    merged_from = _merge_lists(_json_list(primary.merged_from_ids_json) or [primary.card_id], _json_list(candidate.merged_from_ids_json) or [candidate.card_id])
    primary.merged_from_ids_json = _json(merged_from)
    primary.evidence_count = max(1, len(merged_from), (primary.evidence_count or 1) + (candidate.evidence_count or 1))
    _refresh_card_retrieval_metadata(primary)
    candidate.is_canonical = False
    candidate.status = "merged"
    candidate.retrievable = False
    candidate.retrieval_level = "evidence"
    candidate.context_role = "evidence"
    candidate.merged_into_card_id = primary.card_id
    candidate.markdown_path = candidate.markdown_path or str(card_markdown_path(primary.knowledge_base, candidate))

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

def _merge_source_ref_lists(left: list[dict[str, Any]], right: list[dict[str, Any]], fallback: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [*left, *right]
    if not refs:
        refs = _card_source_refs(fallback)
    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ref in refs:
        if not ref:
            continue
        key = json.dumps(ref, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        unique.append(ref)
        seen.add(key)
    return unique

def _rag_compact_candidate_cards(db: Session, knowledge_base: KnowledgeBase) -> list[KnowledgeCard]:
    return (
        db.query(KnowledgeCard)
        .filter(
            KnowledgeCard.knowledge_base_id == knowledge_base.id,
            KnowledgeCard.status.in_(tuple(RETRIEVABLE_STATUSES)),
            KnowledgeCard.is_canonical.is_(True),
            KnowledgeCard.retrievable.is_(True),
            KnowledgeCard.library_type != "memory",
            KnowledgeCard.source_kind != "rag_compact",
            ~KnowledgeCard.card_type.in_(tuple(RAG_COMPACT_EXCLUDED_CARD_TYPES)),
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
        source_refs_json=_json(_card_source_refs(source_ref)),
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
        normalized_title_hash=normalized_title_hash(f"RAG compact {first.library_type}/{first.card_type}"),
        canonical_group_id=canonical_group_id(
            first.library_type,
            first.card_type,
            {"scope_level": first.scope_level, "volume_index": first.volume_index, "chapter_index": first.chapter_index},
            normalized_title_hash(f"RAG compact {first.library_type}/{first.card_type}"),
        ),
        retrieval_level="primary",
        context_role=_default_context_role({}, first.library_type, first.card_type, "approved"),
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
        card.retrieval_level = "evidence"
        card.context_role = "evidence"
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
    sample_refs = [ref for ref in refs if ref][:RAG_COMPACT_SAMPLE_REF_LIMIT]
    source_groups: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in refs:
        if not ref:
            continue
        source = str(ref.get("source") or ref.get("source_file") or ref.get("package_id") or "").strip()
        source_path = str(ref.get("source_path") or "").strip()
        key = (source, source_path)
        group = source_groups.setdefault(
            key,
            {
                "source": source,
                "source_path": source_path,
                "section_count": 0,
                "sample_headings": [],
            },
        )
        group["section_count"] += 1
        heading = ref.get("heading_path")
        if isinstance(heading, list) and len(group["sample_headings"]) < RAG_COMPACT_SOURCE_HEADING_LIMIT:
            group["sample_headings"].append(" / ".join(str(item) for item in heading if str(item).strip()))
    return {
        "source": "rag_compact",
        "source_kind": "rag_compact",
        "source_count": len([ref for ref in refs if ref]),
        "sources": list(source_groups.values())[:RAG_COMPACT_SOURCE_GROUP_LIMIT],
        "sample_source_refs": sample_refs,
        "compact_source_card_count": len(cards),
        "compact_source_card_ids": [card.card_id for card in cards],
    }

