from __future__ import annotations

from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisJob, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from ..schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
    KnowledgeDocumentBulkDeleteRequest,
    KnowledgeDocumentBulkDeleteResponse,
    KnowledgeDocumentRead,
    KnowledgeImportJobRequest,
    KnowledgeImportResponse,
    KnowledgeTextCreate,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from ..services.knowledge_base import (
    add_document_from_text,
    add_uploaded_document,
    import_deconstruction_job,
    knowledge_base_storage_dir,
    reindex_document,
    search_knowledge,
)
from .workspace import get_workspace_id


router = APIRouter(tags=["knowledge"])


def _kb_read(db: Session, kb: KnowledgeBase) -> KnowledgeBaseRead:
    document_count = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id).count()
    chunk_count = db.query(KnowledgeChunk).filter(KnowledgeChunk.knowledge_base_id == kb.id).count()
    return KnowledgeBaseRead.model_validate(
        {
            "id": kb.id,
            "name": kb.name,
            "description": kb.description,
            "source_job_id": kb.source_job_id,
            "created_at": kb.created_at,
            "updated_at": kb.updated_at,
            "document_count": document_count,
            "chunk_count": chunk_count,
        }
    )


def _get_kb(db: Session, knowledge_base_id: int, workspace_id: str) -> KnowledgeBase:
    kb = db.get(KnowledgeBase, knowledge_base_id)
    if not kb or kb.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb


def _get_document(db: Session, document_id: int, workspace_id: str) -> KnowledgeDocument:
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    _get_kb(db, document.knowledge_base_id, workspace_id)
    return document


def _workspace_kb_ids(db: Session, workspace_id: str, requested_ids: list[int]) -> list[int]:
    query = db.query(KnowledgeBase.id).filter(KnowledgeBase.workspace_id == workspace_id)
    if requested_ids:
        query = query.filter(KnowledgeBase.id.in_(requested_ids))
    return [item.id for item in query.all()]


