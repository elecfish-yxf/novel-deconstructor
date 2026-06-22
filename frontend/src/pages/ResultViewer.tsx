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

type WritableFileStream = {
  write: (data: Blob) => Promise<void>;
  close: () => Promise<void>;
};

type FileSystemFileHandle = {
  createWritable: () => Promise<WritableFileStream>;
};

type FileSystemDirectoryHandle = {
  getDirectoryHandle: (name: string, options?: { create?: boolean }) => Promise<FileSystemDirectoryHandle>;
  getFileHandle: (name: string, options?: { create?: boolean }) => Promise<FileSystemFileHandle>;
};

type WindowWithDirectoryPicker = Window & {
  showDirectoryPicker?: () => Promise<FileSystemDirectoryHandle>;
};

function safePathParts(path: string) {
  return path.split(/[\\/]+/).filter((part) => part && part !== "." && part !== "..");
}

export default function ResultViewer({ jobId }: { jobId: string }) {
  const [files, setFiles] = useState<ResultFile[]>([]);
  const [active, setActive] = useState<ResultFile | null>(null);
  const [preview, setPreview] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

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

  async function saveAllToLocalFolder() {
    setError("");
    const picker = (window as WindowWithDirectoryPicker).showDirectoryPicker;
    if (!picker) {
      setError("当前浏览器不支持直接保存到本地文件夹，请使用“下载全部 ZIP”。");
      return;
    }
    if (!files.length) {
      setError("还没有可保存的结果文件。");
      return;
    }
    setSaving(true);
    try {
      const root = await picker();
      const jobFolder = await root.getDirectoryHandle(`novel-deconstructor-${jobId}`, { create: true });
      for (const file of files) {
        const parts = safePathParts(file.path);
        if (!parts.length) continue;
        let directory = jobFolder;
        for (const part of parts.slice(0, -1)) {
          directory = await directory.getDirectoryHandle(part, { create: true });
        }
        const handle = await directory.getFileHandle(parts[parts.length - 1], { create: true });
        const writable = await handle.createWritable();
        const response = await fetch(api.downloadUrl(jobId, file.path));
        if (!response.ok) throw new Error(`保存失败：${file.path}`);
        await writable.write(await response.blob());
        await writable.close();
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存到本地文件夹失败");
    } finally {
      setSaving(false);
    }
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
        <div className="button-row">
          <button onClick={() => load()}>刷新</button>
          <button onClick={saveAllToLocalFolder} disabled={saving || !files.length}>
            {saving ? "保存中..." : "保存全部到本地文件夹"}
          </button>
          <a className="button-link" href={api.downloadZipUrl(jobId)}>
            下载全部 ZIP
          </a>
        </div>
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
