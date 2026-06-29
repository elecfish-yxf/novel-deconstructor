from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
import json
import math
import re
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import PROJECT_ROOT
from ..config import get_settings
from ..database import SessionLocal, get_db
from ..models import DeconstructionSkill, KnowledgeBase, KnowledgeCard, Outline, WritingDraftJob, WritingMemory
from ..schemas import (
    KnowledgeCardBulkDeleteRequest,
    KnowledgeCardRead,
    KnowledgeCardUpdate,
    KnowledgeDocumentBulkDeleteResponse,
    KnowledgeMergeApplyResponse,
    KnowledgeMergePreviewResponse,
    KnowledgeMergeRequest,
    KnowledgeMergeStatsResponse,
    KnowledgeMarkdownDocBulkDeleteRequest,
    KnowledgeMarkdownImportRequest,
    KnowledgeMarkdownImportResponse,
    KnowledgeMarkdownDocContent,
    KnowledgeMarkdownDocRead,
    KnowledgeMarkdownDocSave,
    KnowledgeMarkdownSyncResponse,
    KnowledgePackageImportRequest,
    KnowledgePackageImportResponse,
    RAGSearchRequest,
    RAGSearchResponse,
    WorldbuildingDraftRequest,
    WorldbuildingDraftResponse,
    WritingDraftRequest,
    WritingDraftJobRead,
    WritingGenerateRequest,
    WritingGenerateResponse,
    WritingMemoryBulkDeleteRequest,
    WritingMemoryConfirmRequest,
    WritingMemoryCreate,
    WritingMemoryRead,
    WritingOutlineRequest,
    WritingRevisionRequest,
    WritingScopeBulkDeleteRequest,
    WritingScopeBulkDeleteResponse,
    OutlineCreate,
    OutlineUpdate,
    OutlineNode,
    OutlineTree,
)
from ..services.knowledge_cards import (
    BLOCKED_STATUSES,
    RETRIEVABLE_STATUSES,
    canonical_group_id,
    card_markdown_path,
    card_to_read,
    delete_card_physical,
    delete_markdown_doc,
    export_card_markdown,
    get_card_or_404,
    apply_knowledge_card_merges,
    import_knowledge_package,
    import_markdown_knowledge_source,
    knowledge_card_merge_stats,
    list_markdown_docs,
    normalized_title_hash,
    preview_knowledge_card_merges,
    read_markdown_doc,
    save_markdown_doc,
    sync_card_from_markdown,
    sync_deleted_markdown,
    sync_memory_card,
    unmerge_knowledge_card,
    used_knowledge_from_results,
    write_card_markdown,
)
from ..services.knowledge_base import search_knowledge
from ..services.llm_provider import DoubaoResponsesProvider, LLMProvider, LLMRequest, OpenAICompatibleProvider, is_doubao_base_url
from ..services.rag_retrieval import search_rag_cards
from ..services.retrieval_service import (
    delete_card_vector,
    delete_memory_vector,
    index_knowledge_card,
    index_writing_memory,
    rebuild_knowledge_base_vectors,
    retrieve_for_writing,
)
from .workspace import get_workspace_id


from ..services.writing.common import *
from ..services.writing.markdown import *
from ..services.writing.memory import *
from ..services.writing.merge import *
from ..services.writing import orchestration as writing_orchestration
from ..services.writing.orchestration import *
from ..services.writing.retrieval import *

router = APIRouter(prefix="/api/writing", tags=["writing"])
writing_orchestration.set_writing_model_resolver(lambda payload, settings: _resolve_writing_model(payload, settings))





