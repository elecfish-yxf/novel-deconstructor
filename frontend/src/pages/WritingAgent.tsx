import { ChangeEvent, FormEvent, PointerEvent, useEffect, useMemo, useState } from "react";
import {
  api,
  getWorkspaceId,
  Job,
  KnowledgeBase,
  KnowledgeCard,
  KnowledgeDocument,
  KnowledgeImportResult,
  KnowledgeMergeGroup,
  KnowledgeMergeStats,
  KnowledgeMarkdownDoc,
  LongGenerationSection,
  PublicConfig,
  RAGSearchResult,
  RetrievalDebug,
  RetrievalHit,
  UsedKnowledge,
  WritingDraftJob,
  WritingMemory,
} from "../api";

const DRAFT_JOB_KEY = "novel-deconstructor.last-draft-job";

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

type PositionValue = number | "";

function parsePositionInput(value: string): PositionValue {
  if (value.trim() === "") return "";
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return "";
  return Math.floor(parsed);
}

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

function compactSourceRef(sourceRef: Record<string, unknown>) {
  const entries = Object.entries(sourceRef || {});
  if (!entries.length) return "";
  return entries
    .slice(0, 3)
    .map(([key, value]) => `${key}: ${typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}`)
    .join(" · ");
}

function storeDraftJobRef(workId: number, jobId: string) {
  window.localStorage.setItem(DRAFT_JOB_KEY, JSON.stringify({ workId, jobId }));
}

function readDraftJobRef(): { workId: number; jobId: string } | null {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DRAFT_JOB_KEY) || "null");
    return typeof parsed?.workId === "number" && typeof parsed?.jobId === "string" ? parsed : null;
  } catch {
    return null;
  }
}

