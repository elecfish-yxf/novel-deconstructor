import { Dispatch, ChangeEvent, useState, useMemo, useRef } from "react";
import { WritingAction, WritingState } from "./types";
import { KnowledgeBase, KnowledgeDocument, KnowledgeCard, KnowledgeMarkdownDoc, api } from "../../api";
import { formatSize, compactSourceRef, documentTitle } from "./utils";
import { SkeletonCard } from "../common/Skeleton";

const CARDS_PER_PAGE = 20;

interface Props {
  state: WritingState; dispatch: Dispatch<WritingAction>;
  selected: KnowledgeBase | null;
  documentsByType: Record<string, KnowledgeDocument[]>;
  selectedDocumentSet: Set<number>;
  selectedCardSet: Set<string>;
  selectedDocSet: Set<string>;
  selectedMemorySet: Set<number>;
  refreshKnowledgeCards: (id?: number) => Promise<void>;
  reloadWorkIfStillActive: (id: number) => Promise<void>;
  load: (id?: number | null) => Promise<void>;
  ragRetrievalPayload: Record<string, unknown>;
  resolvedRagTopK: number;
  positionMissing: boolean;
  workspaceId: string;
  uploadType: string;
  packagePath: string;
  markdownSourcePath: string;
  knowledgeTypeLabel: (type: string) => string;
}

