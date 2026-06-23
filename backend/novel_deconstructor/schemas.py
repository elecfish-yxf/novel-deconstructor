from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthUserRead(ORMModel):
    id: int
    email: str
    username: str | None
    display_name: str
    avatar_url: str | None
    status: str
    created_at: datetime


class AuthRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    username: str | None = Field(default=None, max_length=80)
    display_name: str = Field(default="", max_length=120)


class AuthLoginRequest(BaseModel):
    identity: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    workspace_id: str
    user: AuthUserRead


class AuthMeResponse(BaseModel):
    user: AuthUserRead
    workspace_id: str


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    root_output_dir: str | None = None


class ProjectRead(ORMModel):
    id: int
    name: str
    description: str
    root_output_dir: str | None
    created_at: datetime
    updated_at: datetime
    latest_job_status: str | None = None


class SourceFileRead(ORMModel):
    id: int
    project_id: int
    original_filename: str
    stored_path: str
    file_type: str
    size_bytes: int
    parse_status: str
    parse_error: str | None
    created_at: datetime
    chapter_count: int = 0


class ChapterChunkRead(ORMModel):
    id: str
    project_id: int
    source_file_id: int
    chapter_index: int
    title: str
    text_path: str
    char_start: int
    char_end: int
    char_count: int
    token_estimate: int
    metadata_json: str
    created_at: datetime
    preview: str | None = None


class SplitRequest(BaseModel):
    max_chapter_chars: int | None = None
    overlap_chars: int | None = None
    strict_chapter_split: bool = True


class SplitResponse(BaseModel):
    file_id: int
    chapter_count: int
    chapters: list[ChapterChunkRead]


class JobCreate(BaseModel):
    project_id: int
    source_file_id: int
    output_dir: str | None = None
    skill_id: int | None = None
    modes: list[str] = Field(default_factory=lambda: ["chapter_structure"])
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None
    temperature: float = 0.3
    max_tokens: int = 8192
    concurrency: int = 1
    allow_short_quotes: bool = False
    generate_kb: bool = False
    generate_obsidian: bool = False
    generate_graph: bool = False
    dry_run: bool = True
    resume: bool = False


class JobRead(ORMModel):
    id: str
    project_id: int
    source_file_id: int
    status: str
    modes_json: str
    output_dir: str
    base_url: str | None
    model: str | None
    temperature: float
    max_tokens: int
    concurrency: int
    allow_short_quotes: bool
    generate_kb: bool
    generate_obsidian: bool
    generate_graph: bool
    dry_run: bool
    skill_id: int | None
    total_chunks: int
    completed_chunks: int
    failed_chunks: int
    current_chunk_title: str | None
    current_mode: str | None
    created_at: datetime
    updated_at: datetime
    error_message: str | None


class JobRuntimeKeyRequest(BaseModel):
    api_key: str | None = None


class AnalysisResultRead(ORMModel):
    id: int
    job_id: str
    chunk_id: str
    mode: str
    status: str
    markdown_path: str | None
    json_path: str | None
    prompt_path: str | None
    response_path: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class JobLogRead(ORMModel):
    id: int
    job_id: str
    level: str
    message: str
    created_at: datetime


class PromptTemplateCreate(BaseModel):
    name: str
    mode: str
    content: str
    source: str = "custom"
    editable: bool = True


class PromptTemplateUpdate(BaseModel):
    name: str | None = None
    content: str | None = None
    editable: bool | None = None


class PromptTemplateRead(ORMModel):
    id: int
    name: str
    mode: str
    content: str
    source: str
    editable: bool
    created_at: datetime
    updated_at: datetime


class SkillCreate(BaseModel):
    key: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    source: str = "custom"
    phase: int = 2
    enabled: bool = True
    default_modes: list[str] = Field(default_factory=lambda: ["chapter_structure"])
    system_prompt: str | None = None
    prompt_template: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SkillUpdate(BaseModel):
    key: str | None = Field(default=None, min_length=1, max_length=128)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    source: str | None = None
    phase: int | None = None
    enabled: bool | None = None
    default_modes: list[str] | None = None
    system_prompt: str | None = None
    prompt_template: str | None = None
    metadata: dict[str, Any] | None = None


