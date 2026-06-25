import { useCallback, useRef } from "react";
import { api, WritingDraftJob } from "../api";
import { WritingAction } from "../components/writing/types";

/**
 * Hook: 作品数据加载（列表、详情、刷新）。
 * 提取自 WritingAgent.tsx 的 load / chooseKnowledgeBase / refreshKnowledgeCards 等函数。
 */
export function useWritingData(
  dispatch: React.Dispatch<WritingAction>,
  selectedIdRef: React.MutableRefObject<number | null>,
  dataLoadSeqRef: React.MutableRefObject<number>,
  expandedWorkIds: number[],
  selectedDocumentIds: number[],
) {
  const load = useCallback(async (nextSelectedId?: number | null) => {
    const seq = ++dataLoadSeqRef.current;
    const [nc, nb] = await Promise.all([api.getPublicConfig(), api.listKnowledgeBases()]);
    if (seq !== dataLoadSeqRef.current) return;
    dispatch({ type: "SET_CONFIG", config: nc });
    const opts = nc.writing_models || [];
    dispatch({ type: "SET_WRITING_MODEL_ID", id: opts[0]?.id || nc.deepseek_model });
    dispatch({ type: "SET_KNOWLEDGE_BASES", bases: nb });
    let pref = nextSelectedId ?? nb[0]?.id ?? null;
    if (pref && !nb.some((kb) => kb.id === pref)) pref = nb[0]?.id ?? null;
    selectedIdRef.current = pref;
    dispatch({ type: "SET_SELECTED_ID", id: pref });
    if (pref) {
      dispatch({ type: "SET_EXPANDED_WORK_IDS", ids: expandedWorkIds.includes(pref) ? expandedWorkIds : [...expandedWorkIds, pref] });
      const [nd, nm, nc2, nmd, ns] = await Promise.all([
        api.listKnowledgeDocuments(pref), api.listWritingMemories(pref),
        api.listKnowledgeCards(pref), api.listKnowledgeMarkdownDocs(pref),
        api.getKnowledgeMergeStats(pref),
      ]);
      if (seq !== dataLoadSeqRef.current || selectedIdRef.current !== pref) return;
      dispatch({ type: "SET_DOCUMENTS", documents: nd });
      dispatch({ type: "SET_MEMORIES", memories: nm });
      dispatch({ type: "SET_CARDS", cards: nc2 });
      dispatch({ type: "SET_MARKDOWN_DOCS", docs: nmd });
      dispatch({ type: "SET_MERGE_STATS", stats: ns });
      dispatch({ type: "SET_MERGE_GROUPS", groups: [] });
      dispatch({ type: "SET_SELECTED_DOCUMENT_IDS", ids: selectedDocumentIds.filter((id) => nd.some((d) => d.id === id)) });
    } else {
      dispatch({ type: "SET_DOCUMENTS", documents: [] });
      dispatch({ type: "SET_MEMORIES", memories: [] });
      dispatch({ type: "SET_CARDS", cards: [] });
      dispatch({ type: "SET_MARKDOWN_DOCS", docs: [] });
      dispatch({ type: "SET_MERGE_STATS", stats: null });
      dispatch({ type: "SET_MERGE_GROUPS", groups: [] });
      dispatch({ type: "SET_SELECTED_DOCUMENT_IDS", ids: [] });
    }
  }, [dispatch, selectedIdRef, dataLoadSeqRef, expandedWorkIds, selectedDocumentIds]);

  const chooseKnowledgeBase = useCallback(async (id: number) => {
    const seq = ++dataLoadSeqRef.current;
    selectedIdRef.current = id;
    dispatch({ type: "SET_SELECTED_ID", id });
    dispatch({ type: "SET_SELECTED_DOCUMENT_IDS", ids: [] });
    dispatch({ type: "SET_EXPANDED_WORK_IDS", ids: expandedWorkIds.includes(id) ? expandedWorkIds : [...expandedWorkIds, id] });
    dispatch({ type: "SET_ERROR", error: "" });
    const [nd, nm, nc2, nmd, ns] = await Promise.all([
      api.listKnowledgeDocuments(id), api.listWritingMemories(id),
      api.listKnowledgeCards(id), api.listKnowledgeMarkdownDocs(id),
      api.getKnowledgeMergeStats(id),
    ]);
    if (seq !== dataLoadSeqRef.current || selectedIdRef.current !== id) return;
    dispatch({ type: "SET_DOCUMENTS", documents: nd });
    dispatch({ type: "SET_MEMORIES", memories: nm });
    dispatch({ type: "SET_CARDS", cards: nc2 });
    dispatch({ type: "SET_MARKDOWN_DOCS", docs: nmd });
    dispatch({ type: "SET_MERGE_STATS", stats: ns });
    dispatch({ type: "SET_MERGE_GROUPS", groups: [] });
  }, [dispatch, selectedIdRef, dataLoadSeqRef, expandedWorkIds]);

  const refreshKnowledgeCards = useCallback(async (workId?: number) => {
    if (!workId) return;
    const [nc2, nmd, ns] = await Promise.all([
      api.listKnowledgeCards(workId), api.listKnowledgeMarkdownDocs(workId),
      api.getKnowledgeMergeStats(workId),
    ]);
    if (selectedIdRef.current !== workId) return;
    dispatch({ type: "SET_CARDS", cards: nc2 });
    dispatch({ type: "SET_MARKDOWN_DOCS", docs: nmd });
    dispatch({ type: "SET_MERGE_STATS", stats: ns });
  }, [dispatch, selectedIdRef]);

  const reloadWorkIfStillActive = useCallback(async (workId: number) => {
    if (selectedIdRef.current === workId) await load(workId);
  }, [load, selectedIdRef]);

  return { load, chooseKnowledgeBase, refreshKnowledgeCards, reloadWorkIfStillActive };
}

