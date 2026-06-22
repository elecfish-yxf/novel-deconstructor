import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { api, Job, KnowledgeBase, KnowledgeDocument, PublicConfig, RetrievalHit } from "../api";

function formatSize(value: number) {
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

export default function WritingAgent({ job }: { job?: Job | null }) {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [name, setName] = useState("小说拆书知识库");
  const [description, setDescription] = useState("用于 AI 写作 Agent 的本地知识库");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<RetrievalHit[]>([]);
  const [task, setTask] = useState("请基于知识库，为我生成一份可复用的小说章节写作提纲。");
  const [currentContent, setCurrentContent] = useState("");
  const [mode, setMode] = useState("fast");
  const [knowledgeMode, setKnowledgeMode] = useState("reference");
  const [dryRun, setDryRun] = useState(true);
  const [generated, setGenerated] = useState("");
  const [citations, setCitations] = useState<RetrievalHit[]>([]);
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const selected = useMemo(() => knowledgeBases.find((item) => item.id === selectedId) || null, [knowledgeBases, selectedId]);

  async function load(nextSelectedId?: number | null) {
    const [nextConfig, nextBases] = await Promise.all([api.getPublicConfig(), api.listKnowledgeBases()]);
    setConfig(nextConfig);
    setKnowledgeBases(nextBases);
    const preferred = nextSelectedId || selectedId || nextBases[0]?.id || null;
    setSelectedId(preferred);
    if (preferred) {
      setDocuments(await api.listKnowledgeDocuments(preferred));
    } else {
      setDocuments([]);
    }
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "加载写作 Agent 失败"));
  }, []);

  async function createKnowledgeBase(event: FormEvent) {
    event.preventDefault();
    setBusy("create");
    setError("");
    setMessage("");
    try {
      const kb = await api.createKnowledgeBase({ name, description });
      setMessage("知识库已创建");
      await load(kb.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建知识库失败");
    } finally {
      setBusy("");
    }
  }

  async function chooseKnowledgeBase(id: number) {
    setSelectedId(id);
    setError("");
    setDocuments(await api.listKnowledgeDocuments(id));
  }

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!selected || !files?.length) return;
    setBusy("upload");
    setError("");
    setMessage("");
    try {
      const result = await api.uploadKnowledgeDocuments(selected.id, files);
      setMessage(result.message);
      await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传知识库文件失败");
    } finally {
      event.target.value = "";
      setBusy("");
    }
  }

  async function importCurrentJob() {
    if (!selected || !job) return;
    setBusy("import");
    setError("");
    setMessage("");
    try {
      const result = await api.importJobToKnowledgeBase(selected.id, job.id);
      setMessage(result.message);
      await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入拆书结果失败");
    } finally {
      setBusy("");
    }
  }

  async function deleteDocument(documentId: number) {
    if (!window.confirm("确定删除这个知识文档和对应分块吗？")) return;
    setBusy(`delete-${documentId}`);
    setError("");
    try {
      await api.deleteKnowledgeDocument(documentId);
      if (selected) await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除文档失败");
    } finally {
      setBusy("");
    }
  }

  async function reindexDocument(documentId: number) {
    setBusy(`reindex-${documentId}`);
    setError("");
    try {
      await api.reindexKnowledgeDocument(documentId);
      if (selected) await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新索引失败");
    } finally {
      setBusy("");
    }
  }

  async function search(event: FormEvent) {
    event.preventDefault();
    if (!selected || !query.trim()) return;
    setBusy("search");
    setError("");
    try {
      const result = await api.searchKnowledge({ knowledge_base_ids: [selected.id], query });
      setHits(result.hits);
    } catch (err) {
      setError(err instanceof Error ? err.message : "检索失败");
    } finally {
      setBusy("");
    }
  }

  async function generate(event: FormEvent) {
    event.preventDefault();
    if (!selected || !task.trim()) return;
    setBusy("generate");
    setError("");
    setGenerated("");
    setCitations([]);
    try {
      const result = await api.generateWriting({
        knowledge_base_ids: [selected.id],
        task,
        current_content: currentContent,
        mode,
        knowledge_mode: knowledgeMode,
        dry_run: dryRun,
      });
      setGenerated(result.content);
      setCitations(result.citations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Writing Agent</p>
          <h1>AI 写作 Agent</h1>
        </div>
        <p>上传资料或导入拆书结果，建立本地知识库；写作时只把召回片段发送给模型，并保留引用来源。</p>
      </div>

      {config && <div className="notice panel">{config.privacy_note} 当前模型：{config.deepseek_model}；API Key：{config.has_deepseek_api_key ? "已配置" : "未配置"}。</div>}
      {error && <div className="alert">{error}</div>}
      {message && <div className="panel notice">{message}</div>}

      <div className="agent-layout">
        <aside className="panel agent-sidebar">
          <form className="compact-form" onSubmit={createKnowledgeBase}>
            <h2>知识库</h2>
            <label>
              名称
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label>
              描述
              <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <button className="primary" disabled={busy === "create"}>
              新建知识库
            </button>
          </form>

          <div className="file-group kb-list">
            {knowledgeBases.map((kb) => (
              <button key={kb.id} className={selectedId === kb.id ? "active-file" : ""} onClick={() => chooseKnowledgeBase(kb.id)}>
                <span>
                  <strong>{kb.name}</strong>
                  <small>
                    {kb.document_count} 文档 · {kb.chunk_count} 分块
                  </small>
                </span>
              </button>
            ))}
            {!knowledgeBases.length && <p className="muted">还没有知识库。</p>}
          </div>
        </aside>

        <div className="agent-main">
          <div className="panel compact-form">
            <div className="button-row">
              <strong>{selected?.name || "请选择知识库"}</strong>
              <label className="button-link">
                上传知识文件
                <input
                  className="hidden-input"
                  type="file"
                  multiple
                  accept=".txt,.md,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  onChange={uploadFiles}
                  disabled={!selected || busy === "upload"}
                />
              </label>
              <button type="button" onClick={importCurrentJob} disabled={!selected || !job || busy === "import"}>
                导入当前拆书结果
              </button>
            </div>
            <small className="muted">适配结构：final_reports、knowledge_base、knowledge_base_obsidian、graph_outputs、chapter_analysis、拆文库。</small>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文档</th>
                  <th>结构路径</th>
                  <th>状态</th>
                  <th>分块</th>
                  <th>大小</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {documents.map((document) => (
                  <tr key={document.id}>
                    <td>
                      <strong>{document.document_title || document.original_filename}</strong>
                      <br />
                      <small className="muted">{document.original_filename}</small>
                      {document.error_message && <div className="warn-cell">{document.error_message}</div>}
                    </td>
                    <td>{document.structure_path}</td>
                    <td>
                      <span className={`status-pill status-${document.status}`}>{document.status}</span>
                    </td>
                    <td>{document.chunk_count}</td>
                    <td>{formatSize(document.size_bytes)}</td>
                    <td>
                      <div className="button-row">
                        <button type="button" onClick={() => reindexDocument(document.id)} disabled={busy === `reindex-${document.id}`}>
                          重索引
                        </button>
                        <button className="danger" type="button" onClick={() => deleteDocument(document.id)} disabled={busy === `delete-${document.id}`}>
                          删除
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!documents.length && (
                  <tr>
                    <td colSpan={6} className="muted">
                      当前知识库还没有文档。可以上传文件，或导入已完成的拆书任务结果。
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>

          <div className="agent-two-col">
            <form className="panel compact-form" onSubmit={search}>
              <h2>检索测试</h2>
              <label>
                问题或关键词
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：黄金三章如何制造期待？" />
              </label>
              <button className="primary" disabled={!selected || busy === "search"}>
                检索知识库
              </button>
              <div className="hit-list">
                {hits.map((hit) => (
                  <article key={hit.chunk_id}>
                    <strong>[{hit.citation_id}] {hit.document_title || hit.original_filename}</strong>
                    <small>
                      {hit.structure_path} · score {hit.score}
                    </small>
                    <p>{hit.text}</p>
                  </article>
                ))}
              </div>
            </form>

            <form className="panel compact-form" onSubmit={generate}>
              <h2>写作生成</h2>
              <label>
                写作任务
                <textarea rows={4} value={task} onChange={(event) => setTask(event.target.value)} />
              </label>
              <label>
                当前正文，可选
                <textarea rows={5} value={currentContent} onChange={(event) => setCurrentContent(event.target.value)} />
              </label>
              <div className="mode-grid">
                <label>
                  生成模式
                  <select value={mode} onChange={(event) => setMode(event.target.value)}>
                    <option value="fast">快速</option>
                    <option value="standard">标准</option>
                    <option value="deep">深度</option>
                  </select>
                </label>
                <label>
                  知识模式
                  <select value={knowledgeMode} onChange={(event) => setKnowledgeMode(event.target.value)}>
                    <option value="reference">参考知识</option>
                    <option value="strict">严格知识</option>
                  </select>
                </label>
              </div>
              <label className="check-row">
                <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
                dry-run：不调用模型，只验证检索和引用
              </label>
              <button className="primary" disabled={!selected || busy === "generate"}>
                生成内容
              </button>
            </form>
          </div>

          <div className="preview-panel agent-output">
            <div className="preview-toolbar">
              <strong>生成结果</strong>
              <button type="button" disabled={!generated} onClick={() => navigator.clipboard.writeText(generated)}>
                复制
              </button>
            </div>
            <pre>{generated || "生成后会显示在这里。"}</pre>
          </div>

          {!!citations.length && (
            <div className="panel compact-form">
              <h2>参考资料</h2>
              <div className="hit-list">
                {citations.map((hit) => (
                  <article key={hit.chunk_id}>
                    <strong>[{hit.citation_id}] {hit.original_filename}</strong>
                    <small>{hit.structure_path}</small>
                    <p>{hit.text}</p>
                  </article>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
