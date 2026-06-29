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
    "_decode_markdown_bytes",
    "_load_markdown_payload",
    "_load_package_payload",
    "_resolve_local_knowledge_path",
]

def _load_package_payload(payload: KnowledgePackageImportRequest) -> dict[str, Any]:
    if payload.package_json:
        return payload.package_json
    if not payload.package_path:
        raise HTTPException(status_code=400, detail="请提供 package_path 或 package_json")
    raw_path = Path(payload.package_path)
    path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"知识包路径无效：{payload.package_path}") from exc
    allowed_roots = [
        PROJECT_ROOT.resolve(),
        get_settings().output_dir.resolve(),
        get_settings().knowledge_dir.resolve(),
        get_settings().storage_dir.resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="知识包路径必须位于项目目录、outputs 或 storage 内")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="知识包文件不存在")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"知识包 JSON 无法解析：{exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="知识包 JSON 顶层必须是对象")
    return data

def _load_markdown_payload(payload: KnowledgeMarkdownImportRequest) -> tuple[str, str]:
    if payload.content and payload.content.strip():
        return payload.content, payload.source_name or "external_knowledge.md"
    if not payload.source_path:
        raise HTTPException(status_code=400, detail="请提供 source_path 或 content")
    path = _resolve_local_knowledge_path(payload.source_path, allowed_suffixes={".md", ".markdown"})
    return path.read_text(encoding="utf-8-sig"), path.name

def _resolve_local_knowledge_path(raw_value: str, *, allowed_suffixes: set[str]) -> Path:
    raw_path = Path(raw_value)
    path = raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path
    try:
        resolved = path.resolve()
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"文件路径无效：{raw_value}") from exc
    settings = get_settings()
    allowed_roots = [
        PROJECT_ROOT.resolve(),
        settings.output_dir.resolve(),
        settings.knowledge_dir.resolve(),
        settings.storage_dir.resolve(),
    ]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise HTTPException(status_code=400, detail="文件路径必须位于项目目录、outputs 或 storage 内")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Markdown 文件不存在")
    if resolved.suffix.lower() not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="只支持 .md 或 .markdown 文件")
    return resolved

def _decode_markdown_bytes(data: bytes, source_name: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Markdown 文件不是有效 UTF-8：{source_name}") from exc

