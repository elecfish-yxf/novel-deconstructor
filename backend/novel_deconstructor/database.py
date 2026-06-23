from pathlib import Path
import json

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import AnalysisJob, Base, DeconstructionSkill, JobLog, KnowledgeDocument, PromptTemplate


settings = get_settings()


def _connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


engine = create_engine(settings.app_database_url, connect_args=_connect_args(settings.app_database_url))
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def ensure_runtime_dirs() -> None:
    for path in [settings.storage_dir, settings.upload_dir, settings.output_dir, settings.knowledge_dir]:
        path.mkdir(parents=True, exist_ok=True)


def seed_prompt_templates(db: Session) -> None:
    prompt_dir = Path(__file__).resolve().parent / "prompts"
    if not prompt_dir.exists():
        return
    for prompt_file in prompt_dir.glob("*.md"):
        mode = prompt_file.stem
        existing = db.query(PromptTemplate).filter(PromptTemplate.mode == mode, PromptTemplate.source == "builtin").first()
        content = prompt_file.read_text(encoding="utf-8")
        if existing:
            existing.name = prompt_file.stem.replace("_", " ").title()
            existing.content = content
            existing.editable = True
            continue
        db.add(
            PromptTemplate(
                name=prompt_file.stem.replace("_", " ").title(),
                mode=mode,
                content=content,
                source="builtin",
                editable=True,
            )
        )
    db.commit()


def ensure_schema_upgrades() -> None:
    if not settings.app_database_url.startswith("sqlite"):
        return
    with engine.begin() as connection:
        rows = connection.execute(text("PRAGMA table_info(analysis_jobs)")).mappings().all()
        columns = {row["name"] for row in rows}
        if "skill_id" not in columns:
            connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN skill_id INTEGER"))
        if "generate_graph" not in columns:
            connection.execute(text("ALTER TABLE analysis_jobs ADD COLUMN generate_graph BOOLEAN NOT NULL DEFAULT 0"))
        rows = connection.execute(text("PRAGMA table_info(projects)")).mappings().all()
        columns = {row["name"] for row in rows}
        if "workspace_id" not in columns:
            connection.execute(text("ALTER TABLE projects ADD COLUMN workspace_id VARCHAR(80) NOT NULL DEFAULT 'legacy'"))
        rows = connection.execute(text("PRAGMA table_info(knowledge_bases)")).mappings().all()
        columns = {row["name"] for row in rows}
        if rows and "workspace_id" not in columns:
            connection.execute(text("ALTER TABLE knowledge_bases ADD COLUMN workspace_id VARCHAR(80) NOT NULL DEFAULT 'legacy'"))
        rows = connection.execute(text("PRAGMA table_info(knowledge_documents)")).mappings().all()
        columns = {row["name"] for row in rows}
        if rows and "knowledge_type" not in columns:
            connection.execute(text("ALTER TABLE knowledge_documents ADD COLUMN knowledge_type VARCHAR(32) NOT NULL DEFAULT 'worldbuilding'"))


def seed_deconstruction_skills(db: Session) -> None:
    prompt_dir = Path(__file__).resolve().parent / "prompts"
    chapter_prompt = (prompt_dir / "chapter_structure.md").read_text(encoding="utf-8")
    builtin_key = "oh_story_long_analyze_phase2"
    default_modes = [
        "chapter_structure",
        "conflict_analysis",
        "character_growth",
        "information_delivery",
        "language_style",
        "ai_bad_patterns",
    ]
    skill = db.query(DeconstructionSkill).filter(DeconstructionSkill.key == builtin_key).first()
    if not skill:
        db.add(
            DeconstructionSkill(
                key=builtin_key,
                name="oh-story 长篇拆文内核",
                description="基于 oh-story-codex 的长篇拆书方法，默认启用章节结构、冲突推进、人物变化、信息投放、语言风格和 AI 味检查。",
                source="builtin:oh-story-codex",
                phase=2,
                enabled=True,
                builtin=True,
                default_modes_json=json.dumps(default_modes, ensure_ascii=False),
                prompt_template=chapter_prompt,
                metadata_json=json.dumps(
                    {
                        "phase3_ready": True,
                        "reserved_outputs": ["knowledge_base", "knowledge_base_obsidian", "graph_outputs"],
                        "source_repo": settings.oh_story_repo_url,
                    },
                    ensure_ascii=False,
                ),
            )
        )
        db.commit()
        return
    if skill.builtin:
        skill.name = "oh-story 长篇拆文内核"
        skill.description = "基于 oh-story-codex 的长篇拆书方法，默认启用章节结构、冲突推进、人物变化、信息投放、语言风格和 AI 味检查。"
        skill.source = "builtin:oh-story-codex"
        skill.phase = 2
        skill.enabled = True
        skill.default_modes_json = json.dumps(default_modes, ensure_ascii=False)
        skill.prompt_template = chapter_prompt
        db.commit()


def mark_interrupted_jobs(db: Session) -> None:
    running_jobs = db.query(AnalysisJob).filter(AnalysisJob.status == "running").all()
    for job in running_jobs:
        job.status = "failed"
        job.error_message = "服务重启导致后台任务中断，请使用重试失败项重新开始。"
        db.add(JobLog(job_id=job.id, level="error", message=job.error_message))
    if running_jobs:
        db.commit()


def mark_interrupted_knowledge_documents(db: Session) -> None:
    indexing_docs = (
        db.query(KnowledgeDocument)
        .filter(KnowledgeDocument.status.in_(["pending", "parsing", "indexing"]))
        .all()
    )
    for document in indexing_docs:
        document.status = "failed"
        document.error_message = "服务重启导致索引中断，请重新索引。"
    if indexing_docs:
        db.commit()


def init_db() -> None:
    ensure_runtime_dirs()
    Base.metadata.create_all(bind=engine)
    ensure_schema_upgrades()
    db = SessionLocal()
    try:
        seed_prompt_templates(db)
        seed_deconstruction_skills(db)
        mark_interrupted_jobs(db)
        mark_interrupted_knowledge_documents(db)
    finally:
        db.close()