export function KnowledgePanel({ state, dispatch, selected, documentsByType, selectedDocumentSet, selectedCardSet, selectedDocSet, selectedMemorySet, refreshKnowledgeCards, reloadWorkIfStillActive, load, ragRetrievalPayload, resolvedRagTopK, positionMissing, workspaceId, uploadType, packagePath, markdownSourcePath, knowledgeTypeLabel }: Props) {
  const [cardPage, setCardPage] = useState(1);
  const mdFileRef = useRef<HTMLInputElement>(null);

  const cardFilterGroups = (() => {
    const visible = state.showRawCards ? state.cards : state.cards.filter((c) => c.is_canonical);
    const grouped: Record<string, { key: string; label: string; count: number }> = {};
    visible.forEach((c) => { const k = `${c.library_type}/${c.card_type}`; if (!grouped[k]) grouped[k] = { key: k, label: k, count: 0 }; grouped[k].count++; });
    return [{ key: "all", label: state.showRawCards ? "全部" : "Canonical", count: visible.length }, ...Object.values(grouped).sort((a, b) => a.label.localeCompare(b.label))];
  })();

  const filteredCards = (() => {
    const visible = state.showRawCards ? state.cards : state.cards.filter((c) => c.is_canonical);
    return state.cardTypeFilter === "all" ? visible : visible.filter((c) => `${c.library_type}/${c.card_type}` === state.cardTypeFilter);
  })();

  // Pagination
  const totalPages = Math.max(1, Math.ceil(filteredCards.length / CARDS_PER_PAGE));
  const pagedCards = useMemo(() => {
    const start = (cardPage - 1) * CARDS_PER_PAGE;
    return filteredCards.slice(start, start + CARDS_PER_PAGE);
  }, [filteredCards, cardPage]);

  // Reset page when filter changes
  const setFilter = (filter: string) => {
    dispatch({ type: "SET_CARD_TYPE_FILTER", filter });
    setCardPage(1);
  };

  const searchRAG = async () => {
    if (!selected || !state.query.trim()) return;
    if (positionMissing) { dispatch({ type: "SET_ERROR", error: "请先填写当前 Volume 和 Chapter。" }); return; }
    dispatch({ type: "SET_BUSY", busy: "rag-search" });
    try {
      const r = await api.searchWorkRAG(selected.id, { stage: state.ragStage, query: state.query, top_k: resolvedRagTopK, ...ragRetrievalPayload });
      dispatch({ type: "SET_RAG_RESULTS", results: r.results });
      dispatch({ type: "SET_RETRIEVAL_DEBUG", debug: r.retrieval_debug });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "RAG 召回失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const uploadFiles = async (e: ChangeEvent<HTMLInputElement>) => {
    if (!selected || !e.target.files?.length) return;
    dispatch({ type: "SET_BUSY", busy: "upload" });
    try {
      const r = await api.uploadKnowledgeDocumentsAs(selected.id, e.target.files, uploadType);
      dispatch({ type: "SET_MESSAGE", message: `${knowledgeTypeLabel(uploadType)}已上传：${r.message}` });
      await reloadWorkIfStillActive(selected.id);
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "上传失败" });
    } finally { e.target.value = ""; dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const importPackage = async () => {
    if (!selected || !packagePath.trim()) return;
    dispatch({ type: "SET_BUSY", busy: "import-package" });
    try {
      const r = await api.importKnowledgePackage(selected.id, { package_path: packagePath, library_type: uploadType, status: "approved", merge_mode: "safe", markdown_scope: "canonical_only" });
      dispatch({ type: "SET_MESSAGE", message: `知识包已导入：${r.message}` });
      await refreshKnowledgeCards(selected.id);
      dispatch({ type: "SET_ACTIVE_KNOWLEDGE_TAB", tab: "cards" });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "导入失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const importMD = async () => {
    if (!selected || !markdownSourcePath.trim()) return;
    dispatch({ type: "SET_BUSY", busy: "import-md-path" });
    try {
      const r = await api.importKnowledgeMarkdown(selected.id, { source_path: markdownSourcePath, library_type: uploadType, status: "raw_extracted" });
      dispatch({ type: "SET_MESSAGE", message: `Markdown 已拆卡：${r.message}` });
      await refreshKnowledgeCards(selected.id);
      dispatch({ type: "SET_ACTIVE_KNOWLEDGE_TAB", tab: "cards" });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "拆卡失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const importMarkdownFiles = async (e: ChangeEvent<HTMLInputElement>) => {
    if (!selected || !e.target.files?.length) return;
    dispatch({ type: "SET_BUSY", busy: "import-md-files" });
    try {
      const results = await api.uploadKnowledgeMarkdownFiles(selected.id, e.target.files, uploadType, "raw_extracted");
      const imported = results.reduce((t, r) => t + r.imported_count, 0);
      const skipped = results.reduce((t, r) => t + r.skipped_count, 0);
      dispatch({ type: "SET_MESSAGE", message: `Markdown 文件已拆卡：导入 ${imported} 张，跳过 ${skipped} 项` });
      await refreshKnowledgeCards(selected.id);
      dispatch({ type: "SET_ACTIVE_KNOWLEDGE_TAB", tab: "cards" });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "Markdown 文件导入失败" });
    } finally { e.target.value = ""; dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const deleteDocument = async (docId: number) => {
    if (!selected || !window.confirm("确定删除这个文件和对应分块吗？")) return;
    dispatch({ type: "SET_BUSY", busy: `delete-doc-${docId}` });
    try {
      await api.deleteKnowledgeDocument(docId);
      dispatch({ type: "SET_SELECTED_DOCUMENT_IDS", ids: state.selectedDocumentIds.filter((id) => id !== docId) });
      await reloadWorkIfStillActive(selected.id);
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "删除文件失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const toggleDocumentSelection = (docId: number) => {
    dispatch({ type: "SET_SELECTED_DOCUMENT_IDS", ids: state.selectedDocumentIds.includes(docId) ? state.selectedDocumentIds.filter((id) => id !== docId) : [...state.selectedDocumentIds, docId] });
  };

  const toggleCardSelection = (id: string) => dispatch({ type: "SET_SELECTED_CARD_IDS", ids: state.selectedCardIds.includes(id) ? state.selectedCardIds.filter((x) => x !== id) : [...state.selectedCardIds, id] });
  const toggleDocSelection = (id: string) => dispatch({ type: "SET_SELECTED_DOC_IDS", ids: state.selectedDocIds.includes(id) ? state.selectedDocIds.filter((x) => x !== id) : [...state.selectedDocIds, id] });

  return (
    <>
      {/* Tabs */}
      <div className="writing-tab-row">
        {(["cards", "files", "docs", "result"] as const).map((t) => (
          <button key={t} className={state.activeKnowledgeTab === t ? "active" : ""} onClick={() => dispatch({ type: "SET_ACTIVE_KNOWLEDGE_TAB", tab: t })}>
            {t === "cards" ? `知识卡 (${state.cards.length})` : t === "files" ? `文件 (${state.documents.length})` : t === "docs" ? `Markdown (${state.markdownDocs.length})` : "结果"}
          </button>
        ))}
      </div>

      {/* Import section */}
      <div className="writing-card-import">
        <div className="writing-card-import-head">
          <strong>导入知识</strong>
          <select value={uploadType} onChange={(e) => dispatch({ type: "SET_UPLOAD_TYPE", utype: e.target.value })}>
            <option value="writing_guide">写作技巧指南</option>
            <option value="worldbuilding">世界观设定</option>
          </select>
        </div>
        <label>文件上传（任何格式）<input type="file" multiple onChange={uploadFiles} disabled={state.busy === "upload"} /></label>
        <div className="writing-card-divider" />
        <label>知识包路径 <input value={packagePath} onChange={(e) => dispatch({ type: "SET_PACKAGE_PATH", path: e.target.value })} placeholder="如 demo_rain_lamp_street" /></label>
        <button onClick={importPackage} disabled={state.busy === "import-package" || !packagePath.trim()}>导入知识包</button>
        <div className="writing-card-divider" />
        <label>Markdown 路径（拆卡）<input value={markdownSourcePath} onChange={(e) => dispatch({ type: "SET_MARKDOWN_SOURCE_PATH", path: e.target.value })} placeholder="本地 .md 文件路径" /></label>
        <button onClick={importMD} disabled={state.busy === "import-md-path" || !markdownSourcePath.trim()}>路径拆卡</button>
        <label style={{ marginTop: 6 }}>Markdown 文件上传（拆卡）<input ref={mdFileRef} type="file" accept=".md,.markdown" multiple onChange={importMarkdownFiles} disabled={state.busy === "import-md-files"} /></label>
        <button onClick={() => mdFileRef.current?.click()} disabled={state.busy === "import-md-files"}>上传 .md 并拆卡</button>
      </div>

      {/* Files tab — uploaded knowledge documents */}
      {state.activeKnowledgeTab === "files" && (
        <div className="writing-card-list">
          {state.documents.length === 0 && <p className="muted">暂无上传文件。请在上方导入知识区域上传文件。</p>}
          {Object.entries(documentsByType).map(([type, docs]) =>
            docs.length > 0 ? (
              <div key={type}>
                <h4 style={{ margin: "8px 0 4px", color: "#374151", fontSize: 13 }}>{knowledgeTypeLabel(type)} ({docs.length})</h4>
                {docs.map((doc) => (
                  <div key={doc.id} className="writing-card-item">
                    <input type="checkbox" checked={selectedDocumentSet.has(doc.id)} onChange={() => toggleDocumentSelection(doc.id)} />
                    <div>
                      <strong>{documentTitle(doc)}</strong>
                      <small>{doc.file_type} · {formatSize(doc.size_bytes)} · {doc.status} · {doc.chunk_count} 分块</small>
                    </div>
                    <button onClick={() => deleteDocument(doc.id)} disabled={state.busy === `delete-doc-${doc.id}`}>删</button>
                  </div>
                ))}
              </div>
            ) : null
          )}
        </div>
      )}

      {/* Knowledge cards tab */}
      {state.activeKnowledgeTab === "cards" && (
        <>
          <div className="writing-card-filters">
            <select value={state.cardTypeFilter} onChange={(e) => setFilter(e.target.value)}>
              {cardFilterGroups.map((g) => (<option key={g.key} value={g.key}>{g.label} ({g.count})</option>))}
            </select>
            <label className="check-row"><input type="checkbox" checked={state.showRawCards} onChange={(e) => dispatch({ type: "SET_SHOW_RAW_CARDS", show: e.target.checked })} />显示原始卡</label>
            {state.selectedCardIds.length > 0 && <button onClick={async () => { if (!selected) return; dispatch({ type: "SET_BUSY", busy: "delete-cards" }); try { await api.bulkDeleteKnowledgeCards(selected.id, state.selectedCardIds); dispatch({ type: "SET_SELECTED_CARD_IDS", ids: [] }); await refreshKnowledgeCards(selected.id); } catch (err) { dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "删除失败" }); } finally { dispatch({ type: "SET_BUSY", busy: "" }); } }}>删除选中</button>}
          </div>
          {state.busy && state.busy.startsWith("card") ? (
            <div style={{ padding: 8 }}>{Array.from({ length: 5 }).map((_, i) => <SkeletonCard key={i} />)}</div>
          ) : (
            <div className="writing-card-list">
              {pagedCards.map((card) => (
                <div key={card.card_id} className="writing-card-item">
                  <input type="checkbox" checked={selectedCardSet.has(card.card_id)} onChange={() => toggleCardSelection(card.card_id)} />
                  <div>
                    <strong>[{card.card_type}] {card.title}</strong>
                    <small>{card.status} · {card.scope_level}{card.volume_index ? ` V${card.volume_index}` : ""}{card.chapter_index ? ` C${card.chapter_index}` : ""}</small>
                    <p>{card.summary || card.content.slice(0, 150)}</p>
                  </div>
                </div>
              ))}
              {!filteredCards.length && <p className="muted">无知识卡。</p>}
            </div>
          )}
          {totalPages > 1 && (
            <div className="writing-pagination">
              <button disabled={cardPage <= 1} onClick={() => setCardPage(1)}>«</button>
              <button disabled={cardPage <= 1} onClick={() => setCardPage((p) => p - 1)}>‹</button>
              {Array.from({ length: Math.min(totalPages, 7) }).map((_, i) => {
                let pageNum: number;
                if (totalPages <= 7) { pageNum = i + 1; }
                else if (cardPage <= 4) { pageNum = i + 1; }
                else if (cardPage >= totalPages - 3) { pageNum = totalPages - 6 + i; }
                else { pageNum = cardPage - 3 + i; }
                return (<button key={pageNum} className={pageNum === cardPage ? "active" : ""} onClick={() => setCardPage(pageNum)}>{pageNum}</button>);
              })}
              <button disabled={cardPage >= totalPages} onClick={() => setCardPage((p) => p + 1)}>›</button>
              <button disabled={cardPage >= totalPages} onClick={() => setCardPage(totalPages)}>»</button>
              <span>{filteredCards.length} 张</span>
            </div>
          )}
        </>
      )}

      {/* Markdown docs tab */}
      {state.activeKnowledgeTab === "docs" && (
        <div className="writing-card-list">
          {state.markdownDocs.map((doc) => (
            <div key={doc.doc_id} className="writing-card-item">
              <input type="checkbox" checked={selectedDocSet.has(doc.doc_id)} onChange={() => toggleDocSelection(doc.doc_id)} />
              <div>
                <strong>{doc.title}</strong>
                <small>{doc.library_type}/{doc.card_type} · {doc.status}</small>
              </div>
            </div>
          ))}
          {!state.markdownDocs.length && <p className="muted">无 Markdown 文档。</p>}
        </div>
      )}

      {/* Search result tab */}
      {state.activeKnowledgeTab === "result" && (
        <>
          <div className="writing-side-card">
            <div className="writing-side-card-head"><strong>RAG 搜索</strong></div>
            <input value={state.query} onChange={(e) => dispatch({ type: "SET_QUERY", query: e.target.value })} placeholder="搜索知识库" />
            <div className="mode-grid">
              <label>阶段 <select value={state.ragStage} onChange={(e) => dispatch({ type: "SET_RAG_STAGE", stage: e.target.value })}>
                {["outline", "draft", "worldbuilding_draft", "revision", "continuation"].map((s) => (<option key={s} value={s}>{s}</option>))}
              </select></label>
            </div>
            <button onClick={searchRAG} disabled={!selected || state.busy === "rag-search" || !state.query.trim() || positionMissing}>搜索</button>
          </div>
          {state.ragResults.length > 0 && (
            <div className="writing-card-list">
              {state.ragResults.map((r, i) => (
                <div key={i} className="writing-card-item">
                  <strong>[{r.card_type}] {r.title}</strong>
                  <small>score: {r.score.toFixed(3)}</small>
                  <p>{r.content_preview}</p>
                </div>
              ))}
            </div>
          )}
          {state.retrievalDebug && (
            <details className="writing-debug-details">
              <summary>检索 Debug</summary>
              <pre>{JSON.stringify(state.retrievalDebug, null, 2)}</pre>
            </details>
          )}
        </>
      )}
    </>
  );
}