/**
 * Hook: 提纲生成与确认。
 */
export function useWritingOutline(
  dispatch: React.Dispatch<WritingAction>,
  selectedIdRef: React.MutableRefObject<number | null>,
) {
  const generateOutline = useCallback(async (
    workId: number, task: string, mode: string, knowledgeMode: string,
    modelPayload: Record<string, unknown>, dryRun: boolean, topK: number,
    retrievalPayload: Record<string, unknown>, scopePayload: Record<string, unknown>,
  ) => {
    dispatch({ type: "SET_BUSY", busy: "outline" });
    dispatch({ type: "SET_OUTLINE", outline: "" });
    dispatch({ type: "SET_CONFIRMED_OUTLINE", outline: "" });
    try {
      const r = await api.generateWorkOutline(workId, {
        task, mode, knowledge_mode: knowledgeMode, ...modelPayload,
        dry_run: dryRun, top_k: topK, ...retrievalPayload, ...scopePayload,
      });
      if (selectedIdRef.current === workId) {
        dispatch({ type: "SET_OUTLINE", outline: r.content });
        dispatch({ type: "SET_USED_KNOWLEDGE", knowledge: r.used_knowledge || [] });
        dispatch({ type: "SET_RETRIEVAL_DEBUG", debug: r.retrieval_debug || null });
        dispatch({ type: "SET_PROMPT_PREVIEW", preview: r.prompt_preview || "" });
      }
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "生成提纲失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef]);

  const confirmOutline = useCallback(async (
    workId: number, outline: string, scope: string, chapterTitle: string,
    scopePayload: Record<string, unknown>, memories: WritingMemory[],
    refreshCards: (id?: number) => Promise<void>,
  ) => {
    dispatch({ type: "SET_BUSY", busy: "confirm-outline" });
    try {
      const label = scope === "chapter" ? (chapterTitle || "已确认提纲") : (scope === "volume" ? "全卷" : "全书");
      const saved = await api.confirmOutlineMemory(workId, {
        title: `${label} · 提纲`, content: outline, tags: ["outline"], ...scopePayload,
      });
      // 成功后才设置 confirmedOutline，防止 API 失败时状态不一致
      dispatch({ type: "SET_CONFIRMED_OUTLINE", outline: outline });
      dispatch({ type: "SET_MEMORIES", memories: [saved, ...memories] });
      dispatch({ type: "SET_MESSAGE", message: "提纲已确认。" });
      // 刷新知识卡独立处理，不阻塞确认结果
      try { await refreshCards(workId); } catch { /* 知识卡刷新失败不影响确认 */ }
    } catch (err) {
      // API 失败时不清除任何已设置的状态，但也不会设置 confirmedOutline
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "确认提纲失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef]);

  return { generateOutline, confirmOutline };
}

/**
 * Hook: 正文草稿生成、润色、保存。
 */
export function useWritingDraft(
  dispatch: React.Dispatch<WritingAction>,
  selectedIdRef: React.MutableRefObject<number | null>,
) {
  const applyDraftJob = useCallback((job: WritingDraftJob, expectedWorkId = job.work_id) => {
    if (job.work_id !== expectedWorkId || selectedIdRef.current !== expectedWorkId) return;
    dispatch({ type: "SET_DRAFT_JOB", job });
    dispatch({ type: "SET_DRAFT", draft: job.content || "" });
    dispatch({ type: "SET_USED_KNOWLEDGE", knowledge: job.used_knowledge || [] });
    dispatch({ type: "SET_RETRIEVAL_DEBUG", debug: job.retrieval_debug || null });
    dispatch({ type: "SET_ACTUAL_CHARS", chars: job.actual_chars ?? null });
    dispatch({ type: "SET_LONG_SECTIONS", sections: job.sections || [] });
    dispatch({ type: "SET_GENERATION_WARNINGS", warnings: job.warnings || [] });
    if (job.status === "failed" && job.error_message) dispatch({ type: "SET_ERROR", error: job.error_message });
  }, [dispatch, selectedIdRef]);

  const startDraftJob = useCallback(async (
    workId: number, task: string, confirmedOutline: string, mode: string,
    knowledgeMode: string, modelPayload: Record<string, unknown>,
    dryRun: boolean, topK: number, targetChars: number,
    retrievalPayload: Record<string, unknown>,
  ) => {
    dispatch({ type: "SET_BUSY", busy: "draft-job" });
    dispatch({ type: "SET_DRAFT_JOB", job: null });
    dispatch({ type: "SET_DRAFT", draft: "" });
    try {
      const job = await api.createWorkDraftJob(workId, {
        task, confirmed_outline: confirmedOutline, mode, knowledge_mode: knowledgeMode,
        ...modelPayload, dry_run: dryRun, top_k: topK,
        target_chars: targetChars, ...retrievalPayload,
      });
      const { storeDraftJobRef } = await import("../components/writing/utils");
      storeDraftJobRef(workId, job.job_id);
      applyDraftJob(job);
      dispatch({ type: "SET_ACTIVE_KNOWLEDGE_TAB", tab: "result" });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "创建正文任务失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef, applyDraftJob]);

  const generateRevision = useCallback(async (
    workId: number, task: string, confirmedOutline: string, currentDraft: string,
    mode: string, knowledgeMode: string, modelPayload: Record<string, unknown>,
    dryRun: boolean, topK: number, actualChars: number | null, targetChars: number,
    retrievalPayload: Record<string, unknown>,
  ) => {
    dispatch({ type: "SET_BUSY", busy: "revision" });
    try {
      const r = await api.generateWorkRevision(workId, {
        task, confirmed_outline: confirmedOutline, current_content: currentDraft,
        mode, knowledge_mode: knowledgeMode, ...modelPayload,
        dry_run: dryRun, top_k: topK,
        target_chars: actualChars || targetChars, ...retrievalPayload,
      });
      if (selectedIdRef.current === workId) {
        dispatch({ type: "SET_DRAFT", draft: r.content });
        dispatch({ type: "SET_USED_KNOWLEDGE", knowledge: r.used_knowledge || [] });
      }
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "润色失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef]);

  const saveDraftToMemory = useCallback(async (
    workId: number, draft: string, chapterTitle: string,
    positionPayload: { current_volume_index: number | null; current_chapter_index: number | null },
  ) => {
    dispatch({ type: "SET_BUSY", busy: "memory" });
    try {
      const saved = await api.confirmDraftMemory(workId, {
        title: `${chapterTitle || "正文片段"} · 正文`, content: draft, tags: ["draft"],
        scope_level: "chapter", volume_index: positionPayload.current_volume_index,
        chapter_index: positionPayload.current_chapter_index,
      });
      const next = await api.listWritingMemories(workId);
      if (!next.some((m) => m.id === saved.id)) next.unshift(saved);
      dispatch({ type: "SET_MEMORIES", memories: next as any });
      dispatch({ type: "SET_MESSAGE", message: "正文已保存。" });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "保存失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef]);

  const cancelDraftJob = useCallback(async (
    workId: number, draftJob: WritingDraftJob,
  ) => {
    dispatch({ type: "SET_BUSY", busy: "draft-job-cancel" });
    try {
      const job = await api.cancelWorkDraftJob(workId, draftJob.job_id);
      applyDraftJob(job, workId);
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "取消失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef, applyDraftJob]);

  return { applyDraftJob, startDraftJob, generateRevision, saveDraftToMemory, cancelDraftJob };
}

/**
 * Hook: 作品空间管理（创建、删除）。
 */
export function useWritingWorkspace(
  dispatch: React.Dispatch<WritingAction>,
  selectedIdRef: React.MutableRefObject<number | null>,
) {
  const createKnowledgeBase = useCallback(async (
    name: string, description: string, kbCount: number,
    load: (id?: number | null) => Promise<void>,
  ) => {
    dispatch({ type: "SET_BUSY", busy: "create" });
    try {
      const kb = await api.createKnowledgeBase({ name, description });
      dispatch({ type: "SET_MESSAGE", message: "作品已创建" });
      dispatch({ type: "SET_NAME", name: `作品 ${kbCount + 2}` });
      await load(kb.id);
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "创建作品失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef]);

  const deleteSelectedWorks = useCallback(async (
    selectedWorkIds: number[], knowledgeBases: { id: number }[],
    currentSelectedId: number | null,
    load: (id?: number | null) => Promise<void>,
  ) => {
    const ids = selectedWorkIds.filter((id) => knowledgeBases.some((w) => w.id === id));
    if (!ids.length) return;
    if (!window.confirm(`确定彻底删除选中的 ${ids.length} 个作品吗？`)) return;
    dispatch({ type: "SET_BUSY", busy: "delete-works" });
    try {
      const r = await api.bulkDeleteKnowledgeBases(ids);
      dispatch({ type: "SET_SELECTED_WORK_IDS", ids: [] });
      await load(currentSelectedId && !ids.includes(currentSelectedId) ? currentSelectedId : null);
      dispatch({ type: "SET_MESSAGE", message: r.message });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "删除失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef]);

  const deleteCurrentChapter = useCallback(async (
    workId: number, volumeIndex: number, chapterIndex: number,
    load: (id?: number | null) => Promise<void>,
  ) => {
    if (!window.confirm(`确定彻底删除当前第 ${volumeIndex} 卷第 ${chapterIndex} 章吗？`)) return;
    dispatch({ type: "SET_BUSY", busy: "delete-current-chapter" });
    try {
      await api.bulkDeleteWritingScope(workId, { chapters: [{ volume_index: volumeIndex, chapter_index: chapterIndex }] });
      await load(workId);
      dispatch({ type: "SET_CURRENT_CHAPTER", index: 1 });
      dispatch({ type: "CLEAR_TRANSIENT" });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "删除失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  }, [dispatch, selectedIdRef]);

  return { createKnowledgeBase, deleteSelectedWorks, deleteCurrentChapter };
}
