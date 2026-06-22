import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { Chapter, Job, Project, SourceFile } from "./api";
import ProjectList from "./pages/ProjectList";
import FileUpload from "./pages/FileUpload";
import ChapterPreview from "./pages/ChapterPreview";
import JobConfig from "./pages/JobConfig";
import JobProgress from "./pages/JobProgress";
import ResultViewer from "./pages/ResultViewer";
import SkillImport from "./pages/SkillImport";
import SkillManager from "./pages/SkillManager";
import WritingAgent from "./pages/WritingAgent";

type View = "projects" | "upload" | "chapters" | "config" | "progress" | "results" | "agent" | "skills" | "imports";
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
  if (preferred && ["projects", "skills", "imports", "agent"].includes(preferred)) return preferred;
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
  }, [openProject]);

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

  function navDisabled(key: View) {
    if (["projects", "imports", "skills", "agent"].includes(key)) return false;
    if (!project) return true;
    if (["chapters", "config"].includes(key)) return !sourceFile;
    if (["progress", "results"].includes(key)) return !job;
    return false;
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
          <span>当前项目</span>
          <strong>{project?.name || "未选择"}</strong>
          <span>当前文件</span>
          <strong>{sourceFile?.original_filename || "未上传"}</strong>
          <span>当前任务</span>
          <strong>{job?.id || "未启动"}</strong>
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
      </main>
    </div>
  );
}
