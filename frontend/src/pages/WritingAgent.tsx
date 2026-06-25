import { FormEvent, useEffect, useMemo, useReducer, useRef } from "react";
import {
  api, getWorkspaceId,
} from "../api";
import {
  getInitialState,
} from "../components/writing/types";
import { writingReducer } from "../components/writing/reducer";
import {
  chapterTitleKey, parseChapterTitleKey, defaultChapterTitle, readChapterTitles,
  writeChapterTitles, parseOutlineContent, resolveOptionalNumber,
  getOutlineScopePayload, isOutlinePositionMissing,
} from "../components/writing/utils";
import { useWritingData, useWritingOutline, useWritingDraft, useWritingWorkspace } from "../hooks/useWriting";
import { ErrorBoundary } from "../components/common/ErrorBoundary";
import { SkeletonPanel } from "../components/common/Skeleton";
import { LeftPanel } from "../components/writing/LeftPanel";
import { Editor } from "../components/writing/Editor";
import { OutlinePanel } from "../components/writing/OutlinePanel";
import { MemoryPanel } from "../components/writing/MemoryPanel";
import { WorldbuildingPanel } from "../components/writing/WorldbuildingPanel";
import { KnowledgePanel } from "../components/writing/KnowledgePanel";
import { Header } from "../components/writing/Header";

const KNOWLEDGE_GROUPS = [
  { key: "writing_guide", label: "写作技巧指南" },
  { key: "worldbuilding", label: "世界观设定" },
] as const;
function knowledgeTypeLabel(type: string) { return KNOWLEDGE_GROUPS.find((g) => g.key === type)?.label || type; }

