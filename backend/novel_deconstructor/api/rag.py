from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import KnowledgeBase
from ..schemas import RAGHealthResponse, RAGPreviewRequest, RAGPreviewResponse, RAGRebuildRequest, RAGRebuildResponse
from ..services.retrieval_service import rebuild_vectors, retrieve_for_writing
from ..services.vector_store import VectorStore
from .workspace import get_workspace_id


router = APIRouter(prefix="/api/rag", tags=["rag"])


@router.get("/health", response_model=RAGHealthResponse)
def rag_health():
    health = VectorStore().healthcheck()
    return RAGHealthResponse(
        qdrant_available=bool(health.get("qdrant_available") or health.get("ok")),
        collection=str(health.get("collection") or ""),
        collection_exists=bool(health.get("collection_exists")),
        points_count=int(health.get("points_count") or 0),
        vector_size=int(health.get("vector_size") or 0),
        distance=str(health.get("distance") or ""),
        embedding_provider=str(health.get("embedding_provider") or ""),
        retrieval_mode=str(health.get("retrieval_mode") or ""),
        error=health.get("error"),
    )


@router.post("/rebuild", response_model=RAGRebuildResponse)
def rag_rebuild(
    payload: RAGRebuildRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    result = rebuild_vectors(
        db,
        workspace_id=workspace_id,
        knowledge_base_ids=_workspace_kb_ids(db, workspace_id, payload.knowledge_base_ids),
        document_ids=payload.document_ids,
        card_ids=payload.card_ids,
        memory_ids=payload.memory_ids,
        dry_run=payload.dry_run,
        force=payload.force,
    )
    return RAGRebuildResponse.model_validate(result)


@router.post("/preview", response_model=RAGPreviewResponse)
def rag_preview(
    payload: RAGPreviewRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb_ids = _workspace_kb_ids(db, workspace_id, payload.knowledge_base_ids)
    result = retrieve_for_writing(
        db,
        workspace_id=workspace_id,
        knowledge_base_ids=kb_ids,
        query=payload.query,
        phase=payload.phase,
        library_types=payload.library_types,
        target_volume_index=payload.target_volume_index,
        target_chapter_index=payload.target_chapter_index,
        top_k=payload.top_k,
        include_future=payload.include_future,
        include_raw=payload.include_raw,
    )
    return RAGPreviewResponse.model_validate(result)


def _workspace_kb_ids(db: Session, workspace_id: str, requested_ids: list[int]) -> list[int]:
    query = db.query(KnowledgeBase.id).filter(KnowledgeBase.workspace_id == workspace_id)
    if requested_ids:
        query = query.filter(KnowledgeBase.id.in_(requested_ids))
    return [item.id for item in query.all()]
