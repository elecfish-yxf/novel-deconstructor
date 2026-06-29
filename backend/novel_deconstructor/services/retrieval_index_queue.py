from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from sqlalchemy.orm import Session

from ..models import KnowledgeBase, KnowledgeCard, KnowledgeDocument, RetrievalIndexEvent, WritingMemory
from .retrieval_service import (
    delete_card_vector,
    delete_document_vectors,
    delete_memory_vector,
    index_document_chunks,
    index_knowledge_card,
    index_writing_memory,
    rebuild_knowledge_base_vectors,
)
from .vector_store import VectorStore


PENDING_STATUSES = {"pending", "failed"}


def enqueue_index_event(
    db: Session,
    *,
    source_type: str,
    source_id: str | int,
    operation: str,
    workspace_id: str | None = None,
    knowledge_base_id: int | None = None,
    process_now: bool = True,
) -> RetrievalIndexEvent:
    event = RetrievalIndexEvent(
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        source_type=source_type,
        source_id=str(source_id),
        operation=operation,
        status="pending",
    )
    db.add(event)
    db.flush()
    if process_now:
        process_index_event(db, event)
    return event


def enqueue_document_index(db: Session, document: KnowledgeDocument | int, *, process_now: bool = True) -> RetrievalIndexEvent:
    item = _document(db, document)
    kb = db.get(KnowledgeBase, item.knowledge_base_id)
    return enqueue_index_event(
        db,
        source_type="document",
        source_id=item.id,
        operation="upsert",
        workspace_id=kb.workspace_id if kb else None,
        knowledge_base_id=item.knowledge_base_id,
        process_now=process_now,
    )


def enqueue_document_delete(db: Session, document: KnowledgeDocument | int, *, process_now: bool = True) -> RetrievalIndexEvent:
    document_id = document.id if isinstance(document, KnowledgeDocument) else int(document)
    knowledge_base_id = document.knowledge_base_id if isinstance(document, KnowledgeDocument) else None
    workspace_id = None
    if isinstance(document, KnowledgeDocument):
        kb = db.get(KnowledgeBase, document.knowledge_base_id)
        workspace_id = kb.workspace_id if kb else None
    return enqueue_index_event(
        db,
        source_type="document",
        source_id=document_id,
        operation="delete",
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        process_now=process_now,
    )


def enqueue_card_index(db: Session, card: KnowledgeCard | str, *, process_now: bool = True) -> RetrievalIndexEvent:
    item = _card_by_ref(db, card)
    kb = db.get(KnowledgeBase, item.knowledge_base_id)
    return enqueue_index_event(
        db,
        source_type="card",
        source_id=item.card_id,
        operation="upsert",
        workspace_id=kb.workspace_id if kb else None,
        knowledge_base_id=item.knowledge_base_id,
        process_now=process_now,
    )


def enqueue_card_delete(db: Session, card: KnowledgeCard | str, *, process_now: bool = True) -> RetrievalIndexEvent:
    card_id = card.card_id if isinstance(card, KnowledgeCard) else str(card)
    knowledge_base_id = card.knowledge_base_id if isinstance(card, KnowledgeCard) else None
    workspace_id = None
    if isinstance(card, KnowledgeCard):
        kb = db.get(KnowledgeBase, card.knowledge_base_id)
        workspace_id = kb.workspace_id if kb else None
    return enqueue_index_event(
        db,
        source_type="card",
        source_id=card_id,
        operation="delete",
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        process_now=process_now,
    )


def enqueue_memory_index(db: Session, memory: WritingMemory | int, *, process_now: bool = True) -> RetrievalIndexEvent:
    item = _memory(db, memory)
    return enqueue_index_event(
        db,
        source_type="memory",
        source_id=item.id,
        operation="upsert",
        workspace_id=item.workspace_id,
        knowledge_base_id=item.knowledge_base_id,
        process_now=process_now,
    )


def enqueue_memory_delete(db: Session, memory: WritingMemory | int, *, process_now: bool = True) -> RetrievalIndexEvent:
    memory_id = memory.id if isinstance(memory, WritingMemory) else int(memory)
    workspace_id = memory.workspace_id if isinstance(memory, WritingMemory) else None
    knowledge_base_id = memory.knowledge_base_id if isinstance(memory, WritingMemory) else None
    return enqueue_index_event(
        db,
        source_type="memory",
        source_id=memory_id,
        operation="delete",
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        process_now=process_now,
    )


def enqueue_knowledge_base_rebuild(db: Session, knowledge_base: KnowledgeBase | int, *, process_now: bool = True) -> list[RetrievalIndexEvent]:
    kb = db.get(KnowledgeBase, knowledge_base) if isinstance(knowledge_base, int) else knowledge_base
    if not kb:
        return []
    events: list[RetrievalIndexEvent] = []
    for document in (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == kb.id)
        .order_by(KnowledgeDocument.id)
        .all()
    ):
        events.append(enqueue_document_index(db, document, process_now=False))
    for card in (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == kb.id)
        .order_by(KnowledgeCard.id)
        .all()
    ):
        events.append(enqueue_card_index(db, card, process_now=False))
    for memory in (
        db.query(WritingMemory)
        .filter(WritingMemory.workspace_id == kb.workspace_id, WritingMemory.knowledge_base_id == kb.id)
        .order_by(WritingMemory.id)
        .all()
    ):
        events.append(enqueue_memory_index(db, memory, process_now=False))
    if process_now:
        for event in events:
            process_index_event(db, event)
    return events