@router.get("/api/knowledge-bases", response_model=list[KnowledgeBaseRead])
def list_knowledge_bases(workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    items = db.query(KnowledgeBase).filter(KnowledgeBase.workspace_id == workspace_id).order_by(KnowledgeBase.updated_at.desc()).all()
    if not items:
        return []
    ids = [item.id for item in items]
    doc_counts = dict(
        db.query(KnowledgeDocument.knowledge_base_id, func.count(KnowledgeDocument.id))
        .filter(KnowledgeDocument.knowledge_base_id.in_(ids))
        .group_by(KnowledgeDocument.knowledge_base_id)
        .all()
    )
    chunk_counts = dict(
        db.query(KnowledgeChunk.knowledge_base_id, func.count(KnowledgeChunk.id))
        .filter(KnowledgeChunk.knowledge_base_id.in_(ids))
        .group_by(KnowledgeChunk.knowledge_base_id)
        .all()
    )
    return [
        KnowledgeBaseRead.model_validate(
            {
                "id": item.id,
                "name": item.name,
                "description": item.description,
                "source_job_id": item.source_job_id,
                "created_at": item.created_at,
                "updated_at": item.updated_at,
                "document_count": doc_counts.get(item.id, 0),
                "chunk_count": chunk_counts.get(item.id, 0),
            }
        )
        for item in items
    ]


@router.post("/api/knowledge-bases", response_model=KnowledgeBaseRead)
def create_knowledge_base(payload: KnowledgeBaseCreate, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = KnowledgeBase(name=payload.name, description=payload.description, workspace_id=workspace_id)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return _kb_read(db, kb)


@router.patch("/api/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeBaseRead)
def update_knowledge_base(
    knowledge_base_id: int,
    payload: KnowledgeBaseUpdate,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _get_kb(db, knowledge_base_id, workspace_id)
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(kb, key, value)
    db.commit()
    db.refresh(kb)
    return _kb_read(db, kb)


@router.delete("/api/knowledge-bases/{knowledge_base_id}")
def delete_knowledge_base(knowledge_base_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _get_kb(db, knowledge_base_id, workspace_id)
    base_dir = knowledge_base_storage_dir(kb)
    db.delete(kb)
    db.commit()
    if base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)
    return {"ok": True}


@router.get("/api/knowledge-bases/{knowledge_base_id}/documents", response_model=list[KnowledgeDocumentRead])
def list_documents(knowledge_base_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    _get_kb(db, knowledge_base_id, workspace_id)
    return (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )


@router.post("/api/knowledge-bases/{knowledge_base_id}/documents", response_model=KnowledgeImportResponse)
async def upload_documents(
    knowledge_base_id: int,
    files: list[UploadFile] = File(...),
    knowledge_type: str = Form("worldbuilding"),
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _get_kb(db, knowledge_base_id, workspace_id)
    imported: list[KnowledgeDocument] = []
    skipped = 0
    for upload in files:
        result = await add_uploaded_document(db, kb, upload, knowledge_type)
        if result.created:
            imported.append(result.document)
        else:
            skipped += 1
    return KnowledgeImportResponse(
        imported=imported,
        skipped_duplicates=skipped,
        message=f"已导入 {len(imported)} 个文档，跳过重复 {skipped} 个。",
    )


@router.post("/api/knowledge-bases/{knowledge_base_id}/documents/text", response_model=KnowledgeImportResponse)
def create_text_document(
    knowledge_base_id: int,
    payload: KnowledgeTextCreate,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _get_kb(db, knowledge_base_id, workspace_id)
    result = add_document_from_text(
        db,
        kb,
        filename=payload.filename,
        content=payload.content,
        knowledge_type=payload.knowledge_type,
    )
    imported = [result.document] if result.created else []
    skipped = 0 if result.created else 1
    return KnowledgeImportResponse(
        imported=imported,
        skipped_duplicates=skipped,
        message=f"已导入 {len(imported)} 个文本知识文档，跳过重复 {skipped} 个。",
    )


@router.post("/api/knowledge-bases/{knowledge_base_id}/import-job", response_model=KnowledgeImportResponse)
def import_job_outputs(
    knowledge_base_id: int,
    payload: KnowledgeImportJobRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _get_kb(db, knowledge_base_id, workspace_id)
    job = db.get(AnalysisJob, payload.job_id)
    if not job or not job.project or job.project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="拆书任务不存在")
    flags = payload.model_dump(exclude={"job_id"})
    imported, skipped = import_deconstruction_job(db, kb, job, flags)
    kb.source_job_id = job.id
    db.commit()
    return KnowledgeImportResponse(
        imported=imported,
        skipped_duplicates=skipped,
        message=f"已从拆书任务导入 {len(imported)} 个写作技巧指南文档，跳过重复 {skipped} 个。",
    )


@router.get("/api/documents/{document_id}", response_model=KnowledgeDocumentRead)
def get_document(document_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    return _get_document(db, document_id, workspace_id)


@router.post("/api/documents/{document_id}/reindex", response_model=KnowledgeDocumentRead)
def reindex(document_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    document = _get_document(db, document_id, workspace_id)
    return reindex_document(db, document)


@router.delete("/api/documents/{document_id}")
def delete_document(document_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    document = _get_document(db, document_id, workspace_id)
    stored_dir = Path(document.stored_path).parent if document.stored_path else None
    db.delete(document)
    db.commit()
    if stored_dir and stored_dir.exists():
        shutil.rmtree(stored_dir, ignore_errors=True)
    return {"ok": True}


@router.post("/api/knowledge-bases/{knowledge_base_id}/documents/bulk-delete", response_model=KnowledgeDocumentBulkDeleteResponse)
def bulk_delete_documents(
    knowledge_base_id: int,
    payload: KnowledgeDocumentBulkDeleteRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _get_kb(db, knowledge_base_id, workspace_id)
    query = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
    if payload.knowledge_type:
        query = query.filter(KnowledgeDocument.knowledge_type == payload.knowledge_type)
    if not payload.delete_all:
        unique_ids = list(dict.fromkeys(payload.document_ids))
        if not unique_ids:
            return KnowledgeDocumentBulkDeleteResponse(deleted=0, message="没有选择要删除的文件")
        query = query.filter(KnowledgeDocument.id.in_(unique_ids))

    documents = query.all()
    stored_dirs = [Path(document.stored_path).parent for document in documents if document.stored_path]
    for document in documents:
        db.delete(document)
    db.commit()
    for stored_dir in stored_dirs:
        if stored_dir.exists():
            shutil.rmtree(stored_dir, ignore_errors=True)
    return KnowledgeDocumentBulkDeleteResponse(deleted=len(documents), message=f"已删除 {len(documents)} 个文件")


@router.post("/api/retrieval/search", response_model=RetrievalSearchResponse)
def retrieval_search(payload: RetrievalSearchRequest, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb_ids = _workspace_kb_ids(db, workspace_id, payload.knowledge_base_ids)
    hits = search_knowledge(db, kb_ids, payload.query, payload.top_k) if kb_ids else []
    return RetrievalSearchResponse(hits=hits)
