import { FormEvent, useState } from "react";
import { api } from "../api";

export default function SkillImport() {
  const [githubUrl, setGithubUrl] = useState("");
  const [localPath, setLocalPath] = useState("");
  const [message, setMessage] = useState("");
  const [files, setFiles] = useState<Array<Record<string, unknown>>>([]);
  const [imported, setImported] = useState<Array<Record<string, unknown>>>([]);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const result = await api.scanImports({ github_url: githubUrl || undefined, local_path: localPath || undefined });
      setMessage(result.message);
      setFiles(result.files);
      setImported([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "扫描失败");
    }
  }

  async function importSkills() {
    setError("");
    try {
      const result = await api.importSkills({ github_url: githubUrl || undefined, local_path: localPath || undefined });
      setMessage(result.message);
      setImported(result.skills);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入失败");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Phase 3 interface</p>
          <h1>Prompt / Skill 导入</h1>
        </div>
        <p>Phase 2 已支持手动管理 Skill；这里保留本地/远程仓库扫描入口，自动转换将在 Phase 3 完整实现。</p>
      </div>
      {error && <div className="alert">{error}</div>}
      <form className="panel config-form" onSubmit={submit}>
        <label>
          GitHub 仓库 URL
          <input value={githubUrl} onChange={(event) => setGithubUrl(event.target.value)} placeholder="Phase 3 支持拉取" />
        </label>
        <label>
          本地仓库路径
          <input value={localPath} onChange={(event) => setLocalPath(event.target.value)} placeholder="./third_party_references/oh-story-claudecode" />
        </label>
        <button className="primary" type="submit">
          扫描
        </button>
        <button type="button" onClick={importSkills} disabled={!localPath}>
          导入为 Skill
        </button>
      </form>
      {message && <div className="panel">{message}</div>}
      {!!imported.length && (
        <div className="grid-list">
          {imported.map((skill) => (
            <article className="project-card" key={String(skill.id)}>
              <strong>{String(skill.name)}</strong>
              <small>{String(skill.key)}</small>
            </article>
          ))}
        </div>
      )}
      <div className="grid-list">
        {files.map((file) => (
          <article className="project-card" key={String(file.path)}>
            <strong>{String(file.name)}</strong>
            <small>{String(file.path)}</small>
            <span>匹配分：{String(file.score)}</span>
          </article>
        ))}
      </div>
    </section>
  );
}
