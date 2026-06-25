import { Dispatch } from "react";

export type PositionValue = number | "";
export type OptionalNumberValue = number | "";
export type ChapterTitleMap = Record<string, string>;
export type OutlineScope = "global" | "volume" | "chapter";

export type ChapterRef = { volume_index: number; chapter_index: number };
export type ParsedOutlineNode = {
  heading: string;
  level: number;
  body: string[];
  children: ParsedOutlineNode[];
};

export type VolumeTreeNode = {
  volume: number;
  chapters: { chapter: number; title: string; memoryCount: number }[];
};

export type WritingTab = "outline" | "memory" | "worldbuilding" | "resources";
export type MainNavTab = "memory" | "writing_guide" | "worldbuilding" | "history";
export type ActiveKnowledgeTab = "cards" | "files" | "docs" | "result";

// ── Actions ──

export type WritingAction =
  | { type: "SET_CONFIG"; config: import("../../api").PublicConfig | null }
  | { type: "SET_KNOWLEDGE_BASES"; bases: import("../../api").KnowledgeBase[] }
  | { type: "SET_SELECTED_ID"; id: number | null }
  | { type: "SET_DOCUMENTS"; documents: import("../../api").KnowledgeDocument[] }
  | { type: "SET_CARDS"; cards: import("../../api").KnowledgeCard[] }
  | { type: "SET_MARKDOWN_DOCS"; docs: import("../../api").KnowledgeMarkdownDoc[] }
  | { type: "SET_MERGE_STATS"; stats: import("../../api").KnowledgeMergeStats | null }
  | { type: "SET_MERGE_GROUPS"; groups: import("../../api").KnowledgeMergeGroup[] }
  | { type: "SET_MEMORIES"; memories: import("../../api").WritingMemory[] }
  | { type: "SET_NAME"; name: string }
  | { type: "SET_DESCRIPTION"; description: string }
  | { type: "SET_EXPANDED_WORK_IDS"; ids: number[] }
  | { type: "SET_CURRENT_VOLUME"; index: PositionValue }
  | { type: "SET_CURRENT_CHAPTER"; index: PositionValue }
  | { type: "SET_CHAPTER_TITLE"; title: string }
  | { type: "SET_CHAPTER_TITLES"; titles: ChapterTitleMap }
  | { type: "SET_OUTLINE_TASK"; task: string }
  | { type: "SET_OUTLINE_SCOPE"; scope: OutlineScope }
  | { type: "SET_OUTLINE"; outline: string }
  | { type: "SET_CONFIRMED_OUTLINE"; outline: string }
  | { type: "SET_DRAFT"; draft: string }
  | { type: "SET_TARGET_CHARS"; chars: OptionalNumberValue }
  | { type: "SET_ACTUAL_CHARS"; chars: number | null }
  | { type: "SET_QUERY"; query: string }
  | { type: "SET_RAG_STAGE"; stage: string }
  | { type: "SET_RAG_TOP_K"; k: OptionalNumberValue }
  | { type: "SET_RAG_RESULTS"; results: import("../../api").RAGSearchResult[] }
  | { type: "SET_RETRIEVAL_DEBUG"; debug: import("../../api").RetrievalDebug | null }
  | { type: "SET_USED_KNOWLEDGE"; knowledge: import("../../api").UsedKnowledge[] }
  | { type: "SET_PROMPT_PREVIEW"; preview: string }
  | { type: "SET_HITS"; hits: import("../../api").RetrievalHit[] }
  | { type: "SET_CITATIONS"; citations: import("../../api").RetrievalHit[] }
  | { type: "SET_WORLDBUILDING_DRAFT"; draft: string }
  | { type: "SET_LONG_SECTIONS"; sections: import("../../api").LongGenerationSection[] }
  | { type: "SET_GENERATION_WARNINGS"; warnings: string[] }
  | { type: "SET_DRAFT_JOB"; job: import("../../api").WritingDraftJob | null }
  | { type: "SET_MEMORY_TYPE"; mtype: string }
  | { type: "SET_MEMORY_TITLE"; title: string }
  | { type: "SET_MEMORY_CONTENT"; content: string }
  | { type: "SET_MODE"; mode: string }
  | { type: "SET_KNOWLEDGE_MODE"; mode: string }
  | { type: "SET_DRY_RUN"; dry: boolean }
  | { type: "SET_WRITING_MODEL_ID"; id: string }
  | { type: "SET_WRITING_API_KEY"; key: string }
  | { type: "SET_MAIN_NAV_TAB"; tab: MainNavTab }
  | { type: "SET_ASSISTANT_TAB"; tab: WritingTab }
  | { type: "SET_ACTIVE_KNOWLEDGE_TAB"; tab: ActiveKnowledgeTab }
  | { type: "SET_LEFT_PANEL_WIDTH"; width: number }
  | { type: "SET_RIGHT_PANEL_WIDTH"; width: number }
  | { type: "SET_BUSY"; busy: string }
  | { type: "SET_MESSAGE"; message: string }
  | { type: "SET_ERROR"; error: string }
  | { type: "SET_CARD_TYPE_FILTER"; filter: string }
  | { type: "SET_SHOW_RAW_CARDS"; show: boolean }
  | { type: "SET_SELECTED_CARD_ID"; id: string }
  | { type: "SET_SELECTED_DOC_ID"; id: string }
  | { type: "SET_MARKDOWN_CONTENT"; content: string }
  | { type: "SET_UPLOAD_TYPE"; utype: string }
  | { type: "SET_STORY_SEED"; seed: string }
  | { type: "SET_PACKAGE_PATH"; path: string }
  | { type: "SET_MARKDOWN_SOURCE_PATH"; path: string }
  | { type: "SET_EXPANDED_TYPES"; types: Record<string, boolean> }
  | { type: "SET_SELECTED_WORK_IDS"; ids: number[] }
  | { type: "SET_SELECTED_VOLUME_KEYS"; keys: number[] }
  | { type: "SET_SELECTED_CHAPTER_KEYS"; keys: string[] }
  | { type: "SET_SELECTED_DOCUMENT_IDS"; ids: number[] }
  | { type: "SET_SELECTED_CARD_IDS"; ids: string[] }
  | { type: "SET_SELECTED_DOC_IDS"; ids: string[] }
  | { type: "SET_SELECTED_MEMORY_IDS"; ids: number[] }
  | { type: "SET_DEBUG_RAW_KNOWLEDGE"; debug: boolean }
  | { type: "CLEAR_TRANSIENT" };

