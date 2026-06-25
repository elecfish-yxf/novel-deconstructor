import { WritingAction, WritingState } from "./types";

export function writingReducer(state: WritingState, action: WritingAction): WritingState {
  switch (action.type) {
    // Data loading
    case "SET_CONFIG": return { ...state, config: action.config };
    case "SET_KNOWLEDGE_BASES": return { ...state, knowledgeBases: action.bases };
    case "SET_SELECTED_ID": return { ...state, selectedId: action.id };
    case "SET_DOCUMENTS": return { ...state, documents: action.documents };
    case "SET_CARDS": return { ...state, cards: action.cards };
    case "SET_MARKDOWN_DOCS": return { ...state, markdownDocs: action.docs };
    case "SET_MERGE_STATS": return { ...state, mergeStats: action.stats };
    case "SET_MERGE_GROUPS": return { ...state, mergeGroups: action.groups };
    case "SET_MEMORIES": return { ...state, memories: action.memories };

    // Workspace
    case "SET_NAME": return { ...state, name: action.name };
    case "SET_DESCRIPTION": return { ...state, description: action.description };
    case "SET_EXPANDED_WORK_IDS": return { ...state, expandedWorkIds: action.ids };
    case "SET_EXPANDED_TYPES": return { ...state, expandedTypes: action.types };

    // Position
    case "SET_CURRENT_VOLUME": return { ...state, currentVolumeIndex: action.index };
    case "SET_CURRENT_CHAPTER": return { ...state, currentChapterIndex: action.index };
    case "SET_CHAPTER_TITLE": return { ...state, chapterTitle: action.title };
    case "SET_CHAPTER_TITLES": return { ...state, chapterTitles: action.titles };

    // Outline
    case "SET_OUTLINE_TASK": return { ...state, outlineTask: action.task };
    case "SET_OUTLINE_SCOPE": return { ...state, outlineScope: action.scope };
    case "SET_OUTLINE": return { ...state, outline: action.outline };
    case "SET_CONFIRMED_OUTLINE": return { ...state, confirmedOutline: action.outline };

    // Draft
    case "SET_DRAFT": return { ...state, draft: action.draft };
    case "SET_TARGET_CHARS": return { ...state, targetChars: action.chars };
    case "SET_ACTUAL_CHARS": return { ...state, actualChars: action.chars };

    // Query & RAG
    case "SET_QUERY": return { ...state, query: action.query };
    case "SET_RAG_STAGE": return { ...state, ragStage: action.stage };
    case "SET_RAG_TOP_K": return { ...state, ragTopK: action.k };
    case "SET_RAG_RESULTS": return { ...state, ragResults: action.results };
    case "SET_RETRIEVAL_DEBUG": return { ...state, retrievalDebug: action.debug };
    case "SET_USED_KNOWLEDGE": return { ...state, usedKnowledge: action.knowledge };
    case "SET_PROMPT_PREVIEW": return { ...state, promptPreview: action.preview };
    case "SET_HITS": return { ...state, hits: action.hits };
    case "SET_CITATIONS": return { ...state, citations: action.citations };

    // Worldbuilding
    case "SET_WORLDBUILDING_DRAFT": return { ...state, worldbuildingDraft: action.draft };
    case "SET_STORY_SEED": return { ...state, storySeed: action.seed };

    // Long generation
    case "SET_LONG_SECTIONS": return { ...state, longSections: action.sections };
    case "SET_GENERATION_WARNINGS": return { ...state, generationWarnings: action.warnings };
    case "SET_DRAFT_JOB": return { ...state, draftJob: action.job };

    // Memory
    case "SET_MEMORY_TYPE": return { ...state, memoryType: action.mtype };
    case "SET_MEMORY_TITLE": return { ...state, memoryTitle: action.title };
    case "SET_MEMORY_CONTENT": return { ...state, memoryContent: action.content };

    // Generation settings
    case "SET_MODE": return { ...state, mode: action.mode };
    case "SET_KNOWLEDGE_MODE": return { ...state, knowledgeMode: action.mode };
    case "SET_DRY_RUN": return { ...state, dryRun: action.dry };
    case "SET_WRITING_MODEL_ID": return { ...state, writingModelId: action.id };
    case "SET_WRITING_API_KEY": return { ...state, writingApiKey: action.key };

    // Navigation
    case "SET_MAIN_NAV_TAB": return { ...state, mainNavTab: action.tab };
    case "SET_ASSISTANT_TAB": return { ...state, assistantTab: action.tab };
    case "SET_ACTIVE_KNOWLEDGE_TAB": return { ...state, activeKnowledgeTab: action.tab };

    // Panel
    case "SET_LEFT_PANEL_WIDTH": return { ...state, leftPanelWidth: action.width };
    case "SET_RIGHT_PANEL_WIDTH": return { ...state, rightPanelWidth: action.width };

    // Status
    case "SET_BUSY": return { ...state, busy: action.busy };
    case "SET_MESSAGE": return { ...state, message: action.message };
    case "SET_ERROR": return { ...state, error: action.error };

    // Card filters
    case "SET_CARD_TYPE_FILTER": return { ...state, cardTypeFilter: action.filter };
    case "SET_SHOW_RAW_CARDS": return { ...state, showRawCards: action.show };
    case "SET_SELECTED_CARD_ID": return { ...state, selectedCardId: action.id };
    case "SET_SELECTED_DOC_ID": return { ...state, selectedDocId: action.id };
    case "SET_MARKDOWN_CONTENT": return { ...state, markdownContent: action.content };

    // Upload
    case "SET_UPLOAD_TYPE": return { ...state, uploadType: action.utype };
    case "SET_PACKAGE_PATH": return { ...state, packagePath: action.path };
    case "SET_MARKDOWN_SOURCE_PATH": return { ...state, markdownSourcePath: action.path };

    // Selection
    case "SET_SELECTED_WORK_IDS": return { ...state, selectedWorkIds: action.ids };
    case "SET_SELECTED_VOLUME_KEYS": return { ...state, selectedVolumeKeys: action.keys };
    case "SET_SELECTED_CHAPTER_KEYS": return { ...state, selectedChapterKeys: action.keys };
    case "SET_SELECTED_DOCUMENT_IDS": return { ...state, selectedDocumentIds: action.ids };
    case "SET_SELECTED_CARD_IDS": return { ...state, selectedCardIds: action.ids };
    case "SET_SELECTED_DOC_IDS": return { ...state, selectedDocIds: action.ids };
    case "SET_SELECTED_MEMORY_IDS": return { ...state, selectedMemoryIds: action.ids };
    case "SET_DEBUG_RAW_KNOWLEDGE": return { ...state, debugRawKnowledge: action.debug };

    // Clear transient state (between chapter switches)
    case "CLEAR_TRANSIENT":
      return {
        ...state,
        hits: [], ragResults: [], retrievalDebug: null,
        usedKnowledge: [], promptPreview: "", citations: [],
        worldbuildingDraft: "", outline: "", confirmedOutline: "",
        draft: "", actualChars: null, longSections: [],
        generationWarnings: [], draftJob: null,
      };

    default:
      return state;
  }
}
