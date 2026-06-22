from pathlib import Path
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisJob, AnalysisResult
from ..schemas import AnalysisResultRead, FileListItem
from ..services.exporter import list_result_files, should_include_result_file
from ..services.path_safety import safe_relative_file
from .workspace import get_workspace_id


router = APIRouter(prefix="/api/jobs", tags=["results"])


def _get_job(db: Session, job_id: str, workspace_id: str) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if not job or not job.project or job.project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.get("/{job_id}/results", response_model=list[AnalysisResultRead])
def list_results(job_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    _get_job(db, job_id, workspace_id)
    return db.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).order_by(AnalysisResult.id.asc()).all()


@router.get("/{job_id}/files", response_model=list[FileListItem])
def list_files(job_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    job = _get_job(db, job_id, workspace_id)
    return list_result_files(Path(job.output_dir))


@router.get("/{job_id}/download")
def download_file(job_id: str, path: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    job = _get_job(db, job_id, workspace_id)
    target = safe_relative_file(Path(job.output_dir), path)
    relative = target.relative_to(Path(job.output_dir)).as_posix()
    if not should_include_result_file(relative):
        raise HTTPException(status_code=404, detail="结果文件不存在")
    return FileResponse(target, filename=target.name)


@router.get("/{job_id}/download-zip")
def download_zip(job_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    job = _get_job(db, job_id, workspace_id)
    output_dir = Path(job.output_dir)
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="结果目录不存在")

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for item in sorted(output_dir.rglob("*")):
            if not item.is_file() or item.name.endswith(".tmp"):
                continue
            relative = item.relative_to(output_dir).as_posix()
            if not should_include_result_file(relative):
                continue
            archive.write(item, relative)
    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{job_id}_results.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)
