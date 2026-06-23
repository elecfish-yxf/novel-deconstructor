import { ChangeEvent, DragEvent, useEffect, useState } from "react";
import { api, Chapter, Project, SourceFile } from "../api";
import StatusPill from "../components/StatusPill";

function formatSize(size: number) {
  if (size > 1024 * 1024) return `${(size / 1024 / 1024).toFixed(1)} MB`;
  if (size > 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${size} B`;
}

export default function FileUpload({
  project,
  selectedFile,
  onFileReady,
}: {
  project: Project;
  selectedFile: SourceFile | null;
  onFileReady: (file: SourceFile, chapters: Chapter[]) => void;
}) {
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [activeFile, setActiveFile] = useState<SourceFile | null>(selectedFile);
  const [maxChars, setMaxChars] = useState(12000);
  const [overlap, setOverlap] = useState(800);
  const [strictChapterSplit, setStrictChapterSplit] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function loadFiles() {
    setFiles(await api.listFiles(project.id));
  }

  useEffect(() => {
    loadFiles().catch((err) => setError(err.message));
  }, [project.id]);

  async function handleFile(file: File) {
    setBusy(true);
    setError("");
    try {
      const uploaded = await api.uploadFile(project.id, file);
      const parsed = await api.parseFile(uploaded.id);
      const split = await api.splitFile(parsed.id, {
        max_chapter_chars: maxChars,
        overlap_chars: overlap,
        strict_chapter_split: strictChapterSplit,
      });
      setActiveFile(parsed);
      await loadFiles();
      onFileReady(parsed, split.chapters);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function resplit(file: SourceFile) {
    setBusy(true);
    setError("");
    try {
      const parsed = file.parse_status === "parsed" ? file : await api.parseFile(file.id);
      const split = await api.splitFile(parsed.id, {
        max_chapter_chars: maxChars,
        overlap_chars: overlap,
        strict_chapter_split: strictChapterSplit,
      });
      setActiveFile(parsed);
      await loadFiles();
      onFileReady(parsed, split.chapters);
    } catch (err) {
      setError(err instanceof Error ? err.message : "切分失败");
    } finally {
      setBusy(false);
    }
  }

  function onInput(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (file) handleFile(file);
  }

  function onDrop(event: DragEvent<HTMLLabelElement>) {
    event.preventDefault();
    const file = event.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">{project.name}</p>
          <h1>文件上传与切章</h1>
        </div>
        <p>支持 TXT / MD / DOCX / PDF。上传过程直接传文件，不在浏览器读取整本文本，适合本地拆书演示。</p>
      </div>
      {error && <div className="alert">{error}</div>}

      <div className="split-layout">
        <label className={`dropzone ${busy ? "busy" : ""}`} onDragOver={(event) => event.preventDefault()} onDrop={onDrop}>
          <input type="file" accept=".txt,.md,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document" onChange={onInput} disabled={busy} />
          <strong>{busy ? "处理中..." : "拖拽或点击上传 TXT / MD / DOCX / PDF"}</strong>
          <span>上传后自动解析并切分章节</span>
        </label>

        <div className="panel compact-form">
          <label>
            每章最大字符数
            <input type="number" value={maxChars} min={1000} onChange={(event) => setMaxChars(Number(event.target.value))} />
          </label>
          <label>
            overlap 字符数
            <input type="number" value={overlap} min={0} onChange={(event) => setOverlap(Number(event.target.value))} />
          </label>
          <label className="check-row">
            <input type="checkbox" checked={strictChapterSplit} onChange={(event) => setStrictChapterSplit(event.target.checked)} />
            识别到章节标题时严格按章切分
          </label>
          <p className="muted">开启后会优先按“第一章 / 第1章 / Chapter 1”等标题切分；关闭后，超长章节会按最大字符数二次分块。</p>
        </div>
      </div>

      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>文件</th>
              <th>大小</th>
              <th>状态</th>
              <th>章节数</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {files.map((file) => (
              <tr key={file.id} className={activeFile?.id === file.id ? "selected-row" : ""}>
                <td>{file.original_filename}</td>
                <td>{formatSize(file.size_bytes)}</td>
                <td>
                  <StatusPill status={file.parse_status} />
                </td>
                <td>{file.chapter_count}</td>
                <td>
                  <button onClick={() => resplit(file)} disabled={busy}>
                    解析/重新切分
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
