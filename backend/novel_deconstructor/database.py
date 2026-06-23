from pathlib import Path
import json

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings
from .models import AnalysisJob, Base, DeconstructionSkill, JobLog, KnowledgeDocument, PromptTemplate, Workspace


settings = get_settings()


def _connect_args(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    if database_url.startswith("mysql"):
        return {"charset": "utf8mb4"}
    return {}


def _engine_kwargs(database_url: str) -> dict:
    kwargs = {"connect_args": _connect_args(database_url)}
    if database_url.startswith("mysql"):
        kwargs.update({"pool_pre_ping": True, "pool_recycle": 280})
    return kwargs


engine = create_engine(settings.app_database_url, **_engine_kwargs(settings.app_database_url))
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


def seed_builtin_workspaces(db: Session) -> None:
    changed = False
    for workspace_id, name in [("anonymous", "Anonymous Workspace"), ("legacy", "Legacy Workspace")]:
        if not db.get(Workspace, workspace_id):
            db.add(Workspace(id=workspace_id, name=name, slug=workspace_id, plan="legacy"))
            changed = True
    if changed:
        db.commit()


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
    def table_columns(table_name: str) -> set[str]:
        inspector = inspect(engine)
        if not inspector.has_table(table_name):
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}

    def add_column_if_missing(table_name: str, column_name: str, sqlite_sql: str, mysql_sql: str | None = None) -> None:
        columns = table_columns(table_name)
        if columns and column_name not in columns:
            statement = mysql_sql if settings.app_database_url.startswith("mysql") and mysql_sql else sqlite_sql
            connection.execute(text(statement))

    with engine.begin() as connection:
        add_column_if_missing("analysis_jobs", "skill_id", "ALTER TABLE analysis_jobs ADD COLUMN skill_id INTEGER")
        add_column_if_missing(
            "analysis_jobs",
            "generate_graph",
            "ALTER TABLE analysis_jobs ADD COLUMN generate_graph BOOLEAN NOT NULL DEFAULT 0",
        )
        add_column_if_missing(
            "projects",
            "workspace_id",
            "ALTER TABLE projects ADD COLUMN workspace_id VARCHAR(80) NOT NULL DEFAULT 'legacy'",
        )
        add_column_if_missing(
            "knowledge_bases",
            "workspace_id",
            "ALTER TABLE knowledge_bases ADD COLUMN workspace_id VARCHAR(80) NOT NULL DEFAULT 'legacy'",
        )
        add_column_if_missing(
            "knowledge_documents",
            "knowledge_type",
            "ALTER TABLE knowledge_documents ADD COLUMN knowledge_type VARCHAR(32) NOT NULL DEFAULT 'worldbuilding'",
        )
        add_column_if_missing(
            "writing_memories",
            "tags_json",
            "ALTER TABLE writing_memories ADD COLUMN tags_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE writing_memories ADD COLUMN tags_json TEXT NULL",
        )
        add_column_if_missing(
            "writing_memories",
            "source_ref_json",
            "ALTER TABLE writing_memories ADD COLUMN source_ref_json TEXT NOT NULL DEFAULT '{}'",
            "ALTER TABLE writing_memories ADD COLUMN source_ref_json TEXT NULL",
        )
        add_column_if_missing(
            "knowledge_cards",
            "is_canonical",
            "ALTER TABLE knowledge_cards ADD COLUMN is_canonical BOOLEAN NOT NULL DEFAULT 1",
        )
        add_column_if_missing(
            "knowledge_cards",
            "merged_into_card_id",
            "ALTER TABLE knowledge_cards ADD COLUMN merged_into_card_id VARCHAR(96)",
        )
        add_column_if_missing(
            "knowledge_cards",
            "merged_from_ids_json",
            "ALTER TABLE knowledge_cards ADD COLUMN merged_from_ids_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE knowledge_cards ADD COLUMN merged_from_ids_json TEXT NULL",
        )
        add_column_if_missing(
            "knowledge_cards",
            "evidence_count",
            "ALTER TABLE knowledge_cards ADD COLUMN evidence_count INTEGER NOT NULL DEFAULT 1",
        )
        add_column_if_missing(
            "knowledge_cards",
            "content_fingerprint",
            "ALTER TABLE knowledge_cards ADD COLUMN content_fingerprint VARCHAR(64) NOT NULL DEFAULT ''",
        )
        if settings.app_database_url.startswith("mysql"):
            if "tags_json" in table_columns("writing_memories"):
                connection.execute(text("UPDATE writing_memories SET tags_json = '[]' WHERE tags_json IS NULL"))
            if "source_ref_json" in table_columns("writing_memories"):
                connection.execute(text("UPDATE writing_memories SET source_ref_json = '{}' WHERE source_ref_json IS NULL"))
            if "merged_from_ids_json" in table_columns("knowledge_cards"):
                connection.execute(text("UPDATE knowledge_cards SET merged_from_ids_json = '[]' WHERE merged_from_ids_json IS NULL"))


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
        seed_builtin_workspaces(db)
        seed_prompt_templates(db)
        seed_deconstruction_skills(db)
        mark_interrupted_jobs(db)
        mark_interrupted_knowledge_documents(db)
    finally:
        db.close()