class SkillRead(ORMModel):
    id: int
    key: str
    name: str
    description: str
    source: str
    phase: int
    enabled: bool
    builtin: bool
    default_modes_json: str
    system_prompt: str | None
    prompt_template: str | None
    metadata_json: str
    created_at: datetime
    updated_at: datetime


class FileListItem(BaseModel):
    path: str
    name: str
    size_bytes: int
    kind: str
    modified_at: datetime


class ImportScanRequest(BaseModel):
    github_url: str | None = None
    local_path: str | None = None


class ImportScanResponse(BaseModel):
    files: list[dict[str, Any]]
    message: str


class DirectoryPickRequest(BaseModel):
    initial_dir: str | None = None


class DirectoryPickResponse(BaseModel):
    path: str | None
    message: str


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""


class KnowledgeBaseUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


class KnowledgeBaseRead(ORMModel):
    id: int
    name: str
    description: str
    source_job_id: str | None
    created_at: datetime
    updated_at: datetime
    document_count: int = 0
    chunk_count: int = 0


class KnowledgeDocumentRead(ORMModel):
    id: int
    knowledge_base_id: int
    original_filename: str
    file_type: str
    size_bytes: int
    file_hash: str
    document_title: str
    source_kind: str
    knowledge_type: str
    source_path: str
    structure_path: str
    status: str
    error_message: str | None
    page_count: int
    paragraph_count: int
    chunk_count: int
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentBulkDeleteRequest(BaseModel):
    document_ids: list[int] = Field(default_factory=list)
    knowledge_type: str | None = None
    delete_all: bool = False


class KnowledgeDocumentBulkDeleteResponse(BaseModel):
    deleted: int
    message: str


class KnowledgeImportJobRequest(BaseModel):
    job_id: str
    include_chapter_analysis: bool = False
    include_final_reports: bool = True
    include_knowledge_base: bool = True
    include_obsidian: bool = False
    include_graph: bool = False
    include_oh_story: bool = False


class KnowledgeImportResponse(BaseModel):
    imported: list[KnowledgeDocumentRead]
    skipped_duplicates: int = 0
    message: str


class KnowledgePackageImportRequest(BaseModel):
    package_path: str | None = None
    package_json: dict[str, Any] | None = None
    library_type: str = "writing_guide"
    status: str = "approved"


class KnowledgePackageImportResponse(BaseModel):
    imported_count: int
    generated_markdown_count: int = 0
    skipped_count: int = 0
    card_types: dict[str, int] = Field(default_factory=dict)
    markdown_root: str
    message: str


class KnowledgeMarkdownImportRequest(BaseModel):
    source_name: str = "external_knowledge.md"
    source_path: str | None = None
    content: str | None = None
    library_type: str = "writing_guide"
    status: str = "raw_extracted"


class KnowledgeMarkdownImportResponse(KnowledgePackageImportResponse):
    source_name: str | None = None


class KnowledgeCardRead(ORMModel):
    id: int
    knowledge_base_id: int
    card_id: str
    library_type: str
    card_type: str
    title: str
    content: str
    summary: str
    tags: list[str] = Field(default_factory=list)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    use_when: list[str] = Field(default_factory=list)
    avoid: str
    confidence: float
    status: str
    source_kind: str
    package_id: str
    markdown_path: str
    created_at: datetime
    updated_at: datetime


class KnowledgeCardUpdate(BaseModel):
    title: str | None = None
    content: str | None = None
    summary: str | None = None
    tags: list[str] | None = None
    source_ref: dict[str, Any] | None = None
    use_when: list[str] | None = None
    avoid: str | None = None
    confidence: float | None = None
    status: str | None = None


class KnowledgeMarkdownDocRead(BaseModel):
    doc_id: str
    card_id: str
    library_type: str
    card_type: str
    title: str
    status: str
    path: str
    exists: bool
    updated_at: datetime


