from pathlib import Path
from uuid import uuid4
import json

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import ChapterChunk, Project, SourceFile
from ..schemas import ChapterChunkRead, SourceFileRead, SplitRequest, SplitResponse
from ..services.chapter_splitter import split_text_file
from ..services.file_parser import normalize_text_file, save_upload, validate_extension
from ..services.path_safety import project_output_dir, secure_slug


router = APIRouter(tags=["files"])


def _raw_path(project: Project, source_file: SourceFile) -> Path:
    return project_output_dir(project.name, project.root_output_dir) / "raw" / f"source_{source_file.id}.txt"


def _chunks_dir(project: Project, source_file: SourceFile) -> Path:
    safe_name = secure_slug(Path(source_file.original_filename).stem, "source")
    return project_output_dir(project.name, project.root_output_dir) / "chunks" / f"source_{source_file.id}_{safe_name}"


def _file_read(db: Session, source_file: SourceFile) -> SourceFileRead:
    data = SourceFileRead.model_validate(source_file)
    data.chapter_count = db.query(ChapterChunk).filter(ChapterChunk.source_file_id == source_file.id).count()
    return data


def _chapter_read(chapter: ChapterChunk) -> ChapterChunkRead:
    data = ChapterChunkRead.model_validate(chapter)
    try:
        data.preview = Path(chapter.text_path).read_text(encoding="utf-8")[:180].replace("\n", " ")
    except OSError:
        data.preview = ""
    return data


@router.post("/api/projects/{project_id}/files/upload", response_model=SourceFileRead)
async def upload_file(project_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    settings = get_settings()
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    file_type = validate_extension(file.filename or "")
    max_bytes = settings.max_upload_size_mb * 1024 * 1024
    stored_name = f"{uuid4().hex}_{Path(file.filename or 'source').name}"
    stored_path = settings.upload_dir / str(project_id) / stored_name
    size_bytes = await save_upload(file, stored_path, max_bytes)

    source_file = SourceFile(
        project_id=project_id,
        original_filename=file.filename or stored_name,
        stored_path=str(stored_path),
        file_type=file_type,
        size_bytes=size_bytes,
        parse_status="uploaded",
    )
    db.add(source_file)
    db.commit()
    db.refresh(source_file)
    return _file_read(db, source_file)


@router.get("/api/projects/{project_id}/files", response_model=list[SourceFileRead])
def list_files(project_id: int, db: Session = Depends(get_db)):
    if not db.get(Project, project_id):
        raise HTTPException(status_code=404, detail="项目不存在")
    files = db.query(SourceFile).filter(SourceFile.project_id == project_id).order_by(SourceFile.created_at.desc()).all()
    return [_file_read(db, item) for item in files]


@router.post("/api/files/{file_id}/parse", response_model=SourceFileRead)
def parse_file(file_id: int, db: Session = Depends(get_db)):
    source_file = db.get(SourceFile, file_id)
    if not source_file:
        raise HTTPException(status_code=404, detail="文件不存在")
    project = db.get(Project, source_file.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    try:
        normalize_text_file(Path(source_file.stored_path), _raw_path(project, source_file))
        source_file.parse_status = "parsed"
        source_file.parse_error = None
    except Exception as exc:  # noqa: BLE001 - surfaced in UI.
        source_file.parse_status = "failed"
        source_file.parse_error = str(exc)
    db.commit()
    db.refresh(source_file)
    return _file_read(db, source_file)


@router.post("/api/files/{file_id}/split", response_model=SplitResponse)
def split_file(file_id: int, payload: SplitRequest | None = None, db: Session = Depends(get_db)):
    settings = get_settings()
    payload = payload or SplitRequest()
    source_file = db.get(SourceFile, file_id)
    if not source_file:
        raise HTTPException(status_code=404, detail="文件不存在")
    project = db.get(Project, source_file.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    raw_path = _raw_path(project, source_file)
    if source_file.parse_status != "parsed" or not raw_path.exists():
        parse_file(file_id, db)
        db.refresh(source_file)
    if source_file.parse_status != "parsed":
        raise HTTPException(status_code=400, detail=source_file.parse_error or "文件解析失败")

    db.query(ChapterChunk).filter(ChapterChunk.source_file_id == file_id).delete()
    db.commit()
    artifacts = split_text_file(
        raw_path,
        _chunks_dir(project, source_file),
        source_file.id,
        payload.max_chapter_chars or settings.max_chapter_chars,
        payload.overlap_chars if payload.overlap_chars is not None else settings.chunk_overlap_chars,
        payload.strict_chapter_split,
    )
    for artifact in artifacts:
        db.add(
            ChapterChunk(
                id=artifact.stable_id,
                project_id=project.id,
                source_file_id=source_file.id,
                chapter_index=artifact.chapter_index,
                title=artifact.title,
                text_path=str(artifact.text_path),
                char_start=artifact.char_start,
                char_end=artifact.char_end,
                char_count=artifact.char_count,
                token_estimate=artifact.token_estimate,
                metadata_json=json.dumps(artifact.metadata, ensure_ascii=False),
            )
        )
    db.commit()
    chapters = (
        db.query(ChapterChunk)
        .filter(ChapterChunk.source_file_id == file_id)
        .order_by(ChapterChunk.chapter_index.asc())
        .all()
    )
    return SplitResponse(file_id=file_id, chapter_count=len(chapters), chapters=[_chapter_read(item) for item in chapters])


@router.get("/api/files/{file_id}/chapters", response_model=list[ChapterChunkRead])
def list_chapters(file_id: int, db: Session = Depends(get_db)):
    if not db.get(SourceFile, file_id):
        raise HTTPException(status_code=404, detail="文件不存在")
    chapters = (
        db.query(ChapterChunk)
        .filter(ChapterChunk.source_file_id == file_id)
        .order_by(ChapterChunk.chapter_index.asc())
        .all()
    )
    return [_chapter_read(item) for item in chapters]
