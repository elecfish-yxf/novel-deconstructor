import { FormEvent, useEffect, useState } from "react";
import { api, Project } from "../api";
import StatusPill from "../components/StatusPill";

export default function ProjectList({
  selectedId,
  onSelect,
  onDeleted,
}: {
  selectedId?: number;
  onSelect: (project: Project) => void;
  onDeleted?: (projectId: number) => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [rootOutputDir, setRootOutputDir] = useState("");
  const [error, setError] = useState("");

  async function load() {
    setProjects(await api.listProjects());
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
    const timer = window.setInterval(() => {
      load().catch((err) => setError(err.message));
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const project = await api.createProject({ name, description, root_output_dir: rootOutputDir || undefined });
      setName("");
      setDescription("");
      setRootOutputDir("");
      await load();
      onSelect(project);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  }

  async function remove(project: Project) {
    await api.deleteProject(project.id);
    onDeleted?.(project.id);
    await load();
  }

  async function pickRootOutputDir() {
    setError("");
    try {
      const result = await api.pickDirectory({ initial_dir: rootOutputDir || undefined });
      if (result.path) setRootOutputDir(result.path);
    } catch (err) {
      setError(
        err instanceof Error
          ? `${err.message} 任务完成后可在结果页保存全部文件到本地目录。`
          : "无法打开文件夹选择器；任务完成后可在结果页保存全部文件到本地目录。",
      );
    }
  }

  function actionLabel(project: Project) {
    if (project.latest_job_status === "running") return "查看进度";
    if (project.latest_job_status === "completed") return "查看结果";
    if (["failed", "paused", "cancelled"].includes(project.latest_job_status || "")) return "继续处理";
    return "进入";
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Workspace</p>
          <h1>项目列表</h1>
        </div>
        <p>新建项目后上传 TXT / MD / DOCX / PDF，系统会解析文本、识别章节并启动拆书任务。</p>
      </div>

      {error && <div className="alert">{error}</div>}

      <form className="panel form-grid" onSubmit={submit}>
        <label>
          项目名称
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：仙侠长篇拆书" required />
        </label>
        <label>
          项目描述
          <input value={description} onChange={(event) => setDescription(event.target.value)} placeholder="可选" />
        </label>
        <label>
          默认输出路径
          <div className="path-picker-row">
            <input value={rootOutputDir} onChange={(event) => setRootOutputDir(event.target.value)} placeholder="留空使用 outputs/" />
            <button type="button" onClick={pickRootOutputDir}>
              选择文件夹
            </button>
          </div>
        </label>
        <button className="primary" type="submit">
          新建并进入
        </button>
      </form>

      <div className="grid-list">
        {projects.map((project) => (
          <article key={project.id} className={`project-card ${selectedId === project.id ? "selected" : ""}`}>
            <div>
              <h2>{project.name}</h2>
              <p>{project.description || "暂无描述"}</p>
            </div>
            <StatusPill status={project.latest_job_status} />
            <small>{new Date(project.created_at).toLocaleString()}</small>
            <div className="button-row">
              <button onClick={() => onSelect(project)}>{actionLabel(project)}</button>
              <button className="ghost danger" onClick={() => remove(project)}>
                删除
              </button>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}
