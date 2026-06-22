import { useEffect, useState } from "react";
import { api, ResultFile } from "../api";

const markdownKinds = new Set([
  "chapter_analysis",
  "拆文库",
  "volume_analysis",
  "final_reports",
  "knowledge_base",
  "knowledge_base_obsidian",
  "graph_outputs",
]);

export default function ResultViewer({ jobId }: { jobId: string }) {
  const [files, setFiles] = useState<ResultFile[]>([]);
  const [active, setActive] = useState<ResultFile | null>(null);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");

  async function load() {
    const next = await api.listResultFiles(jobId);
    setFiles(next);
    const firstMarkdown = next.find((item) => item.name.endsWith(".md"));
    if (firstMarkdown && !active) {
      await openPreview(firstMarkdown);
    }
  }

  async function openPreview(file: ResultFile) {
    setActive(file);
    setPreview("");
    if (!file.name.endsWith(".md")) return;
    const response = await fetch(api.downloadUrl(jobId, file.path));
    setPreview(await response.text());
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, [jobId]);

  const grouped = files.reduce<Record<string, ResultFile[]>>((acc, file) => {
    acc[file.kind] ||= [];
    acc[file.kind].push(file);
    return acc;
  }, {});

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">{jobId}</p>
          <h1>结果预览与下载</h1>
        </div>
        <button onClick={() => load()}>刷新</button>
      </div>
      {error && <div className="alert">{error}</div>}

      <div className="results-layout">
        <div className="file-tree">
          {Object.entries(grouped).map(([kind, items]) => (
            <div key={kind} className="file-group">
              <h2>{kind}</h2>
              {items.map((file) => (
                <button key={file.path} className={active?.path === file.path ? "active-file" : ""} onClick={() => openPreview(file)}>
                  <span>{file.name}</span>
                  <a href={api.downloadUrl(jobId, file.path)} onClick={(event) => event.stopPropagation()}>
                    下载
                  </a>
                </button>
              ))}
            </div>
          ))}
          {!files.length && <p className="muted">还没有结果文件。任务完成后会显示 Markdown 输出。</p>}
        </div>
        <div className="preview-panel">
          <div className="preview-toolbar">
            <strong>{active?.path || "未选择文件"}</strong>
            {active && markdownKinds.has(active.kind) && (
              <button onClick={() => navigator.clipboard.writeText(preview)} disabled={!preview}>
                复制
              </button>
            )}
          </div>
          <pre>{preview || "选择 Markdown 文件后在这里预览。"}</pre>
        </div>
      </div>
    </section>
  );
}
