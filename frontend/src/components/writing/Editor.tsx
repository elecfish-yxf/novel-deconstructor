import { Dispatch } from "react";
import { WritingAction, WritingState } from "./types";
import { parsePositionInput, defaultChapterTitle } from "./utils";
import { KnowledgeBase, getWorkspaceId } from "../../api";

interface Props {
  state: WritingState; dispatch: Dispatch<WritingAction>;
  selected: KnowledgeBase | null;
  positionMissing: boolean; activeDraftJob: boolean;
  draftWordCount: number; modelCallBlocked: boolean;
  startDraftJob: () => Promise<void>;
  generateRevision: () => Promise<void>;
  cancelDraftJob: () => Promise<void>;
  saveDraftToMemory: () => Promise<void>;
  deleteCurrentChapter: () => Promise<void>;
}

export function Editor({ state, dispatch, selected, positionMissing, activeDraftJob, draftWordCount, modelCallBlocked, startDraftJob, generateRevision, cancelDraftJob, saveDraftToMemory, deleteCurrentChapter }: Props) {
  const copyText = async (text: string, label: string) => {
    if (!text) return;
    try { await navigator.clipboard.writeText(text); dispatch({ type: "SET_MESSAGE", message: `${label}已复制` }); }
    catch { const ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove(); dispatch({ type: "SET_MESSAGE", message: `${label}已复制` }); }
  };

  const updateChapterTitle = (value: string) => {
    dispatch({ type: "SET_CHAPTER_TITLE", title: value });
    if (!selected || typeof state.currentVolumeIndex !== "number" || typeof state.currentChapterIndex !== "number") return;
    const key = `${getWorkspaceId()}:${selected.id}:${state.currentVolumeIndex}:${state.currentChapterIndex}`;
    dispatch({ type: "SET_CHAPTER_TITLES", titles: { ...state.chapterTitles, [key]: value } });
  };

  return (
    <main className="writing-agent-editor">
      <div className="writing-editor-titlebar">
        <input value={state.chapterTitle} onChange={(e) => updateChapterTitle(e.target.value)} placeholder="请输入章节标题" />
        <div className="writing-editor-position">
          <label>V <input type="number" min={1} value={state.currentVolumeIndex}
            onChange={(e) => { const nv = parsePositionInput(e.target.value); if (typeof nv === "number") {
              const ch = typeof state.currentChapterIndex === "number" ? state.currentChapterIndex : 1;
              dispatch({ type: "SET_CURRENT_VOLUME", index: nv }); dispatch({ type: "SET_CURRENT_CHAPTER", index: ch });
              if (selected) dispatch({ type: "SET_CHAPTER_TITLE", title: state.chapterTitles[`${getWorkspaceId()}:${selected.id}:${nv}:${ch}`] || defaultChapterTitle(ch) });
            } else dispatch({ type: "SET_CURRENT_VOLUME", index: nv }); }} /></label>
          <label>C <input type="number" min={1} value={state.currentChapterIndex}
            onChange={(e) => { const nc = parsePositionInput(e.target.value); if (typeof nc === "number") {
              const vol = typeof state.currentVolumeIndex === "number" ? state.currentVolumeIndex : 1;
              dispatch({ type: "SET_CURRENT_VOLUME", index: vol }); dispatch({ type: "SET_CURRENT_CHAPTER", index: nc });
              if (selected) dispatch({ type: "SET_CHAPTER_TITLE", title: state.chapterTitles[`${getWorkspaceId()}:${selected.id}:${vol}:${nc}`] || defaultChapterTitle(nc) });
            } else dispatch({ type: "SET_CURRENT_CHAPTER", index: nc }); }} /></label>
        </div>
      </div>
      <div className="writing-editor-toolbar">
        <button title="生成提纲" onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "outline" })}>提纲</button>
        <button title="生成正文" onClick={() => void startDraftJob()} disabled={!selected || !state.confirmedOutline.trim() || state.busy === "draft-job" || modelCallBlocked || positionMissing}>正文</button>
        <button title="润色正文" onClick={generateRevision} disabled={!selected || !state.draft || state.busy === "revision" || modelCallBlocked || positionMissing}>润色</button>
        <span className="writing-toolbar-divider" />
        <button title="复制正文" onClick={() => void copyText(state.draft, "正文")} disabled={!state.draft}>复制</button>
        <button title="清空正文" onClick={() => window.confirm("确定清空吗？") && dispatch({ type: "SET_DRAFT", draft: "" })} disabled={!state.draft}>清空</button>
        <button title="删除当前章节" onClick={deleteCurrentChapter} disabled={!selected || positionMissing || state.busy === "delete-current-chapter"}>删章</button>
        <button title="生成结果" onClick={() => { dispatch({ type: "SET_ASSISTANT_TAB", tab: "resources" }); dispatch({ type: "SET_ACTIVE_KNOWLEDGE_TAB", tab: "result" }); }}>结果</button>
        <div className="writing-word-count">字数：{draftWordCount}</div>
      </div>
      <div className="writing-editor-surface">
        <textarea value={state.draft} onChange={(e) => dispatch({ type: "SET_DRAFT", draft: e.target.value })} placeholder={state.confirmedOutline ? "正文生成后会显示在这里。" : "请先在右侧生成并确认提纲。"} />
      </div>
      {(activeDraftJob || state.generationWarnings.length > 0 || positionMissing) && (
        <div className="writing-editor-inline-status">
          {positionMissing && <span className="is-error">请填写当前 Volume 和 Chapter。</span>}
          {activeDraftJob && <span>长文本任务：{state.draftJob?.status} · {state.draftJob?.current_section || 0}/{state.draftJob?.section_count || state.longSections.length || 0}</span>}
          {state.generationWarnings.slice(0, 2).map((w) => <span key={w}>{w}</span>)}
        </div>
      )}
      <div className="writing-editor-footer">
        <div>
          <button className="primary" onClick={saveDraftToMemory} disabled={!selected || !state.draft || state.busy === "memory" || positionMissing}>保存草稿</button>
          <button onClick={() => { dispatch({ type: "SET_ASSISTANT_TAB", tab: "resources" }); dispatch({ type: "SET_ACTIVE_KNOWLEDGE_TAB", tab: "result" }); }}>预览</button>
        </div>
        <div>
          <button onClick={cancelDraftJob} disabled={!state.draftJob || !activeDraftJob || state.busy === "draft-job-cancel"}>取消任务</button>
          <button className="publish" onClick={saveDraftToMemory} disabled={!selected || !state.draft || state.busy === "memory" || positionMissing}>存入 Memory</button>
        </div>
      </div>
    </main>
  );
}
