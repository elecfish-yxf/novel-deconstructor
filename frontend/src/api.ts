const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://localhost:8000" : "");
const WORKSPACE_KEY = "novel-deconstructor.workspace-id";
const AUTH_KEY = "novel-deconstructor.auth-session";

export type AuthUser = {
  id: number;
  email: string;
  username?: string | null;
  display_name: string;
  avatar_url?: string | null;
  status: string;
  created_at: string;
};

export type AuthSession = {
  access_token: string;
  token_type: string;
  expires_at: string;
  workspace_id: string;
  user: AuthUser;
};

export function getWorkspaceId() {
  const session = getStoredAuthSession();
  if (session?.workspace_id) return session.workspace_id;
  let existing = window.localStorage.getItem(WORKSPACE_KEY);
  if (existing) return existing;
  existing = `ws_${crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}_${Math.random().toString(36).slice(2)}`}`;
  window.localStorage.setItem(WORKSPACE_KEY, existing);
  return existing;
}

export function getStoredAuthSession(): AuthSession | null {
  try {
    const raw = window.localStorage.getItem(AUTH_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AuthSession;
    return parsed?.access_token ? parsed : null;
  } catch {
    return null;
  }
}

export function storeAuthSession(session: AuthSession) {
  window.localStorage.setItem(AUTH_KEY, JSON.stringify(session));
}

export function clearAuthSession() {
  window.localStorage.removeItem(AUTH_KEY);
}

function authToken() {
  return getStoredAuthSession()?.access_token || "";
}

function authHeaders(): Record<string, string> {
  const token = authToken();
  return token ? { Authorization: `Bearer ${token}` } : { "X-Workspace-Id": getWorkspaceId() };
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const baseHeaders = authHeaders();
  const headers =
    options.body instanceof FormData
      ? { ...baseHeaders, ...(options.headers || {}) }
      : { "Content-Type": "application/json", ...baseHeaders, ...(options.headers || {}) };
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (!response.ok) {
    let message = response.statusText;
    try {
      const data = await response.json();
      message = data.detail || message;
    } catch {
      // Keep HTTP status text when the server did not return JSON.
    }
    throw new Error(Array.isArray(message) ? message.map((item) => item.msg).join("; ") : message);
  }
  return response.json() as Promise<T>;
}

export type Project = {
  id: number;
  name: string;
  description: string;
  root_output_dir?: string | null;
  created_at: string;
  updated_at: string;
  latest_job_status?: string | null;
};

export type SourceFile = {
  id: number;
  project_id: number;
  original_filename: string;
  stored_path: string;
  file_type: string;
  size_bytes: number;
  parse_status: string;
  parse_error?: string | null;
  created_at: string;
  chapter_count: number;
};

export type Chapter = {
  id: string;
  project_id: number;
  source_file_id: number;
  chapter_index: number;
  title: string;
  text_path: string;
  char_start: number;
  char_end: number;
  char_count: number;
  token_estimate: number;
  metadata_json: string;
  created_at: string;
  preview?: string | null;
};

export type Job = {
  id: string;
  project_id: number;
  source_file_id: number;
  status: string;
  modes_json: string;
  output_dir: string;
  base_url?: string | null;
  model?: string | null;
  temperature: number;
  max_tokens: number;
  concurrency: number;
  allow_short_quotes: boolean;
  generate_kb: boolean;
  generate_obsidian: boolean;
  generate_graph: boolean;
  dry_run: boolean;
  total_chunks: number;
  completed_chunks: number;
  failed_chunks: number;
  current_chunk_title?: string | null;
  current_mode?: string | null;
  created_at: string;
  updated_at: string;
  error_message?: string | null;
};

export type JobLog = {
  id: number;
  job_id: string;
  level: string;
  message: string;
  created_at: string;
};

export type ResultFile = {
  path: string;
  name: string;
  size_bytes: number;
  kind: string;
  modified_at: string;
};

export type PromptTemplate = {
  id: number;
  name: string;
  mode: string;
  content: string;
  source: string;
  editable: boolean;
  created_at: string;
  updated_at: string;
};

export type DeconstructionSkill = {
  id: number;
  key: string;
  name: string;
  description: string;
  source: string;
  phase: number;
  enabled: boolean;
  builtin: boolean;
  default_modes_json: string;
  system_prompt?: string | null;
  prompt_template?: string | null;
  metadata_json: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeBase = {
  id: number;
  name: string;
  description: string;
  source_job_id?: string | null;
  created_at: string;
  updated_at: string;
  document_count: number;
  chunk_count: number;
};

export type KnowledgeDocument = {
  id: number;
  knowledge_base_id: number;
  original_filename: string;
  file_type: string;
  size_bytes: number;
  file_hash: string;
  document_title: string;
  source_kind: string;
  knowledge_type: string;
  source_path: string;
  structure_path: string;
  status: string;
  error_message?: string | null;
  page_count: number;
  paragraph_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeCard = {
  id: number;
  knowledge_base_id: number;
  card_id: string;
  library_type: string;
  card_type: string;
  title: string;
  content: string;
  summary: string;
  tags: string[];
  source_ref: Record<string, unknown>;
  source_refs?: Record<string, unknown>[];
  use_when: string[];
  avoid: string;
  confidence: number;
  status: string;
  source_kind: string;
  package_id: string;
  markdown_path: string;
  is_canonical: boolean;
  merged_into_card_id?: string | null;
  merged_from_ids: string[];
  evidence_count: number;
  content_fingerprint: string;
  normalized_title_hash?: string;
  canonical_group_id?: string;
  retrieval_level?: string;
  context_role?: string;
  scope_level: string;
  volume_index?: number | null;
  volume_title?: string | null;
  chapter_index?: number | null;
  chapter_title?: string | null;
  valid_from_volume_index?: number | null;
  valid_from_chapter_index?: number | null;
  valid_until_volume_index?: number | null;
  valid_until_chapter_index?: number | null;
  reveal_at_volume_index?: number | null;
  reveal_at_chapter_index?: number | null;
  retrievable: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
};

export type KnowledgeMergeCardSummary = {
  card_id: string;
  title: string;
  library_type: string;
  card_type: string;
  status: string;
  is_canonical: boolean;
  evidence_count: number;
};

export type KnowledgeMergeGroup = {
  group_id: string;
  action: string;
  reason: string;
  similarity: number;
  primary_card_id: string;
  candidate_card_ids: string[];
  cards: KnowledgeMergeCardSummary[];
};

export type KnowledgeMergePreview = {
  groups: KnowledgeMergeGroup[];
  auto_merge_count: number;
  review_required_count: number;
  exact_duplicate_count: number;
};

export type KnowledgeMergeApplyResult = {
  merged_card_count: number;
  generated_markdown_count: number;
  groups: KnowledgeMergeGroup[];
  message: string;
};

export type KnowledgeMergeStats = {
  raw_card_count: number;
  canonical_card_count: number;
  merged_card_count: number;
  disabled_card_count: number;
  deleted_card_count: number;
  review_required_count: number;
  reduction_rate: number;
};

export type KnowledgeMarkdownDoc = {
  doc_id: string;
  card_id: string;
  library_type: string;
  card_type: string;
  title: string;
  status: string;
  path: string;
  exists: boolean;
  updated_at: string;
};

export type KnowledgeImportResult = {
  imported_count: number;
  generated_markdown_count: number;
  skipped_count: number;
  raw_card_count?: number;
  canonical_card_count?: number;
  exact_duplicate_count?: number;
  merged_card_count?: number;
  review_required_count?: number;
  reduction_rate?: number;
  card_types: Record<string, number>;
  markdown_root: string;
  message: string;
  source_name?: string | null;
};

export type UsedKnowledge = {
  id: string;
  library_type: string;
  card_type: string;
  title: string;
  score: number;
  source_type?: string | null;
  reason?: string | null;
  source_ref: Record<string, unknown>;
  content_preview?: string;
  concise_content?: string | null;
  tags?: string[];
  status?: string | null;
  retrieval_level?: string | null;
  context_role?: string | null;
  scope_level?: string | null;
  volume_index?: number | null;
  chapter_index?: number | null;
};

export type RAGSearchResult = UsedKnowledge & {
  content_preview: string;
  tags: string[];
  status: string;
  final_score?: number | null;
  vector_score?: number | null;
  keyword_score?: number | null;
  type_bonus?: number | null;
  priority_bonus?: number | null;
  source_modes?: string[];
};

export type RAGHealth = {
  qdrant_available: boolean;
  collection: string;
  collection_exists: boolean;
  points_count: number;
  vector_size: number;
  distance: string;
  embedding_provider: string;
  embedding_model: string;
  embedding_base_url: string;
  embedding_configured: boolean;
  embedding_vector_size?: number | null;
  embedding_missing: string[];
  embedding_qdrant_size_match?: boolean | null;
  collection_vector_size_matches_config?: boolean | null;
  collection_distance_matches_config?: boolean | null;
  retrieval_mode: string;
  warnings: string[];
  error?: string | null;
};

export type RAGRebuildPayload = {
  knowledge_base_ids?: number[];
  document_ids?: number[];
  card_ids?: string[];
  memory_ids?: number[];
  dry_run?: boolean;
  force?: boolean;
};

export type RAGRebuildResult = {
  dry_run: boolean;
  force: boolean;
  planned: Record<string, number>;
  indexed: Record<string, number>;
  skipped: Array<Record<string, unknown>>;
  errors: Array<Record<string, unknown>>;
};

export type RAGPreviewPayload = {
  query: string;
  phase?: string;
  knowledge_base_ids?: number[];
  library_types?: string[] | null;
  target_volume_index?: number | null;
  target_chapter_index?: number | null;
  top_k?: number | null;
  include_future?: boolean;
  include_raw?: boolean;
};

export type RAGPreviewResponse = {
  hits: RAGSearchResult[];
  used_knowledge: UsedKnowledge[];
  retrieval_debug: RetrievalDebug;
};

export type LongGenerationSection = {
  index: number;
  target_chars: number;
  actual_chars: number;
  status: string;
  focus: string;
  content: string;
  continuity_state?: string;
  supplement_count?: number;
  cjk_chars?: number;
  non_space_chars?: number;
  estimated_tokens?: number;
  error_message?: string | null;
  used_knowledge: UsedKnowledge[];
  retrieval_debug?: RetrievalDebug | null;
};

export type RetrievalDebug = {
  query: string;
  raw_query?: string | null;
  expanded_terms?: string[];
  preferred_card_types: string[];
  mode?: string | null;
  effective_mode?: string | null;
  scope_filter?: Record<string, unknown>;
  vector_candidates?: number;
  keyword_candidates?: number;
  merged_candidates?: number;
  final_hits?: number;
  fallback?: string | null;
  filters_applied?: string[];
  weights?: Record<string, number>;
  dropped?: Array<Record<string, unknown>>;
  keyword_debug?: Record<string, unknown>;
  total_candidates: number;
  candidate_count_total?: number;
  current_volume_index?: number | null;
  current_chapter_index?: number | null;
  candidate_count_after_db_filter?: number;
  candidate_count_after_status_filter?: number;
  candidate_count_after_retrieval_level_filter?: number;
  candidate_count_after_visibility_filter?: number;
  candidate_count_before_scope_filter?: number;
  candidate_count_after_scope_filter?: number;
  filtered_by_status_count?: number;
  filtered_by_scope_count?: number;
  filtered_by_future_count?: number;
  raw_cards_excluded_count?: number;
  secondary_cards_excluded_count?: number;
  future_cards_excluded_count?: number;
  duplicate_group_excluded_count?: number;
  source_cap_excluded_count?: number;
  selected_card_ids?: string[];
  selected_card_scope?: Record<string, string>;
  selected_card_type_distribution?: Record<string, number>;
  selected_scope_distribution?: Record<string, number>;
  selected_pinned_context?: string[];
  selected_top_k_cards?: Array<Record<string, unknown>>;
  selected_count: number;
  filtered_duplicate_count?: number;
  diversity_buckets?: Record<string, number>;
  stage?: string | null;
  top_k?: number | null;
  warnings?: string[];
};

export type WritingGenerateResult = {
  content: string;
  citations: RetrievalHit[];
  stage?: string | null;
  used_knowledge?: UsedKnowledge[];
  retrieval_debug?: RetrievalDebug | null;
  prompt_preview?: string | null;
  target_chars?: number | null;
  actual_chars?: number | null;
  cjk_chars?: number | null;
  non_space_chars?: number | null;
  estimated_tokens?: number | null;
  completion_ratio?: number | null;
  section_count?: number | null;
  sections?: LongGenerationSection[];
  warnings?: string[];
  memory_written?: boolean;
};

export type WritingDraftJob = {
  job_id: string;
  work_id: number;
  status: string;
  stage: string;
  target_chars?: number | null;
  actual_chars?: number | null;
  cjk_chars?: number | null;
  non_space_chars?: number | null;
  estimated_tokens?: number | null;
  completion_ratio?: number | null;
  section_count?: number | null;
  current_section?: number | null;
  content: string;
  sections: LongGenerationSection[];
  used_knowledge: UsedKnowledge[];
  retrieval_debug?: RetrievalDebug | null;
  warnings: string[];
  error_message?: string | null;
  created_at: string;
  updated_at: string;
};

export type RetrievalHit = {
  citation_id: string;
  knowledge_base_id: number;
  document_id: number;
  chunk_id: string;
  score: number;
  original_filename: string;
  document_title: string;
  knowledge_type: string;
  heading: string;
  page_number?: number | null;
  structure_path: string;
  source_kind: string;
  source_path: string;
  text: string;
};

export type WritingMemory = {
  id: number;
  knowledge_base_id: number;
  workspace_id: string;
  memory_type: string;
  title: string;
  content: string;
  tags: string[];
  source_ref: Record<string, unknown>;
  source: string;
  scope_level: string;
  volume_index?: number | null;
  chapter_index?: number | null;
  retrievable: boolean;
  priority: number;
  created_at: string;
  updated_at: string;
};

export type PublicConfig = {
  deepseek_base_url: string;
  deepseek_model: string;
  has_deepseek_api_key: boolean;
  doubao_base_url?: string;
  doubao_model?: string;
  has_doubao_api_key?: boolean;
  default_writing_model?: string;
  writing_models?: WritingModelOption[];
  knowledge_chunk_size: number;
  knowledge_chunk_overlap: number;
  retrieval_top_k: number;
  max_upload_size_mb: number;
  auth_required?: boolean;
  privacy_note: string;
};

export type WritingModelOption = {
  id: string;
  label: string;
  provider: string;
  model: string;
  available: boolean;
};

export type SkillPayload = {
  key: string;
  name: string;
  description: string;
  source?: string;
  phase?: number;
  enabled?: boolean;
  default_modes: string[];
  system_prompt?: string | null;
  prompt_template?: string | null;
  metadata?: Record<string, unknown>;
};

export const api = {
  register: (payload: { email: string; password: string; username?: string; display_name?: string }) =>
    request<AuthSession>("/api/auth/register", { method: "POST", body: JSON.stringify(payload) }),
  login: (payload: { identity: string; password: string }) =>
    request<AuthSession>("/api/auth/login", { method: "POST", body: JSON.stringify(payload) }),
  me: () => request<{ user: AuthUser; workspace_id: string }>("/api/auth/me"),
  logout: () => request<{ ok: boolean }>("/api/auth/logout", { method: "POST" }),
  getPublicConfig: () => request<PublicConfig>("/api/config/public"),
  listProjects: () => request<Project[]>("/api/projects"),
  getProject: (id: number) => request<Project>(`/api/projects/${id}`),
  createProject: (payload: { name: string; description: string; root_output_dir?: string }) =>
    request<Project>("/api/projects", { method: "POST", body: JSON.stringify(payload) }),
  deleteProject: (id: number) => request<{ ok: boolean }>(`/api/projects/${id}`, { method: "DELETE" }),
  listProjectJobs: (projectId: number) => request<Job[]>(`/api/projects/${projectId}/jobs`),
  listFiles: (projectId: number) => request<SourceFile[]>(`/api/projects/${projectId}/files`),
  uploadFile: (projectId: number, file: File) => {
    const data = new FormData();
    data.append("file", file);
    return request<SourceFile>(`/api/projects/${projectId}/files/upload`, { method: "POST", body: data });
  },
  parseFile: (fileId: number) => request<SourceFile>(`/api/files/${fileId}/parse`, { method: "POST" }),
  splitFile: (fileId: number, payload: { max_chapter_chars?: number; overlap_chars?: number; strict_chapter_split?: boolean }) =>
    request<{ file_id: number; chapter_count: number; chapters: Chapter[] }>(`/api/files/${fileId}/split`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listChapters: (fileId: number) => request<Chapter[]>(`/api/files/${fileId}/chapters`),
  createJob: (payload: Record<string, unknown>) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(payload) }),
  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
  getLogs: (jobId: string) => request<JobLog[]>(`/api/jobs/${jobId}/logs`),
  pauseJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/pause`, { method: "POST" }),
  resumeJob: (jobId: string, payload: { api_key?: string } = {}) =>
    request<Job>(`/api/jobs/${jobId}/resume`, { method: "POST", body: JSON.stringify(payload) }),
  cancelJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  retryFailed: (jobId: string, payload: { api_key?: string } = {}) =>
    request<Job>(`/api/jobs/${jobId}/retry-failed`, { method: "POST", body: JSON.stringify(payload) }),
  listResultFiles: (jobId: string) => request<ResultFile[]>(`/api/jobs/${jobId}/files`),
  listPrompts: () => request<PromptTemplate[]>("/api/prompts"),
  listSkills: () => request<DeconstructionSkill[]>("/api/skills"),
  createSkill: (payload: SkillPayload) => request<DeconstructionSkill>("/api/skills", { method: "POST", body: JSON.stringify(payload) }),
  updateSkill: (id: number, payload: Partial<SkillPayload>) =>
    request<DeconstructionSkill>(`/api/skills/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteSkill: (id: number) => request<{ ok: boolean; disabled?: boolean }>(`/api/skills/${id}`, { method: "DELETE" }),
  listKnowledgeBases: () => request<KnowledgeBase[]>("/api/knowledge-bases"),
  createKnowledgeBase: (payload: { name: string; description?: string }) =>
    request<KnowledgeBase>("/api/knowledge-bases", { method: "POST", body: JSON.stringify(payload) }),
  updateKnowledgeBase: (id: number, payload: { name?: string; description?: string }) =>
    request<KnowledgeBase>(`/api/knowledge-bases/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteKnowledgeBase: (id: number) => request<{ ok: boolean }>(`/api/knowledge-bases/${id}`, { method: "DELETE" }),
  bulkDeleteKnowledgeBases: (ids: number[]) =>
    request<{ deleted: number; message: string }>("/api/knowledge-bases/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ knowledge_base_ids: ids }),
    }),
  listKnowledgeDocuments: (id: number) => request<KnowledgeDocument[]>(`/api/knowledge-bases/${id}/documents`),
  uploadKnowledgeDocuments: (id: number, files: FileList | File[]) => {
    const data = new FormData();
    Array.from(files).forEach((file) => data.append("files", file));
    data.append("knowledge_type", "worldbuilding");
    return request<{ imported: KnowledgeDocument[]; skipped_duplicates: number; message: string }>(`/api/knowledge-bases/${id}/documents`, {
      method: "POST",
      body: data,
    });
  },
  uploadKnowledgeDocumentsAs: (id: number, files: FileList | File[], knowledgeType: string) => {
    const data = new FormData();
    Array.from(files).forEach((file) => data.append("files", file));
    data.append("knowledge_type", knowledgeType);
    return request<{ imported: KnowledgeDocument[]; skipped_duplicates: number; message: string }>(`/api/knowledge-bases/${id}/documents`, {
      method: "POST",
      body: data,
    });
  },
  createKnowledgeTextDocument: (id: number, payload: { filename: string; content: string; knowledge_type: string }) =>
    request<{ imported: KnowledgeDocument[]; skipped_duplicates: number; message: string }>(`/api/knowledge-bases/${id}/documents/text`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  importJobToKnowledgeBase: (id: number, jobId: string) =>
    request<{ imported: KnowledgeDocument[]; skipped_duplicates: number; message: string }>(`/api/knowledge-bases/${id}/import-job`, {
      method: "POST",
      body: JSON.stringify({ job_id: jobId }),
    }),
  importKnowledgePackage: (
    workId: number,
    payload: {
      package_path?: string;
      package_json?: Record<string, unknown>;
      library_type?: string;
      status?: string;
      merge_mode?: string;
      auto_merge_threshold?: number;
      review_threshold?: number;
      generate_markdown?: boolean;
      markdown_scope?: string;
    },
  ) =>
    request<KnowledgeImportResult>(
      `/api/writing/works/${workId}/knowledge/import-package`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  importKnowledgeMarkdown: (
    workId: number,
    payload: { source_name?: string; source_path?: string; content?: string; library_type?: string; status?: string },
  ) =>
    request<KnowledgeImportResult>(`/api/writing/works/${workId}/knowledge/import-markdown`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  uploadKnowledgeMarkdownFiles: async (workId: number, files: FileList | File[], libraryType: string, status = "approved") => {
    const results: KnowledgeImportResult[] = [];
    for (const file of Array.from(files)) {
      const data = new FormData();
      data.append("file", file);
      data.append("library_type", libraryType);
      data.append("status", status);
      results.push(
        await request<KnowledgeImportResult>(`/api/writing/works/${workId}/knowledge/import-markdown-file`, {
          method: "POST",
          body: data,
        }),
      );
    }
    return results;
  },
  listKnowledgeCards: (workId: number, params: { library_type?: string; card_type?: string; status?: string; tag?: string; keyword?: string; is_canonical?: boolean } = {}) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
    });
    return request<KnowledgeCard[]>(`/api/writing/works/${workId}/knowledge/cards${query.toString() ? `?${query}` : ""}`);
  },
  updateKnowledgeCard: (workId: number, cardId: string, payload: Partial<KnowledgeCard>) =>
    request<KnowledgeCard>(`/api/writing/works/${workId}/knowledge/cards/${encodeURIComponent(cardId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  deleteKnowledgeCard: (workId: number, cardId: string) =>
    request<KnowledgeCard>(`/api/writing/works/${workId}/knowledge/cards/${encodeURIComponent(cardId)}`, { method: "DELETE" }),
  bulkDeleteKnowledgeCards: (workId: number, cardIds: string[]) =>
    request<{ deleted: number; message: string }>(`/api/writing/works/${workId}/knowledge/cards/bulk-delete`, {
      method: "POST",
      body: JSON.stringify({ card_ids: cardIds }),
    }),
  previewKnowledgeMerges: (workId: number, payload: { merge_mode?: string; auto_merge_threshold?: number; review_threshold?: number } = {}) =>
    request<KnowledgeMergePreview>(`/api/writing/works/${workId}/knowledge/merge/preview`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  applyKnowledgeMerges: (workId: number, payload: { merge_mode?: string; auto_merge_threshold?: number; review_threshold?: number } = {}) =>
    request<KnowledgeMergeApplyResult>(`/api/writing/works/${workId}/knowledge/merge/apply`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getKnowledgeMergeStats: (workId: number) => request<KnowledgeMergeStats>(`/api/writing/works/${workId}/knowledge/merge/stats`),
  unmergeKnowledgeCard: (workId: number, cardId: string) =>
    request<KnowledgeCard>(`/api/writing/works/${workId}/knowledge/cards/${encodeURIComponent(cardId)}/unmerge`, { method: "POST" }),
  listKnowledgeMarkdownDocs: (workId: number) => request<KnowledgeMarkdownDoc[]>(`/api/writing/works/${workId}/knowledge/docs`),
  readKnowledgeMarkdownDoc: (workId: number, docId: string) =>
    request<{ doc_id: string; card_id: string; content: string; path: string }>(`/api/writing/works/${workId}/knowledge/docs/${encodeURIComponent(docId)}`),
  saveKnowledgeMarkdownDoc: (workId: number, docId: string, content: string) =>
    request<{ doc_id: string; card_id: string; content: string; path: string }>(`/api/writing/works/${workId}/knowledge/docs/${encodeURIComponent(docId)}`, {
      method: "PUT",
      body: JSON.stringify({ content }),
    }),
  syncKnowledgeMarkdownDoc: (workId: number, docId: string) =>
    request<{ card_id: string; status: string; updated_fields: string[] }>(`/api/writing/works/${workId}/knowledge/docs/${encodeURIComponent(docId)}/sync`, {
      method: "POST",
    }),
  deleteKnowledgeMarkdownDoc: (workId: number, docId: string) =>
    request<{ card_id: string; status: string; updated_fields: string[] }>(`/api/writing/works/${workId}/knowledge/docs/${encodeURIComponent(docId)}`, {
      method: "DELETE",
    }),
  bulkDeleteKnowledgeMarkdownDocs: (workId: number, docIds: string[]) =>
    request<{ deleted: number; message: string }>(`/api/writing/works/${workId}/knowledge/docs/bulk-delete`, {
      method: "POST",
      body: JSON.stringify({ doc_ids: docIds }),
    }),
  exportKnowledgeCardMarkdown: (workId: number, cardId: string) =>
    request<{ doc_id: string; card_id: string; content: string; path: string }>(
      `/api/writing/works/${workId}/knowledge/cards/${encodeURIComponent(cardId)}/export-md`,
      { method: "POST" },
    ),
  syncDeletedKnowledgeMarkdownDocs: (workId: number) =>
    request<{ card_id: string; status: string; updated_fields: string[] }>(`/api/writing/works/${workId}/knowledge/docs/sync-deleted`, { method: "POST" }),
  reindexKnowledgeDocument: (id: number) => request<KnowledgeDocument>(`/api/documents/${id}/reindex`, { method: "POST" }),
  deleteKnowledgeDocument: (id: number) => request<{ ok: boolean }>(`/api/documents/${id}`, { method: "DELETE" }),
  bulkDeleteKnowledgeDocuments: (
    id: number,
    payload: { document_ids?: number[]; knowledge_type?: string; delete_all?: boolean },
  ) =>
    request<{ deleted: number; message: string }>(`/api/knowledge-bases/${id}/documents/bulk-delete`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  searchKnowledge: (payload: { knowledge_base_ids: number[]; query: string; top_k?: number }) =>
    request<{ hits: RetrievalHit[] }>("/api/retrieval/search", { method: "POST", body: JSON.stringify(payload) }),
  getRAGHealth: () => request<RAGHealth>("/api/rag/health"),
  rebuildRAG: (payload: RAGRebuildPayload) =>
    request<RAGRebuildResult>("/api/rag/rebuild", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  previewRAG: (payload: RAGPreviewPayload) =>
    request<RAGPreviewResponse>("/api/rag/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  searchWorkRAG: (
    workId: number,
    payload: {
      stage: string;
      query: string;
      top_k?: number;
      library_type?: string;
      include_inactive?: boolean;
      current_volume_index?: number | null;
      current_chapter_index?: number | null;
      include_future?: boolean;
      include_raw?: boolean;
      allowed_scope_levels?: string[];
    },
  ) =>
    request<{ results: RAGSearchResult[]; retrieval_debug: RetrievalDebug }>(`/api/writing/works/${workId}/rag/search`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listWritingMemories: (knowledgeBaseId: number) => request<WritingMemory[]>(`/api/writing/memories?knowledge_base_id=${knowledgeBaseId}`),
  createWritingMemory: (payload: {
    knowledge_base_id: number;
    memory_type: string;
    title: string;
    content: string;
    tags?: string[];
    source_ref?: Record<string, unknown>;
    source?: string;
    scope_level?: string;
    volume_index?: number | null;
    chapter_index?: number | null;
  }) =>
    request<WritingMemory>("/api/writing/memories", { method: "POST", body: JSON.stringify(payload) }),
  confirmOutlineMemory: (
    workId: number,
    payload: { title: string; content: string; tags?: string[]; source_ref?: Record<string, unknown>; scope_level?: string; volume_index?: number | null; chapter_index?: number | null },
  ) =>
    request<WritingMemory>(`/api/writing/works/${workId}/memory/confirm-outline`, { method: "POST", body: JSON.stringify(payload) }),
  confirmDraftMemory: (
    workId: number,
    payload: { title: string; content: string; tags?: string[]; source_ref?: Record<string, unknown>; scope_level?: string; volume_index?: number | null; chapter_index?: number | null },
  ) =>
    request<WritingMemory>(`/api/writing/works/${workId}/memory/confirm-draft`, { method: "POST", body: JSON.stringify(payload) }),
  deleteWritingMemory: (id: number) => request<{ ok: boolean }>(`/api/writing/memories/${id}`, { method: "DELETE" }),
  bulkDeleteWritingMemories: (ids: number[]) =>
    request<{ deleted: number; message: string }>("/api/writing/memories/bulk-delete", {
      method: "POST",
      body: JSON.stringify({ memory_ids: ids }),
    }),
  bulkDeleteWritingScope: (
    workId: number,
    payload: { volume_indices?: number[]; chapters?: { volume_index: number; chapter_index: number }[] },
  ) =>
    request<{ deleted_volumes: number; deleted_chapters: number; deleted_memories: number; deleted_cards: number; deleted_markdown_files: number; message: string }>(
      `/api/writing/works/${workId}/chapters/bulk-delete`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    ),
  generateOutline: (payload: {
    knowledge_base_ids: number[];
    task: string;
    current_content?: string;
    mode?: string;
    knowledge_mode?: string;
    model_provider?: string;
    model?: string;
    api_key?: string;
    dry_run?: boolean;
  }) => request<WritingGenerateResult>("/api/writing/outline", { method: "POST", body: JSON.stringify(payload) }),
  generateDraft: (payload: {
    knowledge_base_ids: number[];
    task: string;
    confirmed_outline: string;
    current_content?: string;
    mode?: string;
    knowledge_mode?: string;
    model_provider?: string;
    model?: string;
    api_key?: string;
    dry_run?: boolean;
  }) => request<WritingGenerateResult>("/api/writing/draft", { method: "POST", body: JSON.stringify(payload) }),
  generateWorkOutline: (
    workId: number,
    payload: {
      knowledge_base_ids?: number[];
      task: string;
      scope_level?: string;
      current_content?: string;
      mode?: string;
      knowledge_mode?: string;
      model_provider?: string;
      model?: string;
      base_url?: string;
      api_key?: string;
      dry_run?: boolean;
      top_k?: number;
      current_volume_index?: number | null;
      current_chapter_index?: number | null;
      include_future_knowledge?: boolean;
      include_raw_knowledge?: boolean;
    },
  ) =>
    request<WritingGenerateResult>(
      `/api/writing/works/${workId}/agent/outline`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  generateWorkDraft: (
    workId: number,
    payload: {
      knowledge_base_ids?: number[];
      task: string;
      confirmed_outline: string;
      current_content?: string;
      mode?: string;
      knowledge_mode?: string;
      model_provider?: string;
      model?: string;
      base_url?: string;
      api_key?: string;
      dry_run?: boolean;
      top_k?: number;
      target_chars?: number;
      current_volume_index?: number | null;
      current_chapter_index?: number | null;
      include_future_knowledge?: boolean;
      include_raw_knowledge?: boolean;
    },
  ) =>
    request<WritingGenerateResult>(
      `/api/writing/works/${workId}/agent/draft`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  createWorkDraftJob: (
    workId: number,
    payload: {
      knowledge_base_ids?: number[];
      task: string;
      confirmed_outline: string;
      current_content?: string;
      mode?: string;
      knowledge_mode?: string;
      model_provider?: string;
      model?: string;
      base_url?: string;
      api_key?: string;
      dry_run?: boolean;
      top_k?: number;
      target_chars?: number;
      current_volume_index?: number | null;
      current_chapter_index?: number | null;
      include_future_knowledge?: boolean;
      include_raw_knowledge?: boolean;
    },
  ) =>
    request<WritingDraftJob>(
      `/api/writing/works/${workId}/agent/draft-jobs`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  getWorkDraftJob: (workId: number, jobId: string) =>
    request<WritingDraftJob>(`/api/writing/works/${workId}/agent/draft-jobs/${encodeURIComponent(jobId)}`),
  cancelWorkDraftJob: (workId: number, jobId: string) =>
    request<WritingDraftJob>(`/api/writing/works/${workId}/agent/draft-jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  generateWorkRevision: (
    workId: number,
    payload: {
      knowledge_base_ids?: number[];
      task: string;
      confirmed_outline?: string;
      current_content?: string;
      mode?: string;
      knowledge_mode?: string;
      model_provider?: string;
      model?: string;
      base_url?: string;
      api_key?: string;
      dry_run?: boolean;
      top_k?: number;
      target_chars?: number;
      current_volume_index?: number | null;
      current_chapter_index?: number | null;
      include_future_knowledge?: boolean;
      include_raw_knowledge?: boolean;
    },
  ) =>
    request<WritingGenerateResult>(
      `/api/writing/works/${workId}/agent/revision`,
      { method: "POST", body: JSON.stringify(payload) },
    ),
  generateWriting: (payload: {
    knowledge_base_ids: number[];
    task: string;
    current_content?: string;
    mode?: string;
    knowledge_mode?: string;
    model_provider?: string;
    model?: string;
    api_key?: string;
    dry_run?: boolean;
  }) => request<{ content: string; citations: RetrievalHit[] }>("/api/writing/generate", { method: "POST", body: JSON.stringify(payload) }),
  generateWorldbuildingDraft: (payload: {
    knowledge_base_ids: number[];
    story_seed: string;
    requirements?: string;
    model_provider?: string;
    model?: string;
    api_key?: string;
    dry_run?: boolean;
  }) =>
    request<{ content: string; citations: RetrievalHit[] }>("/api/writing/worldbuilding-draft", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  pickDirectory: (payload: { initial_dir?: string }) =>
    request<{ path?: string | null; message: string }>("/api/system/pick-directory", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  scanImports: (payload: { github_url?: string; local_path?: string }) =>
    request<{ files: Array<Record<string, unknown>>; message: string }>("/api/imports/scan", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  importSkills: (payload: { github_url?: string; local_path?: string }) =>
    request<{ message: string; skills: Array<Record<string, unknown>> }>("/api/imports/import-skills", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  downloadUrl: (jobId: string, path: string) => {
    const token = authToken();
    const access = token ? `access_token=${encodeURIComponent(token)}` : `workspace_id=${encodeURIComponent(getWorkspaceId())}`;
    return `${API_BASE}/api/jobs/${jobId}/download?path=${encodeURIComponent(path)}&${access}`;
  },
  downloadZipUrl: (jobId: string) => {
    const token = authToken();
    const access = token ? `access_token=${encodeURIComponent(token)}` : `workspace_id=${encodeURIComponent(getWorkspaceId())}`;
    return `${API_BASE}/api/jobs/${jobId}/download-zip?${access}`;
  },
};
