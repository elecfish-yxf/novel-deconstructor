import { Dispatch } from "react";
import { WritingAction, WritingState } from "./types";
import { KnowledgeBase, api } from "../../api";

interface Props {
  state: WritingState; dispatch: Dispatch<WritingAction>;
  selected: KnowledgeBase | null;
  selectedWritingModelPayload: Record<string, unknown>;
  reloadWorkIfStillActive: (id: number) => Promise<void>;
}

export function WorldbuildingPanel({ state, dispatch, selected, selectedWritingModelPayload, reloadWorkIfStillActive }: Props) {
  const generateDraft = async () => {
    if (!selected || !state.storySeed.trim()) return;
    dispatch({ type: "SET_BUSY", busy: "worldbuilding" });
    try {
      const r = await api.generateWorldbuildingDraft({
        knowledge_base_ids: [selected.id], story_seed: state.storySeed,
        requirements: "生成原创世界观。可以参考写作技巧指南，但不要沿用拆书原作的世界观、角色、势力、地名和独特设定。",
        ...selectedWritingModelPayload, dry_run: state.dryRun,
      });
      dispatch({ type: "SET_WORLDBUILDING_DRAFT", draft: r.content });
      dispatch({ type: "SET_CITATIONS", citations: r.citations });
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "生成失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  const confirmImport = async () => {
    if (!selected || !state.worldbuildingDraft.trim()) return;
    dispatch({ type: "SET_BUSY", busy: "confirm-worldbuilding" });
    try {
      const r = await api.createKnowledgeTextDocument(selected.id, {
        filename: "worldbuilding_confirmed.md", content: state.worldbuildingDraft, knowledge_type: "worldbuilding",
      });
      dispatch({ type: "SET_MESSAGE", message: `世界观已导入：${r.message}` });
      await reloadWorkIfStillActive(selected.id);
    } catch (err) {
      dispatch({ type: "SET_ERROR", error: err instanceof Error ? err.message : "导入失败" });
    } finally { dispatch({ type: "SET_BUSY", busy: "" }); }
  };

  return (
    <>
      <div className="writing-side-card">
        <div className="writing-side-card-head"><strong>世界观草案</strong></div>
        <label>故事种子 <textarea rows={2} value={state.storySeed} onChange={(e) => dispatch({ type: "SET_STORY_SEED", seed: e.target.value })} /></label>
        <label className="check-row"><input type="checkbox" checked={state.dryRun} onChange={(e) => dispatch({ type: "SET_DRY_RUN", dry: e.target.checked })} />dry-run</label>
        <button className="primary" onClick={generateDraft} disabled={!selected || state.busy === "worldbuilding" || !state.storySeed.trim()}>生成世界观草案</button>
      </div>
      {state.worldbuildingDraft && (
        <div className="writing-side-card">
          <div className="writing-side-card-head"><strong>世界观草案结果</strong></div>
          <pre>{state.worldbuildingDraft.slice(0, 3000)}{state.worldbuildingDraft.length > 3000 ? "..." : ""}</pre>
          <button className="primary" onClick={confirmImport} disabled={state.busy === "confirm-worldbuilding"}>确认导入世界观</button>
        </div>
      )}
    </>
  );
}
