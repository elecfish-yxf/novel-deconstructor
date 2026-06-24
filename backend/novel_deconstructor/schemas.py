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


class KnowledgeBaseBulkDeleteRequest(BaseModel):
    knowledge_base_ids: list[int] = Field(default_factory=list)


class KnowledgeBaseBulkDeleteResponse(BaseModel):
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
    merge_mode: str = "safe"
    auto_merge_threshold: float = 0.88
    review_threshold: float = 0.72
    generate_markdown: bool = True
    markdown_scope: str = "canonical_only"


class KnowledgePackageImportResponse(BaseModel):
    imported_count: int
    generated_markdown_count: int = 0
    skipped_count: int = 0
    raw_card_count: int = 0
    canonical_card_count: int = 0
    exact_duplicate_count: int = 0
    merged_card_count: int = 0
    compacted_card_count: int = 0
    compacted_evidence_count: int = 0
    review_required_count: int = 0
    reduction_rate: float = 0
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
    is_canonical: bool = True
    merged_into_card_id: str | None = None
    merged_from_ids: list[str] = Field(default_factory=list)
    evidence_count: int = 1
    content_fingerprint: str = ""
    scope_level: str = "global"
    volume_index: int | None = None
    volume_title: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    valid_from_volume_index: int | None = None
    valid_from_chapter_index: int | None = None
    valid_until_volume_index: int | None = None
    valid_until_chapter_index: int | None = None
    reveal_at_volume_index: int | None = None
    reveal_at_chapter_index: int | None = None
    retrievable: bool = False
    priority: int = 0
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
    is_canonical: bool | None = None
    scope_level: str | None = None
    volume_index: int | None = None
    volume_title: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    valid_from_volume_index: int | None = None
    valid_from_chapter_index: int | None = None
    valid_until_volume_index: int | None = None
    valid_until_chapter_index: int | None = None
    reveal_at_volume_index: int | None = None
    reveal_at_chapter_index: int | None = None
    retrievable: bool | None = None
    priority: int | None = None


class KnowledgeCardBulkDeleteRequest(BaseModel):
    card_ids: list[str] = Field(default_factory=list)


class KnowledgeMarkdownDocBulkDeleteRequest(BaseModel):
    doc_ids: list[str] = Field(default_factory=list)


class KnowledgeMergeRequest(BaseModel):
    merge_mode: str = "safe"
    auto_merge_threshold: float = 0.88
    review_threshold: float = 0.72


class KnowledgeMergeCardSummary(BaseModel):
    card_id: str
    title: str
    library_type: str
    card_type: str
    status: str
    is_canonical: bool
    evidence_count: int


class KnowledgeMergeGroup(BaseModel):
    group_id: str
    action: str
    reason: str
    similarity: float
    primary_card_id: str
    candidate_card_ids: list[str] = Field(default_factory=list)
    cards: list[KnowledgeMergeCardSummary] = Field(default_factory=list)


class KnowledgeMergePreviewResponse(BaseModel):
    groups: list[KnowledgeMergeGroup] = Field(default_factory=list)
    auto_merge_count: int = 0
    review_required_count: int = 0
    exact_duplicate_count: int = 0


class KnowledgeMergeApplyResponse(BaseModel):
    merged_card_count: int = 0
    generated_markdown_count: int = 0
    compacted_card_count: int = 0
    compacted_evidence_count: int = 0
    groups: list[KnowledgeMergeGroup] = Field(default_factory=list)
    message: str


class KnowledgeMergeStatsResponse(BaseModel):
    raw_card_count: int = 0
    canonical_card_count: int = 0
    merged_card_count: int = 0
    disabled_card_count: int = 0
    deleted_card_count: int = 0
    review_required_count: int = 0
    reduction_rate: float = 0


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


class WritingChapterRef(BaseModel):
    volume_index: int = Field(ge=1)
    chapter_index: int = Field(ge=1)


class WritingScopeBulkDeleteRequest(BaseModel):
    volume_indices: list[int] = Field(default_factory=list)
    chapters: list[WritingChapterRef] = Field(default_factory=list)


class WritingScopeBulkDeleteResponse(BaseModel):
    deleted_volumes: int = 0
    deleted_chapters: int = 0
    deleted_memories: int = 0
    deleted_cards: int = 0
    deleted_markdown_files: int = 0
    message: str


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
    current_volume_index: int | None = None
    current_chapter_index: int | None = None
    include_future: bool = False
    include_raw: bool = False
    allowed_scope_levels: list[str] | None = None


