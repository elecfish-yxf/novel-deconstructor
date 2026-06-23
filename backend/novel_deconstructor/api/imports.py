from pathlib import Path
import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DeconstructionSkill
from ..schemas import ImportScanRequest, ImportScanResponse
from ..services.skill_importer import build_skill_payloads_from_source, scan_local_prompt_sources


router = APIRouter(prefix="/api/imports", tags=["imports"])


@router.post("/scan", response_model=ImportScanResponse)
def scan_imports(payload: ImportScanRequest):
    if payload.github_url:
        return ImportScanResponse(files=[], message="远程仓库拉取仍是预留能力；请先提供本地仓库路径。")
    if not payload.local_path:
        raise HTTPException(status_code=400, detail="请提供 local_path")
    files = scan_local_prompt_sources(Path(payload.local_path))
    return ImportScanResponse(files=files, message=f"扫描到 {len(files)} 个可能相关的 Prompt / Skill 文件")


@router.post("/import-skills")
def import_skills(payload: ImportScanRequest, db: Session = Depends(get_db)):
    if payload.github_url:
        raise HTTPException(status_code=400, detail="当前支持导入本地仓库；GitHub 拉取将在后续补全。")
    if not payload.local_path:
        raise HTTPException(status_code=400, detail="请提供 local_path")
    source = Path(payload.local_path)
    skill_payloads = build_skill_payloads_from_source(source)
    imported: list[dict] = []
    for item in skill_payloads:
        skill = db.query(DeconstructionSkill).filter(DeconstructionSkill.key == item["key"]).first()
        values = {
            "name": item["name"],
            "description": item["description"],
            "source": item["source"],
            "phase": item["phase"],
            "enabled": item["enabled"],
            "builtin": False,
            "default_modes_json": json.dumps(item["default_modes"], ensure_ascii=False),
            "system_prompt": item["system_prompt"],
            "prompt_template": item["prompt_template"],
            "metadata_json": json.dumps(item["metadata"], ensure_ascii=False),
        }
        if skill:
            for key, value in values.items():
                setattr(skill, key, value)
        else:
            skill = DeconstructionSkill(key=item["key"], **values)
            db.add(skill)
        db.commit()
        db.refresh(skill)
        imported.append({"id": skill.id, "key": skill.key, "name": skill.name})
    return {"message": f"已导入 {len(imported)} 个 Skill", "skills": imported}
