import { Dispatch, FormEvent, PointerEvent } from "react";
import { WritingAction, WritingState, VolumeTreeNode } from "./types";
import { chapterSelectionKey, chapterTitleKey, defaultChapterTitle, parseChapterSelectionKey, parseChapterTitleKey } from "./utils";
import { KnowledgeBase } from "../../api";

interface Props {
  state: WritingState; dispatch: Dispatch<WritingAction>;
  selected: KnowledgeBase | null;
  workspaceId: string; volumeTree: VolumeTreeNode[];
  currentPositionPayload: { current_volume_index: number | null; current_chapter_index: number | null };
  selectedWorkSet: Set<number>; selectedVolumeSet: Set<number>; selectedChapterSet: Set<string>;
  createKnowledgeBase: (e: FormEvent) => Promise<void>;
  chooseKnowledgeBase: (id: number) => Promise<void>;
  selectWritingPosition: (v: number, c: number) => void;
  addVolume: () => void; addChapter: () => void;
  deleteSelectedWorks: () => Promise<void>;
  reloadWorkIfStillActive: (id: number) => Promise<void>;
  load: (id?: number | null) => Promise<void>;
}

export function LeftPanel({ state, dispatch, selected, workspaceId, volumeTree, currentPositionPayload, selectedWorkSet, selectedVolumeSet, selectedChapterSet, createKnowledgeBase, chooseKnowledgeBase, selectWritingPosition, addVolume, addChapter, deleteSelectedWorks, reloadWorkIfStillActive, load }: Props) {
  const toggleWork = (id: number) => {
    if (state.expandedWorkIds.includes(id)) {
      dispatch({ type: "SET_EXPANDED_WORK_IDS", ids: state.expandedWorkIds.filter((x) => x !== id) });
    } else { chooseKnowledgeBase(id).catch((err) => dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "加载失败" })); }
  };

  const toggleWorkSelection = (id: number) => dispatch({ type: "SET_SELECTED_WORK_IDS", ids: state.selectedWorkIds.includes(id) ? state.selectedWorkIds.filter((x) => x !== id) : [...state.selectedWorkIds, id] });
  const toggleVolumeSelection = (v: number) => dispatch({ type: "SET_SELECTED_VOLUME_KEYS", keys: state.selectedVolumeKeys.includes(v) ? state.selectedVolumeKeys.filter((x) => x !== v) : [...state.selectedVolumeKeys, v] });
  const toggleChapterSelection = (v: number, c: number) => { const k = chapterSelectionKey(v, c); dispatch({ type: "SET_SELECTED_CHAPTER_KEYS", keys: state.selectedChapterKeys.includes(k) ? state.selectedChapterKeys.filter((x) => x !== k) : [...state.selectedChapterKeys, k] }); };

  const deleteSelectedWritingScopes = async () => {
    if (!selected) return;
    const vols = state.selectedVolumeKeys.filter((v) => volumeTree.some((t) => t.volume === v));
    const chs = state.selectedChapterKeys.map(parseChapterSelectionKey).filter((item): item is { volume_index: number; chapter_index: number } => Boolean(item)).filter((ch) => volumeTree.some((t) => t.volume === ch.volume_index && t.chapters.some((c) => c.chapter === ch.chapter_index)));
    if (!vols.length && !chs.length) return;
    if (!window.confirm(`确定彻底删除选中的 ${vols.length} 个卷、${chs.length} 个章节吗？`)) return;
    dispatch({ type: "SET_BUSY", busy: "delete-scopes" });
    try {
      const r = await import("../../api").then((m) => m.api.bulkDeleteWritingScope(selected.id, { volume_indices: vols, chapters: chs }));
      dispatch({ type: "SET_SELECTED_VOLUME_KEYS", keys: [] });
      dispatch({ type: "SET_SELECTED_CHAPTER_KEYS", keys: [] });
      await load(selected.id);
      dispatch({ type: "SET_CURRENT_VOLUME", index: 1 });
      dispatch({ type: "SET_CURRENT_CHAPTER", index: 1 });
      dispatch({ type: "SET_CHAPTER_TITLE", title: defaultChapterTitle(1) });
      dispatch({ type: "SET_MESSAGE", message: r.message });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "删除失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  return (
    <aside className="writing-agent-left-panel" style={{ width: state.leftPanelWidth }}>
      <div className="writing-panel-head">
        <span>章节管理</span>
        <div>
          <button type="button" title="新建卷" onClick={addVolume} disabled={!selected}>卷+</button>
          <button type="button" title="新建章" onClick={addChapter} disabled={!selected}>章+</button>
          <button type="button" title="删除选中作品" onClick={deleteSelectedWorks} disabled={!state.selectedWorkIds.length || state.busy === "delete-works"}>删作品</button>
        </div>
      </div>
      <div className="writing-agent-left-scroll">
        <form className="writing-work-create" onSubmit={createKnowledgeBase}>
          <label>作品名 <input value={state.name} onChange={(e) => dispatch({ type: "SET_NAME", name: e.target.value })} /></label>
          <label>作品备注 <textarea rows={2} value={state.description} onChange={(e) => dispatch({ type: "SET_DESCRIPTION", description: e.target.value })} /></label>
          <button className="primary" disabled={state.busy === "create"}>新建作品</button>
        </form>
        <div className="writing-work-tree">
          {state.knowledgeBases.map((kb) => {
            const expanded = state.expandedWorkIds.includes(kb.id);
            const active = selected?.id === kb.id;
            return (
              <section key={kb.id} className={`writing-work-node ${active ? "active" : ""}`}>
                <div className="writing-work-node-head">
                  <input type="checkbox" checked={selectedWorkSet.has(kb.id)} onChange={() => toggleWorkSelection(kb.id)} />
                  <button className="writing-tree-toggle" onClick={() => toggleWork(kb.id)}>{expanded ? "⌄" : "›"}</button>
                  <button className="writing-work-title" onClick={() => chooseKnowledgeBase(kb.id)}>
                    <strong>{kb.name}</strong>
                    <small>{active ? `${volumeTree.length} 卷 · ${volumeTree.reduce((t, v) => t + v.chapters.length, 0)} 章` : "点击查看"}</small>
                  </button>
                </div>
                {expanded && active && (
                  <div className="writing-volume-tree">
                    <div className="writing-scope-toolbar">
                      <button onClick={deleteSelectedWritingScopes} disabled={(!state.selectedVolumeKeys.length && !state.selectedChapterKeys.length) || state.busy === "delete-scopes"}>删除所选卷章</button>
                      <button onClick={() => { dispatch({ type: "SET_SELECTED_VOLUME_KEYS", keys: [] }); dispatch({ type: "SET_SELECTED_CHAPTER_KEYS", keys: [] }); }}>取消选择</button>
                    </div>
                    {volumeTree.map((vol) => (
                      <section key={vol.volume} className="writing-volume-node">
                        <div className="writing-volume-head">
                          <label><input type="checkbox" checked={selectedVolumeSet.has(vol.volume)} onChange={() => toggleVolumeSelection(vol.volume)} /><span>卷 {vol.volume}</span></label>
                          <small>{vol.chapters.length} 章</small>
                        </div>
                        <div className="writing-chapter-list">
                          {vol.chapters.map((ch) => {
                            const activeCh = currentPositionPayload.current_volume_index === vol.volume && currentPositionPayload.current_chapter_index === ch.chapter;
                            return (
                              <div key={ch.chapter} className="writing-chapter-row">
                                <input type="checkbox" checked={selectedChapterSet.has(chapterSelectionKey(vol.volume, ch.chapter))} onChange={() => toggleChapterSelection(vol.volume, ch.chapter)} />
                                <button className={activeCh ? "active" : ""} onClick={() => selectWritingPosition(vol.volume, ch.chapter)}>
                                  <span>第 {ch.chapter} 章</span><strong>{ch.title}</strong>
                                  <small>{ch.memoryCount ? `${ch.memoryCount} 条 Memory` : "未写入"}</small>
                                </button>
                              </div>
                            );
                          })}
                        </div>
                      </section>
                    ))}
                  </div>
                )}
              </section>
            );
          })}
          {!state.knowledgeBases.length && <p className="muted file-empty">还没有作品。</p>}
        </div>
      </div>
    </aside>
  );
}
