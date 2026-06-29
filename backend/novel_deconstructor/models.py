from datetime import datetime

import json

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


def utcnow() -> datetime:
    return datetime.utcnow()


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(80), unique=True, nullable=True, index=True)
    password_hash = Column(Text, nullable=False)
    display_name = Column(String(120), default="", nullable=False)
    avatar_url = Column(Text, nullable=True)
    status = Column(String(32), default="active", nullable=False, index=True)
    email_verified_at = Column(DateTime, nullable=True)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    owned_workspaces = relationship("Workspace", back_populates="owner", foreign_keys="Workspace.owner_user_id")
    memberships = relationship("WorkspaceMember", back_populates="user", cascade="all, delete-orphan")
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    api_keys = relationship("UserAPIKey", back_populates="user", cascade="all, delete-orphan")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String(80), primary_key=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), default="Default Workspace", nullable=False)
    slug = Column(String(120), unique=True, nullable=True, index=True)
    plan = Column(String(32), default="free", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    owner = relationship("User", back_populates="owned_workspaces", foreign_keys=[owner_user_id])
    members = relationship("WorkspaceMember", back_populates="workspace", cascade="all, delete-orphan")
    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")
    knowledge_bases = relationship("KnowledgeBase", back_populates="workspace", cascade="all, delete-orphan")
    memories = relationship("WritingMemory", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"

    workspace_id = Column(String(80), ForeignKey("workspaces.id", ondelete="CASCADE"), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    role = Column(String(32), default="owner", nullable=False)
    status = Column(String(32), default="active", nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="memberships")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    refresh_token_hash = Column(String(255), unique=True, nullable=False, index=True)
    user_agent = Column(Text, nullable=True)
    ip_address = Column(String(64), nullable=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    revoked_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")


class PasswordResetToken(Base):
    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash = Column(String(255), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False, index=True)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User")


class UserAPIKey(Base):
    __tablename__ = "user_api_keys"
    __table_args__ = (UniqueConstraint("user_id", "provider", "label", name="uq_user_api_keys_user_provider_label"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider = Column(String(64), nullable=False, index=True)
    label = Column(String(120), default="", nullable=False)
    encrypted_api_key = Column(Text, nullable=False)
    base_url = Column(Text, nullable=True)
    model = Column(String(255), nullable=True)
    status = Column(String(32), default="active", nullable=False, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    user = relationship("User", back_populates="api_keys")


class UserUsageLog(Base):
    __tablename__ = "user_usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    workspace_id = Column(String(80), ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(80), nullable=False, index=True)
    provider = Column(String(64), nullable=True)
    model = Column(String(255), nullable=True)
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    estimated_cost = Column(Numeric(12, 6), default=0.0, nullable=False)
    metadata_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    user = relationship("User")
    workspace = relationship("Workspace")


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    workspace_id = Column(String(80), ForeignKey("workspaces.id", ondelete="CASCADE"), default="anonymous", nullable=False, index=True)
    root_output_dir = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    files = relationship("SourceFile", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("AnalysisJob", back_populates="project", cascade="all, delete-orphan")
    workspace = relationship("Workspace", back_populates="projects")


class SourceFile(Base):
    __tablename__ = "source_files"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = Column(String(512), nullable=False)
    stored_path = Column(Text, nullable=False)
    file_type = Column(String(32), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    parse_status = Column(String(32), default="uploaded", nullable=False)
    parse_error = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    project = relationship("Project", back_populates="files")
    chunks = relationship("ChapterChunk", back_populates="source_file", cascade="all, delete-orphan")
    jobs = relationship("AnalysisJob", back_populates="source_file")


class ChapterChunk(Base):
    __tablename__ = "chapter_chunks"

    id = Column(String(80), primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_index = Column(Integer, nullable=False)
    title = Column(String(512), nullable=False)
    text_path = Column(Text, nullable=False)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    char_count = Column(Integer, nullable=False)
    token_estimate = Column(Integer, nullable=False)
    metadata_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    source_file = relationship("SourceFile", back_populates="chunks")


class AnalysisJob(Base):
    __tablename__ = "analysis_jobs"

    id = Column(String(64), primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(32), default="pending", nullable=False)
    modes_json = Column(Text, default='["chapter_structure"]', nullable=False)
    output_dir = Column(Text, nullable=False)
    base_url = Column(Text, nullable=True)
    model = Column(String(255), nullable=True)
    temperature = Column(Float, default=0.3, nullable=False)
    max_tokens = Column(Integer, default=8192, nullable=False)
    concurrency = Column(Integer, default=1, nullable=False)
    allow_short_quotes = Column(Boolean, default=False, nullable=False)
    generate_kb = Column(Boolean, default=False, nullable=False)
    generate_obsidian = Column(Boolean, default=False, nullable=False)
    generate_graph = Column(Boolean, default=False, nullable=False)
    dry_run = Column(Boolean, default=True, nullable=False)
    skill_id = Column(Integer, ForeignKey("deconstruction_skills.id", ondelete="SET NULL"), nullable=True, index=True)
    total_chunks = Column(Integer, default=0, nullable=False)
    completed_chunks = Column(Integer, default=0, nullable=False)
    failed_chunks = Column(Integer, default=0, nullable=False)
    current_chunk_title = Column(String(512), nullable=True)
    current_mode = Column(String(128), nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    error_message = Column(Text, nullable=True)

    project = relationship("Project", back_populates="jobs")
    source_file = relationship("SourceFile", back_populates="jobs")
    skill = relationship("DeconstructionSkill")
    results = relationship("AnalysisResult", back_populates="job", cascade="all, delete-orphan")
    logs = relationship("JobLog", back_populates="job", cascade="all, delete-orphan")


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_id = Column(String(80), ForeignKey("chapter_chunks.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(String(128), nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    markdown_path = Column(Text, nullable=True)
    json_path = Column(Text, nullable=True)
    prompt_path = Column(Text, nullable=True)
    response_path = Column(Text, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    job = relationship("AnalysisJob", back_populates="results")


class JobLog(Base):
    __tablename__ = "job_logs"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(String(64), ForeignKey("analysis_jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    level = Column(String(32), default="info", nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    job = relationship("AnalysisJob", back_populates="logs")


class PromptTemplate(Base):
    __tablename__ = "prompt_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    mode = Column(String(128), nullable=False, index=True)
    content = Column(Text, nullable=False)
    source = Column(String(255), default="builtin", nullable=False)
    editable = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class DeconstructionSkill(Base):
    __tablename__ = "deconstruction_skills"

    id = Column(Integer, primary_key=True, index=True)
    key = Column("key", String(128), unique=True, nullable=False, index=True, quote=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="", nullable=False)
    source = Column(String(255), default="custom", nullable=False)
    phase = Column(Integer, default=2, nullable=False)
    enabled = Column(Boolean, default=True, nullable=False)
    builtin = Column(Boolean, default=False, nullable=False)
    default_modes_json = Column(Text, default='["chapter_structure"]', nullable=False)
    system_prompt = Column(Text, nullable=True)
    prompt_template = Column(Text, nullable=True)
    metadata_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)


class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="", nullable=False)
    workspace_id = Column(String(80), ForeignKey("workspaces.id", ondelete="CASCADE"), default="anonymous", nullable=False, index=True)
    source_job_id = Column(String(64), ForeignKey("analysis_jobs.id", ondelete="SET NULL"), nullable=True, index=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    documents = relationship("KnowledgeDocument", back_populates="knowledge_base", cascade="all, delete-orphan")
    cards = relationship("KnowledgeCard", back_populates="knowledge_base", cascade="all, delete-orphan")
    memories = relationship("WritingMemory", back_populates="knowledge_base", cascade="all, delete-orphan")
    outlines = relationship("Outline", back_populates="knowledge_base", cascade="all, delete-orphan")
    draft_jobs = relationship("WritingDraftJob", back_populates="knowledge_base", cascade="all, delete-orphan")
    workspace = relationship("Workspace", back_populates="knowledge_bases")


class KnowledgeDocument(Base):
    __tablename__ = "knowledge_documents"

    id = Column(Integer, primary_key=True, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    original_filename = Column(String(512), nullable=False)
    stored_path = Column(Text, nullable=False)
    normalized_path = Column(Text, nullable=True)
    file_type = Column(String(32), nullable=False)
    size_bytes = Column(Integer, nullable=False)
    file_hash = Column(String(64), nullable=False, index=True)
    document_title = Column(String(512), default="", nullable=False)
    source_kind = Column(String(64), default="upload", nullable=False)
    knowledge_type = Column(String(32), default="worldbuilding", nullable=False, index=True)
    source_path = Column(Text, default="", nullable=False)
    structure_path = Column(Text, default="", nullable=False)
    status = Column(String(32), default="pending", nullable=False)
    error_message = Column(Text, nullable=True)
    page_count = Column(Integer, default=0, nullable=False)
    paragraph_count = Column(Integer, default=0, nullable=False)
    chunk_count = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")
    chunks = relationship("KnowledgeChunk", back_populates="document", cascade="all, delete-orphan")


class KnowledgeChunk(Base):
    __tablename__ = "knowledge_chunks"

    id = Column(String(96), primary_key=True, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_id = Column(Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False, index=True)
    chunk_index = Column(Integer, nullable=False)
    heading = Column(String(512), default="", nullable=False)
    page_number = Column(Integer, nullable=True)
    text = Column(Text, nullable=False)
    token_estimate = Column(Integer, default=0, nullable=False)
    metadata_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)

    document = relationship("KnowledgeDocument", back_populates="chunks")


class KnowledgeCard(Base):
    __tablename__ = "knowledge_cards"
    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "card_id", name="uq_knowledge_cards_base_card"),
        Index("idx_card_kb_library_status", "knowledge_base_id", "library_type", "status", "is_canonical", "retrievable"),
        Index("idx_card_scope_position", "knowledge_base_id", "scope_level", "volume_index", "chapter_index"),
        Index(
            "idx_card_visibility_window",
            "knowledge_base_id",
            "retrievable",
            "status",
            "reveal_at_volume_index",
            "reveal_at_chapter_index",
            "valid_from_volume_index",
            "valid_from_chapter_index",
            "valid_until_volume_index",
            "valid_until_chapter_index",
        ),
        Index("idx_card_type_priority", "knowledge_base_id", "card_type", "priority"),
        Index("idx_card_content_hash", "knowledge_base_id", "content_fingerprint"),
        Index("idx_card_title_group", "knowledge_base_id", "normalized_title_hash", "canonical_group_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    card_id = Column(String(96), nullable=False, index=True)
    library_type = Column(String(32), default="writing_guide", nullable=False, index=True)
    card_type = Column(String(64), default="writing_rule", nullable=False, index=True)
    title = Column(String(512), nullable=False)
    content = Column(Text, nullable=False)
    summary = Column(Text, default="", nullable=False)
    tags_json = Column(Text, default="[]", nullable=False)
    source_ref_json = Column(Text, default="{}", nullable=False)
    source_refs_json = Column(Text, default="[]", nullable=False)
    use_when_json = Column(Text, default="[]", nullable=False)
    avoid = Column(Text, default="", nullable=False)
    confidence = Column(Float, default=0.7, nullable=False)
    status = Column(String(32), default="raw_extracted", nullable=False, index=True)
    source_kind = Column(String(64), default="knowledge_package", nullable=False)
    package_id = Column(String(255), default="", nullable=False)
    markdown_path = Column(Text, default="", nullable=False)
    is_canonical = Column(Boolean, default=True, nullable=False, index=True)
    merged_into_card_id = Column(String(96), nullable=True, index=True)
    merged_from_ids_json = Column(Text, default="[]", nullable=False)
    evidence_count = Column(Integer, default=1, nullable=False)
    content_fingerprint = Column(String(64), default="", nullable=False, index=True)
    normalized_title_hash = Column(String(64), default="", nullable=False, index=True)
    canonical_group_id = Column(String(96), default="", nullable=False, index=True)
    retrieval_level = Column(String(24), default="evidence", nullable=False, index=True)
    context_role = Column(String(32), default="auxiliary", nullable=False, index=True)
    scope_level = Column(String(16), default="global", nullable=False, index=True)
    volume_index = Column(Integer, nullable=True, index=True)
    volume_title = Column(String(512), nullable=True)
    chapter_index = Column(Integer, nullable=True, index=True)
    chapter_title = Column(String(512), nullable=True)
    valid_from_volume_index = Column(Integer, nullable=True)
    valid_from_chapter_index = Column(Integer, nullable=True)
    valid_until_volume_index = Column(Integer, nullable=True)
    valid_until_chapter_index = Column(Integer, nullable=True)
    reveal_at_volume_index = Column(Integer, nullable=True)
    reveal_at_chapter_index = Column(Integer, nullable=True)
    retrievable = Column(Boolean, default=False, nullable=False, index=True)
    priority = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    knowledge_base = relationship("KnowledgeBase", back_populates="cards")


class WritingMemory(Base):
    __tablename__ = "writing_memories"

    id = Column(Integer, primary_key=True, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(80), ForeignKey("workspaces.id", ondelete="CASCADE"), default="anonymous", nullable=False, index=True)
    memory_type = Column(String(32), default="note", nullable=False, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, nullable=False)
    tags_json = Column(Text, default="[]", nullable=False)
    source_ref_json = Column(Text, default="{}", nullable=False)
    source = Column(String(64), default="manual", nullable=False)
    scope_level = Column(String(16), default="chapter", nullable=False, index=True)
    volume_index = Column(Integer, nullable=True, index=True)
    volume_title = Column(String(512), nullable=True)
    chapter_index = Column(Integer, nullable=True, index=True)
    chapter_title = Column(String(512), nullable=True)
    valid_from_volume_index = Column(Integer, nullable=True)
    valid_from_chapter_index = Column(Integer, nullable=True)
    valid_until_volume_index = Column(Integer, nullable=True)
    valid_until_chapter_index = Column(Integer, nullable=True)
    reveal_at_volume_index = Column(Integer, nullable=True)
    reveal_at_chapter_index = Column(Integer, nullable=True)
    retrievable = Column(Boolean, default=True, nullable=False, index=True)
    priority = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    knowledge_base = relationship("KnowledgeBase", back_populates="memories")
    workspace = relationship("Workspace", back_populates="memories")

    @property
    def tags(self) -> list[str]:
        try:
            value = json.loads(self.tags_json or "[]")
        except json.JSONDecodeError:
            return []
        return [str(item) for item in value] if isinstance(value, list) else []

    @property
    def source_ref(self) -> dict:
        try:
            value = json.loads(self.source_ref_json or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}


class RetrievalIndexEvent(Base):
    __tablename__ = "retrieval_index_events"
    __table_args__ = (
        Index("idx_retrieval_index_events_status_created", "status", "created_at"),
        Index("idx_retrieval_index_events_source", "source_type", "source_id", "operation"),
        Index("idx_retrieval_index_events_workspace", "workspace_id", "knowledge_base_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(String(80), nullable=True, index=True)
    knowledge_base_id = Column(Integer, nullable=True, index=True)
    source_type = Column(String(32), nullable=False, index=True)
    source_id = Column(String(96), nullable=False, index=True)
    operation = Column(String(32), nullable=False, index=True)
    status = Column(String(24), default="pending", nullable=False, index=True)
    attempt_count = Column(Integer, default=0, nullable=False)
    last_error = Column(Text, nullable=True)
    result_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)
    processed_at = Column(DateTime, nullable=True)


class WritingDraftJob(Base):
    __tablename__ = "writing_draft_jobs"

    job_id = Column(String(64), primary_key=True, index=True)
    work_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(80), nullable=False, index=True)
    status = Column(String(32), default="queued", nullable=False, index=True)
    stage = Column(String(32), default="draft", nullable=False)
    target_chars = Column(Integer, nullable=True)
    actual_chars = Column(Integer, nullable=True)
    cjk_chars = Column(Integer, nullable=True)
    non_space_chars = Column(Integer, nullable=True)
    estimated_tokens = Column(Integer, nullable=True)
    completion_ratio = Column(Float, nullable=True)
    section_count = Column(Integer, nullable=True)
    current_section = Column(Integer, nullable=True)
    content = Column(Text, default="", nullable=False)
    sections_json = Column(Text, default="[]", nullable=False)
    used_knowledge_json = Column(Text, default="[]", nullable=False)
    retrieval_debug_json = Column(Text, nullable=True)
    warnings_json = Column(Text, default="[]", nullable=False)
    request_payload_json = Column(Text, default="{}", nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    knowledge_base = relationship("KnowledgeBase", back_populates="draft_jobs")


class Outline(Base):
    """书→卷→章 三层提纲树。通过 parent_id 构建树形结构，seq 控制同级排序。"""

    __tablename__ = "outlines"

    id = Column(Integer, primary_key=True, index=True)
    knowledge_base_id = Column(Integer, ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True)
    workspace_id = Column(String(80), ForeignKey("workspaces.id", ondelete="CASCADE"), default="anonymous", nullable=False, index=True)
    parent_id = Column(Integer, ForeignKey("outlines.id", ondelete="CASCADE"), nullable=True, index=True)
    level = Column(String(16), default="chapter", nullable=False, index=True, comment="book / volume / chapter")
    seq = Column(Integer, default=0, nullable=False, comment="同级排序序号")
    volume_index = Column(Integer, nullable=True, index=True)
    chapter_index = Column(Integer, nullable=True, index=True)
    title = Column(String(512), default="", nullable=False)
    content = Column(Text, nullable=True)
    source = Column(String(64), default="ai_generated", nullable=False, comment="auto_generated / ai_generated / user_confirmed / manual")
    status = Column(String(32), default="draft", nullable=False, index=True, comment="draft / confirmed / archived")
    metadata_json = Column(Text, nullable=True)
    content_fingerprint = Column(String(64), default="", nullable=False)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    knowledge_base = relationship("KnowledgeBase", foreign_keys=[knowledge_base_id])
    workspace = relationship("Workspace")
    parent = relationship("Outline", remote_side=[id], back_populates="children")
    children = relationship("Outline", back_populates="parent", cascade="all, delete-orphan")

    @property
    def metadata_dict(self) -> dict:
        try:
            value = json.loads(self.metadata_json or "{}")
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

