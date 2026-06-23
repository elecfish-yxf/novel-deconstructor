from pathlib import Path
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..modes import (
    AGGREGATE_MODES,
    CHAPTER_ANALYSIS_MODES,
    RESERVED_PROMPT_MODES,
    ignored_aggregate_modes,
    normalize_mode_list,
    sanitize_chapter_modes,
)
from ..models import AnalysisJob, AnalysisResult, ChapterChunk, DeconstructionSkill, JobLog, Project, PromptTemplate, SourceFile
from ..schemas import JobCreate, JobLogRead, JobRead, JobRuntimeKeyRequest
from ..services.path_safety import job_output_dir
from ..services.pipeline import job_id_now, resolve_model, run_analysis_job
from .workspace import get_workspace_id


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get_job(db: Session, job_id: str, workspace_id: str) -> AnalysisJob:
    job = db.get(AnalysisJob, job_id)
    if not job or not job.project or job.project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job


@router.post("", response_model=JobRead)
async def create_job(payload: JobCreate, background_tasks: BackgroundTasks, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    settings = get_settings()
    project = db.get(Project, payload.project_id)
    source_file = db.get(SourceFile, payload.source_file_id)
    if not project or project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="项目不存在")
    if not source_file or source_file.project_id != project.id:
        raise HTTPException(status_code=404, detail="源文件不存在")
    chunks = db.query(ChapterChunk).filter(ChapterChunk.source_file_id == source_file.id).count()
    if chunks == 0:
        raise HTTPException(status_code=400, detail="请先完成章节切分")
    skill = None
    if payload.skill_id:
        skill = db.get(DeconstructionSkill, payload.skill_id)
        if not skill or not skill.enabled:
            raise HTTPException(status_code=404, detail="Skill 不存在或已禁用")

    requested_modes = payload.modes
    if not requested_modes and skill:
        requested_modes = json.loads(skill.default_modes_json)
    raw_modes = normalize_mode_list(requested_modes)
    invalid_modes = [
        mode
        for mode in raw_modes
        if mode not in CHAPTER_ANALYSIS_MODES and mode not in AGGREGATE_MODES and mode not in RESERVED_PROMPT_MODES
    ]
    if invalid_modes:
        raise HTTPException(status_code=400, detail=f"分析模式不存在: {', '.join(invalid_modes)}")
    ignored_modes = ignored_aggregate_modes(requested_modes)
    modes = sanitize_chapter_modes(requested_modes)
    available_modes = {item.mode for item in db.query(PromptTemplate.mode).all()} & CHAPTER_ANALYSIS_MODES
    missing_modes = [mode for mode in modes if mode not in available_modes]
    if missing_modes:
        raise HTTPException(status_code=400, detail=f"分析模式不存在: {', '.join(missing_modes)}")

    job_id = job_id_now()
    base_url = payload.base_url or settings.openai_base_url
    if not payload.dry_run and not (payload.api_key or "").strip():
        raise HTTPException(status_code=400, detail="关闭 dry-run 后必须填写你自己的 API Key。服务器不会使用站长的 Key 替你调用模型。")
    output_dir = job_output_dir(project.name, job_id, payload.output_dir or project.root_output_dir)
    for name in ["chapter_analysis", "logs", "metadata/llm_calls"]:
        (Path(output_dir) / name).mkdir(parents=True, exist_ok=True)

    job = AnalysisJob(
        id=job_id,
        project_id=project.id,
        source_file_id=source_file.id,
        status="pending",
        modes_json=json.dumps(modes, ensure_ascii=False),
        output_dir=str(output_dir),
        base_url=base_url,
        model=resolve_model(base_url, payload.model),
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        concurrency=max(payload.concurrency, 1),
        allow_short_quotes=payload.allow_short_quotes,
        generate_kb=payload.generate_kb,
        generate_obsidian=payload.generate_obsidian,
        generate_graph=payload.generate_graph,
        dry_run=payload.dry_run,
        skill_id=skill.id if skill else None,
        total_chunks=chunks * len(modes),
    )
    db.add(job)
    db.add(JobLog(job_id=job_id, level="info", message="任务已创建"))
    if ignored_modes:
        db.add(
            JobLog(
                job_id=job_id,
                level="warning",
                message=f"已忽略聚合导出模式: {', '.join(ignored_modes)}；这些内容由导出流程生成。",
            )
        )
    db.commit()
    db.refresh(job)
    background_tasks.add_task(run_analysis_job, job_id, payload.api_key)
    return job


@router.get("/{job_id}", response_model=JobRead)
def get_job(job_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    return _get_job(db, job_id, workspace_id)


@router.get("/{job_id}/logs", response_model=list[JobLogRead])
def get_logs(job_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    _get_job(db, job_id, workspace_id)
    return db.query(JobLog).filter(JobLog.job_id == job_id).order_by(JobLog.created_at.asc()).all()


@router.post("/{job_id}/pause", response_model=JobRead)
def pause_job(job_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    job = _get_job(db, job_id, workspace_id)
    if job.status == "running":
        job.status = "paused"
        db.add(JobLog(job_id=job.id, level="info", message="已请求暂停，当前章节完成后停止"))
        db.commit()
        db.refresh(job)
    return job


@router.post("/{job_id}/resume", response_model=JobRead)
async def resume_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    payload: JobRuntimeKeyRequest | None = None,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id, workspace_id)
    if job.status in {"paused", "failed"}:
        runtime_key = (payload.api_key if payload else None) or ""
        if not job.dry_run and not runtime_key.strip():
            raise HTTPException(status_code=400, detail="当前任务不会保存 API Key。继续任务前请重新填写你自己的 API Key。")
        job.status = "pending"
        db.add(JobLog(job_id=job.id, level="info", message="已请求继续任务"))
        db.commit()
        background_tasks.add_task(run_analysis_job, job_id, runtime_key)
        db.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=JobRead)
def cancel_job(job_id: str, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    job = _get_job(db, job_id, workspace_id)
    if job.status not in {"completed", "cancelled"}:
        job.status = "cancelled"
        db.add(JobLog(job_id=job.id, level="info", message="已请求取消任务"))
        db.commit()
        db.refresh(job)
    return job


@router.post("/{job_id}/retry-failed", response_model=JobRead)
async def retry_failed(
    job_id: str,
    background_tasks: BackgroundTasks,
    payload: JobRuntimeKeyRequest | None = None,
    workspace_id: str = Depends(get_workspace_id),
    db: Session = Depends(get_db),
):
    job = _get_job(db, job_id, workspace_id)
    runtime_key = (payload.api_key if payload else None) or ""
    if not job.dry_run and not runtime_key.strip():
        raise HTTPException(status_code=400, detail="当前任务不会保存 API Key。重试失败项前请重新填写你自己的 API Key。")
    db.query(AnalysisResult).filter(AnalysisResult.job_id == job_id, AnalysisResult.status == "failed").update(
        {"status": "pending", "error_message": None}
    )
    job.status = "pending"
    job.failed_chunks = 0
    db.add(JobLog(job_id=job.id, level="info", message="已重置失败项并重新开始"))
    db.commit()
    background_tasks.add_task(run_analysis_job, job_id, runtime_key)
    db.refresh(job)
    return job
