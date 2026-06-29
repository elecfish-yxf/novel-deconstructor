from __future__ import annotations

from datetime import datetime
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import KnowledgeBase, KnowledgeCard, KnowledgeChunk, KnowledgeDocument, WritingMemory
from .embedding_service import EmbeddingService
from .knowledge_base import search_knowledge
from .knowledge_cards import search_knowledge_cards
from .rag_filters import ACTIVE_VECTOR_STATUSES, build_scope_filter, matches_scope_filter, scope_filter_reason
from .rag_scoring import merge_and_rank_candidates
from .vector_store import VectorHit, VectorPoint, VectorStore, stable_point_id


RETRIEVABLE_CARD_STATUSES = {"approved", "reviewed"}


def retrieve_for_writing(
    db: Session,
    *,
    workspace_id: str,
    knowledge_base_ids: list[int],
    query: str,
    phase: str,
    library_types: list[str] | None = None,
    target_volume_index: int | None = None,
    target_chapter_index: int | None = None,
    top_k: int | None = None,
    include_future: bool = False,
    include_raw: bool = False,
) -> dict[str, Any]:
    settings = get_settings()
    requested_mode = _retrieval_mode(settings.retrieval_mode)
    limit = max(1, min(int(top_k or settings.retrieval_top_k), 100))
    candidate_limit = max(limit, int(settings.retrieval_candidate_k or limit))
    scope_filter = build_scope_filter(
        workspace_id=workspace_id,
        knowledge_base_ids=knowledge_base_ids,
        library_types=library_types,
        target_volume_index=target_volume_index,
        target_chapter_index=target_chapter_index,
        include_future=include_future,
    )
    debug = _empty_debug(
        query=query,
        phase=phase,
        mode=requested_mode,
        top_k=limit,
        scope_filter=scope_filter,
        target_volume_index=target_volume_index,
        target_chapter_index=target_chapter_index,
    )
    if not query.strip() or not knowledge_base_ids:
        return _response([], debug)

    candidates: list[dict[str, Any]] = []
    keyword_candidates: list[dict[str, Any]] = []
    vector_candidates: list[dict[str, Any]] = []

    if requested_mode in {"keyword", "hybrid"}:
        keyword_candidates, keyword_debug = _keyword_candidates(
            db,
            workspace_id=workspace_id,
            knowledge_base_ids=knowledge_base_ids,
            query=query,
            phase=phase,
            library_types=library_types,
            target_volume_index=target_volume_index,
            target_chapter_index=target_chapter_index,
            include_future=include_future,
            include_raw=include_raw,
            limit=candidate_limit,
        )
        _merge_keyword_debug(debug, keyword_debug)
        candidates.extend(keyword_candidates)

    if requested_mode in {"vector", "hybrid"}:
        try:
            vector_candidates, vector_dropped = _vector_candidates(
                db,
                query=query,
                scope_filter=scope_filter,
                limit=candidate_limit,
            )
            debug["dropped"].extend(vector_dropped)
            candidates.extend(vector_candidates)
        except Exception as exc:  # noqa: BLE001 - Qdrant is an index layer, never the source of truth.
            debug["fallback"] = f"qdrant_unavailable:{type(exc).__name__}:{exc}"
            debug["effective_mode"] = "keyword"
            if requested_mode == "vector":
                keyword_candidates, keyword_debug = _keyword_candidates(
                    db,
                    workspace_id=workspace_id,
                    knowledge_base_ids=knowledge_base_ids,
                    query=query,
                    phase=phase,
                    library_types=library_types,
                    target_volume_index=target_volume_index,
                    target_chapter_index=target_chapter_index,
                    include_future=include_future,
                    include_raw=include_raw,
                    limit=candidate_limit,
                )
                _merge_keyword_debug(debug, keyword_debug)
                candidates.extend(keyword_candidates)

    debug["vector_candidates"] = len(vector_candidates)
    debug["keyword_candidates"] = len(keyword_candidates)
    debug["merged_candidates"] = len(candidates)
    final_hits = merge_and_rank_candidates(candidates, top_k=limit, debug=debug)
    for index, hit in enumerate(final_hits, start=1):
        hit["citation_id"] = hit.get("citation_id") or f"资料{index}"
        hit["score"] = round(float(hit.get("final_score") or hit.get("score") or 0), 4)
    debug["final_hits"] = len(final_hits)
    debug["selected_count"] = len(final_hits)
    debug["selected_card_ids"] = [hit["id"] for hit in final_hits if hit.get("source_type") == "card"]
    debug["selected_non_card_ids"] = [hit["id"] for hit in final_hits if hit.get("source_type") != "card"]
    debug["selected_non_card_count"] = len(debug["selected_non_card_ids"])
    debug["selected_top_k_cards"] = [
        {"id": hit.get("id"), "score": hit.get("score"), "source_type": hit.get("source_type")}
        for hit in final_hits
    ]
    return _response(final_hits, debug)