export default function WritingAgent({ job }: { job?: Job | null }) {
  const [config, setConfig] = useState<PublicConfig | null>(null);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBase[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [documents, setDocuments] = useState<KnowledgeDocument[]>([]);
  const [cards, setCards] = useState<KnowledgeCard[]>([]);
  const [markdownDocs, setMarkdownDocs] = useState<KnowledgeMarkdownDoc[]>([]);
  const [mergeStats, setMergeStats] = useState<KnowledgeMergeStats | null>(null);
  const [mergeGroups, setMergeGroups] = useState<KnowledgeMergeGroup[]>([]);
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
  const [ragStage, setRagStage] = useState("draft");
  const [ragTopK, setRagTopK] = useState(8);
  const [currentVolumeIndex, setCurrentVolumeIndex] = useState<PositionValue>(1);
  const [currentChapterIndex, setCurrentChapterIndex] = useState<PositionValue>(1);
  const [debugRawKnowledge, setDebugRawKnowledge] = useState(false);
  const [ragResults, setRagResults] = useState<RAGSearchResult[]>([]);
  const [retrievalDebug, setRetrievalDebug] = useState<RetrievalDebug | null>(null);
  const [usedKnowledge, setUsedKnowledge] = useState<UsedKnowledge[]>([]);
  const [promptPreview, setPromptPreview] = useState("");
  const [packagePath, setPackagePath] = useState("");
  const [markdownSourcePath, setMarkdownSourcePath] = useState("");
  const [activeKnowledgeTab, setActiveKnowledgeTab] = useState<"cards" | "docs" | "result">("cards");
  const [cardTypeFilter, setCardTypeFilter] = useState("all");
  const [showRawCards, setShowRawCards] = useState(false);
  const [selectedCardId, setSelectedCardId] = useState("");
  const [selectedDocId, setSelectedDocId] = useState("");
  const [markdownContent, setMarkdownContent] = useState("");
  const [uploadType, setUploadType] = useState("writing_guide");
  const [storySeed, setStorySeed] = useState("一个普通人在高压规则世界中寻找自我选择权。");
  const [worldbuildingDraft, setWorldbuildingDraft] = useState("");
  const [outlineTask, setOutlineTask] = useState("请基于世界观设定，结合写作技巧指南，为我生成一份原创小说第一章章节提纲。");
  const [outlineContext, setOutlineContext] = useState("");
  const [outline, setOutline] = useState("");
  const [confirmedOutline, setConfirmedOutline] = useState("");
  const [draft, setDraft] = useState("");
  const [targetChars, setTargetChars] = useState(3000);
  const [actualChars, setActualChars] = useState<number | null>(null);
  const [longSections, setLongSections] = useState<LongGenerationSection[]>([]);
  const [generationWarnings, setGenerationWarnings] = useState<string[]>([]);
  const [draftJob, setDraftJob] = useState<WritingDraftJob | null>(null);
  const [memoryType, setMemoryType] = useState("note");
  const [memoryTitle, setMemoryTitle] = useState("");
  const [memoryContent, setMemoryContent] = useState("");
  const [mode, setMode] = useState("fast");
  const [knowledgeMode, setKnowledgeMode] = useState("reference");
  const [dryRun, setDryRun] = useState(true);
  const [writingModelId, setWritingModelId] = useState("");
  const [writingApiKey, setWritingApiKey] = useState("");
  const [citations, setCitations] = useState<RetrievalHit[]>([]);
  const [mainNavTab, setMainNavTab] = useState<"memory" | "writing_guide" | "worldbuilding" | "history">("memory");
  const [assistantTab, setAssistantTab] = useState<"outline" | "memory" | "worldbuilding" | "resources">("outline");
  const [leftPanelWidth, setLeftPanelWidth] = useState(276);
  const [rightPanelWidth, setRightPanelWidth] = useState(340);
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
  const cardFilterGroups = useMemo(() => {
    const visibleCards = showRawCards ? cards : cards.filter((card) => card.is_canonical);
    const grouped = visibleCards.reduce<Record<string, { key: string; label: string; count: number }>>((acc, card) => {
      const key = `${card.library_type}/${card.card_type}`;
      if (!acc[key]) {
        acc[key] = { key, label: key, count: 0 };
      }
      acc[key].count += 1;
      return acc;
    }, {});
    return [{ key: "all", label: showRawCards ? "全部" : "Canonical", count: visibleCards.length }, ...Object.values(grouped).sort((a, b) => a.label.localeCompare(b.label))];
  }, [cards, showRawCards]);
  const filteredCards = useMemo(() => {
    const visibleCards = showRawCards ? cards : cards.filter((card) => card.is_canonical);
    if (cardTypeFilter === "all") return visibleCards;
    return visibleCards.filter((card) => `${card.library_type}/${card.card_type}` === cardTypeFilter);
  }, [cards, cardTypeFilter, showRawCards]);
  const writingModels = useMemo(() => {
    if (config?.writing_models?.length) return config.writing_models;
    return [
      {
        id: config?.deepseek_model || "deepseek-v4-pro",
        label: config?.deepseek_model || "DeepSeek",
        provider: "deepseek",
        model: config?.deepseek_model || "deepseek-v4-pro",
        available: Boolean(config?.has_deepseek_api_key),
      },
    ];
  }, [config]);
  const selectedWritingModel = useMemo(() => {
    return writingModels.find((item) => item.id === writingModelId) || writingModels[0] || null;
  }, [writingModelId, writingModels]);
  const selectedWritingModelPayload = selectedWritingModel
    ? { model_provider: selectedWritingModel.provider, model: selectedWritingModel.model, api_key: writingApiKey.trim() || undefined }
    : {};
  const currentPositionPayload = {
    current_volume_index: typeof currentVolumeIndex === "number" ? currentVolumeIndex : null,
    current_chapter_index: typeof currentChapterIndex === "number" ? currentChapterIndex : null,
  };
  const generationRetrievalPayload = {
    ...currentPositionPayload,
    include_raw_knowledge: debugRawKnowledge && dryRun,
  };
  const ragRetrievalPayload = {
    ...currentPositionPayload,
    include_raw: debugRawKnowledge,
  };
  const modelCallBlocked = !dryRun && !writingApiKey.trim();
  const positionMissing = !currentPositionPayload.current_volume_index || !currentPositionPayload.current_chapter_index;
  const draftWordCount = useMemo(() => draft.replace(/\s/g, "").length, [draft]);
  const activeDraftJob = Boolean(draftJob && !["completed", "failed", "cancelled"].includes(draftJob.status));

  function clearTransientWritingState() {
    setHits([]);
    setRagResults([]);
    setRetrievalDebug(null);
    setUsedKnowledge([]);
    setPromptPreview("");
    setCitations([]);
    setWorldbuildingDraft("");
    setOutline("");
    setConfirmedOutline("");
    setDraft("");
    setActualChars(null);
    setLongSections([]);
    setGenerationWarnings([]);
    setDraftJob(null);
  }

  async function load(nextSelectedId?: number | null) {
    const [nextConfig, nextBases] = await Promise.all([api.getPublicConfig(), api.listKnowledgeBases()]);
    setConfig(nextConfig);
    setWritingModelId((current) => {
      const options = nextConfig.writing_models || [];
      if (current && options.some((item) => item.id === current)) return current;
      return nextConfig.default_writing_model || options[0]?.id || nextConfig.deepseek_model;
    });
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
      const [nextDocuments, nextMemories, nextCards, nextDocs, nextStats] = await Promise.all([
        api.listKnowledgeDocuments(preferred),
        api.listWritingMemories(preferred),
        api.listKnowledgeCards(preferred),
        api.listKnowledgeMarkdownDocs(preferred),
        api.getKnowledgeMergeStats(preferred),
      ]);
      setDocuments(nextDocuments);
      setMemories(nextMemories);
      setCards(nextCards);
      setMarkdownDocs(nextDocs);
      setMergeStats(nextStats);
      setMergeGroups([]);
      setSelectedDocumentIds((items) => items.filter((id) => nextDocuments.some((document) => document.id === id)));
    } else {
      setDocuments([]);
      setMemories([]);
      setCards([]);
      setMarkdownDocs([]);
      setMergeStats(null);
      setMergeGroups([]);
      setSelectedDocumentIds([]);
    }
  }

  useEffect(() => {
    load().catch((err) => setError(err instanceof Error ? err.message : "加载写作 Agent 失败"));
  }, []);

  function applyDraftJob(job: WritingDraftJob) {
    setDraftJob(job);
    setDraft(job.content || "");
    setUsedKnowledge(job.used_knowledge || []);
    setRetrievalDebug(job.retrieval_debug || null);
    setActualChars(job.actual_chars ?? null);
    setLongSections(job.sections || []);
    setGenerationWarnings(job.warnings || []);
    if (job.status === "failed" && job.error_message) setError(job.error_message);
  }

  useEffect(() => {
    if (!selected || !draftJob || ["completed", "failed", "cancelled"].includes(draftJob.status)) return;
    const timer = window.setTimeout(() => {
      api
        .getWorkDraftJob(selected.id, draftJob.job_id)
        .then(applyDraftJob)
        .catch((err) => setError(err instanceof Error ? err.message : "查询长文本任务失败"));
    }, 1200);
    return () => window.clearTimeout(timer);
  }, [selected, draftJob]);

  useEffect(() => {
    if (!selected || draftJob) return;
    const ref = readDraftJobRef();
    if (!ref || ref.workId !== selected.id) return;
    api.getWorkDraftJob(selected.id, ref.jobId).then(applyDraftJob).catch(() => undefined);
  }, [selected, draftJob]);

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
    const [nextDocuments, nextMemories, nextCards, nextDocs, nextStats] = await Promise.all([
      api.listKnowledgeDocuments(id),
      api.listWritingMemories(id),
      api.listKnowledgeCards(id),
      api.listKnowledgeMarkdownDocs(id),
      api.getKnowledgeMergeStats(id),
    ]);
    setDocuments(nextDocuments);
    setMemories(nextMemories);
    setCards(nextCards);
    setMarkdownDocs(nextDocs);
    setMergeStats(nextStats);
    setMergeGroups([]);
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

  async function uploadFilesTo(event: ChangeEvent<HTMLInputElement>, knowledgeType = uploadType) {
    const files = event.target.files;
    if (!selected || !files?.length) return;
    setBusy("upload");
    setError("");
    setMessage("");
    try {
      const result = await api.uploadKnowledgeDocumentsAs(selected.id, files, knowledgeType);
      setMessage(`${knowledgeTypeLabel(knowledgeType)}已上传：${result.message}`);
      await load(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传作品文件失败");
    } finally {
      event.target.value = "";
      setBusy("");
    }
  }

  async function uploadFiles(event: ChangeEvent<HTMLInputElement>) {
    await uploadFilesTo(event, uploadType);
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

  async function refreshKnowledgeCards(workId = selected?.id) {
    if (!workId) return;
    const [nextCards, nextDocs, nextStats] = await Promise.all([api.listKnowledgeCards(workId), api.listKnowledgeMarkdownDocs(workId), api.getKnowledgeMergeStats(workId)]);
    setCards(nextCards);
    setMarkdownDocs(nextDocs);
    setMergeStats(nextStats);
  }

  async function importKnowledgePackage() {
    if (!selected || !packagePath.trim()) return;
    setBusy("import-package");
    setError("");
    setMessage("");
    try {
      const result = await api.importKnowledgePackage(selected.id, {
        package_path: packagePath,
        library_type: uploadType,
        status: "approved",
        merge_mode: "safe",
        markdown_scope: "canonical_only",
      });
      setMessage(result.message);
      await refreshKnowledgeCards(selected.id);
      setActiveKnowledgeTab("cards");
    } catch (err) {
      setError(err instanceof Error ? err.message : "导入知识包失败");
    } finally {
      setBusy("");
    }
  }

  function summarizeImportResults(results: KnowledgeImportResult[]) {
    const imported = results.reduce((total, item) => total + item.imported_count, 0);
    const generated = results.reduce((total, item) => total + item.generated_markdown_count, 0);
    const skipped = results.reduce((total, item) => total + item.skipped_count, 0);
    const typeTotals = results.reduce<Record<string, number>>((acc, item) => {
      Object.entries(item.card_types || {}).forEach(([type, count]) => {
        acc[type] = (acc[type] || 0) + count;
      });
      return acc;
    }, {});
    const typeText = Object.entries(typeTotals)
      .map(([type, count]) => `${type} ${count}`)
      .join(" / ");
    return `Markdown 已自动生成 ${imported} 张知识卡，归档 ${generated} 个文档，跳过 ${skipped} 项${typeText ? `；${typeText}` : ""}`;
  }

  async function importMarkdownPath() {
    if (!selected || !markdownSourcePath.trim()) return;
    setBusy("import-md-path");
    setError("");
    setMessage("");
    try {
      const result = await api.importKnowledgeMarkdown(selected.id, {
        source_path: markdownSourcePath,
        library_type: uploadType,
        status: "raw_extracted",
      });
      setMessage(summarizeImportResults([result]));
      await refreshKnowledgeCards(selected.id);
      setActiveKnowledgeTab("cards");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Markdown 拆卡失败");
    } finally {
      setBusy("");
    }
  }

  async function importMarkdownFiles(event: ChangeEvent<HTMLInputElement>) {
    if (!selected || !event.target.files?.length) return;
    const files = event.target.files;
    setBusy("import-md-files");
    setError("");
    setMessage("");
    try {
      const results = await api.uploadKnowledgeMarkdownFiles(selected.id, files, uploadType, "raw_extracted");
      setMessage(summarizeImportResults(results));
      await refreshKnowledgeCards(selected.id);
      setActiveKnowledgeTab("cards");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Markdown 文件导入失败");
    } finally {
      event.target.value = "";
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
        ...selectedWritingModelPayload,
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

  async function searchRAG(event?: FormEvent) {
    event?.preventDefault();
    if (!selected || !query.trim()) return;
    if (positionMissing) {
      setError("请先填写当前 Volume 和 Chapter，再进行写作检索。");
      return;
    }
    setBusy("rag-search");
    setError("");
    try {
      const result = await api.searchWorkRAG(selected.id, { stage: ragStage, query, top_k: ragTopK, ...ragRetrievalPayload });
      setRagResults(result.results);
      setRetrievalDebug(result.retrieval_debug);
    } catch (err) {
      setError(err instanceof Error ? err.message : "RAG 召回失败");
    } finally {
      setBusy("");
    }
  }

  async function updateCardStatus(card: KnowledgeCard, status: string) {
    if (!selected) return;
    setBusy(`card-${card.card_id}`);
    setError("");
    try {
      await api.updateKnowledgeCard(selected.id, card.card_id, { status });
      await refreshKnowledgeCards(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "更新知识卡失败");
    } finally {
      setBusy("");
    }
  }

  async function previewMerges() {
    if (!selected) return;
    setBusy("merge-preview");
    setError("");
    try {
      const result = await api.previewKnowledgeMerges(selected.id, { merge_mode: "preview" });
      setMergeGroups(result.groups);
      setMessage(`发现 ${result.auto_merge_count} 张可安全合并卡片，${result.review_required_count} 组需要人工确认。`);
      await refreshKnowledgeCards(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "合并预览失败");
    } finally {
      setBusy("");
    }
  }

  async function applySafeMerges() {
    if (!selected) return;
    setBusy("merge-apply");
    setError("");
    try {
      const result = await api.applyKnowledgeMerges(selected.id, { merge_mode: "safe" });
      setMergeGroups(result.groups);
      setMessage(result.message);
      await refreshKnowledgeCards(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "执行安全合并失败");
    } finally {
      setBusy("");
    }
  }

  async function unmergeCard(card: KnowledgeCard) {
    if (!selected) return;
    setBusy(`unmerge-${card.card_id}`);
    setError("");
    try {
      await api.unmergeKnowledgeCard(selected.id, card.card_id);
      await refreshKnowledgeCards(selected.id);
      setMessage(`已恢复知识卡：${card.title}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "恢复知识卡失败");
    } finally {
      setBusy("");
    }
  }

  async function deleteKnowledgeCard(card: KnowledgeCard) {
    if (!selected || !window.confirm(`确定软删除知识卡「${card.title}」吗？`)) return;
    setBusy(`card-${card.card_id}`);
    setError("");
    try {
      await api.deleteKnowledgeCard(selected.id, card.card_id);
      await refreshKnowledgeCards(selected.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除知识卡失败");
    } finally {
      setBusy("");
    }
  }

  async function openMarkdownDoc(docId: string) {
    if (!selected) return;
    setBusy(`doc-${docId}`);
    setError("");
    try {
      const doc = await api.readKnowledgeMarkdownDoc(selected.id, docId);
      setSelectedDocId(doc.doc_id);
      setMarkdownContent(doc.content);
      setActiveKnowledgeTab("docs");
    } catch (err) {
      setError(err instanceof Error ? err.message : "读取 Markdown 失败");
    } finally {
      setBusy("");
    }
  }

  async function saveMarkdownDoc() {
    if (!selected || !selectedDocId || !markdownContent.trim()) return;
    setBusy(`doc-save-${selectedDocId}`);
    setError("");
    try {
      await api.saveKnowledgeMarkdownDoc(selected.id, selectedDocId, markdownContent);
      await refreshKnowledgeCards(selected.id);
      setMessage("Markdown 已保存");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存 Markdown 失败");
    } finally {
      setBusy("");
    }
  }

  async function syncMarkdownDoc() {
    if (!selected || !selectedDocId) return;
    setBusy(`doc-sync-${selectedDocId}`);
    setError("");
    try {
      const result = await api.syncKnowledgeMarkdownDoc(selected.id, selectedDocId);
      await refreshKnowledgeCards(selected.id);
      setMessage(`已同步到知识卡：${result.updated_fields.join("、") || "无字段变化"}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "同步 Markdown 失败");
    } finally {
      setBusy("");
    }
  }

  async function deleteMarkdownDoc() {
    if (!selected || !selectedDocId || !window.confirm("确定删除这个 Markdown 文档并软删除对应知识卡吗？")) return;
    setBusy(`doc-delete-${selectedDocId}`);
    setError("");
    try {
      await api.deleteKnowledgeMarkdownDoc(selected.id, selectedDocId);
      setSelectedDocId("");
      setMarkdownContent("");
      await refreshKnowledgeCards(selected.id);
      setMessage("Markdown 已删除，对应知识卡已标记为 deleted。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除 Markdown 失败");
    } finally {
      setBusy("");
    }
  }

  async function regenerateMarkdown(card: KnowledgeCard) {
    if (!selected) return;
    setBusy(`export-${card.card_id}`);
    setError("");
    try {
      const doc = await api.exportKnowledgeCardMarkdown(selected.id, card.card_id);
      setSelectedDocId(doc.doc_id);
      setMarkdownContent(doc.content);
      await refreshKnowledgeCards(selected.id);
      setActiveKnowledgeTab("docs");
    } catch (err) {
      setError(err instanceof Error ? err.message : "重新生成 Markdown 失败");
    } finally {
      setBusy("");
    }
  }

  async function generateOutline(event: FormEvent) {
    event.preventDefault();
    if (!selected || !outlineTask.trim()) return;
    if (positionMissing) {
      setError("请先填写当前 Volume 和 Chapter，避免写作位置与检索位置不同步。");
      return;
    }
    setBusy("outline");
    setError("");
    setOutline("");
    setConfirmedOutline("");
    setCitations([]);
    setActualChars(null);
    setLongSections([]);
    setGenerationWarnings([]);
    try {
      const result = await api.generateWorkOutline(selected.id, {
        task: outlineTask,
        current_content: outlineContext,
        mode,
        knowledge_mode: knowledgeMode,
        ...selectedWritingModelPayload,
        dry_run: dryRun,
        top_k: ragTopK,
        ...generationRetrievalPayload,
      });
      setOutline(result.content);
      setCitations(result.citations);
      setUsedKnowledge(result.used_knowledge || []);
      setRetrievalDebug(result.retrieval_debug || null);
      setPromptPreview(result.prompt_preview || "");
      setActualChars(result.actual_chars ?? result.content.length);
      setGenerationWarnings(result.warnings || []);
      setRagResults(
        (result.used_knowledge || []).map((item) => ({
          ...item,
          content_preview: item.content_preview || "",
          tags: item.tags || [],
          status: item.status || "used",
        })),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成提纲失败");
    } finally {
      setBusy("");
    }
  }

  async function confirmOutline() {
    if (!selected || !outline.trim()) return;
    if (positionMissing) {
      setError("请先填写当前 Volume 和 Chapter，再确认提纲 Memory。");
      return;
    }
    setBusy("confirm-outline");
    setError("");
    setMessage("");
    try {
      setConfirmedOutline(outline);
      const saved = await api.confirmOutlineMemory(selected.id, {
        title: `已确认提纲 ${new Date().toLocaleString()}`,
        content: outline,
        tags: ["outline"],
        scope_level: "chapter",
        volume_index: currentPositionPayload.current_volume_index,
        chapter_index: currentPositionPayload.current_chapter_index,
      });
      setMemories((items) => [saved, ...items]);
      await refreshKnowledgeCards(selected.id);
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
    await startDraftJob();
  }

  async function startDraftJob() {
    if (!selected || !confirmedOutline.trim()) return;
    if (positionMissing) {
      setError("请先填写当前 Volume 和 Chapter，再生成正文。");
      return;
    }
    setBusy("draft-job");
    setError("");
    setDraftJob(null);
    setDraft("");
    setLongSections([]);
    setGenerationWarnings([]);
    try {
      const job = await api.createWorkDraftJob(selected.id, {
        task: `请根据用户已确认的章节提纲生成小说正文：${outlineTask}`,
        confirmed_outline: confirmedOutline,
        current_content: outlineContext,
        mode,
        knowledge_mode: knowledgeMode,
        ...selectedWritingModelPayload,
        dry_run: dryRun,
        top_k: ragTopK,
        target_chars: targetChars,
        ...generationRetrievalPayload,
      });
      storeDraftJobRef(selected.id, job.job_id);
      applyDraftJob(job);
      setActiveKnowledgeTab("result");
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建长文本任务失败");
    } finally {
      setBusy("");
    }
  }

  async function cancelDraftJob() {
    if (!selected || !draftJob) return;
    setBusy("draft-job-cancel");
    setError("");
    try {
      const job = await api.cancelWorkDraftJob(selected.id, draftJob.job_id);
      applyDraftJob(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "取消长文本任务失败");
    } finally {
      setBusy("");
    }
  }

  async function generateRevision() {
    if (!selected || !draft.trim()) return;
    if (positionMissing) {
      setError("请先填写当前 Volume 和 Chapter，再润色正文。");
      return;
    }
    setBusy("revision");
    setError("");
    setCitations([]);
    setGenerationWarnings([]);
    try {
      const result = await api.generateWorkRevision(selected.id, {
        task: `请在不改变已确认世界观和人物连续性的前提下润色/改写当前正文：${outlineTask}`,
        confirmed_outline: confirmedOutline,
        current_content: draft,
        mode,
        knowledge_mode: knowledgeMode,
        ...selectedWritingModelPayload,
        dry_run: dryRun,
        top_k: ragTopK,
        target_chars: actualChars || targetChars,
        ...generationRetrievalPayload,
      });
      setDraft(result.content);
      setCitations(result.citations);
      setUsedKnowledge(result.used_knowledge || []);
      setRetrievalDebug(result.retrieval_debug || null);
      setPromptPreview(result.prompt_preview || "");
      setActualChars(result.actual_chars ?? result.content.length);
      setLongSections(result.sections || []);
      setGenerationWarnings(result.warnings || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "润色正文失败");
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
        tags: [type],
        source,
        scope_level: "chapter",
        volume_index: currentPositionPayload.current_volume_index,
        chapter_index: currentPositionPayload.current_chapter_index,
      });
      setMemories((items) => [saved, ...items]);
      await refreshKnowledgeCards(selected.id);
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

  function beginLeftPanelResize(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = leftPanelWidth;
    const move = (moveEvent: globalThis.PointerEvent) => {
      setLeftPanelWidth(Math.min(500, Math.max(220, startWidth + moveEvent.clientX - startX)));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }

  function beginRightPanelResize(event: PointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = rightPanelWidth;
    const move = (moveEvent: globalThis.PointerEvent) => {
      setRightPanelWidth(Math.min(520, Math.max(260, startWidth - (moveEvent.clientX - startX))));
    };
    const stop = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", stop);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", stop);
  }

  function openAgentTab(tab: "memory" | "writing_guide" | "worldbuilding" | "history") {
    setMainNavTab(tab);
    if (tab === "memory" || tab === "history") setAssistantTab("memory");
    if (tab === "writing_guide") setAssistantTab("outline");
    if (tab === "worldbuilding") setAssistantTab("worldbuilding");
  }

  async function saveDraftToMemory() {
    if (!selected || !draft.trim()) return;
    if (positionMissing) {
      setError("请先填写当前 Volume 和 Chapter，再保存正文 Memory。");
      return;
    }
    setBusy("memory");
    setError("");
    setMessage("");
    try {
      const saved = await api.confirmDraftMemory(selected.id, {
        title: `正文片段 ${new Date().toLocaleString()}`,
        content: draft,
        tags: ["draft"],
        scope_level: "chapter",
        volume_index: currentPositionPayload.current_volume_index,
        chapter_index: currentPositionPayload.current_chapter_index,
      });
      setMemories((items) => [saved, ...items]);
      await refreshKnowledgeCards(selected.id);
      setMessage("正文已写入 Memory。");
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存正文 Memory 失败");
    } finally {
      setBusy("");
    }
  }

  return (
    <section className="writing-agent-platform">
      <header className="writing-agent-header">
        <div className="writing-agent-header-left">
          <div className="writing-agent-logo">
            <span>写</span>
            <strong>写作平台</strong>
          </div>

          <div className="writing-agent-work-switcher">
            <select
              value={selectedId ?? ""}
              onChange={(event) => {
                const nextId = Number(event.target.value);
                if (nextId) chooseKnowledgeBase(nextId).catch((err) => setError(err instanceof Error ? err.message : "切换作品失败"));
              }}
            >
              <option value="">选择作品</option>
              {knowledgeBases.map((kb) => (
                <option key={kb.id} value={kb.id}>
                  {kb.name}
                </option>
              ))}
            </select>
          </div>

          <nav className="writing-agent-top-nav" aria-label="写作 Agent 导航">
            <button type="button" className={assistantTab === "outline" ? "active" : ""} onClick={() => openAgentTab("writing_guide")}>
              写作
            </button>
            <button type="button" className={assistantTab === "memory" ? "active" : ""} onClick={() => openAgentTab("memory")}>
              Memory
            </button>
            <button type="button" className={assistantTab === "worldbuilding" ? "active" : ""} onClick={() => openAgentTab("worldbuilding")}>
              世界观
            </button>
            <button
              type="button"
              className={assistantTab === "resources" ? "active" : ""}
              onClick={() => {
                setMainNavTab("writing_guide");
                setAssistantTab("resources");
              }}
            >
              拆卡/资料
            </button>
            <button type="button" className={mainNavTab === "history" ? "active" : ""} onClick={() => openAgentTab("history")}>
              历史
            </button>
          </nav>
        </div>

        <div className="writing-agent-header-right">
          <form className="writing-agent-search" onSubmit={searchRAG}>
            <span>⌕</span>
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="全文搜索 / RAG 召回" />
          </form>
          <button type="button" className="writing-icon-button" title="测试召回" onClick={() => void searchRAG()} disabled={!selected || !query.trim() || busy === "rag-search" || positionMissing}>
            查
          </button>
          <div className="writing-agent-user">
            <span>AI</span>
            <strong>{selectedWritingModel?.label || "写作模型"}</strong>
          </div>
        </div>
      </header>

      {(config || error || message) && (
        <div className="writing-agent-status-strip">
          {config && <span>{config.privacy_note} API Key 只用于本次请求，不会保存。</span>}
          <span>工作区：{getWorkspaceId()}</span>
          {message && <strong>{message}</strong>}
          {error && <strong className="is-error">{error}</strong>}
        </div>
      )}

      <div className="writing-agent-shell">
        <aside className="writing-agent-left-panel" style={{ width: leftPanelWidth }}>
          <div className="writing-panel-head">
            <span>章节管理</span>
            <div>
              <button type="button" title="新建作品" onClick={() => setName(`作品 ${knowledgeBases.length + 1}`)}>
                +
              </button>
              <button type="button" title="全选文件" onClick={selectAllCurrentDocuments} disabled={!documents.length}>
                ⇅
              </button>
            </div>
          </div>

          <div className="writing-agent-left-scroll">
            <form className="writing-work-create" onSubmit={createKnowledgeBase}>
              <label>
                作品名
                <input value={name} onChange={(event) => setName(event.target.value)} />
              </label>
              <label>
                作品备注
                <textarea rows={2} value={description} onChange={(event) => setDescription(event.target.value)} />
              </label>
              <button className="primary" disabled={busy === "create"}>
                新建作品
              </button>
            </form>

            <div className="writing-work-tree">
              {knowledgeBases.map((kb) => {
                const expanded = expandedWorkIds.includes(kb.id);
                const active = selectedId === kb.id;
                return (
                  <section key={kb.id} className={`writing-work-node ${active ? "active" : ""}`}>
                    <div className="writing-work-node-head">
                      <button type="button" className="writing-tree-toggle" onClick={() => toggleWork(kb.id)} aria-label={expanded ? "收起作品" : "展开作品"}>
                        {expanded ? "⌄" : "›"}
                      </button>
                      <button type="button" className="writing-work-title" onClick={() => chooseKnowledgeBase(kb.id)}>
                        <strong>{kb.name}</strong>
                        <small>
                          {kb.document_count} 文件 · {kb.chunk_count} 分块
                        </small>
                      </button>
                    </div>

                    {expanded && active && (
                      <div className="writing-work-files">
                        <div className="writing-import-box">
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
                          <div className="writing-compact-actions">
                            <label className="button-link compact-action">
                              上传{knowledgeTypeLabel(uploadType)}
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
                          <label>
                            知识包路径
                            <input value={packagePath} onChange={(event) => setPackagePath(event.target.value)} placeholder="knowledge_package.json" />
                          </label>
                          <button type="button" onClick={importKnowledgePackage} disabled={!selected || busy === "import-package" || !packagePath.trim()}>
                            导入知识包
                          </button>
                          <label>
                            Markdown 路径
                            <input value={markdownSourcePath} onChange={(event) => setMarkdownSourcePath(event.target.value)} placeholder="examples/my_knowledge.md" />
                          </label>
                          <div className="writing-compact-actions">
                            <button type="button" onClick={importMarkdownPath} disabled={!selected || busy === "import-md-path" || !markdownSourcePath.trim()}>
                              自动拆卡
                            </button>
                            <label className="button-link compact-action">
                              上传 MD
                              <input className="hidden-input" type="file" multiple accept=".md,.markdown,text/markdown,text/plain" onChange={importMarkdownFiles} disabled={!selected || busy === "import-md-files"} />
                            </label>
                          </div>
                        </div>

                        <div className="writing-file-toolbar">
                          <button type="button" onClick={selectAllCurrentDocuments} disabled={!documents.length}>
                            全选
                          </button>
                          <button type="button" onClick={() => setSelectedDocumentIds([])} disabled={!selectedDocumentIds.length}>
                            取消
                          </button>
                          <button type="button" className="danger" onClick={() => bulkDeleteDocuments()} disabled={!selectedDocumentsInWork.length}>
                            删除
                          </button>
                          <button type="button" className="danger" onClick={() => bulkDeleteDocuments(undefined, true)} disabled={!documents.length}>
                            清空
                          </button>
                        </div>

                        {KNOWLEDGE_GROUPS.map((group) => {
                          const groupDocuments = documentsByType[group.key] || [];
                          const groupSelected = groupDocuments.filter((document) => selectedDocumentSet.has(document.id)).length;
                          const allGroupSelected = groupDocuments.length > 0 && groupSelected === groupDocuments.length;
                          return (
                            <div key={group.key} className="writing-file-group">
                              <div className="writing-file-group-head">
                                <button type="button" className="writing-tree-toggle" onClick={() => toggleKnowledgeType(group.key)}>
                                  {expandedTypes[group.key] ? "⌄" : "›"}
                                </button>
                                <input
                                  type="checkbox"
                                  checked={allGroupSelected}
                                  disabled={!groupDocuments.length}
                                  onChange={(event) => setGroupSelection(group.key, event.target.checked)}
                                  aria-label={`选择${group.label}`}
                                />
                                <button type="button" className="writing-file-group-title" onClick={() => toggleKnowledgeType(group.key)}>
                                  <strong>{group.label}</strong>
                                  <small>
                                    {groupDocuments.length} 文件{groupSelected ? ` · 已选 ${groupSelected}` : ""}
                                  </small>
                                </button>
                              </div>
                              {expandedTypes[group.key] && (
                                <div className="writing-file-list">
                                  {!groupDocuments.length && <p className="muted file-empty">{group.hint}</p>}
                                  {groupDocuments.map((document) => (
                                    <div key={document.id} className={`writing-file-row ${selectedDocumentSet.has(document.id) ? "selected" : ""}`}>
                                      <input type="checkbox" checked={selectedDocumentSet.has(document.id)} onChange={() => toggleDocumentSelection(document.id)} aria-label={`选择${documentTitle(document)}`} />
                                      <div>
                                        <strong title={documentTitle(document)}>{documentTitle(document)}</strong>
                                        <small>
                                          {document.chunk_count} 分块 · {formatSize(document.size_bytes)} · {document.status}
                                        </small>
                                        {document.error_message && <small className="warn-cell">{document.error_message}</small>}
                                      </div>
                                      <div className="writing-file-actions">
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
          </div>
        </aside>

        <div className="writing-agent-resizer" onPointerDown={beginLeftPanelResize} />

        <main className="writing-agent-editor">
          <div className="writing-editor-titlebar">
            <input value={outlineTask} onChange={(event) => setOutlineTask(event.target.value)} placeholder="请输入章节标题或本次写作请求" />
            <div className="writing-editor-position">
              <label>
                V
                <input type="number" min={1} value={currentVolumeIndex} onChange={(event) => setCurrentVolumeIndex(parsePositionInput(event.target.value))} />
              </label>
              <label>
                C
                <input type="number" min={1} value={currentChapterIndex} onChange={(event) => setCurrentChapterIndex(parsePositionInput(event.target.value))} />
              </label>
            </div>
          </div>

          <div className="writing-editor-toolbar">
            <button type="button" title="生成提纲" onClick={() => setAssistantTab("outline")}>
              提纲
            </button>
            <button type="button" title="生成正文" onClick={() => void startDraftJob()} disabled={!selected || !confirmedOutline.trim() || busy === "draft-job" || modelCallBlocked || positionMissing}>
              正文
            </button>
            <button type="button" title="润色正文" onClick={generateRevision} disabled={!selected || !draft || busy === "revision" || modelCallBlocked || positionMissing}>
              润色
            </button>
            <span className="writing-toolbar-divider" />
            <button type="button" title="复制正文" onClick={() => navigator.clipboard.writeText(draft)} disabled={!draft}>
              复制
            </button>
            <button type="button" title="清空正文" onClick={() => setDraft("")} disabled={!draft}>
              清空
            </button>
            <button
              type="button"
              title="生成结果"
              onClick={() => {
                setAssistantTab("resources");
                setActiveKnowledgeTab("result");
              }}
            >
              结果
            </button>
            <div className="writing-word-count">字数：{draftWordCount}</div>
          </div>

          <div className="writing-editor-surface">
            <textarea
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              placeholder={confirmedOutline ? "正文生成后会显示在这里，也可以直接粘贴或继续编辑。" : "请先在右侧生成并确认提纲，再生成正文。"}
            />
          </div>

          {(activeDraftJob || generationWarnings.length > 0 || positionMissing) && (
            <div className="writing-editor-inline-status">
              {positionMissing && <span className="is-error">请填写当前 Volume 和 Chapter。</span>}
              {activeDraftJob && (
                <span>
                  长文本任务：{draftJob?.status} · {draftJob?.current_section || 0}/{draftJob?.section_count || longSections.length || 0}
                </span>
              )}
              {generationWarnings.slice(0, 2).map((item) => (
                <span key={item}>{item}</span>
              ))}
            </div>
          )}

          <div className="writing-editor-footer">
            <div>
              <button type="button" className="primary" onClick={saveDraftToMemory} disabled={!selected || !draft || busy === "memory" || positionMissing}>
                保存草稿
              </button>
              <button
                type="button"
                onClick={() => {
                  setAssistantTab("resources");
                  setActiveKnowledgeTab("result");
                }}
              >
                预览
              </button>
            </div>
            <div>
              <button type="button" onClick={cancelDraftJob} disabled={!draftJob || !activeDraftJob || busy === "draft-job-cancel"}>
                取消任务
              </button>
              <button type="button" className="publish" onClick={saveDraftToMemory} disabled={!selected || !draft || busy === "memory" || positionMissing}>
                存入 Memory
              </button>
            </div>
          </div>
        </main>

        <div className="writing-agent-resizer" onPointerDown={beginRightPanelResize} />

        <aside className="writing-agent-right-panel" style={{ width: rightPanelWidth }}>
          <div className="writing-assistant-tabs">
            <button type="button" className={assistantTab === "outline" ? "active" : ""} onClick={() => setAssistantTab("outline")}>
              大纲
            </button>
            <button type="button" className={assistantTab === "memory" ? "active" : ""} onClick={() => setAssistantTab("memory")}>
              人设
            </button>
            <button type="button" className={assistantTab === "worldbuilding" ? "active" : ""} onClick={() => setAssistantTab("worldbuilding")}>
              设定
            </button>
            <button type="button" className={assistantTab === "resources" ? "active" : ""} onClick={() => setAssistantTab("resources")}>
              拆卡
            </button>
          </div>

          <div className="writing-assistant-content">
            {assistantTab === "outline" && (
              <>
                <form className="writing-side-card" onSubmit={generateOutline}>
                  <div className="writing-side-card-head">
                    <strong>发送请求</strong>
                    <span>{dryRun ? "dry-run" : "model"}</span>
                  </div>
                  <label>
                    写作请求
                    <textarea rows={4} value={outlineTask} onChange={(event) => setOutlineTask(event.target.value)} />
                  </label>
                  <label>
                    补充上下文 / 已有正文
                    <textarea rows={4} value={outlineContext} onChange={(event) => setOutlineContext(event.target.value)} />
                  </label>
                  <div className="mode-grid">
                    <label>
                      目标字数
                      <input type="number" min={500} max={50000} step={500} value={targetChars} onChange={(event) => setTargetChars(Number(event.target.value) || 3000)} />
                    </label>
                    <label>
                      RAG top_k
                      <input type="number" min={1} max={200} value={ragTopK} onChange={(event) => setRagTopK(Number(event.target.value) || 8)} />
                    </label>
                  </div>
                  <div className="mode-grid">
                    <label>
                      模型
                      <select value={writingModelId} onChange={(event) => setWritingModelId(event.target.value)}>
                        {writingModels.map((option) => (
                          <option key={option.id} value={option.id}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label>
                      API Key
                      <input type="password" value={writingApiKey} onChange={(event) => setWritingApiKey(event.target.value)} placeholder="本次请求使用" />
                    </label>
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
                    dry-run
                  </label>
                  <label className="check-row">
                    <input type="checkbox" checked={debugRawKnowledge} onChange={(event) => setDebugRawKnowledge(event.target.checked)} />
                    Raw Evidence
                  </label>
                  {modelCallBlocked && <small className="warn-cell">关闭 dry-run 后，请先填写 API Key。</small>}
                  <button className="primary" disabled={!selected || busy === "outline" || modelCallBlocked || positionMissing}>
                    生成提纲
                  </button>
                </form>

                <div className="writing-side-card">
                  <div className="writing-side-card-head">
                    <strong>章节提纲</strong>
                    <span>{confirmedOutline ? "已确认" : "待确认"}</span>
                  </div>
                  <textarea rows={14} value={outline} onChange={(event) => setOutline(event.target.value)} placeholder="提纲会显示在这里。" />
                  <div className="writing-compact-actions">
                    <button type="button" disabled={!outline} onClick={() => navigator.clipboard.writeText(outline)}>
                      复制提纲
                    </button>
                    <button type="button" className="primary" disabled={!selected || !outline.trim() || busy === "confirm-outline" || positionMissing} onClick={confirmOutline}>
                      确认提纲
                    </button>
                  </div>
                </div>

                <div className="writing-side-card">
                  <div className="writing-side-card-head">
                    <strong>正文生成</strong>
                    <span>{draftJob?.status || "ready"}</span>
                  </div>
                  <button className="primary" type="button" disabled={!selected || !confirmedOutline.trim() || busy === "draft-job" || modelCallBlocked || positionMissing} onClick={() => void startDraftJob()}>
                    根据确认提纲生成正文
                  </button>
                  <div className="writing-compact-actions">
                    <button type="button" disabled={!draft} onClick={() => navigator.clipboard.writeText(draft)}>
                      复制正文
                    </button>
                    <button type="button" disabled={!selected || !draft || busy === "revision" || modelCallBlocked || positionMissing} onClick={generateRevision}>
                      润色正文
                    </button>
                  </div>
                </div>
              </>
            )}

            {assistantTab === "memory" && (
              <>
                <form className="writing-side-card" onSubmit={searchRAG}>
                  <div className="writing-side-card-head">
                    <strong>RAG 召回预览</strong>
                    <span>{ragResults.length} 条</span>
                  </div>
                  <label>
                    任务或关键词
                    <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="黄金三章如何制造期待？" />
                  </label>
                  <div className="mode-grid">
                    <label>
                      Stage
                      <select value={ragStage} onChange={(event) => setRagStage(event.target.value)}>
                        <option value="outline">outline</option>
                        <option value="draft">draft</option>
                        <option value="revision">revision</option>
                        <option value="continue">continue</option>
                        <option value="worldbuilding_check">worldbuilding_check</option>
                      </select>
                    </label>
                    <label>
                      top_k
                      <input type="number" min={1} max={200} value={ragTopK} onChange={(event) => setRagTopK(Number(event.target.value) || 8)} />
                    </label>
                  </div>
                  <button className="primary" disabled={!selected || busy === "rag-search" || positionMissing}>
                    测试召回
                  </button>
                  {retrievalDebug && (
                    <div className="retrieval-debug">
                      <strong>召回策略</strong>
                      <small>
                        {retrievalDebug.stage} · top_k {retrievalDebug.top_k} · 候选 {retrievalDebug.total_candidates} · 选中 {retrievalDebug.selected_count}
                      </small>
                      {!!retrievalDebug.warnings?.length && <p className="warn-cell">{retrievalDebug.warnings.join(" / ")}</p>}
                    </div>
                  )}
                  <div className="hit-list">
                    {ragResults.map((hit) => (
                      <article key={hit.id}>
                        <strong>{hit.title}</strong>
                        <small>
                          {hit.library_type} / {hit.card_type} · score {hit.score}
                        </small>
                        <p>{hit.content_preview || "本次生成使用了这张知识卡。"}</p>
                      </article>
                    ))}
                  </div>
                </form>

                <div className="writing-side-card">
                  <div className="writing-side-card-head">
                    <strong>长期 Memory</strong>
                    <span>{memories.length} 条</span>
                  </div>
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
                      <input value={memoryTitle} onChange={(event) => setMemoryTitle(event.target.value)} placeholder="第一章结尾状态" />
                    </label>
                  </div>
                  <textarea rows={4} value={memoryContent} onChange={(event) => setMemoryContent(event.target.value)} placeholder="写下需要长期承接的上下文。" />
                  <button type="button" className="primary" disabled={!selected || busy === "memory" || !memoryTitle.trim() || !memoryContent.trim() || positionMissing} onClick={() => saveMemory(memoryTitle, memoryContent)}>
                    保存 Memory
                  </button>
                  <div className="hit-list memory-list">
                    {memories.map((memory) => (
                      <article key={memory.id}>
                        <strong>{memory.title}</strong>
                        <small>
                          {memory.memory_type} · {memory.source}
                          {mainNavTab === "history" && memory.created_at ? ` · ${new Date(memory.created_at).toLocaleString()}` : ""}
                        </small>
                        <p>{memory.content}</p>
                        {mainNavTab !== "history" && (
                          <button type="button" className="danger" onClick={() => deleteMemory(memory.id)} disabled={busy === `memory-${memory.id}`}>
                            删除
                          </button>
                        )}
                      </article>
                    ))}
                    {!memories.length && <p className="muted">还没有 Memory。</p>}
                  </div>
                </div>
              </>
            )}

            {assistantTab === "worldbuilding" && (
              <div className="writing-side-card">
                <div className="writing-side-card-head">
                  <strong>世界观设定草案</strong>
                  <span>{worldbuildingDraft ? "draft" : "empty"}</span>
                </div>
                <div className="writing-setting-upload">
                  <div>
                    <strong>上传设定文件</strong>
                    <small>支持 txt、md、docx、pdf；会导入当前作品的世界观设定。</small>
                  </div>
                  <label className="button-link compact-action">
                    上传设定
                    <input
                      className="hidden-input"
                      type="file"
                      multiple
                      accept=".txt,.md,.docx,.pdf,text/plain,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                      onChange={(event) => uploadFilesTo(event, "worldbuilding")}
                      disabled={!selected || busy === "upload"}
                    />
                  </label>
                </div>
                <div className="writing-setting-list">
                  <strong>已导入设定</strong>
                  {(documentsByType.worldbuilding || []).slice(0, 5).map((document) => (
                    <div key={document.id}>
                      <span title={documentTitle(document)}>{documentTitle(document)}</span>
                      <small>
                        {document.chunk_count} 分块 · {document.status}
                      </small>
                    </div>
                  ))}
                  {!(documentsByType.worldbuilding || []).length && <small>当前作品还没有设定文件。</small>}
                </div>
                <label>
                  故事种子
                  <textarea rows={4} value={storySeed} onChange={(event) => setStorySeed(event.target.value)} />
                </label>
                <div className="writing-compact-actions">
                  <button type="button" onClick={generateWorldbuildingDraft} disabled={!selected || busy === "worldbuilding" || modelCallBlocked}>
                    生成草案
                  </button>
                  <button type="button" className="primary" onClick={confirmWorldbuildingImport} disabled={!selected || !worldbuildingDraft || busy === "confirm-worldbuilding"}>
                    确认导入
                  </button>
                </div>
                <textarea rows={18} value={worldbuildingDraft} onChange={(event) => setWorldbuildingDraft(event.target.value)} placeholder="生成或粘贴世界观设定，确认后导入当前作品。" />
              </div>
            )}

            {assistantTab === "resources" && (
              <div className="writing-side-card resource-card">
                <div className="writing-side-card-head">
                  <strong>资料库</strong>
                  <span>{cards.length} 卡</span>
                </div>
                <div className="writing-card-import">
                  <div className="writing-card-import-head">
                    <div>
                      <strong>拆卡导入</strong>
                      <small>导入知识包，或把 Markdown 自动拆成知识卡。</small>
                    </div>
                    <label>
                      类型
                      <select value={uploadType} onChange={(event) => setUploadType(event.target.value)}>
                        {KNOWLEDGE_GROUPS.map((group) => (
                          <option key={group.key} value={group.key}>
                            {group.label}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  <label>
                    知识包路径
                    <input value={packagePath} onChange={(event) => setPackagePath(event.target.value)} placeholder="knowledge_package.json" />
                  </label>
                  <button type="button" className="primary" onClick={importKnowledgePackage} disabled={!selected || busy === "import-package" || !packagePath.trim()}>
                    导入 knowledge_package
                  </button>

                  <label>
                    Markdown 知识文档路径
                    <input value={markdownSourcePath} onChange={(event) => setMarkdownSourcePath(event.target.value)} placeholder="examples/my_knowledge.md" />
                  </label>
                  <div className="writing-compact-actions">
                    <button type="button" onClick={importMarkdownPath} disabled={!selected || busy === "import-md-path" || !markdownSourcePath.trim()}>
                      自动拆卡
                    </button>
                    <label className="button-link compact-action">
                      上传 MD 拆卡
                      <input className="hidden-input" type="file" multiple accept=".md,.markdown,text/markdown,text/plain" onChange={importMarkdownFiles} disabled={!selected || busy === "import-md-files"} />
                    </label>
                    <button type="button" onClick={importCurrentJob} disabled={!selected || !job || busy === "import"}>
                      导入拆书结果
                    </button>
                  </div>
                </div>
                <div className="tab-row">
                  <button type="button" className={activeKnowledgeTab === "cards" ? "active-tab" : ""} onClick={() => setActiveKnowledgeTab("cards")}>
                    知识卡
                  </button>
                  <button type="button" className={activeKnowledgeTab === "docs" ? "active-tab" : ""} onClick={() => setActiveKnowledgeTab("docs")}>
                    Markdown
                  </button>
                  <button type="button" className={activeKnowledgeTab === "result" ? "active-tab" : ""} onClick={() => setActiveKnowledgeTab("result")}>
                    结果
                  </button>
                </div>

                {activeKnowledgeTab === "cards" && (
                  <div className="writing-resource-pane">
                    <div className="metric-grid">
                      <div>
                        <strong>{mergeStats?.raw_card_count ?? 0}</strong>
                        <span>Raw</span>
                      </div>
                      <div>
                        <strong>{mergeStats?.canonical_card_count ?? cards.filter((card) => card.is_canonical).length}</strong>
                        <span>Canonical</span>
                      </div>
                      <div>
                        <strong>{mergeStats?.merged_card_count ?? cards.filter((card) => card.status === "merged").length}</strong>
                        <span>已合并</span>
                      </div>
                    </div>
                    <div className="writing-compact-actions">
                      <button type="button" onClick={() => setShowRawCards((value) => !value)}>
                        {showRawCards ? "隐藏 Raw" : "显示 Raw"}
                      </button>
                      <button type="button" onClick={previewMerges} disabled={!selected || busy === "merge-preview"}>
                        预览合并
                      </button>
                      <button type="button" className="primary" onClick={applySafeMerges} disabled={!selected || busy === "merge-apply"}>
                        安全合并
                      </button>
                    </div>
                    <div className="filter-chip-row">
                      {cardFilterGroups.map((group) => (
                        <button key={group.key} type="button" className={cardTypeFilter === group.key ? "active-chip" : ""} onClick={() => setCardTypeFilter(group.key)}>
                          {group.label}
                          <span>{group.count}</span>
                        </button>
                      ))}
                    </div>
                    <div className="knowledge-card-grid">
                      {filteredCards.map((card) => (
                        <article key={card.card_id} className={`knowledge-card-item ${selectedCardId === card.card_id ? "selected-card" : ""}`}>
                          <div className="card-title-row">
                            <strong>{card.title}</strong>
                            <span className={`status-pill status-${card.status}`}>{card.status}</span>
                          </div>
                          <small>
                            {card.library_type} / {card.card_type} · {card.is_canonical ? "canonical" : "raw"} · {Math.round(card.confidence * 100)}%
                          </small>
                          <p>{card.summary || card.content.slice(0, 180)}</p>
                          {!!card.tags.length && (
                            <div className="tag-row">
                              {card.tags.slice(0, 5).map((tag) => (
                                <span key={tag}>{tag}</span>
                              ))}
                            </div>
                          )}
                          <div className="writing-compact-actions">
                            <button type="button" onClick={() => setSelectedCardId(card.card_id)}>
                              详情
                            </button>
                            <button type="button" onClick={() => updateCardStatus(card, card.status === "disabled" ? "approved" : "disabled")} disabled={busy === `card-${card.card_id}`}>
                              {card.status === "disabled" ? "启用" : "禁用"}
                            </button>
                            <button type="button" onClick={() => regenerateMarkdown(card)} disabled={busy === `export-${card.card_id}`}>
                              生成 MD
                            </button>
                            {!card.is_canonical && (
                              <button type="button" onClick={() => unmergeCard(card)} disabled={busy === `unmerge-${card.card_id}`}>
                                恢复
                              </button>
                            )}
                            <button type="button" className="danger" onClick={() => deleteKnowledgeCard(card)} disabled={busy === `card-${card.card_id}`}>
                              删除
                            </button>
                          </div>
                          {selectedCardId === card.card_id && <pre className="card-detail">{card.content}</pre>}
                        </article>
                      ))}
                      {!!cards.length && !filteredCards.length && <p className="muted">当前分类下暂无知识卡。</p>}
                      {!cards.length && <p className="muted">还没有知识卡。</p>}
                    </div>
                  </div>
                )}

                {activeKnowledgeTab === "docs" && (
                  <div className="writing-resource-pane">
                    <div className="doc-list">
                      {markdownDocs.map((doc) => (
                        <button key={doc.doc_id} type="button" className={selectedDocId === doc.doc_id ? "active-file" : ""} onClick={() => openMarkdownDoc(doc.doc_id)}>
                          <span>
                            <strong>{doc.title}</strong>
                            <small>
                              {doc.library_type}/{doc.card_type} · {doc.exists ? doc.status : "missing"}
                            </small>
                          </span>
                        </button>
                      ))}
                      {!markdownDocs.length && <p className="muted">暂无 Markdown 文档。</p>}
                    </div>
                    <textarea rows={14} value={markdownContent} onChange={(event) => setMarkdownContent(event.target.value)} placeholder="Markdown 内容会显示在这里。" />
                    <div className="writing-compact-actions">
                      <button type="button" onClick={saveMarkdownDoc} disabled={!selectedDocId || busy === `doc-save-${selectedDocId}`}>
                        保存
                      </button>
                      <button type="button" className="primary" onClick={syncMarkdownDoc} disabled={!selectedDocId || busy === `doc-sync-${selectedDocId}`}>
                        同步
                      </button>
                      <button type="button" className="danger" onClick={deleteMarkdownDoc} disabled={!selectedDocId || busy === `doc-delete-${selectedDocId}`}>
                        删除
                      </button>
                    </div>
                  </div>
                )}

                {activeKnowledgeTab === "result" && (
                  <div className="writing-resource-pane">
                    <div className="metric-grid">
                      <div>
                        <strong>{usedKnowledge.length}</strong>
                        <span>召回知识</span>
                      </div>
                      <div>
                        <strong>{actualChars ?? draftWordCount}</strong>
                        <span>实际字数</span>
                      </div>
                      <div>
                        <strong>{longSections.length || 1}</strong>
                        <span>分段</span>
                      </div>
                    </div>
                    {!!usedKnowledge.length && (
                      <div className="hit-list">
                        {usedKnowledge.map((item) => (
                          <article key={item.id}>
                            <strong>
                              [{item.card_type}] {item.title}
                            </strong>
                            <small>
                              {item.library_type} · score {item.score}
                            </small>
                            {!!item.content_preview && <p>{item.content_preview}</p>}
                          </article>
                        ))}
                      </div>
                    )}
                    {!!longSections.length && (
                      <div className="section-progress-list">
                        {longSections.map((section) => (
                          <article key={section.index}>
                            <div className="card-title-row">
                              <strong>
                                第 {section.index} 段 · {section.status}
                              </strong>
                              <span>
                                {section.actual_chars}/{section.target_chars}
                              </span>
                            </div>
                            <p>{section.focus}</p>
                          </article>
                        ))}
                      </div>
                    )}
                    <pre>{draft || outline || "生成结果会显示在这里。"}</pre>
                    {promptPreview && (
                      <>
                        <strong>Prompt Preview</strong>
                        <pre>{promptPreview}</pre>
                      </>
                    )}
                    {!!citations.length && (
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
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
