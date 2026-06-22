from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import PromptTemplate
from ..schemas import PromptTemplateCreate, PromptTemplateRead, PromptTemplateUpdate


router = APIRouter(prefix="/api/prompts", tags=["prompts"])


@router.get("", response_model=list[PromptTemplateRead])
def list_prompts(db: Session = Depends(get_db)):
    return db.query(PromptTemplate).order_by(PromptTemplate.mode.asc(), PromptTemplate.id.asc()).all()


@router.get("/{prompt_id}", response_model=PromptTemplateRead)
def get_prompt(prompt_id: int, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    return prompt


@router.post("", response_model=PromptTemplateRead)
def create_prompt(payload: PromptTemplateCreate, db: Session = Depends(get_db)):
    prompt = PromptTemplate(**payload.model_dump())
    db.add(prompt)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.put("/{prompt_id}", response_model=PromptTemplateRead)
def update_prompt(prompt_id: int, payload: PromptTemplateUpdate, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(prompt, key, value)
    db.commit()
    db.refresh(prompt)
    return prompt


@router.delete("/{prompt_id}")
def delete_prompt(prompt_id: int, db: Session = Depends(get_db)):
    prompt = db.get(PromptTemplate, prompt_id)
    if not prompt:
        raise HTTPException(status_code=404, detail="Prompt 不存在")
    db.delete(prompt)
    db.commit()
    return {"ok": True}