def index_document_chunks(db: Session, document: KnowledgeDocument | int) -> dict[str, Any]:
    try:
        doc = _document(db, document)
        kb = db.get(KnowledgeBase, doc.knowledge_base_id)
        if not kb or doc.status != "completed":
            return {"indexed": 0, "skipped": "document_not_completed"}
        delete_document_vectors(doc)
        chunks = (
            db.query(KnowledgeChunk)
            .filter(KnowledgeChunk.document_id == doc.id)
            .order_by(KnowledgeChunk.chunk_index)
            .all()
        )
        texts = [_chunk_index_text(doc, chunk) for chunk in chunks]
        vectors = _embed_batches(texts)
        points = [
            VectorPoint(
                id=stable_point_id("chunk", chunk.id),
                vector=vector,
                payload=_chunk_payload(kb, doc, chunk),
            )
            for chunk, vector in zip(chunks, vectors, strict=False)
        ]
        VectorStore().upsert_points(points)
        return {"indexed": len(points), "source_type": "chunk", "document_id": doc.id}
    except Exception as exc:  # noqa: BLE001
        return {"indexed": 0, "error": str(exc), "source_type": "chunk"}


def index_knowledge_card(db: Session, card: KnowledgeCard | int) -> dict[str, Any]:
    try:
        item = _card(db, card)
        if not _card_indexable(item):
            return delete_card_vector(item)
        kb = db.get(KnowledgeBase, item.knowledge_base_id)
        if not kb:
            return {"indexed": 0, "error": "knowledge_base_missing", "source_type": "card"}
        vector = EmbeddingService().embed_query(_card_index_text(item))
        point = VectorPoint(
            id=stable_point_id("card", item.card_id),
            vector=vector,
            payload=_card_payload(kb, item),
        )
        VectorStore().upsert_points([point])
        return {"indexed": 1, "source_type": "card", "card_id": item.card_id}
    except Exception as exc:  # noqa: BLE001
        return {"indexed": 0, "error": str(exc), "source_type": "card"}


def index_writing_memory(db: Session, memory: WritingMemory | int) -> dict[str, Any]:
    try:
        item = _memory(db, memory)
        if not item.retrievable:
            return delete_memory_vector(item)
        kb = db.get(KnowledgeBase, item.knowledge_base_id)
        if not kb:
            return {"indexed": 0, "error": "knowledge_base_missing", "source_type": "memory"}
        vector = EmbeddingService().embed_query(_memory_index_text(item))
        point = VectorPoint(
            id=stable_point_id("memory", item.id),
            vector=vector,
            payload=_memory_payload(kb, item),
        )
        VectorStore().upsert_points([point])
        return {"indexed": 1, "source_type": "memory", "memory_id": item.id}
    except Exception as exc:  # noqa: BLE001
        return {"indexed": 0, "error": str(exc), "source_type": "memory"}


def delete_document_vectors(document: KnowledgeDocument | int) -> dict[str, Any]:
    document_id = document.id if isinstance(document, KnowledgeDocument) else int(document)
    try:
        VectorStore().delete_by_payload({"must": [{"key": "source_type", "match": "chunk"}, {"key": "document_id", "match": document_id}]})
        return {"deleted": True, "source_type": "chunk", "document_id": document_id}
    except Exception as exc:  # noqa: BLE001
        return {"deleted": False, "error": str(exc), "source_type": "chunk", "document_id": document_id}


def delete_card_vector(card: KnowledgeCard | str) -> dict[str, Any]:
    card_id = card.card_id if isinstance(card, KnowledgeCard) else str(card)
    try:
        VectorStore().delete_by_payload({"must": [{"key": "source_type", "match": "card"}, {"key": "card_id", "match": card_id}]})
        return {"deleted": True, "source_type": "card", "card_id": card_id}
    except Exception as exc:  # noqa: BLE001
        return {"deleted": False, "error": str(exc), "source_type": "card", "card_id": card_id}


def delete_memory_vector(memory: WritingMemory | int) -> dict[str, Any]:
    memory_id = memory.id if isinstance(memory, WritingMemory) else int(memory)
    try:
        VectorStore().delete_by_payload({"must": [{"key": "source_type", "match": "memory"}, {"key": "memory_id", "match": memory_id}]})
        return {"deleted": True, "source_type": "memory", "memory_id": memory_id}
    except Exception as exc:  # noqa: BLE001
        return {"deleted": False, "error": str(exc), "source_type": "memory", "memory_id": memory_id}


