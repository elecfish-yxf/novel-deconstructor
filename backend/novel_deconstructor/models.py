from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


def utcnow() -> datetime:
    return datetime.utcnow()


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    root_output_dir = Column(Text, nullable=True)
    created_at = Column(DateTime, default=utcnow, nullable=False)
    updated_at = Column(DateTime, default=utcnow, onupdate=utcnow, nullable=False)

    files = relationship("SourceFile", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("AnalysisJob", back_populates="project", cascade="all, delete-orphan")


class SourceFile(Base):
    __tablename__ = "source_files"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id"), nullable=False, index=True)
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
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    source_file_id = Column(Integer, ForeignKey("source_files.id"), nullable=False, index=True)
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
    skill_id = Column(Integer, ForeignKey("deconstruction_skills.id"), nullable=True, index=True)
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
    job_id = Column(String(64), ForeignKey("analysis_jobs.id"), nullable=False, index=True)
    chunk_id = Column(String(80), ForeignKey("chapter_chunks.id"), nullable=False, index=True)
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
    job_id = Column(String(64), ForeignKey("analysis_jobs.id"), nullable=False, index=True)
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
    key = Column(String(128), unique=True, nullable=False, index=True)
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

