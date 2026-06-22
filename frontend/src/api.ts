const API_BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.DEV ? "http://localhost:8000" : "");

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: options.body instanceof FormData ? options.headers : { "Content-Type": "application/json", ...(options.headers || {}) },
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
  splitFile: (fileId: number, payload: { max_chapter_chars?: number; overlap_chars?: number }) =>
    request<{ file_id: number; chapter_count: number; chapters: Chapter[] }>(`/api/files/${fileId}/split`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  listChapters: (fileId: number) => request<Chapter[]>(`/api/files/${fileId}/chapters`),
  createJob: (payload: Record<string, unknown>) => request<Job>("/api/jobs", { method: "POST", body: JSON.stringify(payload) }),
  getJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}`),
  getLogs: (jobId: string) => request<JobLog[]>(`/api/jobs/${jobId}/logs`),
  pauseJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/pause`, { method: "POST" }),
  resumeJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/resume`, { method: "POST" }),
  cancelJob: (jobId: string) => request<Job>(`/api/jobs/${jobId}/cancel`, { method: "POST" }),
  retryFailed: (jobId: string) => request<Job>(`/api/jobs/${jobId}/retry-failed`, { method: "POST" }),
  listResultFiles: (jobId: string) => request<ResultFile[]>(`/api/jobs/${jobId}/files`),
  listPrompts: () => request<PromptTemplate[]>("/api/prompts"),
  listSkills: () => request<DeconstructionSkill[]>("/api/skills"),
  createSkill: (payload: SkillPayload) => request<DeconstructionSkill>("/api/skills", { method: "POST", body: JSON.stringify(payload) }),
  updateSkill: (id: number, payload: Partial<SkillPayload>) =>
    request<DeconstructionSkill>(`/api/skills/${id}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteSkill: (id: number) => request<{ ok: boolean; disabled?: boolean }>(`/api/skills/${id}`, { method: "DELETE" }),
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
  downloadUrl: (jobId: string, path: string) => `${API_BASE}/api/jobs/${jobId}/download?path=${encodeURIComponent(path)}`,
};
