import { Dispatch, FormEvent } from "react";
import { WritingAction, WritingState } from "./types";
import { KnowledgeBase } from "../../api";
import { api } from "../../api";

interface Props {
  state: WritingState; dispatch: Dispatch<WritingAction>;
  selected: KnowledgeBase | null;
  currentPositionPayload: { current_volume_index: number | null; current_chapter_index: number | null };
  refreshKnowledgeCards: (id?: number) => Promise<void>;
}

export function MemoryPanel({ state, dispatch, selected, currentPositionPayload, refreshKnowledgeCards }: Props) {
  const saveMemory = async (title: string, content: string, type = state.memoryType, source = "manual") => {
    if (!selected || !title.trim() || !content.trim()) return;
    dispatch({ type: "SET_BUSY", busy: "memory" });
    try {
      const saved = await api.createWritingMemory({
        knowledge_base_id: selected.id, memory_type: type, title, content,
        tags: [type], source, scope_level: "chapter",
        volume_index: currentPositionPayload.current_volume_index,
        chapter_index: currentPositionPayload.current_chapter_index,
      });
      dispatch({ type: "SET_MEMORIES", memories: [saved, ...state.memories] });
      await refreshKnowledgeCards(selected.id);
      dispatch({ type: "SET_MEMORY_TITLE", title: "" });
      dispatch({ type: "SET_MEMORY_CONTENT", content: "" });
      dispatch({ type: "SET_MESSAGE", message: "Memory 已保存。" });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "保存失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const deleteMemory = async (id: number) => {
    if (!selected || !window.confirm("确定删除这条 Memory 吗？")) return;
    dispatch({ type: "SET_BUSY", busy: `memory-${id}` });
    try {
      await api.deleteWritingMemory(id);
      dispatch({ type: "SET_MEMORIES", memories: state.memories.filter((m) => m.id !== id) });
      dispatch({ type: "SET_SELECTED_MEMORY_IDS", ids: state.selectedMemoryIds.filter((x) => x !== id) });
      await refreshKnowledgeCards(selected.id);
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "删除失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const deleteSelectedMemories = async () => {
    if (!selected || !state.selectedMemoryIds.length) return;
    const ids = state.selectedMemoryIds.filter((id) => state.memories.some((m) => m.id === id));
    if (!ids.length) return;
    if (!window.confirm(`确定删除选中的 ${ids.length} 条 Memory 吗？`)) return;
    dispatch({ type: "SET_BUSY", busy: "delete-memories" });
    try {
      const r = await api.bulkDeleteWritingMemories(ids);
      dispatch({ type: "SET_SELECTED_MEMORY_IDS", ids: [] });
      dispatch({ type: "SET_MEMORIES", memories: state.memories.filter((m) => !ids.includes(m.id)) });
      await refreshKnowledgeCards(selected.id);
      dispatch({ type: "SET_MESSAGE", message: r.message });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "删除失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  return (
    <>
      <form className="writing-side-card" onSubmit={(e) => { e.preventDefault(); saveMemory(state.memoryTitle, state.memoryContent); }}>
        <div className="writing-side-card-head"><strong>新建 Memory</strong></div>
        <label>类型 <select value={state.memoryType} onChange={(e) => dispatch({ type: "SET_MEMORY_TYPE", mtype: e.target.value })}>
          {["note", "character_state", "relationship_state", "foreshadowing", "continuity_note"].map((t) => (<option key={t} value={t}>{t}</option>))}
        </select></label>
        <label>标题 <input value={state.memoryTitle} onChange={(e) => dispatch({ type: "SET_MEMORY_TITLE", title: e.target.value })} placeholder="Memory 标题" /></label>
        <label>内容 <textarea rows={4} value={state.memoryContent} onChange={(e) => dispatch({ type: "SET_MEMORY_CONTENT", content: e.target.value })} placeholder="Memory 内容" /></label>
        <button className="primary" disabled={state.busy === "memory" || !state.memoryTitle.trim() || !state.memoryContent.trim()}>保存 Memory</button>
      </form>

      <div className="writing-side-card">
        <div className="writing-side-card-head">
          <strong>Memory 列表</strong>
          <span>{state.memories.length} 条</span>
        </div>
        {state.selectedMemoryIds.length > 0 && (
          <div className="writing-card-actions">
            <button onClick={deleteSelectedMemories} disabled={state.busy === "delete-memories"}>删除选中 ({state.selectedMemoryIds.length})</button>
          </div>
        )}
        {state.memories.map((mem) => (
          <div key={mem.id} className="writing-memory-item">
            <input type="checkbox" checked={new Set(state.selectedMemoryIds).has(mem.id)} onChange={() => {
              dispatch({ type: "SET_SELECTED_MEMORY_IDS", ids: state.selectedMemoryIds.includes(mem.id) ? state.selectedMemoryIds.filter((x) => x !== mem.id) : [...state.selectedMemoryIds, mem.id] });
            }} />
            <div>
              <strong>[{mem.memory_type}] {mem.title}</strong>
              <small>V{mem.volume_index}C{mem.chapter_index} · {mem.source}</small>
              <p>{mem.content.slice(0, 200)}{mem.content.length > 200 ? "..." : ""}</p>
            </div>
            <button onClick={() => deleteMemory(mem.id)}>删</button>
          </div>
        ))}
        {!state.memories.length && <p className="muted">暂无 Memory。</p>}
      </div>
    </>
  );
}
