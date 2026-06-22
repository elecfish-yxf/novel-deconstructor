from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math
import re
import shutil

from fastapi import HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import AnalysisJob, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from ..services.exporter import list_result_files
from ..services.file_parser import normalize_text_file, save_upload, validate_extension
from ..services.path_safety import secure_slug


HEADING_RE = re.compile(r"^(#{1,3})\s+(.+?)\s*$")
PDF_PAGE_RE = re.compile(r"<!--\s*PDF\s+第\s*(\d+)\s*页\s*-->")
WORD_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z0-9_]+")
IMPORTABLE_SUFFIXES = {".md", ".txt"}
DECONSTRUCTION_DIR_FLAGS = {
    "chapter_analysis": "include_chapter_analysis",
    "final_reports": "include_final_reports",
    "knowledge_base": "include_knowledge_base",
    "knowledge_base_obsidian": "include_obsidian",
    "graph_outputs": "include_graph",
    "拆文库": "include_oh_story",
}
KNOWLEDGE_TYPES = {"writing_guide", "worldbuilding"}


@dataclass
class DocumentBuildResult:
    document: KnowledgeDocument
    created: bool


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_upload_name(filename: str) -> str:
    path = Path(filename)
    suffix = path.suffix.lower()
    stem = secure_slug(path.stem, "document")
    return f"{stem}{suffix}"


def normalize_knowledge_type(value: str | None, default: str = "worldbuilding") -> str:
    return value if value in KNOWLEDGE_TYPES else default


async def add_uploaded_document(
    db: Session,
    knowledge_base: KnowledgeBase,
    upload: UploadFile,
    knowledge_type: str = "worldbuilding",
) -> DocumentBuildResult:
    settings = get_settings()
    file_type = validate_extension(upload.filename or "document")
    safe_name = safe_upload_name(upload.filename or f"document.{file_type}")
    incoming = settings.knowledge_dir / str(knowledge_base.id) / "_incoming" / safe_name
    size = await save_upload(upload, incoming, settings.max_upload_size_mb * 1024 * 1024)
    try:
        return add_document_from_path(
            db,
            knowledge_base,
            incoming,
            original_filename=upload.filename or safe_name,
            source_kind="upload",
            knowledge_type=normalize_knowledge_type(knowledge_type),
            source_path_label=upload.filename or safe_name,
            structure_path=safe_name,
            size_bytes=size,
            move_source=True,
        )
    finally:
        incoming.unlink(missing_ok=True)


