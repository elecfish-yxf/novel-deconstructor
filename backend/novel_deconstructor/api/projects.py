from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AnalysisJob, Project
from ..schemas import JobRead, ProjectCreate, ProjectRead
from .workspace import get_workspace_id


router = APIRouter(prefix="/api/projects", tags=["projects"])


def _with_latest_status(db: Session, project: Project) -> ProjectRead:
    latest_job = (
        db.query(AnalysisJob)
        .filter(AnalysisJob.project_id == project.id)
        .order_by(AnalysisJob.created_at.desc())
        .first()
    )
    data = ProjectRead.model_validate(project)
    data.latest_job_status = latest_job.status if latest_job else None
    return data


@router.post("", response_model=ProjectRead)
def create_project(payload: ProjectCreate, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    project = Project(
        name=payload.name,
        description=payload.description,
        root_output_dir=payload.root_output_dir,
        workspace_id=workspace_id,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return _with_latest_status(db, project)


@router.get("", response_model=list[ProjectRead])
def list_projects(workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    projects = db.query(Project).filter(Project.workspace_id == workspace_id).order_by(Project.created_at.desc()).all()
    return [_with_latest_status(db, project) for project in projects]


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(project_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return _with_latest_status(db, project)


@router.get("/{project_id}/jobs", response_model=list[JobRead])
def list_project_jobs(project_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="项目不存在")
    return (
        db.query(AnalysisJob)
        .filter(AnalysisJob.project_id == project_id)
        .order_by(AnalysisJob.created_at.desc())
        .all()
    )


@router.delete("/{project_id}")
def delete_project(project_id: int, workspace_id: str = Depends(get_workspace_id), db: Session = Depends(get_db)):
    project = db.get(Project, project_id)
    if not project or project.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="项目不存在")
    db.delete(project)
    db.commit()
    return {"ok": True}