def enqueue_knowledge_base_force_rebuild(db: Session, knowledge_base: KnowledgeBase | int, *, process_now: bool = True) -> RetrievalIndexEvent | None:
    kb = db.get(KnowledgeBase, knowledge_base) if isinstance(knowledge_base, int) else knowledge_base
    if not kb:
        return None
    return enqueue_index_event(
        db,
        source_type="knowledge_base",
        source_id=kb.id,
        operation="force_rebuild",
        workspace_id=kb.workspace_id,
        knowledge_base_id=kb.id,
        process_now=process_now,
    )


def enqueue_knowledge_base_delete(
    db: Session,
    *,
    workspace_id: str,
    knowledge_base_id: int,
    process_now: bool = True,
) -> RetrievalIndexEvent:
    return enqueue_index_event(
        db,
        source_type="knowledge_base",
        source_id=knowledge_base_id,
        operation="delete",
        workspace_id=workspace_id,
        knowledge_base_id=knowledge_base_id,
        process_now=process_now,
    )


def recover_interrupted_index_events(db: Session) -> int:
    events = db.query(RetrievalIndexEvent).filter(RetrievalIndexEvent.status == "processing").all()
    for event in events:
        event.status = "pending"
        event.last_error = "Recovered interrupted retrieval index event."
        event.updated_at = datetime.utcnow()
    if events:
        db.commit()
    return len(events)


def process_pending_index_events(db: Session, *, limit: int = 100, max_attempts: int = 3, commit_each: bool = False) -> dict[str, Any]:
    events = (
        db.query(RetrievalIndexEvent)
        .filter(RetrievalIndexEvent.status.in_(sorted(PENDING_STATUSES)))
        .filter(RetrievalIndexEvent.attempt_count < max_attempts)
        .order_by(RetrievalIndexEvent.created_at, RetrievalIndexEvent.id)
        .limit(max(1, limit))
        .all()
    )
    result = {"processed": 0, "failed": 0, "done": 0}
    for event in events:
        process_index_event(db, event)
        result["processed"] += 1
        if event.status == "done":
            result["done"] += 1
        elif event.status == "failed":
            result["failed"] += 1
        if commit_each:
            db.commit()
    if not commit_each:
        db.flush()
    return result


def process_index_event(db: Session, event: RetrievalIndexEvent) -> dict[str, Any]:
    event.status = "processing"
    event.attempt_count = int(event.attempt_count or 0) + 1
    event.updated_at = datetime.utcnow()
    db.flush()
    try:
        result = _run_event(db, event)
        error = str(result.get("error") or "")
        if error:
            raise RuntimeError(error)
        event.status = "done"
        event.last_error = None
        event.result_json = json.dumps(result, ensure_ascii=False, default=str)
        event.processed_at = datetime.utcnow()
        event.updated_at = event.processed_at
        db.flush()
        return result
    except Exception as exc:  # noqa: BLE001 - event status is the durable failure boundary.
        event.status = "failed"
        event.last_error = str(exc)
        event.result_json = "{}"
        event.updated_at = datetime.utcnow()
        db.flush()
        return {"error": str(exc), "source_type": event.source_type, "source_id": event.source_id}


def _run_event(db: Session, event: RetrievalIndexEvent) -> dict[str, Any]:
    if event.source_type == "document":
        document_id = int(event.source_id)
        if event.operation == "delete":
            return delete_document_vectors(document_id)
        return index_document_chunks(db, document_id)
    if event.source_type == "card":
        if event.operation == "delete":
            return delete_card_vector(event.source_id)
        card = _card_by_event(db, event)
        return index_knowledge_card(db, card)
    if event.source_type == "memory":
        memory_id = int(event.source_id)
        if event.operation == "delete":
            return delete_memory_vector(memory_id)
        return index_writing_memory(db, memory_id)
    if event.source_type == "knowledge_base" and event.operation == "force_rebuild":
        if event.knowledge_base_id is None:
            raise ValueError("knowledge_base_id is required for force_rebuild")
        return rebuild_knowledge_base_vectors(db, event.knowledge_base_id)
    if event.source_type == "knowledge_base" and event.operation == "delete":
        if not event.workspace_id or event.knowledge_base_id is None:
            raise ValueError("workspace_id and knowledge_base_id are required for knowledge_base delete")
        VectorStore().delete_by_payload(
            {"must": [{"key": "workspace_id", "match": event.workspace_id}, {"key": "knowledge_base_id", "match": event.knowledge_base_id}]}
        )
        return {"deleted": True, "source_type": "knowledge_base", "knowledge_base_id": event.knowledge_base_id}
    raise ValueError(f"Unsupported retrieval index event: {event.source_type}/{event.operation}")


def _document(db: Session, document: KnowledgeDocument | int) -> KnowledgeDocument:
    if isinstance(document, KnowledgeDocument):
        return document
    item = db.get(KnowledgeDocument, int(document))
    if not item:
        raise ValueError(f"KnowledgeDocument not found: {document}")
    return item


def _memory(db: Session, memory: WritingMemory | int) -> WritingMemory:
    if isinstance(memory, WritingMemory):
        return memory
    item = db.get(WritingMemory, int(memory))
    if not item:
        raise ValueError(f"WritingMemory not found: {memory}")
    return item


def _card_by_ref(db: Session, card: KnowledgeCard | str) -> KnowledgeCard:
    if isinstance(card, KnowledgeCard):
        return card
    item = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == str(card)).first()
    if not item:
        raise ValueError(f"KnowledgeCard not found: {card}")
    return item


def _card_by_event(db: Session, event: RetrievalIndexEvent) -> KnowledgeCard:
    query = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == event.source_id)
    if event.knowledge_base_id is not None:
        query = query.filter(KnowledgeCard.knowledge_base_id == event.knowledge_base_id)
    item = query.first()
    if not item:
        raise ValueError(f"KnowledgeCard not found: {event.source_id}")
    return item
