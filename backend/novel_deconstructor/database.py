from pathlib import Path
import json

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
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
    added_columns: set[str] = set()

    def table_columns(table_name: str) -> set[str]:
        inspector = inspect(engine)
        if not inspector.has_table(table_name):
            return set()
        return {column["name"] for column in inspector.get_columns(table_name)}

    def table_indexes(table_name: str) -> set[str]:
        inspector = inspect(engine)
        if not inspector.has_table(table_name):
            return set()
        return {index["name"] for index in inspector.get_indexes(table_name)}

    def add_column_if_missing(table_name: str, column_name: str, sqlite_sql: str, mysql_sql: str | None = None) -> None:
        columns = table_columns(table_name)
        if columns and column_name not in columns:
            statement = mysql_sql if settings.app_database_url.startswith("mysql") and mysql_sql else sqlite_sql
            connection.execute(text(statement))
            added_columns.add(f"{table_name}.{column_name}")

    def create_index_if_missing(index_name: str, sql: str) -> None:
        if index_name not in table_indexes("knowledge_cards"):
            connection.execute(text(sql))

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
        add_column_if_missing(
            "knowledge_cards",
            "source_refs_json",
            "ALTER TABLE knowledge_cards ADD COLUMN source_refs_json TEXT NOT NULL DEFAULT '[]'",
            "ALTER TABLE knowledge_cards ADD COLUMN source_refs_json TEXT NULL",
        )
        add_column_if_missing(
            "knowledge_cards",
            "normalized_title_hash",
            "ALTER TABLE knowledge_cards ADD COLUMN normalized_title_hash VARCHAR(64) NOT NULL DEFAULT ''",
        )
        add_column_if_missing(
            "knowledge_cards",
            "canonical_group_id",
            "ALTER TABLE knowledge_cards ADD COLUMN canonical_group_id VARCHAR(96) NOT NULL DEFAULT ''",
        )
        add_column_if_missing(
            "knowledge_cards",
            "retrieval_level",
            "ALTER TABLE knowledge_cards ADD COLUMN retrieval_level VARCHAR(24) NOT NULL DEFAULT 'evidence'",
        )
        add_column_if_missing(
            "knowledge_cards",
            "context_role",
            "ALTER TABLE knowledge_cards ADD COLUMN context_role VARCHAR(32) NOT NULL DEFAULT 'auxiliary'",
        )
        add_column_if_missing(
            "knowledge_cards",
            "scope_level",
            "ALTER TABLE knowledge_cards ADD COLUMN scope_level VARCHAR(16) NOT NULL DEFAULT 'global'",
        )
        add_column_if_missing("knowledge_cards", "volume_index", "ALTER TABLE knowledge_cards ADD COLUMN volume_index INTEGER")
        add_column_if_missing("knowledge_cards", "volume_title", "ALTER TABLE knowledge_cards ADD COLUMN volume_title VARCHAR(512)")
        add_column_if_missing("knowledge_cards", "chapter_index", "ALTER TABLE knowledge_cards ADD COLUMN chapter_index INTEGER")
        add_column_if_missing("knowledge_cards", "chapter_title", "ALTER TABLE knowledge_cards ADD COLUMN chapter_title VARCHAR(512)")
        add_column_if_missing("knowledge_cards", "valid_from_volume_index", "ALTER TABLE knowledge_cards ADD COLUMN valid_from_volume_index INTEGER")
        add_column_if_missing("knowledge_cards", "valid_from_chapter_index", "ALTER TABLE knowledge_cards ADD COLUMN valid_from_chapter_index INTEGER")
        add_column_if_missing("knowledge_cards", "valid_until_volume_index", "ALTER TABLE knowledge_cards ADD COLUMN valid_until_volume_index INTEGER")
        add_column_if_missing("knowledge_cards", "valid_until_chapter_index", "ALTER TABLE knowledge_cards ADD COLUMN valid_until_chapter_index INTEGER")
        add_column_if_missing("knowledge_cards", "reveal_at_volume_index", "ALTER TABLE knowledge_cards ADD COLUMN reveal_at_volume_index INTEGER")
        add_column_if_missing("knowledge_cards", "reveal_at_chapter_index", "ALTER TABLE knowledge_cards ADD COLUMN reveal_at_chapter_index INTEGER")
        add_column_if_missing(
            "knowledge_cards",
            "retrievable",
            "ALTER TABLE knowledge_cards ADD COLUMN retrievable BOOLEAN NOT NULL DEFAULT 0",
        )
        add_column_if_missing(
            "knowledge_cards",
            "priority",
            "ALTER TABLE knowledge_cards ADD COLUMN priority INTEGER NOT NULL DEFAULT 0",
        )
        add_column_if_missing(
            "writing_memories",
            "scope_level",
            "ALTER TABLE writing_memories ADD COLUMN scope_level VARCHAR(16) NOT NULL DEFAULT 'chapter'",
        )
        add_column_if_missing("writing_memories", "volume_index", "ALTER TABLE writing_memories ADD COLUMN volume_index INTEGER")
        add_column_if_missing("writing_memories", "volume_title", "ALTER TABLE writing_memories ADD COLUMN volume_title VARCHAR(512)")
        add_column_if_missing("writing_memories", "chapter_index", "ALTER TABLE writing_memories ADD COLUMN chapter_index INTEGER")
        add_column_if_missing("writing_memories", "chapter_title", "ALTER TABLE writing_memories ADD COLUMN chapter_title VARCHAR(512)")
        add_column_if_missing("writing_memories", "valid_from_volume_index", "ALTER TABLE writing_memories ADD COLUMN valid_from_volume_index INTEGER")
        add_column_if_missing("writing_memories", "valid_from_chapter_index", "ALTER TABLE writing_memories ADD COLUMN valid_from_chapter_index INTEGER")
        add_column_if_missing("writing_memories", "valid_until_volume_index", "ALTER TABLE writing_memories ADD COLUMN valid_until_volume_index INTEGER")
        add_column_if_missing("writing_memories", "valid_until_chapter_index", "ALTER TABLE writing_memories ADD COLUMN valid_until_chapter_index INTEGER")
        add_column_if_missing("writing_memories", "reveal_at_volume_index", "ALTER TABLE writing_memories ADD COLUMN reveal_at_volume_index INTEGER")
        add_column_if_missing("writing_memories", "reveal_at_chapter_index", "ALTER TABLE writing_memories ADD COLUMN reveal_at_chapter_index INTEGER")
        add_column_if_missing(
            "writing_memories",
            "retrievable",
            "ALTER TABLE writing_memories ADD COLUMN retrievable BOOLEAN NOT NULL DEFAULT 1",
        )
        add_column_if_missing(
            "writing_memories",
            "priority",
            "ALTER TABLE writing_memories ADD COLUMN priority INTEGER NOT NULL DEFAULT 0",
        )
        if "retrievable" in table_columns("knowledge_cards"):
            connection.execute(
                text(
                    "UPDATE knowledge_cards "
                    "SET retrievable = 1 "
                    "WHERE "
                    "library_type IN ('writing_guide', 'worldbuilding', 'memory') "
                    "AND is_canonical = 1 "
                    "AND status IN ('approved', 'reviewed')"
                )
            )
            connection.execute(
                text(
                    "UPDATE knowledge_cards "
                    "SET retrievable = 0 "
                    "WHERE status = 'raw_extracted' OR is_canonical = 0 OR status IN ('merged', 'deleted', 'deprecated', 'superseded', 'disabled')"
                )
            )
        if settings.app_database_url.startswith("mysql"):
            if "tags_json" in table_columns("writing_memories"):
                connection.execute(text("UPDATE writing_memories SET tags_json = '[]' WHERE tags_json IS NULL"))
            if "source_ref_json" in table_columns("writing_memories"):
                connection.execute(text("UPDATE writing_memories SET source_ref_json = '{}' WHERE source_ref_json IS NULL"))
            if "merged_from_ids_json" in table_columns("knowledge_cards"):
                connection.execute(text("UPDATE knowledge_cards SET merged_from_ids_json = '[]' WHERE merged_from_ids_json IS NULL"))
            if "source_refs_json" in table_columns("knowledge_cards"):
                connection.execute(text("UPDATE knowledge_cards SET source_refs_json = '[]' WHERE source_refs_json IS NULL"))
        if "retrieval_level" in table_columns("knowledge_cards"):
            retrieval_level_where = (
                "retrieval_level IS NULL OR retrieval_level = '' OR retrieval_level = 'evidence'"
                if "knowledge_cards.retrieval_level" in added_columns
                else "retrieval_level IS NULL OR retrieval_level = ''"
            )
            connection.execute(
                text(
                    "UPDATE knowledge_cards "
                    "SET retrieval_level = CASE "
                    "WHEN status = 'raw_extracted' OR is_canonical = 0 OR retrievable = 0 THEN 'evidence' "
                    "WHEN library_type = 'memory' OR card_type IN ('ChapterOutline', 'ChapterHandoff', 'character_state', 'relationship_state', 'foreshadowing', 'volume_summary') THEN 'pinned' "
                    "ELSE 'primary' END "
                    f"WHERE {retrieval_level_where}"
                )
            )
        if "context_role" in table_columns("knowledge_cards"):
            context_role_where = (
                "context_role IS NULL OR context_role = '' OR context_role = 'auxiliary'"
                if "knowledge_cards.context_role" in added_columns
                else "context_role IS NULL OR context_role = ''"
            )
            connection.execute(
                text(
                    "UPDATE knowledge_cards "
                    "SET context_role = CASE "
                    "WHEN status = 'raw_extracted' THEN 'evidence' "
                    "WHEN library_type = 'memory' THEN 'memory' "
                    "WHEN library_type = 'worldbuilding' THEN 'fact' "
                    "WHEN card_type = 'anti_pattern' THEN 'anti_pattern' "
                    "WHEN card_type = 'style_pattern' THEN 'style' "
                    "WHEN library_type = 'writing_guide' THEN 'guide' "
                    "ELSE 'auxiliary' END "
                    f"WHERE {context_role_where}"
                )
            )
        create_index_if_missing(
            "idx_card_kb_library_status",
            "CREATE INDEX idx_card_kb_library_status ON knowledge_cards (knowledge_base_id, library_type, status, is_canonical, retrievable)",
        )
        create_index_if_missing(
            "idx_card_scope_position",
            "CREATE INDEX idx_card_scope_position ON knowledge_cards (knowledge_base_id, scope_level, volume_index, chapter_index)",
        )
        create_index_if_missing(
            "idx_card_visibility_window",
            "CREATE INDEX idx_card_visibility_window ON knowledge_cards (knowledge_base_id, retrievable, status, reveal_at_volume_index, reveal_at_chapter_index, valid_from_volume_index, valid_from_chapter_index, valid_until_volume_index, valid_until_chapter_index)",
        )
        create_index_if_missing(
            "idx_card_type_priority",
            "CREATE INDEX idx_card_type_priority ON knowledge_cards (knowledge_base_id, card_type, priority)",
        )
        create_index_if_missing(
            "idx_card_content_hash",
            "CREATE INDEX idx_card_content_hash ON knowledge_cards (knowledge_base_id, content_fingerprint)",
        )
        create_index_if_missing(
            "idx_card_title_group",
            "CREATE INDEX idx_card_title_group ON knowledge_cards (knowledge_base_id, normalized_title_hash, canonical_group_id)",
        )


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
    try:
        Base.metadata.create_all(bind=engine)
        ensure_schema_upgrades()
    except OperationalError as exc:
        if settings.app_database_url.startswith("mysql"):
            raise RuntimeError(
                "RDS/MySQL database initialization failed. Check APP_DATABASE_URL, network access, "
                "security group rules, database name, credentials, and utf8mb4 charset configuration."
            ) from exc
        raise
    db = SessionLocal()
    try:
        seed_builtin_workspaces(db)
        seed_prompt_templates(db)
        seed_deconstruction_skills(db)
        mark_interrupted_jobs(db)
        mark_interrupted_knowledge_documents(db)
    finally:
        db.close()