export default function WritingAgent() {
  const workspaceId = useMemo(() => getWorkspaceId(), []);
  const [state, dispatch] = useReducer(writingReducer, null, getInitialState);
  const selectedIdRef = useRef<number | null>(null);
  const dataLoadSeqRef = useRef(0);
  const initialLoadDone = useRef(false);

  // Derived state
  const selected = useMemo(() => state.knowledgeBases.find((kb) => kb.id === state.selectedId) || null, [state.knowledgeBases, state.selectedId]);
  const selectedWorkSet = useMemo(() => new Set(state.selectedWorkIds), [state.selectedWorkIds]);
  const selectedVolumeSet = useMemo(() => new Set(state.selectedVolumeKeys), [state.selectedVolumeKeys]);
  const selectedChapterSet = useMemo(() => new Set(state.selectedChapterKeys), [state.selectedChapterKeys]);
  const selectedDocumentSet = useMemo(() => new Set(state.selectedDocumentIds), [state.selectedDocumentIds]);
  const selectedCardSet = useMemo(() => new Set(state.selectedCardIds), [state.selectedCardIds]);
  const selectedDocSet = useMemo(() => new Set(state.selectedDocIds), [state.selectedDocIds]);
  const selectedMemorySet = useMemo(() => new Set(state.selectedMemoryIds), [state.selectedMemoryIds]);
  const documentsByType = useMemo(() => state.documents.reduce<Record<string, typeof state.documents>>((g, d) => { const k = d.knowledge_type || "worldbuilding"; g[k] = [...(g[k] || []), d]; return g; }, { writing_guide: [], worldbuilding: [] }), [state.documents]);
  const writingModels = useMemo(() => state.config?.writing_models?.length ? state.config.writing_models : [{ id: state.config?.deepseek_model || "", label: state.config?.deepseek_model || "DeepSeek", provider: "deepseek", model: state.config?.deepseek_model || "", available: Boolean(state.config?.has_deepseek_api_key) }], [state.config]);
  const selectedWritingModel = useMemo(() => writingModels.find((m) => m.id === state.writingModelId) || writingModels[0] || null, [state.writingModelId, writingModels]);
  const currentPositionPayload = { current_volume_index: typeof state.currentVolumeIndex === "number" ? state.currentVolumeIndex : null, current_chapter_index: typeof state.currentChapterIndex === "number" ? state.currentChapterIndex : null };
  const positionMissing = !currentPositionPayload.current_volume_index || !currentPositionPayload.current_chapter_index;
  const outlineScopePositionMissing = isOutlinePositionMissing(state.outlineScope, currentPositionPayload.current_volume_index, currentPositionPayload.current_chapter_index);
  const parsedOutline = useMemo(() => parseOutlineContent(state.outline), [state.outline]);
  const resolvedRagTopK = resolveOptionalNumber(state.ragTopK, 8);
  const resolvedTargetChars = resolveOptionalNumber(state.targetChars, 3000);
  const draftWordCount = useMemo(() => state.draft.replace(/\s/g, "").length, [state.draft]);
  const activeDraftJob = Boolean(state.draftJob && !["completed", "failed", "cancelled"].includes(state.draftJob.status));
  const outlineScopeLabel = state.outlineScope === "global" ? "全书" : state.outlineScope === "volume" ? "全卷" : "章节";
  const modelCallBlocked = !state.dryRun && !state.writingApiKey.trim();
  const selectedWritingModelPayload = selectedWritingModel ? { model_provider: selectedWritingModel.provider, model: selectedWritingModel.model, api_key: state.writingApiKey.trim() || undefined } : {};
  const outlineScopePayload = getOutlineScopePayload(state.outlineScope, currentPositionPayload.current_volume_index, currentPositionPayload.current_chapter_index);
  const generationRetrievalPayload = { ...currentPositionPayload, include_raw_knowledge: state.debugRawKnowledge && state.dryRun };
  const ragRetrievalPayload = { ...currentPositionPayload, include_raw: state.debugRawKnowledge };
  const writingTaskPayload = state.outlineScope === "chapter" && state.chapterTitle.trim() ? state.chapterTitle.trim() + "\n\n" + state.outlineTask : state.outlineTask;
  const volumeTree = useMemo(() => {
    const groups = new Map<number, Map<number, { chapter: number; title: string; memoryCount: number }>>();
    const ensure = (v: number, c: number, t?: string) => { if (!groups.has(v)) groups.set(v, new Map()); const chs = groups.get(v)!; const k = selected ? chapterTitleKey(workspaceId, selected.id, v, c) : ""; const ex = chs.get(c); chs.set(c, { chapter: c, title: t || state.chapterTitles[k] || ex?.title || defaultChapterTitle(c), memoryCount: ex?.memoryCount || 0 }); };
    if (selected) { Object.entries(state.chapterTitles).forEach(([k, t]) => { const p = parseChapterTitleKey(k); if (p && p.workspaceId === workspaceId && p.workId === selected.id) ensure(p.volume, p.chapter, t || undefined); }); }
    if (selected && typeof state.currentVolumeIndex === "number" && typeof state.currentChapterIndex === "number") ensure(state.currentVolumeIndex, state.currentChapterIndex, state.chapterTitle || undefined);
    state.memories.forEach((m) => { const v = m.volume_index || 1; const c = m.chapter_index || 1; ensure(v, c, state.chapterTitles[selected ? chapterTitleKey(workspaceId, selected.id, v, c) : ""]); const chs = groups.get(v)!; const item = chs.get(c)!; chs.set(c, { ...item, memoryCount: item.memoryCount + 1 }); });
    if (!groups.size && selected) ensure(1, 1);
    return Array.from(groups.entries()).sort(([a],[b])=>a-b).map(([v,chs])=>({volume:v,chapters:Array.from(chs.values()).sort((a,b)=>a.chapter-b.chapter)}));
  }, [state.chapterTitle, state.chapterTitles, state.currentChapterIndex, state.currentVolumeIndex, state.memories, selected, workspaceId]);

  const isLoading = !initialLoadDone.current && !state.config;

  // Hooks
  const { load, chooseKnowledgeBase, refreshKnowledgeCards, reloadWorkIfStillActive } = useWritingData(dispatch, selectedIdRef, dataLoadSeqRef, state.expandedWorkIds, state.selectedDocumentIds);
  const { generateOutline, confirmOutline } = useWritingOutline(dispatch, selectedIdRef);
  const { applyDraftJob, startDraftJob, generateRevision, saveDraftToMemory, cancelDraftJob } = useWritingDraft(dispatch, selectedIdRef);
  const { createKnowledgeBase, deleteSelectedWorks, deleteCurrentChapter } = useWritingWorkspace(dispatch, selectedIdRef);

  useEffect(() => { load().then(() => { initialLoadDone.current = true; }).catch((err: unknown) => dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "加载失败" })); }, []);
  useEffect(() => { selectedIdRef.current = state.selectedId; }, [state.selectedId]);
  useEffect(() => { writeChapterTitles(state.chapterTitles); }, [state.chapterTitles]);
  useEffect(() => { if (!selected || !state.draftJob || ["completed","failed","cancelled"].includes(state.draftJob.status)) return; const wid = selected.id; const t = window.setTimeout(() => { api.getWorkDraftJob(wid, state.draftJob!.job_id).then((j) => applyDraftJob(j, wid)).catch(() => {}); }, 1200); return () => window.clearTimeout(t); }, [selected, state.draftJob]);

  function selectWritingPosition(volume: number, chapter: number) {
    const changed = currentPositionPayload.current_volume_index !== volume || currentPositionPayload.current_chapter_index !== chapter;
    dispatch({ type: "SET_CURRENT_VOLUME", index: volume }); dispatch({ type: "SET_CURRENT_CHAPTER", index: chapter });
    if (selected) { const k = chapterTitleKey(workspaceId, selected.id, volume, chapter); dispatch({ type: "SET_CHAPTER_TITLE", title: state.chapterTitles[k] || defaultChapterTitle(chapter) }); }
    if (changed) dispatch({ type: "CLEAR_TRANSIENT" });
  }
  function addChapter() { if (!selected) return; const v = typeof state.currentVolumeIndex === "number" ? state.currentVolumeIndex : 1; const cv = volumeTree.find((t) => t.volume === v); const nc = Math.max(typeof state.currentChapterIndex === "number" ? state.currentChapterIndex : 0, ...(cv?.chapters.map((c) => c.chapter) || [0])) + 1; selectWritingPosition(v, nc); }
  function addVolume() { if (!selected) return; const nv = Math.max(0, ...volumeTree.map((t) => t.volume), typeof state.currentVolumeIndex === "number" ? state.currentVolumeIndex : 0) + 1; selectWritingPosition(nv, 1); }

  async function handleGenerateOutline(e: FormEvent) { e.preventDefault(); if (!selected || !writingTaskPayload.trim()) return; if (outlineScopePositionMissing) { dispatch({ type: "SET_ERROR", error: "请先填写当前位置。" }); return; } await generateOutline(selected.id, writingTaskPayload, state.mode, state.knowledgeMode, selectedWritingModelPayload, state.dryRun, resolvedRagTopK, generationRetrievalPayload, outlineScopePayload); }
  async function handleConfirmOutline() { if (!selected || !state.outline.trim()) return; if (outlineScopePositionMissing) { dispatch({ type: "SET_ERROR", error: "请先填写当前位置。" }); return; } await confirmOutline(selected.id, state.outline, state.outlineScope, state.chapterTitle, outlineScopePayload, state.memories, refreshKnowledgeCards); }
  async function handleStartDraft() { if (!selected || !state.confirmedOutline.trim()) return; if (positionMissing) { dispatch({ type: "SET_ERROR", error: "请先填写当前位置。" }); return; } await startDraftJob(selected.id, writingTaskPayload, state.confirmedOutline, state.mode, state.knowledgeMode, selectedWritingModelPayload, state.dryRun, resolvedRagTopK, resolvedTargetChars, generationRetrievalPayload); }
  async function handleRevision() { if (!selected || !state.draft.trim()) return; if (positionMissing) { dispatch({ type: "SET_ERROR", error: "请先填写当前位置。" }); return; } await generateRevision(selected.id, writingTaskPayload, state.confirmedOutline, state.draft, state.mode, state.knowledgeMode, selectedWritingModelPayload, state.dryRun, resolvedRagTopK, state.actualChars, resolvedTargetChars, generationRetrievalPayload); }
  async function handleSaveDraft() { if (!selected || !state.draft.trim()) return; if (positionMissing) { dispatch({ type: "SET_ERROR", error: "请先填写当前位置。" }); return; } await saveDraftToMemory(selected.id, state.draft, state.chapterTitle, currentPositionPayload); }
  async function handleCancelJob() { if (!selected || !state.draftJob) return; await cancelDraftJob(selected.id, state.draftJob); }
  async function handleCreateKB(e: FormEvent) { e.preventDefault(); await createKnowledgeBase(state.name, state.description, state.knowledgeBases.length, load); }
  async function handleDeleteWorks() { await deleteSelectedWorks(state.selectedWorkIds, state.knowledgeBases, state.selectedId, load); }
  async function handleDeleteChapter() { if (!selected || typeof state.currentVolumeIndex !== "number" || typeof state.currentChapterIndex !== "number") return; await deleteCurrentChapter(selected.id, state.currentVolumeIndex, state.currentChapterIndex, load); }

  return (
    <ErrorBoundary>
      <section className="writing-agent-platform">
        <Header state={state} dispatch={dispatch} selected={selected} writingModels={writingModels} selectedWritingModel={selectedWritingModel} positionMissing={positionMissing} workspaceId={workspaceId} />
        {(state.config || state.error || state.message) && (
          <div className="writing-agent-status-strip">
            {state.config && <span>{state.config.privacy_note} API Key 只用于本次请求。</span>}
            <span>工作区：{workspaceId}</span>
            {state.message && <strong>{state.message}</strong>}
            {state.error && <strong className="is-error">{state.error}</strong>}
          </div>
        )}
        {isLoading ? (
          <div className="writing-agent-shell" style={{ padding: 24 }}><SkeletonPanel /></div>
        ) : (
          <div className="writing-agent-shell">
            <LeftPanel state={state} dispatch={dispatch} selected={selected} workspaceId={workspaceId} volumeTree={volumeTree} currentPositionPayload={currentPositionPayload} selectedWorkSet={selectedWorkSet} selectedVolumeSet={selectedVolumeSet} selectedChapterSet={selectedChapterSet} createKnowledgeBase={handleCreateKB} chooseKnowledgeBase={chooseKnowledgeBase} selectWritingPosition={selectWritingPosition} addVolume={addVolume} addChapter={addChapter} deleteSelectedWorks={handleDeleteWorks} reloadWorkIfStillActive={reloadWorkIfStillActive} load={load} />
            <div className="writing-agent-resizer" onPointerDown={(e) => { e.preventDefault(); const sx = e.clientX; const sw = state.leftPanelWidth; const move = (me: PointerEvent) => dispatch({ type: "SET_LEFT_PANEL_WIDTH", width: Math.min(500, Math.max(220, sw + me.clientX - sx)) }); const stop = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", stop); document.body.style.cursor = ""; document.body.style.userSelect = ""; }; document.body.style.cursor = "col-resize"; document.body.style.userSelect = "none"; window.addEventListener("pointermove", move); window.addEventListener("pointerup", stop); }} />
            <Editor state={state} dispatch={dispatch} selected={selected} positionMissing={positionMissing} activeDraftJob={activeDraftJob} draftWordCount={draftWordCount} modelCallBlocked={modelCallBlocked} startDraftJob={handleStartDraft} generateRevision={handleRevision} cancelDraftJob={handleCancelJob} saveDraftToMemory={handleSaveDraft} deleteCurrentChapter={handleDeleteChapter} />
            <div className="writing-agent-resizer" onPointerDown={(e) => { e.preventDefault(); const sx = e.clientX; const sw = state.rightPanelWidth; const move = (me: PointerEvent) => dispatch({ type: "SET_RIGHT_PANEL_WIDTH", width: Math.min(520, Math.max(260, sw - (me.clientX - sx))) }); const stop = () => { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", stop); document.body.style.cursor = ""; document.body.style.userSelect = ""; }; document.body.style.cursor = "col-resize"; document.body.style.userSelect = "none"; window.addEventListener("pointermove", move); window.addEventListener("pointerup", stop); }} />
            <aside className="writing-agent-right-panel" style={{ width: state.rightPanelWidth }}>
              <div className="writing-assistant-tabs">
                <button className={state.assistantTab === "outline" ? "active" : ""} onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "outline" })}>大纲</button>
                <button className={state.assistantTab === "memory" ? "active" : ""} onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "memory" })}>人设</button>
                <button className={state.assistantTab === "worldbuilding" ? "active" : ""} onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "worldbuilding" })}>设定</button>
                <button className={state.assistantTab === "resources" ? "active" : ""} onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "resources" })}>拆卡</button>
              </div>
              <div className="writing-assistant-content">
                {state.assistantTab === "outline" && (<OutlinePanel state={state} dispatch={dispatch} selected={selected} writingModels={writingModels} selectedWritingModel={selectedWritingModel} selectedWritingModelPayload={selectedWritingModelPayload} writingTaskPayload={writingTaskPayload} parsedOutline={parsedOutline} resolvedRagTopK={resolvedRagTopK} resolvedTargetChars={resolvedTargetChars} generationRetrievalPayload={generationRetrievalPayload} outlineScopePayload={outlineScopePayload} outlineScopeLabel={outlineScopeLabel} outlineScopePositionMissing={outlineScopePositionMissing} modelCallBlocked={modelCallBlocked} generateOutline={handleGenerateOutline} confirmOutline={handleConfirmOutline} startDraftJob={handleStartDraft} />)}
                {state.assistantTab === "memory" && (<MemoryPanel state={state} dispatch={dispatch} selected={selected} currentPositionPayload={currentPositionPayload} refreshKnowledgeCards={refreshKnowledgeCards} />)}
                {state.assistantTab === "worldbuilding" && (<WorldbuildingPanel state={state} dispatch={dispatch} selected={selected} selectedWritingModelPayload={selectedWritingModelPayload} reloadWorkIfStillActive={reloadWorkIfStillActive} />)}
                {state.assistantTab === "resources" && (<KnowledgePanel state={state} dispatch={dispatch} selected={selected} documentsByType={documentsByType} selectedDocumentSet={selectedDocumentSet} selectedCardSet={selectedCardSet} selectedDocSet={selectedDocSet} selectedMemorySet={selectedMemorySet} refreshKnowledgeCards={refreshKnowledgeCards} reloadWorkIfStillActive={reloadWorkIfStillActive} load={load} ragRetrievalPayload={ragRetrievalPayload} resolvedRagTopK={resolvedRagTopK} positionMissing={positionMissing} workspaceId={workspaceId} uploadType={state.uploadType} packagePath={state.packagePath} markdownSourcePath={state.markdownSourcePath} knowledgeTypeLabel={knowledgeTypeLabel} />)}
              </div>
            </aside>
          </div>
        )}
      </section>
    </ErrorBoundary>
  );
}
