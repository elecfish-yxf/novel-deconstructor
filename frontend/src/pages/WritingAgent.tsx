import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
import { api, getWorkspaceId, Job, KnowledgeBase, KnowledgeDocument, PublicConfig, RetrievalHit, WritingMemory } from "../api";

const KNOWLEDGE_GROUPS = [
  {
    key: "writing_guide",
    label: "写作技巧指南",
    hint: "拆书沉淀出的结构、节奏、爽点、人物塑造方法。",
  },
  {
    key: "worldbuilding",
    label: "世界观设定",
    hint: "用户提供或确认导入的原创世界观、人物、地点与规则。",
  },
] as const;

function formatSize(value: number) {
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

function knowledgeTypeLabel(type: string) {
  return KNOWLEDGE_GROUPS.find((group) => group.key === type)?.label || type;
}

function documentTitle(document: KnowledgeDocument) {
  return document.document_title || document.original_filename;
}

export default function WritingAgent({ job }: { job?: Job | null }) {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [memories, setMemories] = useState<WritingMemory[]>([]);
  const [name, setName] = useState("作品 1");
  const [description, setDescription] = useState("用于 AI 写作 Agent 的独立作品空间");
  const [expandedWorkIds, setExpandedWorkIds] = useState<number[]>([]);
  const [expandedTypes, setExpandedTypes] = useState<Record<string, boolean>>({
    writing_guide: true,
    worldbuilding: true,
  });
  const [selectedDocumentIds, setSelectedDocumentIds] = useState<number[]>([]);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<RetrievalHit[]>([]);
  const [uploadType, setUploadType] = useState("writing_guide");
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
  const selectedDocumentSet = useMemo(() => new Set(selectedDocumentIds), [selectedDocumentIds]);
  const documentsByType = useMemo(() => {
    return documents.reduce<Record<string, KnowledgeDocument[]>>(
      (groups, document) => {
        const key = document.knowledge_type || "worldbuilding";
        groups[key] = [...(groups[key] || []), document];
        return groups;
      },
      { writing_guide: [], worldbuilding: [] },
    );
  }, [documents]);
  const selectedDocumentsInWork = useMemo(
    () => documents.filter((document) => selectedDocumentSet.has(document.id)),
    [documents, selectedDocumentSet],
  );

  function clearTransientWritingState() {
    setHits([]);
    setCitations([]);
    setWorldbuildingDraft("");
    setOutline("");
    setConfirmedOutline("");
    setDraft("");
  }

  async function load(nextSelectedId?: number | null) {
    const [nextConfig, nextBases] = await Promise.all([api.getPublicConfig(), api.listKnowledgeBases()]);
    setConfig(nextConfig);
    setKnowledgeBases(nextBases);
    let preferred = nextSelectedId ?? selectedId ?? nextBases[0]?.id ?? null;
    if (preferred && !nextBases.some((item) => item.id === preferred)) {
      preferred = nextBases[0]?.id ?? null;
    }
    const selectedChanged = preferred !== selectedId;
    setSelectedId(preferred);
    if (selectedChanged) clearTransientWritingState();
    if (preferred) {
      setExpandedWorkIds((items) => (items.includes(preferred) ? items : [...items, preferred]));
      const [nextDocuments, nextMemories] = await Promise.all([api.listKnowledgeDocuments(preferred), api.listWritingMemories(preferred)]);
      setDocuments(nextDocuments);
      setMemories(nextMemories);
      setSelectedDocumentIds((items) => items.filter((id) => nextDocuments.some((document) => document.id === id)));
    } else {
      setDocuments([]);
      setMemories([]);
      setSelectedDocumentIds([]);
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
      setMessage("作品已创建");
      setName(`作品 ${knowledgeBases.length + 2}`);
      await load(kb.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建作品失败");
    } finally {
      setBusy("");
    }
  }

  async function chooseKnowledgeBase(id: number) {
    const selectedChanged = id !== selectedId;
    setSelectedId(id);
    setSelectedDocumentIds([]);
    if (selectedChanged) clearTransientWritingState();
    setExpandedWorkIds((items) => (items.includes(id) ? items : [...items, id]));
    setError("");
    const [nextDocuments, nextMemories] = await Promise.all([api.listKnowledgeDocuments(id), api.listWritingMemories(id)]);
    setDocuments(nextDocuments);
    setMemories(nextMemories);
  }

  function toggleWork(id: number) {
    if (expandedWorkIds.includes(id)) {
      setExpandedWorkIds((items) => items.filter((item) => item !== id));
      return;
    }
    chooseKnowledgeBase(id).catch((err) => setError(err instanceof Error ? err.message : "加载作品失败"));
  }

  function toggleKnowledgeType(type: string) {
    setExpandedTypes((items) => ({ ...items, [type]: !items[type] }));
  }

  function toggleDocumentSelection(documentId: number) {
    setSelectedDocumentIds((items) => (items.includes(documentId) ? items.filter((id) => id !== documentId) : [...items, documentId]));
  }

  function setGroupSelection(type: string, checked: boolean) {
    const groupIds = (documentsByType[type] || []).map((document) => document.id);
    setSelectedDocumentIds((items) => {
      if (!checked) return items.filter((id) => !groupIds.includes(id));
      return Array.from(new Set([...items, ...groupIds]));
    });
  }

  function selectAllCurrentDocuments() {
    setSelectedDocumentIds(documents.map((document) => document.id));
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
      setError(err instanceof Error ? err.message : "上传作品文件失败");
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

  async function bulkDeleteDocuments(knowledgeType?: string, deleteAll = false) {
    if (!selected) return;
    const typeDocuments = knowledgeType ? documentsByType[knowledgeType] || [] : documents;
    const selectedIds = typeDocuments.filter((document) => selectedDocumentSet.has(document.id)).map((document) => document.id);
    if (!deleteAll && !selectedIds.length) return;

    const targetLabel = knowledgeType ? knowledgeTypeLabel(knowledgeType) : selected.name;
    const confirmText = deleteAll
      ? `确定删除「${targetLabel}」下的全部文件吗？这个操作不会删除其他作品。`
      : `确定删除已选中的 ${selectedIds.length} 个文件吗？`;
    if (!window.confirm(confirmText)) return;

    setBusy(`bulk-delete-${knowledgeType || "all"}`);
    setError("");
    setMessage("");
    try {
      const result = await api.bulkDeleteKnowledgeDocuments(selected.id, {
        document_ids: selectedIds,
        knowledge_type: knowledgeType,
        delete_all: deleteAll,
      });
      setSelectedDocumentIds([]);
      setMessage(result.message);
      await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "批量删除文件失败");
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
    if (!window.confirm("确定删除这个文件和对应分块吗？")) return;
    setBusy(`delete-${documentId}`);
    setError("");
    try {
      await api.deleteKnowledgeDocument(documentId);
      setSelectedDocumentIds((items) => items.filter((id) => id !== documentId));
      if (selected) await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除文件失败");
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
    setConfirmedOutline("");
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
        <p>每个作品都是独立空间：写作技巧指南用于提升写法，世界观设定用于约束故事事实，作品之间互不共享文件和 Memory。</p>
      </div>

      {config && (
        <div className="notice panel">
          {config.privacy_note} 当前模型：{config.deepseek_model}，API Key：{config.has_deepseek_api_key ? "已配置" : "未配置"}。
        </div>
      )}
      <div className="notice panel">
        当前浏览器工作区：{getWorkspaceId()}。项目、进度、作品和文件会按这个工作区隔离，其他访客默认看不到你的进程。
      </div>
      {error && <div className="alert">{error}</div>}
      {message && <div className="panel notice">{message}</div>}

      <div className="agent-layout">
        <aside className="panel agent-sidebar work-sidebar">
          <form className="compact-form work-create-form" onSubmit={createKnowledgeBase}>
            <div>
              <p className="eyebrow">Agent 写作</p>
              <h2>作品管理</h2>
            </div>
            <label>
              作品名
              <input value={name} onChange={(event) => setName(event.target.value)} />
            </label>
            <label>
              作品备注
              <textarea rows={3} value={description} onChange={(event) => setDescription(event.target.value)} />
            </label>
            <button className="primary" disabled={busy === "create"}>
              新建作品
            </button>
          </form>

          <div className="work-tree">
            <div className="work-tree-title">
              <strong>作品文件树</strong>
              <small>{knowledgeBases.length} 个作品</small>
            </div>
            {knowledgeBases.map((kb) => {
              const expanded = expandedWorkIds.includes(kb.id);
              const active = selectedId === kb.id;
              return (
                <section key={kb.id} className={`work-node ${active ? "active-work" : ""}`}>
                  <div className="work-node-head">
                    <button type="button" className="tree-toggle" onClick={() => toggleWork(kb.id)} aria-label={expanded ? "收起作品" : "展开作品"}>
                      {expanded ? "⌄" : "›"}
                    </button>
                    <button type="button" className="work-title-button" onClick={() => chooseKnowledgeBase(kb.id)}>
                      <strong>{kb.name}</strong>
                      <small>
                        {kb.document_count} 文件 · {kb.chunk_count} 分块
                      </small>
                    </button>
                  </div>

                  {expanded && active && (
                    <div className="work-files">
                      <div className="file-manager-controls">
                        <label>
                          导入到
                          <select value={uploadType} onChange={(event) => setUploadType(event.target.value)}>
                            {KNOWLEDGE_GROUPS.map((group) => (
                              <option key={group.key} value={group.key}>
                                {group.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <div className="button-row tight-row">
                          <label className="button-link compact-action">
                            上传
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
                            导入拆书技巧
                          </button>
                        </div>
                      </div>

                      <div className="file-bulk-toolbar">
                        <button type="button" onClick={selectAllCurrentDocuments} disabled={!documents.length}>
                          全选
                        </button>
                        <button type="button" onClick={() => setSelectedDocumentIds([])} disabled={!selectedDocumentIds.length}>
                          取消
                        </button>
                        <button type="button" className="danger" onClick={() => bulkDeleteDocuments()} disabled={!selectedDocumentsInWork.length}>
                          删除选中
                        </button>
                        <button type="button" className="danger" onClick={() => bulkDeleteDocuments(undefined, true)} disabled={!documents.length}>
                          全部删除
                        </button>
                      </div>

                      {KNOWLEDGE_GROUPS.map((group) => {
                        const groupDocuments = documentsByType[group.key] || [];
                        const groupSelected = groupDocuments.filter((document) => selectedDocumentSet.has(document.id)).length;
                        const allGroupSelected = groupDocuments.length > 0 && groupSelected === groupDocuments.length;
                        return (
                          <div key={group.key} className="knowledge-tree-group">
                            <div className="knowledge-tree-head">
                              <button type="button" className="tree-toggle" onClick={() => toggleKnowledgeType(group.key)}>
                                {expandedTypes[group.key] ? "⌄" : "›"}
                              </button>
                              <input
                                type="checkbox"
                                checked={allGroupSelected}
                                disabled={!groupDocuments.length}
                                onChange={(event) => setGroupSelection(group.key, event.target.checked)}
                                aria-label={`选择${group.label}`}
                              />
                              <button type="button" className="knowledge-title-button" onClick={() => toggleKnowledgeType(group.key)}>
                                <strong>{group.label}</strong>
                                <small>
                                  {groupDocuments.length} 文件
                                  {groupSelected ? ` · 已选 ${groupSelected}` : ""}
                                </small>
                              </button>
                              <button
                                type="button"
                                className="danger compact-action"
                                onClick={() => bulkDeleteDocuments(group.key, true)}
                                disabled={!groupDocuments.length || busy === `bulk-delete-${group.key}`}
                              >
                                清空
                              </button>
                            </div>
                            {expandedTypes[group.key] && (
                              <div className="file-row-list">
                                {!groupDocuments.length && <p className="muted file-empty">{group.hint}</p>}
                                {groupDocuments.map((document) => (
                                  <div key={document.id} className={`file-row-item ${selectedDocumentSet.has(document.id) ? "selected-file" : ""}`}>
                                    <input
                                      type="checkbox"
                                      checked={selectedDocumentSet.has(document.id)}
                                      onChange={() => toggleDocumentSelection(document.id)}
                                      aria-label={`选择${documentTitle(document)}`}
                                    />
                                    <div className="file-row-main">
                                      <strong title={documentTitle(document)}>{documentTitle(document)}</strong>
                                      <small>
                                        {document.chunk_count} 分块 · {formatSize(document.size_bytes)} · {document.status}
                                      </small>
                                      {document.error_message && <small className="warn-cell">{document.error_message}</small>}
                                    </div>
                                    <div className="file-row-actions">
                                      <button type="button" onClick={() => reindexDocument(document.id)} disabled={busy === `reindex-${document.id}`}>
                                        重建
                                      </button>
                                      <button type="button" className="danger" onClick={() => deleteDocument(document.id)} disabled={busy === `delete-${document.id}`}>
                                        删
                                      </button>
                                    </div>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>
              );
            })}
            {!knowledgeBases.length && <p className="muted file-empty">还没有作品。先新建一个作品，再上传知识文件。</p>}
          </div>
        </aside>

        <div className="agent-main">
          <div className="panel compact-form selected-work-card">
            <div>
              <p className="eyebrow">Current Work</p>
              <h2>{selected?.name || "请选择或新建作品"}</h2>
            </div>
            <p className="muted">
              {selected
                ? `${selected.name} 内共有 ${documents.length} 个文件：${documentsByType.writing_guide.length} 个写作技巧指南，${documentsByType.worldbuilding.length} 个世界观设定。`
                : "每个作品有独立文件树、Memory 和生成上下文。"}
            </p>
          </div>

          <div className="agent-two-col">
            <form className="panel compact-form" onSubmit={search}>
              <h2>检索测试</h2>
              <label>
                问题或关键词
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：黄金三章如何制造期待？" />
              </label>
              <button className="primary" disabled={!selected || busy === "search"}>
                检索当前作品
              </button>
              <div className="hit-list">
                {hits.map((hit) => (
                  <article key={hit.chunk_id}>
                    <strong>
                      [{hit.citation_id}] {hit.document_title || hit.original_filename}
                    </strong>
                    <small>
                      {knowledgeTypeLabel(hit.knowledge_type)} · {hit.structure_path} · score {hit.score}
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
              <p className="muted">Memory 会跟随当前作品，用来承接已确认提纲、已写正文、人物状态、伏笔和你的备注。</p>
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
              <button
                type="button"
                className="primary"
                disabled={!selected || busy === "memory" || !memoryTitle.trim() || !memoryContent.trim()}
                onClick={() => saveMemory(memoryTitle, memoryContent)}
              >
                保存 Memory
              </button>
              <div className="hit-list memory-list">
                {memories.slice(0, 6).map((memory) => (
                  <article key={memory.id}>
                    <strong>{memory.title}</strong>
                    <small>
                      {memory.memory_type} · {memory.source}
                    </small>
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
              <p className="muted">把你想写的章节、风格、字数、承接上下文放在这里。系统会先生成提纲，不会直接生成正文。</p>
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
            <p className="muted">这里生成的是原创世界观候选稿。它不会自动进入作品文件树，只有你确认后才会作为世界观设定导入当前作品。</p>
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
            <textarea rows={12} value={worldbuildingDraft} onChange={(event) => setWorldbuildingDraft(event.target.value)} placeholder="生成或粘贴世界观设定，确认后导入当前作品。" />
          </div>

          {!!citations.length && (
            <div className="panel compact-form">
              <h2>参考资料</h2>
              <div className="hit-list">
                {citations.map((hit) => (
                  <article key={hit.chunk_id}>
                    <strong>
                      [{hit.citation_id}] {hit.original_filename}
                    </strong>
                    <small>
                      {knowledgeTypeLabel(hit.knowledge_type)} · {hit.structure_path}
                    </small>
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