def add_document_from_path(
    db: Session,
    knowledge_base: KnowledgeBase,
    file_path: Path,
    *,
    original_filename: str | None = None,
    source_kind: str = "upload",
    knowledge_type: str = "worldbuilding",
    source_path_label: str | None = None,
    structure_path: str | None = None,
    size_bytes: int | None = None,
    move_source: bool = False,
) -> DocumentBuildResult:
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="知识库源文件不存在")
    file_type = validate_extension(original_filename or file_path.name)
    file_hash = sha256_file(file_path)
    existing = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == knowledge_base.id, KnowledgeDocument.file_hash == file_hash)
        .first()
    )
    if existing:
        return DocumentBuildResult(existing, False)

    document = KnowledgeDocument(
        knowledge_base_id=knowledge_base.id,
        original_filename=original_filename or file_path.name,
        stored_path="",
        file_type=file_type,
        size_bytes=size_bytes if size_bytes is not None else file_path.stat().st_size,
        file_hash=file_hash,
        document_title=_document_title(original_filename or file_path.name),
        source_kind=source_kind,
        knowledge_type=normalize_knowledge_type(knowledge_type),
        source_path=source_path_label or file_path.name,
        structure_path=structure_path or file_path.name,
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    target_dir = get_settings().knowledge_dir / str(knowledge_base.id) / str(document.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_path = target_dir / safe_upload_name(original_filename or file_path.name)
    if move_source:
        shutil.move(str(file_path), stored_path)
    else:
        shutil.copy2(file_path, stored_path)
    document.stored_path = str(stored_path)
    document.normalized_path = str(target_dir / "normalized.txt")
    db.commit()
    reindex_document(db, document)
    return DocumentBuildResult(document, True)


def add_document_from_text(
    db: Session,
    knowledge_base: KnowledgeBase,
    *,
    filename: str,
    content: str,
    knowledge_type: str = "worldbuilding",
    source_kind: str = "user_text",
    structure_path: str | None = None,
) -> DocumentBuildResult:
    text = content.strip()
    if not text:
        raise HTTPException(status_code=400, detail="知识文档内容不能为空")
    safe_name = safe_upload_name(filename or "worldbuilding.md")
    if Path(safe_name).suffix.lower() not in {".md", ".txt"}:
        safe_name = f"{Path(safe_name).stem}.md"
    file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    existing = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.knowledge_base_id == knowledge_base.id, KnowledgeDocument.file_hash == file_hash)
        .first()
    )
    if existing:
        return DocumentBuildResult(existing, False)

    document = KnowledgeDocument(
        knowledge_base_id=knowledge_base.id,
        original_filename=safe_name,
        stored_path="",
        file_type=Path(safe_name).suffix.lower().lstrip(".") or "md",
        size_bytes=len(text.encode("utf-8")),
        file_hash=file_hash,
        document_title=_document_title(safe_name),
        source_kind=source_kind,
        knowledge_type=normalize_knowledge_type(knowledge_type),
        source_path=safe_name,
        structure_path=structure_path or safe_name,
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    target_dir = get_settings().knowledge_dir / str(knowledge_base.id) / str(document.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    stored_path = target_dir / safe_name
    stored_path.write_text(text + "\n", encoding="utf-8")
    document.stored_path = str(stored_path)
    document.normalized_path = str(target_dir / "normalized.txt")
    db.commit()
    reindex_document(db, document)
    return DocumentBuildResult(document, True)


def reindex_document(db: Session, document: KnowledgeDocument) -> KnowledgeDocument:
    try:
        document.status = "parsing"
        document.error_message = None
        db.query(KnowledgeChunk).filter(KnowledgeChunk.document_id == document.id).delete()
        db.commit()

        normalized_path = Path(document.normalized_path or "")
        meta = normalize_text_file(Path(document.stored_path), normalized_path)
        text = normalized_path.read_text(encoding="utf-8", errors="ignore")
        document.status = "indexing"
        document.page_count = _page_count(text)
        document.paragraph_count = len(_paragraphs(text))
        db.commit()

        chunks = split_knowledge_text(text, document)
        for chunk in chunks:
            db.add(chunk)
        document.chunk_count = len(chunks)
        document.status = "completed"
        document.error_message = None
        document.document_title = document.document_title or _document_title(document.original_filename)
        document.normalized_path = str(normalized_path)
        if meta.get("parser") == "pdf" and not chunks:
            raise ValueError("该文件可能是扫描版 PDF，当前版本暂未启用 OCR，未进行索引。")
        db.commit()
    except Exception as exc:  # noqa: BLE001 - shown as a readable status in UI.
        db.rollback()
        document.status = "failed"
        document.error_message = str(exc)
        document.chunk_count = 0
        db.commit()
    db.refresh(document)
    return document


def split_knowledge_text(text: str, document: KnowledgeDocument) -> list[KnowledgeChunk]:
    settings = get_settings()
    chunk_size = max(settings.knowledge_chunk_size, 200)
    overlap = max(min(settings.knowledge_chunk_overlap, chunk_size // 2), 0)
    blocks = _structured_blocks(text)
    chunks: list[KnowledgeChunk] = []
    current_text = ""
    current_heading = ""
    current_page: int | None = None
    current_meta: dict = {}

    def flush() -> None:
        nonlocal current_text, current_heading, current_page, current_meta
        clean = current_text.strip()
        if not clean:
            return
        for piece in _split_long_text(clean, chunk_size, overlap):
            index = len(chunks) + 1
            metadata = {
                "file_hash": document.file_hash,
                "source_kind": document.source_kind,
                "knowledge_type": document.knowledge_type,
                "source_path": document.source_path,
                "structure_path": document.structure_path,
                **current_meta,
            }
            chunk_hash = hashlib.sha1(f"{document.id}:{index}:{piece}".encode("utf-8")).hexdigest()[:12]
            chunks.append(
                KnowledgeChunk(
                    id=f"kb{document.knowledge_base_id}_doc{document.id}_{index:04d}_{chunk_hash}",
                    knowledge_base_id=document.knowledge_base_id,
                    document_id=document.id,
                    chunk_index=index,
                    heading=current_heading,
                    page_number=current_page,
                    text=piece,
                    token_estimate=max(1, len(piece) // 2),
                    metadata_json=json.dumps(metadata, ensure_ascii=False),
                )
            )
        current_text = ""

    for block in blocks:
        block_text = block["text"].strip()
        if not block_text:
            continue
        projected = f"{current_text}\n\n{block_text}".strip() if current_text else block_text
        if current_text and len(projected) > chunk_size:
            flush()
            if overlap and chunks:
                current_text = chunks[-1].text[-overlap:]
        current_heading = block.get("heading") or current_heading
        current_page = block.get("page_number") or current_page
        current_meta = block.get("metadata") or {}
        current_text = f"{current_text}\n\n{block_text}".strip() if current_text else block_text
    flush()
    return chunks


def import_deconstruction_job(
    db: Session,
    knowledge_base: KnowledgeBase,
    job: AnalysisJob,
    include_flags: dict[str, bool],
) -> tuple[list[KnowledgeDocument], int]:
    output_dir = Path(job.output_dir)
    imported: list[KnowledgeDocument] = []
    skipped = 0
    for item in list_result_files(output_dir):
        source = output_dir / item.path
        suffix = source.suffix.lower()
        if suffix not in IMPORTABLE_SUFFIXES:
            continue
        top = item.path.split("/", 1)[0]
        flag = DECONSTRUCTION_DIR_FLAGS.get(top)
        if flag and not include_flags.get(flag, True):
            continue
        if top not in DECONSTRUCTION_DIR_FLAGS:
            continue
        result = add_document_from_path(
            db,
            knowledge_base,
            source,
            original_filename=item.path,
            source_kind="deconstruction_job",
            knowledge_type="writing_guide",
            source_path_label=item.path,
            structure_path=item.path,
        )
        if result.created:
            imported.append(result.document)
        else:
            skipped += 1
    return imported, skipped


def search_knowledge(db: Session, knowledge_base_ids: list[int], query: str, top_k: int | None = None) -> list[dict]:
    settings = get_settings()
    limit = max(1, min(top_k or settings.retrieval_top_k, 20))
    q = (query or "").strip()
    if not q:
        return []
    chunks_query = db.query(KnowledgeChunk, KnowledgeDocument).join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
    if knowledge_base_ids:
        chunks_query = chunks_query.filter(KnowledgeChunk.knowledge_base_id.in_(knowledge_base_ids))
    rows = chunks_query.filter(KnowledgeDocument.status == "completed").all()
    scored: list[tuple[float, KnowledgeChunk, KnowledgeDocument]] = []
    for chunk, document in rows:
        score = _score_text(q, "\n".join([chunk.heading or "", document.original_filename, document.structure_path, chunk.text]))
        if score > 0:
            scored.append((score, chunk, document))
    scored.sort(key=lambda item: item[0], reverse=True)

    hits: list[dict] = []
    seen_docs: set[int] = set()
    for score, chunk, document in scored:
        if len(hits) >= limit:
            break
        if len(hits) >= max(3, limit // 2) and document.id in seen_docs:
            continue
        seen_docs.add(document.id)
        hits.append(_hit_dict(len(hits) + 1, score, chunk, document))
    if len(hits) < limit:
        existing = {hit["chunk_id"] for hit in hits}
        for score, chunk, document in scored:
            if len(hits) >= limit:
                break
            if chunk.id in existing:
                continue
            hits.append(_hit_dict(len(hits) + 1, score, chunk, document))
    return hits


def _hit_dict(index: int, score: float, chunk: KnowledgeChunk, document: KnowledgeDocument) -> dict:
    return {
        "citation_id": f"资料{index}",
        "knowledge_base_id": chunk.knowledge_base_id,
        "document_id": document.id,
        "chunk_id": chunk.id,
        "score": round(score, 4),
        "original_filename": document.original_filename,
        "document_title": document.document_title,
        "knowledge_type": document.knowledge_type,
        "heading": chunk.heading,
        "page_number": chunk.page_number,
        "structure_path": document.structure_path,
        "source_kind": document.source_kind,
        "source_path": document.source_path,
        "text": chunk.text,
    }


def _structured_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    heading = ""
    page_number: int | None = None
    for raw in re.split(r"\n\s*\n+", text.replace("\r\n", "\n").replace("\r", "\n")):
        block = raw.strip()
        if not block:
            continue
        page_match = PDF_PAGE_RE.search(block)
        if page_match:
            page_number = int(page_match.group(1))
            block = PDF_PAGE_RE.sub("", block).strip()
            if not block:
                continue
        first_line = block.splitlines()[0].strip()
        heading_match = HEADING_RE.match(first_line)
        if heading_match:
            heading = heading_match.group(2).strip()
        blocks.append({"text": block, "heading": heading, "page_number": page_number, "metadata": {}})
    return blocks


def _paragraphs(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n+", text) if item.strip()]


def _page_count(text: str) -> int:
    pages = [int(match.group(1)) for match in PDF_PAGE_RE.finditer(text)]
    return max(pages) if pages else 0


def _split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    pieces: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            boundary = max(text.rfind("\n", start, end), text.rfind("。", start, end), text.rfind("；", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        pieces.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return [piece for piece in pieces if piece]


def _tokens(value: str) -> list[str]:
    lowered = value.lower()
    words = WORD_RE.findall(lowered)
    if words:
        tokens: list[str] = []
        for word in words:
            if re.fullmatch(r"[\u4e00-\u9fff]+", word) and len(word) > 4:
                tokens.extend(word[index : index + 2] for index in range(len(word) - 1))
            tokens.append(word)
        return tokens
    compact = re.sub(r"\s+", "", lowered)
    return [compact[index : index + 2] for index in range(max(0, len(compact) - 1))]


def _score_text(query: str, text: str) -> float:
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    candidate = text.lower()
    token_hits = sum(1 for token in query_tokens if token and token in candidate)
    exact_bonus = 2.5 if query.lower() in candidate else 0.0
    density = token_hits / math.sqrt(max(len(candidate), 200))
    return exact_bonus + token_hits / max(len(query_tokens), 1) + density


def _document_title(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").strip() or filename