@router.get("/memories", response_model=list[WritingMemoryRead])
def list_memories(
    knowledge_base_id: int,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_workspace_kb(db, workspace_id, knowledge_base_id)
    return (
        db.query(WritingMemory)
        .filter(WritingMemory.workspace_id == workspace_id, WritingMemory.knowledge_base_id == knowledge_base_id)
        .order_by(WritingMemory.updated_at.desc())
        .all()
    )


@router.post("/memories", response_model=WritingMemoryRead)
def create_memory(
    payload: WritingMemoryCreate,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, payload.knowledge_base_id)
    return _create_memory_record(
        db,
        kb,
        workspace_id=workspace_id,
        memory_type=payload.memory_type,
        title=payload.title,
        content=payload.content,
        tags=payload.tags,
        source_ref=payload.source_ref,
        source=payload.source,
        scope_level=payload.scope_level,
        volume_index=payload.volume_index,
        volume_title=payload.volume_title,
        chapter_index=payload.chapter_index,
        chapter_title=payload.chapter_title,
        valid_from_volume_index=payload.valid_from_volume_index,
        valid_from_chapter_index=payload.valid_from_chapter_index,
        valid_until_volume_index=payload.valid_until_volume_index,
        valid_until_chapter_index=payload.valid_until_chapter_index,
        reveal_at_volume_index=payload.reveal_at_volume_index,
        reveal_at_chapter_index=payload.reveal_at_chapter_index,
        retrievable=payload.retrievable,
        priority=payload.priority,
    )


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    memory = (
        db.query(WritingMemory)
        .filter(WritingMemory.id == memory_id, WritingMemory.workspace_id == workspace_id)
        .first()
    )
    if not memory:
        raise HTTPException(status_code=404, detail="Memory 不存在")
    kb = _ensure_workspace_kb(db, workspace_id, memory.knowledge_base_id)
    card = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == memory.knowledge_base_id, KnowledgeCard.card_id == f"MEM-{memory.id:03d}")
        .first()
    )
    if card:
        _safe_delete_card_vector(card)
        delete_card_physical(db, kb, card)
    _safe_delete_memory_vector(memory)
    db.delete(memory)
    db.commit()
    return {"ok": True}


