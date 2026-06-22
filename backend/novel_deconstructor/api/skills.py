import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import DeconstructionSkill
from ..schemas import SkillCreate, SkillRead, SkillUpdate


router = APIRouter(prefix="/api/skills", tags=["skills"])


def _normalize_modes(modes: list[str]) -> str:
    clean = [mode.strip() for mode in modes if mode.strip()]
    if not clean:
        clean = ["chapter_structure"]
    return json.dumps(list(dict.fromkeys(clean)), ensure_ascii=False)


def _normalize_metadata(metadata: dict) -> str:
    return json.dumps(metadata or {}, ensure_ascii=False)


@router.get("", response_model=list[SkillRead])
def list_skills(include_disabled: bool = True, db: Session = Depends(get_db)):
    query = db.query(DeconstructionSkill)
    if not include_disabled:
        query = query.filter(DeconstructionSkill.enabled.is_(True))
    return query.order_by(DeconstructionSkill.builtin.desc(), DeconstructionSkill.updated_at.desc()).all()


@router.get("/{skill_id}", response_model=SkillRead)
def get_skill(skill_id: int, db: Session = Depends(get_db)):
    skill = db.get(DeconstructionSkill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    return skill


@router.post("", response_model=SkillRead)
def create_skill(payload: SkillCreate, db: Session = Depends(get_db)):
    skill = DeconstructionSkill(
        key=payload.key,
        name=payload.name,
        description=payload.description,
        source=payload.source,
        phase=payload.phase,
        enabled=payload.enabled,
        builtin=False,
        default_modes_json=_normalize_modes(payload.default_modes),
        system_prompt=payload.system_prompt,
        prompt_template=payload.prompt_template,
        metadata_json=_normalize_metadata(payload.metadata),
    )
    db.add(skill)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Skill key 已存在") from exc
    db.refresh(skill)
    return skill


@router.put("/{skill_id}", response_model=SkillRead)
def update_skill(skill_id: int, payload: SkillUpdate, db: Session = Depends(get_db)):
    skill = db.get(DeconstructionSkill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    values = payload.model_dump(exclude_unset=True)
    if "default_modes" in values:
        skill.default_modes_json = _normalize_modes(values.pop("default_modes") or [])
    if "metadata" in values:
        skill.metadata_json = _normalize_metadata(values.pop("metadata") or {})
    for key, value in values.items():
        setattr(skill, key, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Skill key 已存在") from exc
    db.refresh(skill)
    return skill


@router.delete("/{skill_id}")
def delete_skill(skill_id: int, db: Session = Depends(get_db)):
    skill = db.get(DeconstructionSkill, skill_id)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    if skill.builtin:
        skill.enabled = False
        db.commit()
        return {"ok": True, "disabled": True}
    db.delete(skill)
    db.commit()
    return {"ok": True}
