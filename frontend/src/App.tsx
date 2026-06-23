import { useCallback, useEffect, useState } from "react";
import type { FormEvent } from "react";
import { api, clearAuthSession, getStoredAuthSession, storeAuthSession } from "./api";
import type { AuthSession, Chapter, Job, Project, SourceFile } from "./api";
import ProjectList from "./pages/ProjectList";
import FileUpload from "./pages/FileUpload";
import ChapterPreview from "./pages/ChapterPreview";
import JobConfig from "./pages/JobConfig";
import JobProgress from "./pages/JobProgress";
import ResultViewer from "./pages/ResultViewer";
import SkillImport from "./pages/SkillImport";
import SkillManager from "./pages/SkillManager";
import WritingAgent from "./pages/WritingAgent";
import HelpPage from "./pages/HelpPage";

type View = "projects" | "upload" | "chapters" | "config" | "progress" | "results" | "agent" | "skills" | "imports" | "help";
type SavedContext = {
  view?: View;
  projectId?: number;
  sourceFileId?: number;
  jobId?: string;
};

const APP_CONTEXT_KEY = "novel-deconstructor.active-context";

const nav: Array<{ key: View; label: string }> = [
  { key: "projects", label: "项目" },
  { key: "upload", label: "上传" },
  { key: "chapters", label: "章节" },
  { key: "config", label: "任务" },
  { key: "progress", label: "进度" },
  { key: "results", label: "结果" },
  { key: "agent", label: "写作 Agent" },
  { key: "skills", label: "Skill 管理" },
  { key: "imports", label: "Prompt 导入" },
  { key: "help", label: "Help" },
];

function isView(value: unknown): value is View {
  return typeof value === "string" && nav.some((item) => item.key === value);
}