@router.post("/memories/bulk-delete", response_model=KnowledgeDocumentBulkDeleteResponse)
def bulk_delete_memories(
    payload: WritingMemoryBulkDeleteRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    unique_ids = list(dict.fromkeys(payload.memory_ids))
    if not unique_ids:
        return KnowledgeDocumentBulkDeleteResponse(deleted=0, message="没有选择要删除的 Memory")
    memories = (
        db.query(WritingMemory)
        .filter(WritingMemory.workspace_id == workspace_id, WritingMemory.id.in_(unique_ids))
        .all()
    )
    deleted = _delete_memories_and_cards(db, workspace_id, memories)
    db.commit()
    return KnowledgeDocumentBulkDeleteResponse(deleted=deleted["memories"], message=f"已删除 {deleted['memories']} 条 Memory")


@router.post("/works/{work_id}/memory/confirm-outline", response_model=WritingMemoryRead)
def confirm_outline_memory(
    work_id: int,
    payload: WritingMemoryConfirmRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    _require_chapter_position(payload.volume_index, payload.chapter_index)
    outline_content = _chapter_outline_memory_content(payload)
    return _create_memory_record(
        db,
        kb,
        workspace_id=workspace_id,
        memory_type="ChapterOutline",
        title=_chapter_outline_title(payload),
        content=outline_content,
        tags=_unique_texts(["ChapterOutline", "outline", "approved", *payload.tags]),
        source_ref=_memory_source_ref(payload, raw_content_chars=len(payload.content)),
        source="confirmed_outline",
        scope_level="chapter",
        volume_index=payload.volume_index,
        volume_title=payload.volume_title,
        chapter_index=payload.chapter_index,
        chapter_title=payload.chapter_title,
        valid_from_volume_index=payload.valid_from_volume_index or payload.volume_index,
        valid_from_chapter_index=payload.valid_from_chapter_index or payload.chapter_index,
        valid_until_volume_index=payload.valid_until_volume_index,
        valid_until_chapter_index=payload.valid_until_chapter_index,
        reveal_at_volume_index=payload.reveal_at_volume_index or payload.volume_index,
        reveal_at_chapter_index=payload.reveal_at_chapter_index or payload.chapter_index,
        retrievable=True,
        priority=max(payload.priority, 60),
    )


@router.post("/works/{work_id}/memory/confirm-draft", response_model=WritingMemoryRead)
def confirm_draft_memory(
    work_id: int,
    payload: WritingMemoryConfirmRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    _require_chapter_position(payload.volume_index, payload.chapter_index)
    next_volume, next_chapter = _next_chapter_position(payload.volume_index, payload.chapter_index)
    handoff_content = _chapter_handoff_memory_content(payload, next_volume=next_volume, next_chapter=next_chapter)
    handoff = _create_memory_record(
        db,
        kb,
        workspace_id=workspace_id,
        memory_type="ChapterHandoff",
        title=_chapter_handoff_title(payload, next_volume=next_volume, next_chapter=next_chapter),
        content=handoff_content,
        tags=_unique_texts(["ChapterHandoff", "handoff", "continuity", "approved", *payload.tags]),
        source_ref=_memory_source_ref(payload, raw_content_chars=len(payload.content)),
        source="confirmed_draft",
        scope_level="chapter",
        volume_index=payload.volume_index,
        volume_title=payload.volume_title,
        chapter_index=payload.chapter_index,
        chapter_title=payload.chapter_title,
        valid_from_volume_index=payload.valid_from_volume_index or next_volume,
        valid_from_chapter_index=payload.valid_from_chapter_index or next_chapter,
        valid_until_volume_index=payload.valid_until_volume_index,
        valid_until_chapter_index=payload.valid_until_chapter_index,
        reveal_at_volume_index=payload.reveal_at_volume_index or next_volume,
        reveal_at_chapter_index=payload.reveal_at_chapter_index or next_chapter,
        retrievable=True,
        priority=max(payload.priority, 90),
    )
    _refresh_volume_continuity_memory(db, kb, workspace_id, payload.volume_index)
    return handoff


# ── Outline (书→卷→章 三层提纲树) API ──

@router.get("/works/{work_id}/outlines", response_model=OutlineTree)
def list_outlines(
    work_id: int,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """获取作品的完整提纲树（book→volume→chapter）。"""
    _ensure_workspace_kb(db, workspace_id, work_id)
    nodes = (
        db.query(Outline)
        .filter(Outline.knowledge_base_id == work_id)
        .order_by(Outline.level, Outline.seq, Outline.volume_index, Outline.chapter_index)
        .all()
    )
    node_map: dict[int, OutlineNode] = {}
    for node in nodes:
        node_map[node.id] = OutlineNode(
            id=node.id,
            knowledge_base_id=node.knowledge_base_id,
            level=node.level,
            seq=node.seq,
            volume_index=node.volume_index,
            chapter_index=node.chapter_index,
            title=node.title,
            content=node.content or "",
            source=node.source,
            status=node.status,
            created_at=node.created_at,
            updated_at=node.updated_at,
        )

    book_node = None
    volume_nodes: list[OutlineNode] = []
    chapter_nodes: list[OutlineNode] = []

    for node in nodes:
        onode = node_map[node.id]
        if node.parent_id and node.parent_id in node_map:
            node_map[node.parent_id].children.append(onode)
        if node.level == "book":
            book_node = onode
        elif node.level == "volume":
            volume_nodes.append(onode)
        elif node.level == "chapter":
            chapter_nodes.append(onode)

    return OutlineTree(
        knowledge_base_id=work_id,
        book_node=book_node,
        volume_nodes=volume_nodes,
        chapter_nodes=chapter_nodes,
    )


@router.post("/works/{work_id}/outlines", response_model=OutlineNode)
def create_outline(
    work_id: int,
    payload: OutlineCreate,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """创建提纲节点。"""
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    node = Outline(
        knowledge_base_id=kb.id,
        workspace_id=workspace_id,
        parent_id=payload.parent_id,
        level=payload.level,
        seq=payload.seq,
        volume_index=payload.volume_index,
        chapter_index=payload.chapter_index,
        title=payload.title,
        content=payload.content or "",
        source=payload.source,
        status=payload.status,
    )
    db.add(node)
    db.commit()
    db.refresh(node)
    return _outline_to_node(node)


@router.patch("/works/{work_id}/outlines/{node_id}", response_model=OutlineNode)
def update_outline(
    work_id: int,
    node_id: int,
    payload: OutlineUpdate,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """更新提纲节点。"""
    _ensure_workspace_kb(db, workspace_id, work_id)
    node = db.query(Outline).filter(Outline.id == node_id, Outline.knowledge_base_id == work_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="提纲节点不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(node, key, value)
    db.commit()
    db.refresh(node)
    return _outline_to_node(node)


@router.delete("/works/{work_id}/outlines/{node_id}")
def delete_outline(
    work_id: int,
    node_id: int,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """删除提纲节点（级联删除子节点）。"""
    _ensure_workspace_kb(db, workspace_id, work_id)
    node = db.query(Outline).filter(Outline.id == node_id, Outline.knowledge_base_id == work_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="提纲节点不存在")
    db.delete(node)
    db.commit()
    return {"ok": True}


@router.post("/works/{work_id}/outlines/sync-from-cards")
def sync_outlines_from_cards(
    work_id: int,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    """从知识卡自动同步生成书卷大纲。"""
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    result = sync_book_volume_outlines_from_cards(db, kb, workspace_id)
    return result


def _outline_to_node(node: Outline) -> OutlineNode:
    return OutlineNode(
        id=node.id,
        knowledge_base_id=node.knowledge_base_id,
        level=node.level,
        seq=node.seq,
        volume_index=node.volume_index,
        chapter_index=node.chapter_index,
        title=node.title,
        content=node.content or "",
        source=node.source,
        status=node.status,
        created_at=node.created_at,
        updated_at=node.updated_at,
    )


@router.post("/works/{work_id}/knowledge/import-package", response_model=KnowledgePackageImportResponse)
def import_package_to_work(
    work_id: int,
    payload: KnowledgePackageImportRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    package = _load_package_payload(payload)
    result = import_knowledge_package(
        db,
        kb,
        package,
        library_type=payload.library_type,
        status=payload.status,
        merge_mode=payload.merge_mode,
        auto_merge_threshold=payload.auto_merge_threshold,
        review_threshold=payload.review_threshold,
        generate_markdown=payload.generate_markdown,
    )
    # 知识卡导入后自动同步书卷大纲
    sync_book_volume_outlines_from_cards(db, kb, workspace_id)
    _safe_rebuild_kb_vectors(db, kb)
    return KnowledgePackageImportResponse(**result)


@router.post("/works/{work_id}/knowledge/import-markdown", response_model=KnowledgeMarkdownImportResponse)
def import_markdown_to_work(
    work_id: int,
    payload: KnowledgeMarkdownImportRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    markdown, source_name = _load_markdown_payload(payload)
    result = import_markdown_knowledge_source(
        db,
        kb,
        markdown,
        source_name=source_name,
        library_type=payload.library_type,
        status=payload.status,
    )
    # 知识卡导入后自动同步书卷大纲
    sync_book_volume_outlines_from_cards(db, kb, workspace_id)
    _safe_rebuild_kb_vectors(db, kb)
    return KnowledgeMarkdownImportResponse(**result)


@router.post("/works/{work_id}/knowledge/import-markdown-file", response_model=KnowledgeMarkdownImportResponse)
async def upload_markdown_to_work(
    work_id: int,
    file: UploadFile = File(...),
    library_type: str = Form("writing_guide"),
    status: str = Form("raw_extracted"),
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    source_name = file.filename or "external_knowledge.md"
    if Path(source_name).suffix.lower() not in {".md", ".markdown"}:
        raise HTTPException(status_code=400, detail="请上传 .md 或 .markdown 文件")
    max_bytes = get_settings().max_upload_size_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(status_code=413, detail="Markdown 文件超过上传大小限制")
    markdown = _decode_markdown_bytes(data, source_name)
    result = import_markdown_knowledge_source(
        db,
        kb,
        markdown,
        source_name=source_name,
        library_type=library_type,
        status=status,
    )
    # 知识卡导入后自动同步书卷大纲
    sync_book_volume_outlines_from_cards(db, kb, workspace_id)
    _safe_rebuild_kb_vectors(db, kb)
    return KnowledgeMarkdownImportResponse(**result)


@router.get("/works/{work_id}/knowledge/cards", response_model=list[KnowledgeCardRead])
def list_cards(
    work_id: int,
    library_type: str | None = None,
    card_type: str | None = None,
    status: str | None = None,
    tag: str | None = None,
    keyword: str | None = None,
    is_canonical: bool | None = None,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_workspace_kb(db, workspace_id, work_id)
    query = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id == work_id)
    if library_type:
        query = query.filter(KnowledgeCard.library_type == library_type)
    if card_type:
        query = query.filter(KnowledgeCard.card_type == card_type)
    if status:
        query = query.filter(KnowledgeCard.status == status)
    if is_canonical is not None:
        query = query.filter(KnowledgeCard.is_canonical.is_(is_canonical))
    if tag:
        query = query.filter(KnowledgeCard.tags_json.ilike(f"%{tag}%"))
    if keyword:
        pattern = f"%{keyword}%"
        query = query.filter(
            KnowledgeCard.title.ilike(pattern)
            | KnowledgeCard.summary.ilike(pattern)
            | KnowledgeCard.content.ilike(pattern)
            | KnowledgeCard.tags_json.ilike(pattern)
        )
    cards = query.order_by(KnowledgeCard.library_type, KnowledgeCard.card_type, KnowledgeCard.card_id).all()
    return [KnowledgeCardRead.model_validate(card_to_read(card)) for card in cards]


@router.post("/works/{work_id}/knowledge/merge/preview", response_model=KnowledgeMergePreviewResponse)
def preview_card_merges(
    work_id: int,
    payload: KnowledgeMergeRequest | None = None,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    payload = payload or KnowledgeMergeRequest()
    return KnowledgeMergePreviewResponse.model_validate(
        preview_knowledge_card_merges(
            db,
            kb,
            merge_mode=payload.merge_mode,
            auto_merge_threshold=payload.auto_merge_threshold,
            review_threshold=payload.review_threshold,
        )
    )


@router.post("/works/{work_id}/knowledge/merge/apply", response_model=KnowledgeMergeApplyResponse)
def apply_card_merges(
    work_id: int,
    payload: KnowledgeMergeRequest | None = None,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    payload = payload or KnowledgeMergeRequest()
    result = apply_knowledge_card_merges(
        db,
        kb,
        merge_mode=payload.merge_mode,
        auto_merge_threshold=payload.auto_merge_threshold,
        review_threshold=payload.review_threshold,
    )
    _safe_rebuild_kb_vectors(db, kb)
    return KnowledgeMergeApplyResponse.model_validate(result)


@router.get("/works/{work_id}/knowledge/merge/stats", response_model=KnowledgeMergeStatsResponse)
def card_merge_stats(work_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return KnowledgeMergeStatsResponse.model_validate(knowledge_card_merge_stats(db, kb))


@router.get("/works/{work_id}/knowledge/cards/{card_id}", response_model=KnowledgeCardRead)
def read_card(work_id: int, card_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return KnowledgeCardRead.model_validate(card_to_read(get_card_or_404(db, kb, card_id)))


@router.patch("/works/{work_id}/knowledge/cards/{card_id}", response_model=KnowledgeCardRead)
def update_card(
    work_id: int,
    card_id: str,
    payload: KnowledgeCardUpdate,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    card = get_card_or_404(db, kb, card_id)
    values = payload.model_dump(exclude_unset=True)
    json_fields = {"tags": "tags_json", "source_ref": "source_ref_json", "source_refs": "source_refs_json", "use_when": "use_when_json"}
    for key, value in values.items():
        if key in json_fields:
            setattr(card, json_fields[key], json.dumps(value, ensure_ascii=False))
        else:
            setattr(card, key, value)
    write_card_markdown(kb, card)
    db.commit()
    db.refresh(card)
    _safe_index_card(db, card)
    return KnowledgeCardRead.model_validate(card_to_read(card))


@router.delete("/works/{work_id}/knowledge/cards/{card_id}", response_model=KnowledgeCardRead)
def delete_card(work_id: int, card_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    card = get_card_or_404(db, kb, card_id)
    result = card_to_read(card)
    _safe_delete_card_vector(card)
    delete_card_physical(db, kb, card)
    db.commit()
    return KnowledgeCardRead.model_validate(result)


@router.post("/works/{work_id}/knowledge/cards/bulk-delete", response_model=KnowledgeDocumentBulkDeleteResponse)
def bulk_delete_cards(
    work_id: int,
    payload: KnowledgeCardBulkDeleteRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    unique_ids = [item for item in dict.fromkeys(payload.card_ids) if item]
    if not unique_ids:
        return KnowledgeDocumentBulkDeleteResponse(deleted=0, message="没有选择要删除的知识卡")
    cards = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == kb.id, KnowledgeCard.card_id.in_(unique_ids))
        .all()
    )
    deleted_files = 0
    for card in cards:
        _safe_delete_card_vector(card)
        if delete_card_physical(db, kb, card):
            deleted_files += 1
    db.commit()
    return KnowledgeDocumentBulkDeleteResponse(deleted=len(cards), message=f"已删除 {len(cards)} 张知识卡，清理 {deleted_files} 个 Markdown 文件")


@router.post("/works/{work_id}/knowledge/cards/{card_id}/unmerge", response_model=KnowledgeCardRead)
def unmerge_card(work_id: int, card_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    card = unmerge_knowledge_card(db, kb, card_id)
    _safe_index_card(db, card)
    return KnowledgeCardRead.model_validate(card_to_read(card))


@router.get("/works/{work_id}/knowledge/docs", response_model=list[KnowledgeMarkdownDocRead])
def list_docs(work_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return [KnowledgeMarkdownDocRead.model_validate(item) for item in list_markdown_docs(db, kb)]


@router.get("/works/{work_id}/knowledge/docs/{doc_id}", response_model=KnowledgeMarkdownDocContent)
def read_doc(work_id: int, doc_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return KnowledgeMarkdownDocContent.model_validate(read_markdown_doc(db, kb, doc_id))


@router.put("/works/{work_id}/knowledge/docs/{doc_id}", response_model=KnowledgeMarkdownDocContent)
def save_doc(
    work_id: int,
    doc_id: str,
    payload: KnowledgeMarkdownDocSave,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return KnowledgeMarkdownDocContent.model_validate(save_markdown_doc(db, kb, doc_id, payload.content))


@router.delete("/works/{work_id}/knowledge/docs/{doc_id}", response_model=KnowledgeMarkdownSyncResponse)
def delete_doc(work_id: int, doc_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    _safe_delete_card_vector(doc_id)
    return KnowledgeMarkdownSyncResponse.model_validate(delete_markdown_doc(db, kb, doc_id))


@router.post("/works/{work_id}/knowledge/docs/bulk-delete", response_model=KnowledgeDocumentBulkDeleteResponse)
def bulk_delete_docs(
    work_id: int,
    payload: KnowledgeMarkdownDocBulkDeleteRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    unique_ids = [item for item in dict.fromkeys(payload.doc_ids) if item]
    if not unique_ids:
        return KnowledgeDocumentBulkDeleteResponse(deleted=0, message="没有选择要删除的 Markdown 文档")
    cards = (
        db.query(KnowledgeCard)
        .filter(KnowledgeCard.knowledge_base_id == kb.id, KnowledgeCard.card_id.in_(unique_ids))
        .all()
    )
    deleted_files = 0
    for card in cards:
        _safe_delete_card_vector(card)
        if delete_card_physical(db, kb, card):
            deleted_files += 1
    db.commit()
    return KnowledgeDocumentBulkDeleteResponse(deleted=len(cards), message=f"已删除 {len(cards)} 个 Markdown 文档，清理 {deleted_files} 个文件")


@router.post("/works/{work_id}/knowledge/docs/{doc_id}/sync", response_model=KnowledgeMarkdownSyncResponse)
def sync_doc_to_card(work_id: int, doc_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    result = sync_card_from_markdown(db, kb, doc_id)
    _safe_index_card(db, get_card_or_404(db, kb, doc_id))
    return KnowledgeMarkdownSyncResponse.model_validate(result)


@router.post("/works/{work_id}/knowledge/cards/{card_id}/export-md", response_model=KnowledgeMarkdownDocContent)
def export_card_to_doc(work_id: int, card_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    result = export_card_markdown(db, kb, card_id)
    _safe_index_card(db, get_card_or_404(db, kb, card_id))
    return KnowledgeMarkdownDocContent.model_validate(result)


@router.post("/works/{work_id}/knowledge/docs/sync-deleted", response_model=KnowledgeMarkdownSyncResponse)
def sync_deleted_docs(work_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    result = sync_deleted_markdown(db, kb)
    _safe_rebuild_kb_vectors(db, kb)
    return KnowledgeMarkdownSyncResponse.model_validate(result)


@router.post("/works/{work_id}/chapters/bulk-delete", response_model=WritingScopeBulkDeleteResponse)
def bulk_delete_writing_scope(
    work_id: int,
    payload: WritingScopeBulkDeleteRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    volume_indices = {int(item) for item in payload.volume_indices if int(item) > 0}
    chapter_refs = {(item.volume_index, item.chapter_index) for item in payload.chapters}
    if not volume_indices and not chapter_refs:
        return WritingScopeBulkDeleteResponse(message="没有选择要删除的卷或章")

    memories = (
        db.query(WritingMemory)
        .filter(WritingMemory.workspace_id == workspace_id, WritingMemory.knowledge_base_id == kb.id)
        .all()
    )
    scoped_memories = [
        memory
        for memory in memories
        if _matches_writing_scope(memory.volume_index, memory.chapter_index, volume_indices, chapter_refs)
    ]
    memory_card_ids = {f"MEM-{memory.id:03d}" for memory in scoped_memories}

    cards = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id == kb.id).all()
    scoped_cards = {
        card.card_id: card
        for card in cards
        if card.card_id in memory_card_ids
        or _matches_writing_scope(card.volume_index, card.chapter_index, volume_indices, chapter_refs)
    }

    deleted_files = 0
    for card in scoped_cards.values():
        _safe_delete_card_vector(card)
        if delete_card_physical(db, kb, card):
            deleted_files += 1
    for memory in scoped_memories:
        _safe_delete_memory_vector(memory)
        db.delete(memory)
    db.commit()
    for volume_index in sorted({volume for volume, _chapter in chapter_refs if volume not in volume_indices}):
        _refresh_volume_continuity_memory(db, kb, workspace_id, volume_index)

    return WritingScopeBulkDeleteResponse(
        deleted_volumes=len(volume_indices),
        deleted_chapters=len(chapter_refs),
        deleted_memories=len(scoped_memories),
        deleted_cards=len(scoped_cards),
        deleted_markdown_files=deleted_files,
        message=f"已删除 {len(volume_indices)} 卷、{len(chapter_refs)} 章，清理 {len(scoped_memories)} 条 Memory 和 {len(scoped_cards)} 张知识卡",
    )


@router.post("/works/{work_id}/rag/search", response_model=RAGSearchResponse)
def rag_search(
    work_id: int,
    payload: RAGSearchRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_workspace_kb(db, workspace_id, work_id)
    results, debug = search_rag_cards(
        db,
        [work_id],
        stage=payload.stage,
        query=payload.query,
        top_k=payload.top_k,
        library_type=payload.library_type,
        include_inactive=payload.include_inactive,
        current_volume_index=payload.current_volume_index,
        current_chapter_index=payload.current_chapter_index,
        include_future=payload.include_future,
        include_raw=payload.include_raw,
        allowed_scope_levels=payload.allowed_scope_levels,
    )
    return RAGSearchResponse(results=results, retrieval_debug=debug)


@router.post("/works/{work_id}/agent/outline", response_model=WritingGenerateResponse)
async def generate_work_outline(
    work_id: int,
    payload: WritingOutlineRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return await _generate_with_cards(db, kb, payload, stage="outline", confirmed_outline="")


@router.post("/works/{work_id}/agent/draft", response_model=WritingGenerateResponse)
async def generate_work_draft(
    work_id: int,
    payload: WritingDraftRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return await _generate_with_cards(db, kb, payload, stage="draft", confirmed_outline=payload.confirmed_outline)


@router.post("/works/{work_id}/agent/draft-jobs", response_model=WritingDraftJobRead)
async def create_work_draft_job(
    work_id: int,
    payload: WritingDraftRequest,
    background_tasks: BackgroundTasks,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    _ensure_workspace_kb(db, workspace_id, work_id)
    job_id = uuid.uuid4().hex
    now = datetime.utcnow()
    target_chars = _resolve_target_chars(payload)
    job = WritingDraftJob(
        job_id=job_id,
        work_id=work_id,
        workspace_id=workspace_id,
        status="queued",
        stage="draft",
        target_chars=target_chars,
        content="",
        sections_json="[]",
        used_knowledge_json="[]",
        retrieval_debug_json=None,
        warnings_json=json.dumps(["长文本任务已排队；确认正文前不会写入 Memory。"], ensure_ascii=False),
        request_payload_json=_draft_request_payload_json(payload),
        created_at=now,
        updated_at=now,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    background_tasks.add_task(_run_draft_generation_job, job_id, work_id, workspace_id, payload.model_dump())
    return _draft_job_read(job)


@router.get("/works/{work_id}/agent/draft-jobs/{job_id}", response_model=WritingDraftJobRead)
def read_work_draft_job(
    work_id: int,
    job_id: str,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    return _job_read_or_404(db, job_id, workspace_id, work_id)


@router.post("/works/{work_id}/agent/draft-jobs/{job_id}/cancel", response_model=WritingDraftJobRead)
def cancel_work_draft_job(
    work_id: int,
    job_id: str,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    job = _job_or_404(db, job_id, workspace_id, work_id)
    if job.status not in DRAFT_TERMINAL_STATUSES:
        warnings = _job_json_list(job.warnings_json)
        warning = "用户已取消任务；已完成内容保留在 job 中。"
        if warning not in warnings:
            warnings.append(warning)
        job.status = "cancelled"
        job.warnings_json = json.dumps(warnings, ensure_ascii=False)
        job.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(job)
    return _draft_job_read(job)


@router.post("/works/{work_id}/agent/revision", response_model=WritingGenerateResponse)
async def generate_work_revision(
    work_id: int,
    payload: WritingRevisionRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    kb = _ensure_workspace_kb(db, workspace_id, work_id)
    return await _generate_with_cards(db, kb, payload, stage="revision", confirmed_outline=payload.confirmed_outline)


@router.post("/outline", response_model=WritingGenerateResponse, deprecated=True)
async def generate_outline(
    payload: WritingOutlineRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    kb_ids = _workspace_kb_ids(db, workspace_id, payload.knowledge_base_ids)
    hits = _retrieve_for_agent_task(db, kb_ids, "outline", _outline_query(payload), settings.retrieval_top_k) if kb_ids else []
    if payload.knowledge_mode == "strict" and not hits:
        pos = f"V{payload.current_volume_index}C{payload.current_chapter_index}" if payload.current_volume_index and payload.current_chapter_index else "未设置"
        return WritingGenerateResponse(
            content=f"严格知识模式：知识库检索结果为空（位置：{pos}，知识库：{kb_ids or '未选择'}）。\n\n请检查知识卡状态（需 approved/reviewed）、当前位置设置，或切换到「参考知识」模式。",
            citations=[],
        )
    memories = _recent_memories(db, workspace_id, kb_ids)
    if payload.dry_run:
        return WritingGenerateResponse(content=_dry_run_outline(payload, hits, memories), citations=hits)

    provider, model = _resolve_writing_model(payload, settings)
    oh_story_kernel = _oh_story_writing_kernel(db)
    request = LLMRequest(
        system_prompt=_system_prompt(payload.knowledge_mode, oh_story_kernel, stage="outline"),
        user_prompt=_outline_prompt(payload, hits, memories, oh_story_kernel),
        model=model,
        temperature=0.3 if payload.mode == "fast" else 0.2,
        max_tokens=settings.openai_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        retry_count=settings.llm_retry_count,
        dry_run=False,
    )
    try:
        content = await provider.complete(request)
    except Exception as exc:  # noqa: BLE001 - display concise Chinese message to frontend.
        raise HTTPException(status_code=502, detail=f"章节提纲生成失败：{exc}") from exc
    return WritingGenerateResponse(content=content, citations=hits)


@router.post("/draft", response_model=WritingGenerateResponse, deprecated=True)
async def generate_draft(
    payload: WritingDraftRequest,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    kb_ids = _workspace_kb_ids(db, workspace_id, payload.knowledge_base_ids)
    hits = _retrieve_for_agent_task(db, kb_ids, "draft", _draft_query(payload), settings.retrieval_top_k) if kb_ids else []
    if payload.knowledge_mode == "strict" and not hits:
        pos = f"V{payload.current_volume_index}C{payload.current_chapter_index}" if payload.current_volume_index and payload.current_chapter_index else "未设置"
        return WritingGenerateResponse(
            content=f"严格知识模式：知识库检索结果为空（位置：{pos}，知识库：{kb_ids or '未选择'}）。\n\n请检查知识卡状态（需 approved/reviewed）、当前位置设置，或切换到「参考知识」模式。",
            citations=[],
        )
    memories = _recent_memories(db, workspace_id, kb_ids)
    if payload.dry_run:
        return WritingGenerateResponse(content=_dry_run_draft(payload, hits, memories), citations=hits)

    provider, model = _resolve_writing_model(payload, settings)
    oh_story_kernel = _oh_story_writing_kernel(db)
    request = LLMRequest(
        system_prompt=_system_prompt(payload.knowledge_mode, oh_story_kernel, stage="draft"),
        user_prompt=_draft_prompt(payload, hits, memories, oh_story_kernel),
        model=model,
        temperature=0.35 if payload.mode == "fast" else 0.25,
        max_tokens=settings.openai_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        retry_count=settings.llm_retry_count,
        dry_run=False,
    )
    try:
        content = await provider.complete(request)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"正文生成失败：{exc}") from exc
    return WritingGenerateResponse(content=content, citations=hits)


@router.post("/generate", response_model=WritingGenerateResponse, deprecated=True)
async def generate(payload: WritingGenerateRequest, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    """Backward-compatible endpoint. New UI uses /outline and /draft."""
    outline_payload = WritingOutlineRequest(**payload.model_dump())
    return await generate_outline(outline_payload, workspace_id, db)


@router.post("/worldbuilding-draft", response_model=WorldbuildingDraftResponse)
async def worldbuilding_draft(payload: WorldbuildingDraftRequest, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    settings = get_settings()
    kb_ids = _workspace_kb_ids(db, workspace_id, payload.knowledge_base_ids)
    hits = _retrieve_for_agent_task(db, kb_ids, "worldbuilding_draft", payload.story_seed, settings.retrieval_top_k) if kb_ids else []
    memories = _recent_memories(db, workspace_id, kb_ids)
    if payload.dry_run:
        return WorldbuildingDraftResponse(content=_dry_run_worldbuilding(payload, hits), citations=hits)
    provider, model = _resolve_writing_model(payload, settings)
    oh_story_kernel = _oh_story_writing_kernel(db)
    request = LLMRequest(
        system_prompt=f"你是原创小说世界观设定助手，使用 oh-story 作为写作内核。你可以参考写作技巧指南和长期 Memory，但不能沿用被拆解作品的专名、势力、地理、人物或独特设定。输出一份可由用户确认后导入知识库的原创世界观设定。\n\n{oh_story_kernel}",
        user_prompt=_worldbuilding_prompt(payload, hits, memories, oh_story_kernel),
        model=model,
        temperature=0.3,
        max_tokens=settings.openai_max_tokens,
        timeout_seconds=settings.llm_timeout_seconds,
        retry_count=settings.llm_retry_count,
    )
    try:
        content = await provider.complete(request)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"世界观草案生成失败：{exc}") from exc
    return WorldbuildingDraftResponse(content=content, citations=hits)


















































































































































































































































