def rebuild_knowledge_base_vectors(db: Session, knowledge_base: KnowledgeBase | int) -> dict[str, Any]:
    kb = db.get(KnowledgeBase, knowledge_base) if isinstance(knowledge_base, int) else knowledge_base
    if not kb:
        return {"indexed": 0, "error": "knowledge_base_missing"}
    result = rebuild_vectors(db, workspace_id=kb.workspace_id, knowledge_base_ids=[kb.id], dry_run=False, force=True)
    return {
        "indexed_chunks": result["indexed"]["chunks"],
        "indexed_cards": result["indexed"]["cards"],
        "indexed_memories": result["indexed"]["memories"],
        "errors": result["errors"],
    }


def rebuild_vectors(
    db: Session,
    *,
    workspace_id: str,
    knowledge_base_ids: list[int] | None = None,
    document_ids: list[int] | None = None,
    card_ids: list[str] | None = None,
    memory_ids: list[int] | None = None,
    dry_run: bool = True,
    force: bool = False,
) -> dict[str, Any]:
    scope = _rebuild_scope(
        db,
        workspace_id=workspace_id,
        knowledge_base_ids=knowledge_base_ids,
        document_ids=document_ids,
        card_ids=card_ids,
        memory_ids=memory_ids,
    )
    result = {
        "dry_run": dry_run,
        "force": force,
        "planned": {
            "documents": len(scope["documents"]),
            "chunks": sum(max(0, document.chunk_count or 0) for document in scope["documents"]),
            "cards": len(scope["cards"]),
            "memories": len(scope["memories"]),
        },
        "indexed": {"chunks": 0, "cards": 0, "memories": 0},
        "skipped": [],
        "errors": [],
    }
    if dry_run:
        return result

    if force and _is_broad_rebuild(document_ids, card_ids, memory_ids):
        for kb_id in scope["knowledge_base_ids"]:
            try:
                VectorStore().delete_by_payload(
                    {"must": [{"key": "workspace_id", "match": workspace_id}, {"key": "knowledge_base_id", "match": kb_id}]}
                )
            except Exception as exc:  # noqa: BLE001
                result["errors"].append({"scope": f"knowledge_base:{kb_id}", "error": str(exc)})

    for document in scope["documents"]:
        item = index_document_chunks(db, document)
        result["indexed"]["chunks"] += int(item.get("indexed") or 0)
        _record_index_result(result, item, f"document:{document.id}")
    for card in scope["cards"]:
        item = index_knowledge_card(db, card)
        result["indexed"]["cards"] += int(item.get("indexed") or 0)
        _record_index_result(result, item, f"card:{card.card_id}")
    for memory in scope["memories"]:
        item = index_writing_memory(db, memory)
        result["indexed"]["memories"] += int(item.get("indexed") or 0)
        _record_index_result(result, item, f"memory:{memory.id}")
    return result


def _rebuild_scope(
    db: Session,
    *,
    workspace_id: str,
    knowledge_base_ids: list[int] | None,
    document_ids: list[int] | None,
    card_ids: list[str] | None,
    memory_ids: list[int] | None,
) -> dict[str, Any]:
    kb_query = db.query(KnowledgeBase.id).filter(KnowledgeBase.workspace_id == workspace_id)
    if knowledge_base_ids:
        kb_query = kb_query.filter(KnowledgeBase.id.in_(knowledge_base_ids))
    kb_ids = [item.id for item in kb_query.all()]
    specific = bool(document_ids or card_ids or memory_ids)

    documents: list[KnowledgeDocument] = []
    if document_ids or not specific:
        query = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id.in_(kb_ids))
        if document_ids:
            query = query.filter(KnowledgeDocument.id.in_(document_ids))
        documents = query.order_by(KnowledgeDocument.id).all()

    cards: list[KnowledgeCard] = []
    if card_ids or not specific:
        query = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id.in_(kb_ids))
        if card_ids:
            query = query.filter(KnowledgeCard.card_id.in_(card_ids))
        cards = query.order_by(KnowledgeCard.id).all()

    memories: list[WritingMemory] = []
    if memory_ids or not specific:
        query = db.query(WritingMemory).filter(WritingMemory.workspace_id == workspace_id, WritingMemory.knowledge_base_id.in_(kb_ids))
        if memory_ids:
            query = query.filter(WritingMemory.id.in_(memory_ids))
        memories = query.order_by(WritingMemory.id).all()

    return {"knowledge_base_ids": kb_ids, "documents": documents, "cards": cards, "memories": memories}


def _is_broad_rebuild(document_ids: list[int] | None, card_ids: list[str] | None, memory_ids: list[int] | None) -> bool:
    return not any([document_ids, card_ids, memory_ids])