class KnowledgeMarkdownDocContent(BaseModel):
    doc_id: str
    card_id: str
    content: str
    path: str


class KnowledgeMarkdownDocSave(BaseModel):
    content: str = Field(min_length=1)


class KnowledgeMarkdownSyncResponse(BaseModel):
    card_id: str
    status: str
    updated_fields: list[str] = Field(default_factory=list)


class RetrievalSearchRequest(BaseModel):
    knowledge_base_ids: list[int] = Field(default_factory=list)
    query: str = Field(min_length=1)
    top_k: int | None = None


class RetrievalHit(BaseModel):
    citation_id: str
    knowledge_base_id: int
    document_id: int
    chunk_id: str
    score: float
    original_filename: str
    document_title: str
    knowledge_type: str
    heading: str
    page_number: int | None
    structure_path: str
    source_kind: str
    source_path: str
    text: str


class RetrievalSearchResponse(BaseModel):
    hits: list[RetrievalHit]


class RAGSearchRequest(BaseModel):
    stage: str = "draft"
    query: str = Field(min_length=1)
    top_k: int = 8
    library_type: str | None = None
    include_inactive: bool = False


class UsedKnowledge(BaseModel):
    id: str
    library_type: str
    card_type: str
    title: str
    score: float
    source_ref: dict[str, Any] = Field(default_factory=dict)


class RAGSearchResult(UsedKnowledge):
    content_preview: str
    tags: list[str] = Field(default_factory=list)
    status: str


class RetrievalDebug(BaseModel):
    query: str
    preferred_card_types: list[str] = Field(default_factory=list)
    total_candidates: int = 0
    selected_count: int = 0
    stage: str | None = None
    top_k: int | None = None


class RAGSearchResponse(BaseModel):
    results: list[RAGSearchResult]
    retrieval_debug: RetrievalDebug


class WritingGenerateRequest(BaseModel):
    knowledge_base_ids: list[int] = Field(default_factory=list)
    task: str = Field(min_length=1)
    current_content: str = ""
    mode: str = "fast"
    knowledge_mode: str = "reference"
    model_provider: str | None = None
    model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    dry_run: bool = False
    top_k: int | None = None
    stage: str | None = None
    target_chars: int | None = None


class WritingOutlineRequest(WritingGenerateRequest):
    pass


class WritingDraftRequest(WritingGenerateRequest):
    confirmed_outline: str = Field(min_length=1)


class WritingMemoryCreate(BaseModel):
    knowledge_base_id: int
    memory_type: str = "note"
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"


class WritingMemoryConfirmRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_ref: dict[str, Any] = Field(default_factory=dict)


class WritingMemoryRead(ORMModel):
    id: int
    knowledge_base_id: int
    workspace_id: str
    memory_type: str
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    source: str
    created_at: datetime
    updated_at: datetime


class KnowledgeTextCreate(BaseModel):
    filename: str = "worldbuilding.md"
    content: str = Field(min_length=1)
    knowledge_type: str = "worldbuilding"


class WorldbuildingDraftRequest(BaseModel):
    knowledge_base_ids: list[int] = Field(default_factory=list)
    story_seed: str = Field(min_length=1)
    requirements: str = ""
    model_provider: str | None = None
    model: str | None = None
    api_key: str | None = None
    dry_run: bool = True


class WorldbuildingDraftResponse(BaseModel):
    content: str
    citations: list[RetrievalHit]


class LongGenerationSection(BaseModel):
    index: int
    target_chars: int
    actual_chars: int
    status: str
    focus: str
    content: str = ""
    used_knowledge: list[UsedKnowledge] = Field(default_factory=list)
    retrieval_debug: RetrievalDebug | None = None


class WritingGenerateResponse(BaseModel):
    content: str
    citations: list[RetrievalHit]
    stage: str | None = None
    used_knowledge: list[UsedKnowledge] = Field(default_factory=list)
    retrieval_debug: RetrievalDebug | None = None
    prompt_preview: str | None = None
    target_chars: int | None = None
    actual_chars: int | None = None
    section_count: int | None = None
    sections: list[LongGenerationSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

