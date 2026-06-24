import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";
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
    .map(([key, value]) => `${key}: ${String(value)}`)
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
  const [currentVolumeIndex, setCurrentVolumeIndex] = useState(1);
  const [currentChapterIndex, setCurrentChapterIndex] = useState(1);
  const [ragResults, setRagResults] = useState<RAGSearchResult[]>([]);
  const [retrievalDebug, setRetrievalDebug] = useState<RetrievalDebug | null>(null);
  const [usedKnowledge, setUsedKnowledge] = useState<UsedKnowledge[]>([]);
  const [promptPreview, setPromptPreview] = useState("");
  const [packagePath, setPackagePath] = useState("examples/sample_knowledge_package.json");
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
    current_volume_index: currentVolumeIndex || null,
    current_chapter_index: currentChapterIndex || null,
  };
  const generationRetrievalPayload = {
    ...currentPositionPayload,
    include_raw_knowledge: true,
  };
  const ragRetrievalPayload = {
    ...currentPositionPayload,
    include_raw: true,
  };
  const modelCallBlocked = !dryRun && !writingApiKey.trim();

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
        library_type: "writing_guide",
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
    if (!selected || !confirmedOutline.trim()) return;
    setBusy("draft");
    setError("");
    setDraft("");
    setCitations([]);
    setActualChars(null);
    setLongSections([]);
    setGenerationWarnings([]);
    try {
      const result = await api.generateWorkDraft(selected.id, {
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
      setDraft(result.content);
      setCitations(result.citations);
      setUsedKnowledge(result.used_knowledge || []);
      setRetrievalDebug(result.retrieval_debug || null);
      setPromptPreview(result.prompt_preview || "");
      setActualChars(result.actual_chars ?? result.content.length);
      setLongSections(result.sections || []);
      setGenerationWarnings(result.warnings || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "生成正文失败");
    } finally {
      setBusy("");
    }
  }

  async function startDraftJob() {
    if (!selected || !confirmedOutline.trim()) return;
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
          {config.privacy_note} 当前写作模型：{selectedWritingModel?.label || config.deepseek_model}。API Key 只用于本次请求，不会保存。
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
                        <label>
                          知识包路径
                          <input value={packagePath} onChange={(event) => setPackagePath(event.target.value)} placeholder="examples/sample_knowledge_package.json" />
                        </label>
                        <button type="button" onClick={importKnowledgePackage} disabled={!selected || busy === "import-package" || !packagePath.trim()}>
                          导入 knowledge_package
                        </button>
                        <label>
                          Markdown 知识文档路径
                          <input value={markdownSourcePath} onChange={(event) => setMarkdownSourcePath(event.target.value)} placeholder="examples/my_knowledge.md" />
                        </label>
                        <div className="button-row tight-row">
                          <button type="button" onClick={importMarkdownPath} disabled={!selected || busy === "import-md-path" || !markdownSourcePath.trim()}>
                            自动拆卡
                          </button>
                          <label className="button-link compact-action">
                            上传 MD 拆卡
                            <input
                              className="hidden-input"
                              type="file"
                              multiple
                              accept=".md,.markdown,text/markdown,text/plain"
                              onChange={importMarkdownFiles}
                              disabled={!selected || busy === "import-md-files"}
                            />
                          </label>
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
                ? `${selected.name} 内共有 ${documents.length} 个文件、${cards.length} 张知识卡、${markdownDocs.length} 个 Markdown 文档。`
                : "每个作品有独立文件树、Memory 和生成上下文。"}
            </p>
          </div>

          <div className="knowledge-workbench panel">
            <div className="knowledge-workbench-head">
              <div>
                <p className="eyebrow">Knowledge Cards</p>
                <h2>知识卡与 Markdown</h2>
              </div>
              <div className="tab-row">
                <button type="button" className={activeKnowledgeTab === "cards" ? "active-tab" : ""} onClick={() => setActiveKnowledgeTab("cards")}>
                  知识卡
                </button>
                <button type="button" className={activeKnowledgeTab === "docs" ? "active-tab" : ""} onClick={() => setActiveKnowledgeTab("docs")}>
                  Markdown 文档
                </button>
                <button type="button" className={activeKnowledgeTab === "result" ? "active-tab" : ""} onClick={() => setActiveKnowledgeTab("result")}>
                  生成结果
                </button>
              </div>
            </div>

            {activeKnowledgeTab === "cards" && (
              <div className="knowledge-card-panel">
                <div className="metric-grid">
                  <div>
                    <strong>{mergeStats?.raw_card_count ?? 0}</strong>
                    <span>Raw Cards</span>
                  </div>
                  <div>
                    <strong>{mergeStats?.canonical_card_count ?? cards.filter((card) => card.is_canonical).length}</strong>
                    <span>Canonical Cards</span>
                  </div>
                  <div>
                    <strong>{mergeStats?.merged_card_count ?? cards.filter((card) => card.status === "merged").length}</strong>
                    <span>已合并</span>
                  </div>
                  <div>
                    <strong>{mergeStats?.review_required_count ?? 0}</strong>
                    <span>待确认组</span>
                  </div>
                  <div>
                    <strong>{Math.round((mergeStats?.reduction_rate ?? 0) * 100)}%</strong>
                    <span>精简比例</span>
                  </div>
                </div>
                <div className="button-row">
                  <button type="button" onClick={() => setShowRawCards((value) => !value)}>
                    {showRawCards ? "隐藏 Raw Evidence" : "显示 Raw Evidence"}
                  </button>
                  <button type="button" onClick={previewMerges} disabled={!selected || busy === "merge-preview"}>
                    预览安全合并
                  </button>
                  <button type="button" className="primary" onClick={applySafeMerges} disabled={!selected || busy === "merge-apply"}>
                    执行安全合并
                  </button>
                </div>
                {!!mergeGroups.length && (
                  <div className="merge-preview-list">
                    {mergeGroups.slice(0, 6).map((group) => (
                      <div key={group.group_id} className="merge-preview-item">
                        <strong>
                          {group.reason} · {group.action} · {Math.round(group.similarity * 100)}%
                        </strong>
                        <small>
                          主卡 {group.primary_card_id}；候选 {group.candidate_card_ids.join("、") || "无"}
                        </small>
                      </div>
                    ))}
                  </div>
                )}
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
                        {card.library_type} / {card.card_type} · {card.is_canonical ? "canonical" : "raw"} · evidence {card.evidence_count} · {Math.round(card.confidence * 100)}%
                      </small>
                      <small>
                        {card.scope_level}
                        {card.volume_index ? ` · V${card.volume_index}` : ""}
                        {card.chapter_index ? ` · C${card.chapter_index}` : ""} · {card.retrievable ? "retrievable" : "not retrievable"}
                      </small>
                      {card.merged_into_card_id && <small className="source-ref">merged into {card.merged_into_card_id}</small>}
                      <p>{card.summary || card.content.slice(0, 180)}</p>
                      <div className="tag-row">
                        {card.tags.slice(0, 5).map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                      {!!compactSourceRef(card.source_ref) && <small className="source-ref">{compactSourceRef(card.source_ref)}</small>}
                      <div className="button-row tight-row">
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
                  {!cards.length && <p className="muted">还没有知识卡。可以先导入 `examples/sample_knowledge_package.json`。</p>}
                </div>
              </div>
            )}

            {activeKnowledgeTab === "docs" && (
              <div className="markdown-doc-layout">
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
                <div className="doc-editor">
                  <div className="preview-toolbar">
                    <strong>{selectedDocId || "选择 Markdown 文档"}</strong>
                    <div className="button-row">
                      <button type="button" onClick={saveMarkdownDoc} disabled={!selectedDocId || busy === `doc-save-${selectedDocId}`}>
                        保存
                      </button>
                      <button type="button" className="primary" onClick={syncMarkdownDoc} disabled={!selectedDocId || busy === `doc-sync-${selectedDocId}`}>
                        同步到知识卡
                      </button>
                      <button type="button" className="danger" onClick={deleteMarkdownDoc} disabled={!selectedDocId || busy === `doc-delete-${selectedDocId}`}>
                        删除文档
                      </button>
                    </div>
                  </div>
                  <textarea rows={18} value={markdownContent} onChange={(event) => setMarkdownContent(event.target.value)} placeholder="Markdown 内容会显示在这里。" />
                </div>
              </div>
            )}

            {activeKnowledgeTab === "result" && (
              <div className="generation-result-panel">
                <div className="metric-strip">
                  <div>
                    <span>目标阶段</span>
                    <strong>{retrievalDebug?.stage || ragStage}</strong>
                  </div>
                  <div>
                    <span>召回知识</span>
                    <strong>{usedKnowledge.length}</strong>
                  </div>
                  <div>
                    <span>Job</span>
                    <strong>{draftJob?.status || "sync"}</strong>
                  </div>
                  <div>
                    <span>目标/实际字数</span>
                    <strong>
                      {targetChars} / {actualChars ?? 0}
                    </strong>
                  </div>
                  <div>
                    <span>分段数</span>
                    <strong>{longSections.length || 1}</strong>
                  </div>
                  <div>
                    <span>Ratio</span>
                    <strong>{draftJob?.completion_ratio ? `${Math.round(draftJob.completion_ratio * 100)}%` : actualChars ? `${Math.round((actualChars / targetChars) * 100)}%` : "0%"}</strong>
                  </div>
                </div>
                {draftJob && (
                  <div className="retrieval-debug">
                    <strong>长文本任务</strong>
                    <small>
                      {draftJob.job_id.slice(0, 8)} · {draftJob.status} · {draftJob.current_section || 0}/{draftJob.section_count || longSections.length || 0}
                    </small>
                    {!!draftJob.error_message && <p>{draftJob.error_message}</p>}
                  </div>
                )}
                {!!generationWarnings.length && (
                  <div className="retrieval-debug">
                    <strong>生成提示</strong>
                    {generationWarnings.map((item) => (
                      <p key={item}>{item}</p>
                    ))}
                  </div>
                )}
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
                        {!!compactSourceRef(item.source_ref) && <small className="source-ref">{compactSourceRef(item.source_ref)}</small>}
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
                        <small>
                          used_knowledge {section.used_knowledge.length} · supplement {section.supplement_count || 0} · cjk {section.cjk_chars || 0}
                        </small>
                      </article>
                    ))}
                  </div>
                )}
                <pre>{draft || outline || "生成结果会显示在下方正文区；这里保留最近一次 used_knowledge 和 prompt preview。"}</pre>
                {promptPreview && (
                  <>
                    <h3>Prompt Preview</h3>
                    <pre>{promptPreview}</pre>
                  </>
                )}
              </div>
            )}
          </div>

          <div className="agent-two-col">
            <form className="panel compact-form" onSubmit={searchRAG}>
              <h2>RAG 召回预览</h2>
              <label>
                任务或关键词
                <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="例如：黄金三章如何制造期待？" />
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
                  <input type="number" min={1} max={30} value={ragTopK} onChange={(event) => setRagTopK(Number(event.target.value) || 8)} />
                </label>
                <label>
                  Volume
                  <input type="number" min={1} value={currentVolumeIndex} onChange={(event) => setCurrentVolumeIndex(Number(event.target.value) || 1)} />
                </label>
                <label>
                  Chapter
                  <input type="number" min={1} value={currentChapterIndex} onChange={(event) => setCurrentChapterIndex(Number(event.target.value) || 1)} />
                </label>
              </div>
              <button className="primary" disabled={!selected || busy === "rag-search"}>
                测试召回
              </button>
              {retrievalDebug && (
                <div className="retrieval-debug">
                  <strong>召回策略</strong>
                  <small>
                    {retrievalDebug.stage} · top_k {retrievalDebug.top_k} · 候选 {retrievalDebug.total_candidates} · 选中 {retrievalDebug.selected_count}
                    {!!retrievalDebug.filtered_duplicate_count && ` · 去重 ${retrievalDebug.filtered_duplicate_count}`}
                  </small>
                  <small>
                    pos V{retrievalDebug.current_volume_index ?? "-"} / C{retrievalDebug.current_chapter_index ?? "-"} · scope{" "}
                    {retrievalDebug.candidate_count_before_scope_filter ?? 0} → {retrievalDebug.candidate_count_after_scope_filter ?? 0} · future{" "}
                    {retrievalDebug.filtered_by_future_count ?? 0} · status {retrievalDebug.filtered_by_status_count ?? 0}
                  </small>
                  {retrievalDebug.raw_query && <p>raw: {retrievalDebug.raw_query}</p>}
                  <p>{retrievalDebug.preferred_card_types.join(" / ")}</p>
                  {!!retrievalDebug.expanded_terms?.length && <p>{retrievalDebug.expanded_terms.slice(0, 16).join(" / ")}</p>}
                  {!!retrievalDebug.selected_card_ids?.length && <p>{retrievalDebug.selected_card_ids.map((id) => `${id}:${retrievalDebug.selected_card_scope?.[id] || "scope"}`).join(" / ")}</p>}
                </div>
              )}
              <div className="hit-list">
                {ragResults.map((hit) => (
                  <article key={hit.id}>
                    <strong>{hit.title}</strong>
                    <small>
                      {hit.library_type} / {hit.card_type} · score {hit.score}
                    </small>
                    {!!hit.tags.length && (
                      <div className="tag-row">
                        {hit.tags.slice(0, 6).map((tag) => (
                          <span key={tag}>{tag}</span>
                        ))}
                      </div>
                    )}
                    {!!compactSourceRef(hit.source_ref) && <small className="source-ref">{compactSourceRef(hit.source_ref)}</small>}
                    <p>{hit.content_preview || "本次生成使用了这张知识卡。"}</p>
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
                  目标字数
                  <input type="number" min={500} max={50000} step={500} value={targetChars} onChange={(event) => setTargetChars(Number(event.target.value) || 3000)} />
                </label>
                <label>
                  RAG top_k
                  <input type="number" min={1} max={30} value={ragTopK} onChange={(event) => setRagTopK(Number(event.target.value) || 8)} />
                </label>
                <label>
                  Volume
                  <input type="number" min={1} value={currentVolumeIndex} onChange={(event) => setCurrentVolumeIndex(Number(event.target.value) || 1)} />
                </label>
                <label>
                  Chapter
                  <input type="number" min={1} value={currentChapterIndex} onChange={(event) => setCurrentChapterIndex(Number(event.target.value) || 1)} />
                </label>
              </div>
              {targetChars > 2500 && <small className="warn-cell">目标字数较长，正文生成会自动分段并合并结果。</small>}
              <div className="mode-grid">
                <label>
                  模型选择
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
                  <input
                    type="password"
                    value={writingApiKey}
                    onChange={(event) => setWritingApiKey(event.target.value)}
                    placeholder={selectedWritingModel?.provider === "doubao" ? "填写你的豆包 Ark API Key" : "填写你的模型 API Key"}
                  />
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
                dry-run：不调用模型，只验证检索和引用
              </label>
              {modelCallBlocked && <small className="warn-cell">关闭 dry-run 后，请先填写你自己的 API Key。</small>}
              <button className="primary" disabled={!selected || busy === "outline" || modelCallBlocked}>
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
              <button className="primary" disabled={!selected || !confirmedOutline.trim() || busy === "draft" || modelCallBlocked}>
                根据确认提纲生成正文
              </button>
              <div className="button-row">
                <button type="button" disabled={!selected || !confirmedOutline.trim() || busy === "draft-job" || modelCallBlocked} onClick={startDraftJob}>
                  后台长文本任务
                </button>
                <button type="button" disabled={!draftJob || ["completed", "failed", "cancelled"].includes(draftJob.status) || busy === "draft-job-cancel"} onClick={cancelDraftJob}>
                  取消任务
                </button>
              </div>
              <div className="preview-panel inline-output">
                <div className="preview-toolbar">
                  <strong>小说正文</strong>
                  <div className="button-row">
                    <button type="button" disabled={!draft} onClick={() => navigator.clipboard.writeText(draft)}>
                      复制正文
                    </button>
                    <button type="button" disabled={!selected || !draft || busy === "revision" || modelCallBlocked} onClick={generateRevision}>
                      润色/改写正文
                    </button>
                    <button
                      type="button"
                      disabled={!selected || !draft || busy === "memory"}
                      onClick={async () => {
                        if (!selected || !draft) return;
                        setBusy("memory");
                        setError("");
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
                      }}
                    >
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
              <button type="button" onClick={generateWorldbuildingDraft} disabled={!selected || busy === "worldbuilding" || modelCallBlocked}>
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