def _record_index_result(result: dict[str, Any], item: dict[str, Any], scope: str) -> None:
    if item.get("error"):
        result["errors"].append({"scope": scope, "error": item["error"]})
    if item.get("skipped"):
        result["skipped"].append({"scope": scope, "reason": item["skipped"]})
    if item.get("deleted") is True and not item.get("indexed"):
        result["skipped"].append({"scope": scope, "reason": "not_indexable_deleted_existing_vector"})


def _keyword_candidates(
    db: Session,
    *,
    workspace_id: str,
    knowledge_base_ids: list[int],
    query: str,
    phase: str,
    library_types: list[str] | None,
    target_volume_index: int | None,
    target_chapter_index: int | None,
    include_future: bool,
    include_raw: bool,
    limit: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    library_filter = library_types[0] if library_types and len(library_types) == 1 else None
    card_results, card_debug = search_knowledge_cards(
        db,
        knowledge_base_ids,
        stage=phase,
        query=query,
        top_k=limit,
        library_type=library_filter,
        current_volume_index=target_volume_index,
        current_chapter_index=target_chapter_index,
        include_future=include_future,
        include_raw=include_raw,
    )
    candidates = [
        _card_keyword_candidate(item)
        for item in card_results
        if not library_types or item.get("library_type") in set(library_types)
    ]
    if not library_types or set(library_types) & {"writing_guide", "worldbuilding"}:
        for hit in search_knowledge(db, knowledge_base_ids, query, min(limit, 100)):
            if library_types and hit.get("knowledge_type") not in set(library_types):
                continue
            payload = _chunk_hit_payload(hit, workspace_id=workspace_id)
            chunk_scope_filter = build_scope_filter(
                workspace_id=workspace_id,
                knowledge_base_ids=knowledge_base_ids,
                library_types=library_types,
                target_volume_index=target_volume_index,
                target_chapter_index=target_chapter_index,
                include_future=include_future,
            )
            if matches_scope_filter(payload, chunk_scope_filter):
                candidates.append(_chunk_keyword_candidate(hit, payload))
    return candidates[:limit], card_debug


def _vector_candidates(
    db: Session,
    *,
    query: str,
    scope_filter: dict[str, Any],
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vector = EmbeddingService().embed_query(query)
    hits = VectorStore().search(vector, scope_filter, limit)
    candidates: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for hit in hits:
        candidate = _hydrate_vector_hit(db, hit, scope_filter)
        if candidate:
            candidates.append(candidate)
        else:
            dropped.append({"id": hit.id, "reason": scope_filter_reason(hit.payload, scope_filter) or "stale_or_scope_filtered"})
    return candidates, dropped


def _hydrate_vector_hit(db: Session, hit: VectorHit, scope_filter: dict[str, Any]) -> dict[str, Any] | None:
    payload = dict(hit.payload or {})
    source_type = payload.get("source_type")
    if source_type == "card":
        card = (
            db.query(KnowledgeCard)
            .filter(KnowledgeCard.knowledge_base_id == payload.get("knowledge_base_id"), KnowledgeCard.card_id == payload.get("card_id"))
            .first()
        )
        if not card:
            return None
        kb = db.get(KnowledgeBase, card.knowledge_base_id)
        hydrated_payload = _card_payload(kb, card) if kb else payload
        reason = scope_filter_reason(hydrated_payload, scope_filter)
        if reason:
            return None
        return {**_card_candidate(card), "vector_score": hit.score}
    if source_type == "memory":
        memory = db.get(WritingMemory, _int_or_none(payload.get("memory_id")))
        if not memory:
            return None
        kb = db.get(KnowledgeBase, memory.knowledge_base_id)
        hydrated_payload = _memory_payload(kb, memory) if kb else payload
        reason = scope_filter_reason(hydrated_payload, scope_filter)
        if reason:
            return None
        return {**_memory_candidate(memory), "vector_score": hit.score}
    if source_type == "chunk":
        row = (
            db.query(KnowledgeChunk, KnowledgeDocument)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .filter(KnowledgeChunk.id == payload.get("chunk_id"))
            .first()
        )
        if not row:
            return None
        chunk, document = row
        kb = db.get(KnowledgeBase, chunk.knowledge_base_id)
        hydrated_payload = _chunk_payload(kb, document, chunk) if kb else payload
        reason = scope_filter_reason(hydrated_payload, scope_filter)
        if reason:
            return None
        return {**_chunk_candidate(chunk, document), "workspace_id": hydrated_payload.get("workspace_id"), "vector_score": hit.score}
    return None


def _response(hits: list[dict[str, Any]], debug: dict[str, Any]) -> dict[str, Any]:
    return {
        "hits": hits,
        "used_knowledge": [_used_knowledge(item) for item in hits],
        "retrieval_debug": debug,
    }


def _empty_debug(
    *,
    query: str,
    phase: str,
    mode: str,
    top_k: int,
    scope_filter: dict[str, Any],
    target_volume_index: int | None,
    target_chapter_index: int | None,
) -> dict[str, Any]:
    settings = get_settings()
    return {
        "query": query,
        "raw_query": query,
        "expanded_terms": [],
        "preferred_card_types": [],
        "mode": mode,
        "effective_mode": mode,
        "scope_filter": scope_filter,
        "vector_candidates": 0,
        "keyword_candidates": 0,
        "merged_candidates": 0,
        "final_hits": 0,
        "fallback": None,
        "filters_applied": [item for item in scope_filter.get("filters_applied", []) if item],
        "weights": {
            "keyword": settings.retrieval_keyword_weight,
            "vector": settings.retrieval_vector_weight,
        },
        "dropped": [],
        "total_candidates": 0,
        "candidate_count_total": 0,
        "candidate_count_after_db_filter": 0,
        "candidate_count_after_status_filter": 0,
        "candidate_count_after_retrieval_level_filter": 0,
        "candidate_count_after_visibility_filter": 0,
        "candidate_count_before_scope_filter": 0,
        "candidate_count_after_scope_filter": 0,
        "filtered_by_status_count": 0,
        "filtered_by_scope_count": 0,
        "filtered_by_future_count": 0,
        "raw_cards_excluded_count": 0,
        "secondary_cards_excluded_count": 0,
        "future_cards_excluded_count": 0,
        "duplicate_group_excluded_count": 0,
        "source_cap_excluded_count": 0,
        "selected_card_ids": [],
        "selected_non_card_ids": [],
        "selected_non_card_count": 0,
        "selected_card_scope": {},
        "selected_card_type_distribution": {},
        "selected_scope_distribution": {},
        "selected_pinned_context": [],
        "selected_top_k_cards": [],
        "selected_count": 0,
        "filtered_duplicate_count": 0,
        "diversity_buckets": {},
        "stage": phase,
        "top_k": top_k,
        "current_volume_index": target_volume_index,
        "current_chapter_index": target_chapter_index,
        "warnings": [],
    }


def _merge_keyword_debug(target: dict[str, Any], source: dict[str, Any]) -> None:
    for key, value in source.items():
        if isinstance(value, int):
            target[key] = int(target.get(key, 0)) + value
        elif key in {"expanded_terms", "preferred_card_types", "warnings"}:
            target[key] = list(dict.fromkeys([*target.get(key, []), *value]))
        elif key not in target or target.get(key) in (None, "", [], {}):
            target[key] = value
    target["keyword_debug"] = source


def _retrieval_mode(value: str) -> str:
    mode = (value or "hybrid").strip().lower()
    return mode if mode in {"keyword", "vector", "hybrid"} else "hybrid"


def _card_indexable(card: KnowledgeCard) -> bool:
    return bool(card.is_canonical) and bool(card.retrievable) and card.status in RETRIEVABLE_CARD_STATUSES


def _document(db: Session, document: KnowledgeDocument | int) -> KnowledgeDocument:
    if isinstance(document, KnowledgeDocument):
        return document
    item = db.get(KnowledgeDocument, int(document))
    if not item:
        raise ValueError(f"KnowledgeDocument not found: {document}")
    return item


def _card(db: Session, card: KnowledgeCard | int) -> KnowledgeCard:
    if isinstance(card, KnowledgeCard):
        return card
    item = db.get(KnowledgeCard, int(card))
    if not item:
        raise ValueError(f"KnowledgeCard not found: {card}")
    return item


def _memory(db: Session, memory: WritingMemory | int) -> WritingMemory:
    if isinstance(memory, WritingMemory):
        return memory
    item = db.get(WritingMemory, int(memory))
    if not item:
        raise ValueError(f"WritingMemory not found: {memory}")
    return item


def _embed_batches(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    settings = get_settings()
    service = EmbeddingService()
    vectors: list[list[float]] = []
    batch_size = max(1, int(settings.embedding_batch_size or 32))
    for start in range(0, len(texts), batch_size):
        vectors.extend(service.embed_texts(texts[start : start + batch_size]))
    return vectors


def _chunk_index_text(document: KnowledgeDocument, chunk: KnowledgeChunk) -> str:
    return "\n".join(
        [
            f"标题：{document.document_title or document.original_filename}",
            f"路径：{document.structure_path or document.source_path}",
            f"小节：{chunk.heading or ''}",
            f"知识类型：{document.knowledge_type}",
            f"正文：{chunk.text}",
        ]
    )


def _card_index_text(card: KnowledgeCard) -> str:
    return "\n".join(
        [
            f"标题：{card.title}",
            f"类型：{card.library_type} / {card.card_type}",
            f"摘要：{card.summary}",
            f"标签：{', '.join(_json_list(card.tags_json))}",
            f"内容：{card.content}",
        ]
    )


def _memory_index_text(memory: WritingMemory) -> str:
    return "\n".join(
        [
            f"标题：{memory.title}",
            f"记忆类型：{memory.memory_type}",
            f"标签：{', '.join(memory.tags)}",
            f"内容：{memory.content}",
        ]
    )


def _base_payload(kb: KnowledgeBase, source_type: str) -> dict[str, Any]:
    return {
        "workspace_id": kb.workspace_id,
        "knowledge_base_id": kb.id,
        "source_type": source_type,
        "document_id": None,
        "chunk_id": None,
        "card_id": None,
        "memory_id": None,
        "library_type": None,
        "knowledge_type": None,
        "card_type": None,
        "status": None,
        "is_canonical": True,
        "retrievable": True,
        "scope_level": "global",
        "volume_index": None,
        "chapter_index": None,
        "reveal_at_volume_index": None,
        "reveal_at_chapter_index": None,
        "valid_until_volume_index": None,
        "valid_until_chapter_index": None,
        "valid_from_volume_index": None,
        "valid_from_chapter_index": None,
        "priority": 0,
        "tags": [],
        "title": "",
        "summary": "",
        "content_fingerprint": "",
        "updated_at": None,
        "entity_ids": [],
        "relation_ids": [],
        "graph_tags": [],
        "depends_on_card_ids": [],
        "contradicts_card_ids": [],
        "supports_card_ids": [],
        "reveals_card_ids": [],
    }


def _chunk_payload(kb: KnowledgeBase, document: KnowledgeDocument, chunk: KnowledgeChunk) -> dict[str, Any]:
    metadata = _json_dict(chunk.metadata_json)
    payload = _base_payload(kb, "chunk")
    payload.update(
        {
            "document_id": document.id,
            "chunk_id": chunk.id,
            "library_type": document.knowledge_type,
            "knowledge_type": document.knowledge_type,
            "card_type": "knowledge_chunk",
            "status": document.status,
            "scope_level": metadata.get("scope_level") or "global",
            "volume_index": metadata.get("volume_index"),
            "chapter_index": metadata.get("chapter_index"),
            "reveal_at_volume_index": metadata.get("reveal_at_volume_index"),
            "reveal_at_chapter_index": metadata.get("reveal_at_chapter_index"),
            "valid_from_volume_index": metadata.get("valid_from_volume_index"),
            "valid_from_chapter_index": metadata.get("valid_from_chapter_index"),
            "valid_until_volume_index": metadata.get("valid_until_volume_index"),
            "valid_until_chapter_index": metadata.get("valid_until_chapter_index"),
            "title": document.document_title or document.original_filename,
            "summary": chunk.heading or document.structure_path,
            "content_fingerprint": hashlib.sha256(chunk.text.encode("utf-8", errors="ignore")).hexdigest(),
            "updated_at": _iso(document.updated_at or chunk.created_at),
        }
    )
    return payload


def _card_payload(kb: KnowledgeBase, card: KnowledgeCard) -> dict[str, Any]:
    source_ref = _json_dict(card.source_ref_json)
    payload = _base_payload(kb, "card")
    payload.update(
        {
            "card_id": card.card_id,
            "library_type": card.library_type,
            "knowledge_type": card.library_type,
            "card_type": card.card_type,
            "status": card.status,
            "is_canonical": bool(card.is_canonical),
            "retrievable": bool(card.retrievable),
            "scope_level": card.scope_level or "global",
            "volume_index": card.volume_index,
            "chapter_index": card.chapter_index,
            "reveal_at_volume_index": card.reveal_at_volume_index,
            "reveal_at_chapter_index": card.reveal_at_chapter_index,
            "valid_until_volume_index": card.valid_until_volume_index,
            "valid_until_chapter_index": card.valid_until_chapter_index,
            "valid_from_volume_index": card.valid_from_volume_index,
            "valid_from_chapter_index": card.valid_from_chapter_index,
            "priority": card.priority or 0,
            "tags": _json_list(card.tags_json),
            "title": card.title,
            "summary": card.summary,
            "content_fingerprint": card.content_fingerprint,
            "updated_at": _iso(card.updated_at),
            "entity_ids": _graph_list(source_ref, "entity_ids"),
            "relation_ids": _graph_list(source_ref, "relation_ids"),
            "graph_tags": _graph_list(source_ref, "graph_tags"),
            "depends_on_card_ids": _graph_list(source_ref, "depends_on_card_ids"),
            "contradicts_card_ids": _graph_list(source_ref, "contradicts_card_ids"),
            "supports_card_ids": _graph_list(source_ref, "supports_card_ids"),
            "reveals_card_ids": _graph_list(source_ref, "reveals_card_ids"),
        }
    )
    return payload


def _memory_payload(kb: KnowledgeBase, memory: WritingMemory) -> dict[str, Any]:
    payload = _base_payload(kb, "memory")
    payload.update(
        {
            "memory_id": memory.id,
            "library_type": "memory",
            "knowledge_type": "memory",
            "card_type": memory.memory_type,
            "status": "approved",
            "retrievable": bool(memory.retrievable),
            "scope_level": memory.scope_level or "chapter",
            "volume_index": memory.volume_index,
            "chapter_index": memory.chapter_index,
            "reveal_at_volume_index": memory.reveal_at_volume_index,
            "reveal_at_chapter_index": memory.reveal_at_chapter_index,
            "valid_until_volume_index": memory.valid_until_volume_index,
            "valid_until_chapter_index": memory.valid_until_chapter_index,
            "valid_from_volume_index": memory.valid_from_volume_index,
            "valid_from_chapter_index": memory.valid_from_chapter_index,
            "priority": memory.priority or 0,
            "tags": memory.tags,
            "title": memory.title,
            "summary": _clip(memory.content, 240),
            "content_fingerprint": hashlib.sha256(memory.content.encode("utf-8", errors="ignore")).hexdigest(),
            "updated_at": _iso(memory.updated_at),
        }
    )
    return payload


def _card_keyword_candidate(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": item["id"],
        "source_type": "card",
        "card_id": item["id"],
        "library_type": item.get("library_type"),
        "knowledge_type": item.get("library_type"),
        "card_type": item.get("card_type"),
        "title": item.get("title") or item["id"],
        "summary": item.get("content_preview", ""),
        "content_preview": item.get("content_preview", ""),
        "source_ref": item.get("source_ref", {}),
        "tags": item.get("tags", []),
        "status": item.get("status"),
        "retrieval_level": item.get("retrieval_level"),
        "context_role": item.get("context_role"),
        "scope_level": item.get("scope_level"),
        "volume_index": item.get("volume_index"),
        "chapter_index": item.get("chapter_index"),
        "keyword_score": float(item.get("score") or 0),
        "priority": item.get("priority") or 0,
    }


def _chunk_keyword_candidate(hit: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": stable_point_id("chunk", hit["chunk_id"]),
        "source_type": "chunk",
        "workspace_id": payload.get("workspace_id"),
        "knowledge_base_id": hit["knowledge_base_id"],
        "document_id": hit["document_id"],
        "chunk_id": hit["chunk_id"],
        "library_type": hit.get("knowledge_type"),
        "knowledge_type": hit.get("knowledge_type"),
        "card_type": "knowledge_chunk",
        "title": hit.get("document_title") or hit.get("original_filename"),
        "summary": hit.get("heading") or hit.get("structure_path"),
        "content_preview": _clip(hit.get("text") or "", 320),
        "text": hit.get("text"),
        "status": payload.get("status"),
        "scope_level": payload.get("scope_level"),
        "volume_index": payload.get("volume_index"),
        "chapter_index": payload.get("chapter_index"),
        "reveal_at_volume_index": payload.get("reveal_at_volume_index"),
        "reveal_at_chapter_index": payload.get("reveal_at_chapter_index"),
        "valid_from_volume_index": payload.get("valid_from_volume_index"),
        "valid_from_chapter_index": payload.get("valid_from_chapter_index"),
        "valid_until_volume_index": payload.get("valid_until_volume_index"),
        "valid_until_chapter_index": payload.get("valid_until_chapter_index"),
        "keyword_score": float(hit.get("score") or 0),
        "priority": 0,
        "citation_id": hit.get("citation_id"),
        "original_filename": hit.get("original_filename"),
        "structure_path": hit.get("structure_path"),
        "source_kind": hit.get("source_kind"),
        "source_path": hit.get("source_path"),
    }


def _card_candidate(card: KnowledgeCard) -> dict[str, Any]:
    return {
        "id": card.card_id,
        "source_type": "card",
        "card_id": card.card_id,
        "library_type": card.library_type,
        "knowledge_type": card.library_type,
        "card_type": card.card_type,
        "title": card.title,
        "summary": card.summary,
        "content_preview": _clip(card.content, 320),
        "source_ref": _json_dict(card.source_ref_json),
        "tags": _json_list(card.tags_json),
        "status": card.status,
        "retrieval_level": card.retrieval_level,
        "context_role": card.context_role,
        "scope_level": card.scope_level,
        "volume_index": card.volume_index,
        "chapter_index": card.chapter_index,
        "priority": card.priority or 0,
    }


def _memory_candidate(memory: WritingMemory) -> dict[str, Any]:
    return {
        "id": stable_point_id("memory", memory.id),
        "source_type": "memory",
        "workspace_id": memory.workspace_id,
        "knowledge_base_id": memory.knowledge_base_id,
        "memory_id": memory.id,
        "library_type": "memory",
        "knowledge_type": "memory",
        "card_type": memory.memory_type,
        "title": memory.title,
        "summary": _clip(memory.content, 240),
        "content_preview": _clip(memory.content, 320),
        "text": memory.content,
        "source_ref": memory.source_ref,
        "tags": memory.tags,
        "status": "approved",
        "retrieval_level": "pinned",
        "context_role": "memory",
        "scope_level": memory.scope_level,
        "volume_index": memory.volume_index,
        "chapter_index": memory.chapter_index,
        "reveal_at_volume_index": memory.reveal_at_volume_index,
        "reveal_at_chapter_index": memory.reveal_at_chapter_index,
        "valid_from_volume_index": memory.valid_from_volume_index,
        "valid_from_chapter_index": memory.valid_from_chapter_index,
        "valid_until_volume_index": memory.valid_until_volume_index,
        "valid_until_chapter_index": memory.valid_until_chapter_index,
        "priority": memory.priority or 0,
    }


def _chunk_candidate(chunk: KnowledgeChunk, document: KnowledgeDocument) -> dict[str, Any]:
    metadata = _json_dict(chunk.metadata_json)
    return {
        "id": stable_point_id("chunk", chunk.id),
        "source_type": "chunk",
        "knowledge_base_id": chunk.knowledge_base_id,
        "document_id": document.id,
        "chunk_id": chunk.id,
        "library_type": document.knowledge_type,
        "knowledge_type": document.knowledge_type,
        "card_type": "knowledge_chunk",
        "title": document.document_title or document.original_filename,
        "summary": chunk.heading or document.structure_path,
        "content_preview": _clip(chunk.text, 320),
        "text": chunk.text,
        "status": document.status,
        "scope_level": metadata.get("scope_level") or "global",
        "volume_index": metadata.get("volume_index"),
        "chapter_index": metadata.get("chapter_index"),
        "reveal_at_volume_index": metadata.get("reveal_at_volume_index"),
        "reveal_at_chapter_index": metadata.get("reveal_at_chapter_index"),
        "valid_from_volume_index": metadata.get("valid_from_volume_index"),
        "valid_from_chapter_index": metadata.get("valid_from_chapter_index"),
        "valid_until_volume_index": metadata.get("valid_until_volume_index"),
        "valid_until_chapter_index": metadata.get("valid_until_chapter_index"),
        "priority": 0,
        "original_filename": document.original_filename,
        "structure_path": document.structure_path,
        "source_kind": document.source_kind,
        "source_path": document.source_path,
    }


def _chunk_hit_payload(hit: dict[str, Any], *, workspace_id: str) -> dict[str, Any]:
    return {
        "workspace_id": workspace_id,
        "knowledge_base_id": hit.get("knowledge_base_id"),
        "source_type": "chunk",
        "document_id": hit.get("document_id"),
        "chunk_id": hit.get("chunk_id"),
        "library_type": hit.get("knowledge_type"),
        "knowledge_type": hit.get("knowledge_type"),
        "status": "completed",
        "is_canonical": True,
        "retrievable": True,
        "scope_level": "global",
    }


def _used_knowledge(item: dict[str, Any]) -> dict[str, Any]:
    preview = _clip(item.get("content_preview") or item.get("summary") or "", 260)
    return {
        "id": item.get("id") or "",
        "library_type": item.get("library_type") or item.get("knowledge_type") or "unknown",
        "card_type": item.get("card_type") or item.get("source_type") or "unknown",
        "title": item.get("title") or "",
        "score": round(float(item.get("score") or item.get("final_score") or 0), 4),
        "source_type": item.get("source_type"),
        "reason": _knowledge_reason(item),
        "source_ref": item.get("source_ref") or {},
        "content_preview": preview,
        "concise_content": preview,
        "tags": item.get("tags") or [],
        "status": item.get("status"),
        "retrieval_level": item.get("retrieval_level"),
        "context_role": item.get("context_role"),
        "scope_level": item.get("scope_level"),
        "volume_index": item.get("volume_index"),
        "chapter_index": item.get("chapter_index"),
    }


def _knowledge_reason(item: dict[str, Any]) -> str:
    modes = item.get("source_modes")
    if isinstance(modes, list) and modes:
        return "+".join(str(mode) for mode in modes)
    if item.get("vector_score"):
        return "vector"
    if item.get("keyword_score"):
        return "keyword"
    return "selected"


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


def _graph_list(source_ref: dict[str, Any], key: str) -> list[str]:
    value = source_ref.get(key)
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _clip(value: str, max_chars: int) -> str:
    text = (value or "").strip()
    if len(text) <= max_chars:
        return text
    return f"{text[: max_chars - 3].rstrip()}..."


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None and value != "" else None
    except (TypeError, ValueError):
        return None
