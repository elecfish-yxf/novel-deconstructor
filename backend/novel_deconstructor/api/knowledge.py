from __future__ import annotations

from pathlib import Path
import shutil

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisJob, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from ..schemas import (
    KnowledgeBaseCreate,
    KnowledgeBaseRead,
    KnowledgeBaseUpdate,
    KnowledgeDocumentRead,
    KnowledgeImportJobRequest,
    KnowledgeImportResponse,
    RetrievalSearchRequest,
    RetrievalSearchResponse,
)
from ..services.knowledge_base import (
    add_uploaded_document,
    import_deconstruction_job,
    reindex_document,
    search_knowledge,
)


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


@router.get("/api/knowledge-bases", response_model=list[KnowledgeBaseRead])
def list_knowledge_bases(db: Session = Depends(get_db)):
    items = db.query(KnowledgeBase).order_by(KnowledgeBase.updated_at.desc()).all()
    return [_kb_read(db, item) for item in items]


@router.post("/api/knowledge-bases", response_model=KnowledgeBaseRead)
def create_knowledge_base(payload: KnowledgeBaseCreate, db: Session = Depends(get_db)):
    kb = KnowledgeBase(name=payload.name, description=payload.description)
    db.add(kb)
    db.commit()
    db.refresh(kb)
    return _kb_read(db, kb)


@router.patch("/api/knowledge-bases/{knowledge_base_id}", response_model=KnowledgeBaseRead)
def update_knowledge_base(knowledge_base_id: int, payload: KnowledgeBaseUpdate, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, knowledge_base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    values = payload.model_dump(exclude_unset=True)
    for key, value in values.items():
        setattr(kb, key, value)
    db.commit()
    db.refresh(kb)
    return _kb_read(db, kb)


@router.delete("/api/knowledge-bases/{knowledge_base_id}")
def delete_knowledge_base(knowledge_base_id: int, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, knowledge_base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    base_dir = None
    first_doc = db.query(KnowledgeDocument).filter(KnowledgeDocument.knowledge_base_id == kb.id).first()
    if first_doc and first_doc.stored_path:
        base_dir = Path(first_doc.stored_path).parents[1]
    db.delete(kb)
    db.commit()
    if base_dir and base_dir.exists():
        shutil.rmtree(base_dir, ignore_errors=True)
    return {"ok": True}


@router.get("/api/knowledge-bases/{knowledge_base_id}/documents", response_model=list[KnowledgeDocumentRead])
def list_documents(knowledge_base_id: int, db: Session = Depends(get_db)):
    if not db.get(KnowledgeBase, knowledge_base_id):
        raise HTTPException(status_code=404, detail="知识库不存在")
    return (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
        .order_by(KnowledgeDocument.created_at.desc())
        .all()
    )


@router.post("/api/knowledge-bases/{knowledge_base_id}/documents", response_model=KnowledgeImportResponse)
async def upload_documents(knowledge_base_id: int, files: list[UploadFile] = File(...), db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, knowledge_base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    imported: list[KnowledgeDocument] = []
    skipped = 0
    for upload in files:
        result = await add_uploaded_document(db, kb, upload)
        if result.created:
            imported.append(result.document)
        else:
            skipped += 1
    return KnowledgeImportResponse(
        imported=imported,
        skipped_duplicates=skipped,
        message=f"已导入 {len(imported)} 个文档，跳过重复 {skipped} 个。",
    )


@router.post("/api/knowledge-bases/{knowledge_base_id}/import-job", response_model=KnowledgeImportResponse)
def import_job_outputs(knowledge_base_id: int, payload: KnowledgeImportJobRequest, db: Session = Depends(get_db)):
    kb = db.get(KnowledgeBase, knowledge_base_id)
    if not kb:
        raise HTTPException(status_code=404, detail="知识库不存在")
    job = db.get(AnalysisJob, payload.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="拆书任务不存在")
    flags = payload.model_dump(exclude={"job_id"})
    imported, skipped = import_deconstruction_job(db, kb, job, flags)
    kb.source_job_id = job.id
    db.commit()
    return KnowledgeImportResponse(
        imported=imported,
        skipped_duplicates=skipped,
        message=f"已从拆书任务导入 {len(imported)} 个结构化知识文档，跳过重复 {skipped} 个。",
    )


@router.get("/api/documents/{document_id}", response_model=KnowledgeDocumentRead)
def get_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    return document


@router.post("/api/documents/{document_id}/reindex", response_model=KnowledgeDocumentRead)
def reindex(document_id: int, db: Session = Depends(get_db)):
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    return reindex_document(db, document)


@router.delete("/api/documents/{document_id}")
def delete_document(document_id: int, db: Session = Depends(get_db)):
    document = db.get(KnowledgeDocument, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    stored_dir = Path(document.stored_path).parent if document.stored_path else None
    db.delete(document)
    db.commit()
    if stored_dir and stored_dir.exists():
        shutil.rmtree(stored_dir, ignore_errors=True)
    return {"ok": True}


@router.post("/api/retrieval/search", response_model=RetrievalSearchResponse)
def retrieval_search(payload: RetrievalSearchRequest, db: Session = Depends(get_db)):
    hits = search_knowledge(db, payload.knowledge_base_ids, payload.query, payload.top_k)
    return RetrievalSearchResponse(hits=hits)
