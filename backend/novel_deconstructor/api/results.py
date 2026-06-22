from pathlib import Path
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisJob, AnalysisResult
from ..schemas import AnalysisResultRead, FileListItem
from ..services.exporter import list_result_files
from ..services.path_safety import safe_relative_file


router = APIRouter(prefix="/api/jobs", tags=["results"])


@router.get("/{job_id}/results", response_model=list[AnalysisResultRead])
def list_results(job_id: str, db: Session = Depends(get_db)):
    if not db.get(AnalysisJob, job_id):
        raise HTTPException(status_code=404, detail="任务不存在")
    return db.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).order_by(AnalysisResult.id.asc()).all()


@router.get("/{job_id}/files", response_model=list[FileListItem])
def list_files(job_id: str, db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return list_result_files(Path(job.output_dir))


@router.get("/{job_id}/download")
def download_file(job_id: str, path: str, db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    target = safe_relative_file(Path(job.output_dir), path)
    return FileResponse(target, filename=target.name)


@router.get("/{job_id}/download-zip")
def download_zip(job_id: str, db: Session = Depends(get_db)):
    job = db.get(AnalysisJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    output_dir = Path(job.output_dir)
    if not output_dir.exists():
        raise HTTPException(status_code=404, detail="结果目录不存在")

    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for item in sorted(output_dir.rglob("*")):
            if not item.is_file() or item.name.endswith(".tmp"):
                continue
            relative = item.relative_to(output_dir).as_posix()
            archive.write(item, relative)
    buffer.seek(0)
    headers = {"Content-Disposition": f'attachment; filename="{job_id}_results.zip"'}
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)