class UsedKnowledge(BaseModel):
    id: str
    library_type: str
    card_type: str
    title: str
    score: float
    source_ref: dict[str, Any] = Field(default_factory=dict)
    content_preview: str = ""
    tags: list[str] = Field(default_factory=list)
    status: str | None = None
    scope_level: str | None = None
    volume_index: int | None = None
    chapter_index: int | None = None


class RAGSearchResult(UsedKnowledge):
    content_preview: str
    tags: list[str] = Field(default_factory=list)
    status: str


class RetrievalDebug(BaseModel):
    query: str
    raw_query: str | None = None
    expanded_terms: list[str] = Field(default_factory=list)
    preferred_card_types: list[str] = Field(default_factory=list)
    total_candidates: int = 0
    current_volume_index: int | None = None
    current_chapter_index: int | None = None
    candidate_count_before_scope_filter: int = 0
    candidate_count_after_scope_filter: int = 0
    filtered_by_status_count: int = 0
    filtered_by_scope_count: int = 0
    filtered_by_future_count: int = 0
    selected_card_ids: list[str] = Field(default_factory=list)
    selected_card_scope: dict[str, str] = Field(default_factory=dict)
    selected_count: int = 0
    filtered_duplicate_count: int = 0
    diversity_buckets: dict[str, int] = Field(default_factory=dict)
    stage: str | None = None
    top_k: int | None = None
    warnings: list[str] = Field(default_factory=list)


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
    current_volume_index: int | None = None
    current_chapter_index: int | None = None
    include_future_knowledge: bool = False
    include_raw_knowledge: bool = False


class WritingOutlineRequest(WritingGenerateRequest):
    pass


class WritingDraftRequest(WritingGenerateRequest):
    confirmed_outline: str = Field(min_length=1)


class WritingRevisionRequest(WritingGenerateRequest):
    confirmed_outline: str = ""


class WritingMemoryCreate(BaseModel):
    knowledge_base_id: int
    memory_type: str = "note"
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    source: str = "manual"
    scope_level: str = "chapter"
    volume_index: int | None = None
    volume_title: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    valid_from_volume_index: int | None = None
    valid_from_chapter_index: int | None = None
    valid_until_volume_index: int | None = None
    valid_until_chapter_index: int | None = None
    reveal_at_volume_index: int | None = None
    reveal_at_chapter_index: int | None = None
    retrievable: bool = True
    priority: int = 0


class WritingMemoryBulkDeleteRequest(BaseModel):
    memory_ids: list[int] = Field(default_factory=list)


class WritingMemoryConfirmRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)
    tags: list[str] = Field(default_factory=list)
    source_ref: dict[str, Any] = Field(default_factory=dict)
    scope_level: str = "chapter"
    volume_index: int | None = None
    volume_title: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    valid_from_volume_index: int | None = None
    valid_from_chapter_index: int | None = None
    valid_until_volume_index: int | None = None
    valid_until_chapter_index: int | None = None
    reveal_at_volume_index: int | None = None
    reveal_at_chapter_index: int | None = None
    retrievable: bool = True
    priority: int = 0


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
    scope_level: str = "chapter"
    volume_index: int | None = None
    volume_title: str | None = None
    chapter_index: int | None = None
    chapter_title: str | None = None
    valid_from_volume_index: int | None = None
    valid_from_chapter_index: int | None = None
    valid_until_volume_index: int | None = None
    valid_until_chapter_index: int | None = None
    reveal_at_volume_index: int | None = None
    reveal_at_chapter_index: int | None = None
    retrievable: bool = True
    priority: int = 0
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
    continuity_state: str = ""
    supplement_count: int = 0
    cjk_chars: int = 0
    non_space_chars: int = 0
    estimated_tokens: int = 0
    error_message: str | None = None
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
    cjk_chars: int | None = None
    non_space_chars: int | None = None
    estimated_tokens: int | None = None
    completion_ratio: float | None = None
    section_count: int | None = None
    sections: list[LongGenerationSection] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    memory_written: bool = False


class WritingDraftJobRead(BaseModel):
    job_id: str
    work_id: int
    status: str
    stage: str = "draft"
    target_chars: int | None = None
    actual_chars: int | None = None
    cjk_chars: int | None = None
    non_space_chars: int | None = None
    estimated_tokens: int | None = None
    completion_ratio: float | None = None
    section_count: int | None = None
    current_section: int | None = None
    content: str = ""
    sections: list[LongGenerationSection] = Field(default_factory=list)
    used_knowledge: list[UsedKnowledge] = Field(default_factory=list)
    retrieval_debug: RetrievalDebug | None = None
    warnings: list[str] = Field(default_factory=list)
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