export type WritingDispatch = Dispatch<WritingAction>;

// ── State ──

export interface WritingState {
  config: import("../../api").PublicConfig | null;
  knowledgeBases: import("../../api").KnowledgeBase[];
  selectedId: number | null;
  documents: import("../../api").KnowledgeDocument[];
  cards: import("../../api").KnowledgeCard[];
  markdownDocs: import("../../api").KnowledgeMarkdownDoc[];
  mergeStats: import("../../api").KnowledgeMergeStats | null;
  mergeGroups: import("../../api").KnowledgeMergeGroup[];
  memories: import("../../api").WritingMemory[];
  name: string;
  description: string;
  expandedWorkIds: number[];
  expandedTypes: Record<string, boolean>;
  currentVolumeIndex: PositionValue;
  currentChapterIndex: PositionValue;
  chapterTitle: string;
  chapterTitles: ChapterTitleMap;
  outlineTask: string;
  outlineScope: OutlineScope;
  outline: string;
  confirmedOutline: string;
  draft: string;
  targetChars: OptionalNumberValue;
  actualChars: number | null;
  query: string;
  ragStage: string;
  ragTopK: OptionalNumberValue;
  ragResults: import("../../api").RAGSearchResult[];
  retrievalDebug: import("../../api").RetrievalDebug | null;
  usedKnowledge: import("../../api").UsedKnowledge[];
  promptPreview: string;
  hits: import("../../api").RetrievalHit[];
  citations: import("../../api").RetrievalHit[];
  worldbuildingDraft: string;
  longSections: import("../../api").LongGenerationSection[];
  generationWarnings: string[];
  draftJob: import("../../api").WritingDraftJob | null;
  memoryType: string;
  memoryTitle: string;
  memoryContent: string;
  mode: string;
  knowledgeMode: string;
  dryRun: boolean;
  writingModelId: string;
  writingApiKey: string;
  mainNavTab: MainNavTab;
  assistantTab: WritingTab;
  activeKnowledgeTab: ActiveKnowledgeTab;
  leftPanelWidth: number;
  rightPanelWidth: number;
  busy: string;
  message: string;
  error: string;
  cardTypeFilter: string;
  showRawCards: boolean;
  selectedCardId: string;
  selectedDocId: string;
  markdownContent: string;
  uploadType: string;
  storySeed: string;
  packagePath: string;
  markdownSourcePath: string;
  selectedWorkIds: number[];
  selectedVolumeKeys: number[];
  selectedChapterKeys: string[];
  selectedDocumentIds: number[];
  selectedCardIds: string[];
  selectedDocIds: string[];
  selectedMemoryIds: number[];
  debugRawKnowledge: boolean;
}

export function getInitialState(): WritingState {
  return {
    config: null, knowledgeBases: [], selectedId: null,
    documents: [], cards: [], markdownDocs: [], mergeStats: null, mergeGroups: [],
    memories: [], name: "作品 1", description: "用于 AI 写作 Agent 的独立作品空间",
    expandedWorkIds: [], expandedTypes: { writing_guide: true, worldbuilding: true },
    currentVolumeIndex: 1, currentChapterIndex: 1, chapterTitle: "第 1 章",
    chapterTitles: {}, outlineTask: "请基于世界观设定，结合写作技巧指南，为我生成一份原创小说第一章章节提纲。",
    outlineScope: "chapter", outline: "", confirmedOutline: "", draft: "",
    targetChars: 3000, actualChars: null, query: "", ragStage: "draft", ragTopK: 8,
    ragResults: [], retrievalDebug: null, usedKnowledge: [], promptPreview: "",
    hits: [], citations: [], worldbuildingDraft: "", longSections: [],
    generationWarnings: [], draftJob: null, memoryType: "note", memoryTitle: "",
    memoryContent: "", mode: "fast", knowledgeMode: "reference", dryRun: true,
    writingModelId: "", writingApiKey: "", mainNavTab: "memory", assistantTab: "outline",
    activeKnowledgeTab: "cards", leftPanelWidth: 276, rightPanelWidth: 340,
    busy: "", message: "", error: "", cardTypeFilter: "all", showRawCards: false,
    selectedCardId: "", selectedDocId: "", markdownContent: "",
    uploadType: "writing_guide", storySeed: "一个普通人在高压规则世界中寻找自我选择权。",
    packagePath: "", markdownSourcePath: "",
    selectedWorkIds: [], selectedVolumeKeys: [], selectedChapterKeys: [],
    selectedDocumentIds: [], selectedCardIds: [], selectedDocIds: [],
    selectedMemoryIds: [], debugRawKnowledge: false,
  };
}