function loadSavedContext(): SavedContext {
  try {
    const raw = window.localStorage.getItem(APP_CONTEXT_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as SavedContext;
    return {
      view: isView(parsed.view) ? parsed.view : undefined,
      projectId: typeof parsed.projectId === "number" ? parsed.projectId : undefined,
      sourceFileId: typeof parsed.sourceFileId === "number" ? parsed.sourceFileId : undefined,
      jobId: typeof parsed.jobId === "string" ? parsed.jobId : undefined,
    };
  } catch {
    return {};
  }
}

function chooseRestoredView(preferred: View | undefined, sourceFile: SourceFile | null, chapters: Chapter[], job: Job | null): View {
  if (preferred && ["projects", "skills", "imports", "agent", "help"].includes(preferred)) return preferred;
  if (preferred) {
    if (["progress", "results"].includes(preferred) && job) return preferred;
    if (["chapters", "config"].includes(preferred) && sourceFile) return preferred;
    if (preferred === "upload") return preferred;
  }
  if (job) return job.status === "completed" ? "results" : "progress";
  if (sourceFile && chapters.length) return "config";
  if (sourceFile) return "chapters";
  return "upload";
}

export default function App() {
  const [view, setView] = useState<View>("projects");
  const [project, setProject] = useState<Project | null>(null);
  const [sourceFile, setSourceFile] = useState<SourceFile | null>(null);
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [job, setJob] = useState<Job | null>(null);
  const [booting, setBooting] = useState(true);
  const [authReady, setAuthReady] = useState(false);
  const [authRequired, setAuthRequired] = useState(false);
  const [authSession, setAuthSession] = useState<AuthSession | null>(getStoredAuthSession());
  const [contextError, setContextError] = useState("");

  const openProject = useCallback(async (nextProject: Project, saved: SavedContext = {}) => {
    setContextError("");
    setProject(nextProject);
    try {
      const [files, jobs] = await Promise.all([api.listFiles(nextProject.id), api.listProjectJobs(nextProject.id)]);
      let nextJob = saved.jobId ? jobs.find((item) => item.id === saved.jobId) || null : jobs[0] || null;
      if (saved.jobId && !nextJob) {
        try {
          nextJob = await api.getJob(saved.jobId);
        } catch {
          nextJob = null;
        }
      }
      const preferredFileId = saved.sourceFileId || nextJob?.source_file_id;
      const nextFile = (preferredFileId ? files.find((item) => item.id === preferredFileId) : null) || files[0] || null;
      let nextChapters: Chapter[] = [];
      if (nextFile) {
        try {
          nextChapters = await api.listChapters(nextFile.id);
        } catch {
          nextChapters = [];
        }
      }
      setSourceFile(nextFile);
      setChapters(nextChapters);
      setJob(nextJob);
      setView(chooseRestoredView(saved.view, nextFile, nextChapters, nextJob));
    } catch (err) {
      setSourceFile(null);
      setChapters([]);
      setJob(null);
      setView("upload");
      setContextError(err instanceof Error ? err.message : "恢复项目上下文失败");
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function restoreAuth() {
      try {
        const config = await api.getPublicConfig();
        if (cancelled) return;
        setAuthRequired(Boolean(config.auth_required));
        const stored = getStoredAuthSession();
        if (stored?.access_token) {
          try {
            const current = await api.me();
            if (!cancelled) {
              const refreshed = { ...stored, user: current.user, workspace_id: current.workspace_id };
              storeAuthSession(refreshed);
              setAuthSession(refreshed);
            }
          } catch {
            clearAuthSession();
            if (!cancelled) setAuthSession(null);
          }
        }
      } finally {
        if (!cancelled) setAuthReady(true);
      }
    }
    restoreAuth();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!authReady) return;
    if (authRequired && !authSession) {
      setBooting(false);
      return;
    }
    let cancelled = false;
    async function restore() {
      const saved = loadSavedContext();
      if (!saved.projectId) {
        setBooting(false);
        return;
      }
      try {
        const savedProject = await api.getProject(saved.projectId);
        if (!cancelled) await openProject(savedProject, saved);
      } catch {
        window.localStorage.removeItem(APP_CONTEXT_KEY);
      } finally {
        if (!cancelled) setBooting(false);
      }
    }
    restore();
    return () => {
      cancelled = true;
    };
  }, [openProject, authReady, authRequired, authSession?.access_token]);

  useEffect(() => {
    if (booting) return;
    const payload: SavedContext = {
      view,
      projectId: project?.id,
      sourceFileId: sourceFile?.id,
      jobId: job?.id,
    };
    window.localStorage.setItem(APP_CONTEXT_KEY, JSON.stringify(payload));
  }, [booting, view, project?.id, sourceFile?.id, job?.id]);

  function clearProjectContext() {
    setProject(null);
    setSourceFile(null);
    setChapters([]);
    setJob(null);
    setView("projects");
    window.localStorage.removeItem(APP_CONTEXT_KEY);
  }

  function handleAuth(session: AuthSession) {
    storeAuthSession(session);
    setAuthSession(session);
    setProject(null);
    setSourceFile(null);
    setChapters([]);
    setJob(null);
    setView("projects");
    window.localStorage.removeItem(APP_CONTEXT_KEY);
    setBooting(false);
  }

  async function logout() {
    try {
      await api.logout();
    } catch {
      // Local cleanup is enough when the server token is already expired.
    }
    clearAuthSession();
    setAuthSession(null);
    clearProjectContext();
  }

  function navDisabled(key: View) {
    if (["projects", "imports", "skills", "agent", "help"].includes(key)) return false;
    if (!project) return true;
    if (["chapters", "config"].includes(key)) return !sourceFile;
    if (["progress", "results"].includes(key)) return !job;
    return false;
  }

  if (!authReady) {
    return <div className="auth-shell panel">正在检查登录状态...</div>;
  }

  if (authRequired && !authSession) {
    return <AuthGate onAuthed={handleAuth} />;
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand-mark">ND</span>
          <div>
            <strong>Novel Deconstructor</strong>
            <small>长篇小说拆书工作台</small>
          </div>
        </div>
        <nav>
          {nav.map((item) => (
            <button
              key={item.key}
              className={view === item.key ? "active" : ""}
              onClick={() => setView(item.key)}
              disabled={navDisabled(item.key)}
            >
              {item.label}
            </button>
          ))}
        </nav>
        <div className="context-panel">
          {authSession && (
            <>
              <span>当前账号</span>
              <strong>{authSession.user.display_name || authSession.user.email}</strong>
            </>
          )}
          <span>当前项目</span>
          <strong>{project?.name || "未选择"}</strong>
          <span>当前文件</span>
          <strong>{sourceFile?.original_filename || "未上传"}</strong>
          <span>当前任务</span>
          <strong>{job?.id || "未启动"}</strong>
          {authSession && (
            <button type="button" className="ghost sidebar-action" onClick={logout}>
              退出登录
            </button>
          )}
        </div>
      </aside>

      <main className="workspace">
        {booting && <div className="notice panel">正在恢复上次打开的项目和后台任务...</div>}
        {contextError && <div className="alert">{contextError}</div>}
        {view === "projects" && (
          <ProjectList
            selectedId={project?.id}
            onSelect={(next) => openProject(next)}
            onDeleted={(deletedId) => {
              if (project?.id === deletedId) clearProjectContext();
            }}
          />
        )}
        {view === "upload" && project && (
          <FileUpload
            project={project}
            selectedFile={sourceFile}
            onFileReady={(file, nextChapters) => {
              setSourceFile(file);
              setChapters(nextChapters);
              setJob(null);
              setView("chapters");
            }}
          />
        )}
        {view === "chapters" && sourceFile && (
          <ChapterPreview chapters={chapters} sourceFile={sourceFile} onRefresh={(items) => setChapters(items)} />
        )}
        {view === "config" && project && sourceFile && (
          <JobConfig
            project={project}
            sourceFile={sourceFile}
            onJobCreated={(next) => {
              setJob(next);
              setView("progress");
            }}
          />
        )}
        {view === "progress" && job && (
          <JobProgress
            jobId={job.id}
            onJobChange={(next) => setJob(next)}
            onViewResults={() => setView("results")}
          />
        )}
        {view === "results" && job && <ResultViewer jobId={job.id} />}
        {view === "agent" && <WritingAgent job={job} />}
        {view === "skills" && <SkillManager />}
        {view === "imports" && <SkillImport />}
        {view === "help" && <HelpPage />}
      </main>
    </div>
  );
}

function AuthGate({ onAuthed }: { onAuthed: (session: AuthSession) => void }) {
  const [mode, setMode] = useState<"login" | "register">("login");
  const [identity, setIdentity] = useState("");
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const session =
        mode === "login"
          ? await api.login({ identity, password })
          : await api.register({ email, password, username: username || undefined, display_name: displayName || undefined });
      onAuthed(session);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="auth-shell">
      <form className="auth-card panel" onSubmit={submit}>
        <div>
          <p className="eyebrow">Account</p>
          <h1>{mode === "login" ? "登录 Novel Deconstructor" : "创建账号"}</h1>
          <p className="muted">登录后，项目、知识库、文件和写作 Memory 都会进入你的独立空间。</p>
        </div>
        {mode === "login" ? (
          <label>
            邮箱或用户名
            <input value={identity} onChange={(event) => setIdentity(event.target.value)} required autoComplete="username" />
          </label>
        ) : (
          <>
            <label>
              邮箱
              <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required autoComplete="email" />
            </label>
            <label>
              用户名
              <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
            </label>
            <label>
              昵称
              <input value={displayName} onChange={(event) => setDisplayName(event.target.value)} />
            </label>
          </>
        )}
        <label>
          密码
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            minLength={8}
            required
            autoComplete={mode === "login" ? "current-password" : "new-password"}
          />
        </label>
        {error && <div className="alert">{error}</div>}
        <button className="primary" disabled={busy}>
          {busy ? "处理中..." : mode === "login" ? "登录" : "注册并进入"}
        </button>
        <button type="button" className="ghost" onClick={() => setMode(mode === "login" ? "register" : "login")}>
          {mode === "login" ? "没有账号？注册" : "已有账号？登录"}
        </button>
      </form>
    </div>
  );
}
