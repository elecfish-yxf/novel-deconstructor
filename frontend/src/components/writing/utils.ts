import { ChapterRef, ChapterTitleMap, OptionalNumberValue, OutlineScope, ParsedOutlineNode, PositionValue } from "./types";
import { getWorkspaceId } from "../../api";

// ── Position parsing ──

export function parsePositionInput(value: string): PositionValue {
  if (value.trim() === "") return "";
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed < 1) return "";
  return Math.floor(parsed);
}

export function parseOptionalNumberInput(value: string, min: number, max: number): OptionalNumberValue {
  if (value.trim() === "") return "";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return "";
  return Math.min(max, Math.max(min, Math.floor(parsed)));
}

export function resolveOptionalNumber(value: OptionalNumberValue, fallback: number) {
  return typeof value === "number" ? value : fallback;
}

// ── Formatting ──

export function formatSize(value: number) {
  if (value > 1024 * 1024) return `${(value / 1024 / 1024).toFixed(1)} MB`;
  if (value > 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${value} B`;
}

// ── Chapter keys ──

export function chapterTitleKey(workspaceId: string, workId: number, volume: number, chapter: number) {
  return `${workspaceId}:${workId}:${volume}:${chapter}`;
}

export function chapterSelectionKey(volume: number, chapter: number) {
  return `${volume}:${chapter}`;
}

export function parseChapterSelectionKey(key: string): ChapterRef | null {
  const [volume, chapter] = key.split(":").map(Number);
  if (!Number.isFinite(volume) || !Number.isFinite(chapter) || volume < 1 || chapter < 1) return null;
  return { volume_index: volume, chapter_index: chapter };
}

export function parseChapterTitleKey(key: string) {
  const parts = key.split(":");
  const chapter = Number(parts.pop());
  const volume = Number(parts.pop());
  const workId = Number(parts.pop());
  const workspaceId = parts.join(":");
  if (!workspaceId || !Number.isFinite(workId) || !Number.isFinite(volume) || !Number.isFinite(chapter)) return null;
  return { workspaceId, workId, volume, chapter };
}

export function defaultChapterTitle(chapter: number) {
  return `第 ${chapter} 章`;
}

// ── LocalStorage helpers ──

const CHAPTER_TITLE_KEY = "novel-deconstructor.chapter-titles";
const DRAFT_JOB_KEY = "novel-deconstructor.last-draft-job";

export function readChapterTitles(): ChapterTitleMap {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(CHAPTER_TITLE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch { return {}; }
}

export function writeChapterTitles(titles: ChapterTitleMap) {
  window.localStorage.setItem(CHAPTER_TITLE_KEY, JSON.stringify(titles));
}

export function storeDraftJobRef(workId: number, jobId: string) {
  window.localStorage.setItem(DRAFT_JOB_KEY, JSON.stringify({ workId, jobId }));
}

export function readDraftJobRef(): { workId: number; jobId: string } | null {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(DRAFT_JOB_KEY) || "null");
    return typeof parsed?.workId === "number" && typeof parsed?.jobId === "string" ? parsed : null;
  } catch { return null; }
}

// ── Outline parsing ──

export function isGlobalOutlineLine(text: string) {
  const trimmed = text.trim();
  return /^(?:#\s*)?(?:全书|全局|global|full novel|complete novel|novel outline|第.*书)/i.test(trimmed);
}

export function isVolumeOutlineLine(text: string) {
  const trimmed = text.trim();
  return /^(?:#{1,2}\s*)?(?:\d+\s*[.\u3002]\s*)?(?:第\s*[一二三四五六七八九十百千万\d]+\s*卷|volume|vol\.?|volume\s*outline|卷纲|全卷)\b/i.test(trimmed);
}

export function isChapterOutlineLine(text: string) {
  const trimmed = text.trim();
  return /^(?:#{1,3}\s*)?(?:\d+\s*[.\u3002]\s*)?(?:第\s*[一二三四五六七八九十百千万\d]+\s*章|第\s*[一二三四五六七八九十百千万\d]+\s*节|chapter|ch\.?|chapter\s*outline)/i.test(trimmed);
}

export function parseOutlineContent(content: string): ParsedOutlineNode[] {
  const lines = (content || "").split(/\r?\n/);
  const roots: ParsedOutlineNode[] = [];
  const stack: ParsedOutlineNode[] = [];

  const appendToCurrent = (line: string) => {
    if (!line) return;
    if (!stack.length) {
      if (roots.length && roots[0]?.heading === "提纲正文") {
        roots[0].body.push(line);
      } else {
        roots.push({ heading: "提纲正文", level: 1, body: [line], children: [] });
      }
      return;
    }
    stack[stack.length - 1].body.push(line);
  };

  for (const rawLine of lines) {
    const trimmed = rawLine.trim();
    if (!trimmed) { appendToCurrent(""); continue; }

    let level = 0; let heading = "";
    const headingMatch = rawLine.match(/^(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      level = headingMatch[1].length; heading = headingMatch[2].trim();
    } else if (isGlobalOutlineLine(trimmed)) {
      level = 1; heading = trimmed;
    } else if (isVolumeOutlineLine(trimmed)) {
      level = 2; heading = trimmed;
    } else if (isChapterOutlineLine(trimmed)) {
      level = 3; heading = trimmed;
    }

    if (!level || !heading) { appendToCurrent(rawLine); continue; }

    while (stack.length && stack[stack.length - 1].level >= level) { stack.pop(); }
    const node: ParsedOutlineNode = { heading, level, body: [], children: [] };
    if (stack.length) { stack[stack.length - 1].children.push(node); }
    else { roots.push(node); }
    stack.push(node);
  }

  return roots;
}

// ── Outline scope ──

export const OUTLINE_SCOPE_OPTIONS: Array<{ value: OutlineScope; label: string }> = [
  { value: "chapter", label: "章节" },
  { value: "volume", label: "全卷" },
  { value: "global", label: "全书" },
];

export const OUTLINE_SCOPE_HINTS: Record<OutlineScope, string> = {
  chapter: "生成当前章节提纲（书卷层大纲自动同步至知识卡）",
  volume: "生成当前卷完整提纲（书卷层大纲自动同步至知识卡）",
  global: "生成全书完整提纲（书卷层大纲自动同步至知识卡）",
};

export function getOutlineScopePayload(
  scopeLevel: OutlineScope,
  currentVolumeIndex: number | null,
  currentChapterIndex: number | null,
) {
  if (scopeLevel === "global") return { scope_level: "global" as const, volume_index: null, chapter_index: null };
  if (scopeLevel === "volume") return { scope_level: "volume" as const, volume_index: currentVolumeIndex, chapter_index: null };
  return { scope_level: "chapter" as const, volume_index: currentVolumeIndex, chapter_index: currentChapterIndex };
}

export function isOutlinePositionMissing(scopeLevel: OutlineScope, currentVolumeIndex: number | null, currentChapterIndex: number | null) {
  if (scopeLevel === "global") return false;
  if (scopeLevel === "volume") return !currentVolumeIndex;
  return !currentVolumeIndex || !currentChapterIndex;
}

// ── Knowledge labels ──

const KNOWLEDGE_GROUPS = [
  { key: "writing_guide", label: "写作技巧指南", hint: "拆书沉淀出的结构、节奏、爽点、人物塑造方法。" },
  { key: "worldbuilding", label: "世界观设定", hint: "用户提供或确认导入的原创世界观、人物、地点与规则。" },
] as const;

export function knowledgeTypeLabel(type: string) {
  return KNOWLEDGE_GROUPS.find((group) => group.key === type)?.label || type;
}

export function documentTitle(document: { document_title: string; original_filename: string }) {
  return document.document_title || document.original_filename;
}

export function compactSourceRef(sourceRef: Record<string, unknown>) {
  const entries = Object.entries(sourceRef || {});
  if (!entries.length) return "";
  return entries.slice(0, 3).map(([key, value]) => `${key}: ${typeof value === "object" && value !== null ? JSON.stringify(value) : String(value)}`).join(" · ");
}
