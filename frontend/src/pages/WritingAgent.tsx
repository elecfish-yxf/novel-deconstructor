import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { api, getWorkspaceId, Job, KnowledgeBase, KnowledgeDocument, PublicConfig, RetrievalHit, WritingMemory } from "../api";

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
  const [memories, setMemories] = useState<WritingMemory[]>([]);
  const [name, setName] = useState("小说拆书知识库");
  const [description, setDescription] = useState("用于 AI 写作 Agent 的本地知识库");
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<RetrievalHit[]>([]);
  const [uploadType, setUploadType] = useState("worldbuilding");
  const [storySeed, setStorySeed] = useState("一个普通人在高压规则世界中寻找自我选择权。");
  const [worldbuildingDraft, setWorldbuildingDraft] = useState("");
  const [outlineTask, setOutlineTask] = useState("请基于世界观设定，结合写作技巧指南，为我生成一份原创小说第一章章节提纲。");
  const [outlineContext, setOutlineContext] = useState("");
  const [outline, setOutline] = useState("");
  const [confirmedOutline, setConfirmedOutline] = useState("");
  const [draft, setDraft] = useState("");
  const [memoryType, setMemoryType] = useState("note");
  const [memoryTitle, setMemoryTitle] = useState("");
  const [memoryContent, setMemoryContent] = useState("");
  const [mode, setMode] = useState("fast");
  const [knowledgeMode, setKnowledgeMode] = useState("reference");
  const [dryRun, setDryRun] = useState(true);
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
      const [nextDocuments, nextMemories] = await Promise.all([api.listKnowledgeDocuments(preferred), api.listWritingMemories(preferred)]);
      setDocuments(nextDocuments);
      setMemories(nextMemories);
    } else {
      setDocuments([]);
      setMemories([]);
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
    const [nextDocuments, nextMemories] = await Promise.all([api.listKnowledgeDocuments(id), api.listWritingMemories(id)]);
    setDocuments(nextDocuments);
    setMemories(nextMemories);
  }

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = event.target.files;
    if (!selected || !files?.length) return;
    setBusy("upload");
    setError("");
    setMessage("");
    try {
      const result = await api.uploadKnowledgeDocumentsAs(selected.id, files, uploadType);
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

  async function generateWorldbuildingDraft() {
    if (!selected || !storySeed.trim()) return;
    setBusy("worldbuilding");
    setError("");
    setMessage("");
    try {
      const result = await api.generateWorldbuildingDraft({
        knowledge_base_ids: [selected.id],
        story_seed: storySeed,
        requirements: "生成原创世界观。可以参考写作技巧指南，但不要沿用拆书原作的世界观、角色、势力、地名和独特设定。",
        dry_run: dryRun,
      });
      setWorldbuildingDraft(result.content);
      setCitations(result.citations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成世界观草案失败");
    } finally {
      setBusy("");
    }
  }

  async function confirmWorldbuildingImport() {
    if (!selected || !worldbuildingDraft.trim()) return;
    setBusy("confirm-worldbuilding");
    setError("");
    setMessage("");
    try {
      const result = await api.createKnowledgeTextDocument(selected.id, {
        filename: "worldbuilding_confirmed.md",
        content: worldbuildingDraft,
        knowledge_type: "worldbuilding",
      });
      setMessage(result.message);
      await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入世界观设定失败");
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

  async function generateOutline(event: FormEvent) {
    event.preventDefault();
    if (!selected || !outlineTask.trim()) return;
    setBusy("outline");
    setError("");
    setOutline("");
    setCitations([]);
    try {
      const result = await api.generateOutline({
        knowledge_base_ids: [selected.id],
        task: outlineTask,
        current_content: outlineContext,
        mode,
        knowledge_mode: knowledgeMode,
        dry_run: dryRun,
      });
      setOutline(result.content);
      setCitations(result.citations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成提纲失败");
    } finally {
      setBusy("");
    }
  }

  async function confirmOutline() {
    if (!selected || !outline.trim()) return;
    setBusy("confirm-outline");
    setError("");
    setMessage("");
    try {
      setConfirmedOutline(outline);
      const saved = await api.createWritingMemory({
        knowledge_base_id: selected.id,
        memory_type: "outline",
        title: `已确认提纲 ${new Date().toLocaleString()}`,
        content: outline,
        source: "confirmed_outline",
      });
      setMemories((items) => [saved, ...items]);
      setMemoryTitle("");
      setMemoryContent("");
      setMessage("提纲已确认，并写入长期 Memory。现在可以生成正文。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "确认提纲失败");
    } finally {
      setBusy("");
    }
  }

  async function generateDraft(event: FormEvent) {
    event.preventDefault();
    if (!selected || !confirmedOutline.trim()) return;
    setBusy("draft");
    setError("");
    setDraft("");
    setCitations([]);
    try {
      const result = await api.generateDraft({
        knowledge_base_ids: [selected.id],
        task: `请根据用户已确认的章节提纲生成小说正文：${outlineTask}`,
        confirmed_outline: confirmedOutline,
        current_content: outlineContext,
        mode,
        knowledge_mode: knowledgeMode,
        dry_run: dryRun,
      });
      setDraft(result.content);
      setCitations(result.citations);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成正文失败");
    } finally {
      setBusy("");
    }
  }

  async function saveMemory(title: string, content: string, type = memoryType, source = "manual") {
    if (!selected || !title.trim() || !content.trim()) return;
    setBusy("memory");
    setError("");
    setMessage("");
    try {
      const saved = await api.createWritingMemory({
        knowledge_base_id: selected.id,
        memory_type: type,
        title,
        content,
        source,
      });
      setMemories((items) => [saved, ...items]);
      setMemoryTitle("");
      setMemoryContent("");
      setMessage("Memory 已保存，后续提纲和正文生成都会自动参考。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Memory 失败");
    } finally {
      setBusy("");
    }
  }

  async function deleteMemory(id: number) {
    if (!window.confirm("确定删除这条 Memory 吗？")) return;
    setBusy(`memory-${id}`);
    setError("");
    try {
      await api.deleteWritingMemory(id);
      setMemories((items) => items.filter((item) => item.id !== id));
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除 Memory 失败");
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
        <p>知识库分为写作技巧指南与世界观设定。故事围绕世界观写，拆书结果只沉淀为技巧指南。</p>
      </div>

      {config && <div className="notice panel">{config.privacy_note} 当前模型：{config.deepseek_model}；API Key：{config.has_deepseek_api_key ? "已配置" : "未配置"}。</div>}
      <div className="notice panel">当前浏览器工作区：{getWorkspaceId()}。项目、进度和知识库会按这个工作区隔离，其他访客默认看不到你的进程。</div>
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
              <label>
                知识类型
                <select value={uploadType} onChange={(event) => setUploadType(event.target.value)}>
                  <option value="worldbuilding">世界观设定</option>
                  <option value="writing_guide">写作技巧指南</option>
                </select>
              </label>
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
                导入当前拆书技巧
              </button>
            </div>
            <small className="muted">拆书任务默认只导入写作技巧指南：final_reports 与 knowledge_base。世界观设定请由用户上传，或生成草案后确认导入。</small>
          </div>

          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>文档</th>
                  <th>结构路径</th>
                  <th>类型</th>
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
                    <td>{document.knowledge_type === "writing_guide" ? "写作技巧" : "世界观"}</td>
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
                    <td colSpan={7} className="muted">
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
                      {hit.knowledge_type === "writing_guide" ? "写作技巧" : "世界观"} · {hit.structure_path} · score {hit.score}
                    </small>
                    <p>{hit.text}</p>
                  </article>
                ))}
              </div>
            </form>

            <div className="panel compact-form memory-panel">
              <div className="preview-toolbar">
                <h2>长期 Memory</h2>
                <span className="muted">{memories.length} 条</span>
              </div>
              <p className="muted">Memory 用来记住已确认提纲、已写正文、人物状态、伏笔和你的备注。后续生成会自动参考。</p>
              <div className="mode-grid">
                <label>
                  类型
                  <select value={memoryType} onChange={(event) => setMemoryType(event.target.value)}>
                    <option value="note">备注</option>
                    <option value="outline">提纲</option>
                    <option value="draft">正文片段</option>
                    <option value="continuity">连续性</option>
                  </select>
                </label>
                <label>
                  标题
                  <input value={memoryTitle} onChange={(event) => setMemoryTitle(event.target.value)} placeholder="例如：第一章结尾状态" />
                </label>
              </div>
              <textarea rows={4} value={memoryContent} onChange={(event) => setMemoryContent(event.target.value)} placeholder="写下需要长期承接的上下文。" />
              <button type="button" className="primary" disabled={!selected || busy === "memory" || !memoryTitle.trim() || !memoryContent.trim()} onClick={() => saveMemory(memoryTitle, memoryContent)}>
                保存 Memory
              </button>
              <div className="hit-list memory-list">
                {memories.slice(0, 6).map((memory) => (
                  <article key={memory.id}>
                    <strong>{memory.title}</strong>
                    <small>{memory.memory_type} · {memory.source}</small>
                    <p>{memory.content}</p>
                    <button type="button" className="danger" onClick={() => deleteMemory(memory.id)} disabled={busy === `memory-${memory.id}`}>
                      删除
                    </button>
                  </article>
                ))}
                {!memories.length && <p className="muted">还没有 Memory。确认提纲或手动保存后会显示在这里。</p>}
              </div>
            </div>
          </div>

          <div className="writing-flow">
            <form className="panel compact-form writing-step" onSubmit={generateOutline}>
              <div className="step-badge">1</div>
              <h2>发送请求</h2>
              <p className="muted">把你想写的章节、风格、字数、承接上下文都放在这里。系统会先生成提纲，不会直接生成正文。</p>
              <label>
                写作请求
                <textarea rows={4} value={outlineTask} onChange={(event) => setOutlineTask(event.target.value)} />
              </label>
              <label>
                补充上下文/已有正文，可选
                <textarea rows={5} value={outlineContext} onChange={(event) => setOutlineContext(event.target.value)} />
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
              <button className="primary" disabled={!selected || busy === "outline"}>
                发送请求，生成提纲
              </button>
            </form>

            <div className="panel compact-form writing-step">
              <div className="step-badge">2</div>
              <h2>生成并确认提纲</h2>
              <p className="muted">这里显示模型生成的章节提纲。你可以直接编辑，确认后才允许进入正文生成。</p>
              <label>
                章节提纲
                <textarea rows={16} value={outline} onChange={(event) => setOutline(event.target.value)} placeholder="提纲会显示在这里。你也可以手动粘贴或修改提纲，然后点击确认。" />
              </label>
              <div className="button-row">
                <button type="button" disabled={!outline} onClick={() => navigator.clipboard.writeText(outline)}>
                  复制提纲
                </button>
                <button type="button" className="primary" disabled={!selected || !outline.trim() || busy === "confirm-outline"} onClick={confirmOutline}>
                  确认提纲
                </button>
              </div>
              <small className="muted">{confirmedOutline ? "已确认提纲，可以生成正文。" : "提纲确认后会写入 Memory，并解锁第三个对话框。"}</small>
            </div>

            <form className="panel compact-form writing-step" onSubmit={generateDraft}>
              <div className="step-badge">3</div>
              <h2>生成正文</h2>
              <p className="muted">用户确认提纲后，点击这里生成小说正文。这里不会再输出提纲、表格、结构核对或写作说明。</p>
              <button className="primary" disabled={!selected || !confirmedOutline.trim() || busy === "draft"}>
                根据确认提纲生成正文
              </button>
              <div className="preview-panel inline-output">
                <div className="preview-toolbar">
                  <strong>小说正文</strong>
                  <div className="button-row">
                    <button type="button" disabled={!draft} onClick={() => navigator.clipboard.writeText(draft)}>
                      复制正文
                    </button>
                    <button type="button" disabled={!selected || !draft || busy === "memory"} onClick={() => saveMemory(`正文片段 ${new Date().toLocaleString()}`, draft, "draft", "generated_draft")}>
                      存入 Memory
                    </button>
                  </div>
                </div>
                <pre>{draft || (confirmedOutline ? "正文会显示在这里。" : "请先在第二个对话框确认提纲。")}</pre>
              </div>
            </form>
          </div>

          <div className="panel compact-form">
            <h2>世界观设定草案</h2>
            <p className="muted">这里生成的是原创世界观候选稿。它不会自动进入知识库，只有你确认后才会作为 worldbuilding 导入。</p>
            <label>
              故事种子
              <textarea rows={3} value={storySeed} onChange={(event) => setStorySeed(event.target.value)} />
            </label>
            <div className="button-row">
              <button type="button" onClick={generateWorldbuildingDraft} disabled={!selected || busy === "worldbuilding"}>
                生成世界观草案
              </button>
              <button type="button" className="primary" onClick={confirmWorldbuildingImport} disabled={!selected || !worldbuildingDraft || busy === "confirm-worldbuilding"}>
                确认导入为世界观设定
              </button>
            </div>
            <textarea rows={12} value={worldbuildingDraft} onChange={(event) => setWorldbuildingDraft(event.target.value)} placeholder="生成或粘贴世界观设定，确认后导入知识库。" />
          </div>

          {!!citations.length && (
            <div className="panel compact-form">
              <h2>参考资料</h2>
              <div className="hit-list">
                {citations.map((hit) => (
                  <article key={hit.chunk_id}>
                    <strong>[{hit.citation_id}] {hit.original_filename}</strong>
                    <small>{hit.knowledge_type === "writing_guide" ? "写作技巧" : "世界观"} · {hit.structure_path}</small>
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
