import { Dispatch, FormEvent } from "react";
import { WritingState, WritingAction } from "./types";
import { parsePositionInput } from "./utils";
import { KnowledgeBase } from "../../api";

interface Props {
  state: WritingState;
  dispatch: Dispatch<WritingAction>;
  selected: KnowledgeBase | null;
  writingModels: Array<{ id: string; label: string; provider: string; model: string; available: boolean }>;
  selectedWritingModel: { id: string; label: string } | null;
  positionMissing: boolean;
  workspaceId: string;
}

export function Header({ state, dispatch, selected, writingModels, selectedWritingModel, positionMissing, workspaceId }: Props) {
  return (
    <header className="writing-agent-header">
      <div className="writing-agent-header-left">
        <div className="writing-agent-logo">
          <span>写</span>
          <strong>写作平台</strong>
        </div>
        <div className="writing-agent-work-switcher">
          <select value={state.selectedId ?? ""}
            onChange={(e) => { const id = Number(e.target.value); if (id) dispatch({ type: "SET_SELECTED_ID", id }); }}>
            <option value="">选择作品</option>
            {state.knowledgeBases.map((kb) => (<option key={kb.id} value={kb.id}>{kb.name}</option>))}
          </select>
        </div>
        <nav className="writing-agent-top-nav">
          <button className={state.assistantTab === "outline" ? "active" : ""} onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "outline" })}>写作</button>
          <button className={state.assistantTab === "memory" ? "active" : ""} onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "memory" })}>Memory</button>
          <button className={state.assistantTab === "worldbuilding" ? "active" : ""} onClick={() => dispatch({ type: "SET_ASSISTANT_TAB", tab: "worldbuilding" })}>世界观</button>
          <button className={state.assistantTab === "resources" ? "active" : ""} onClick={() => { dispatch({ type: "SET_MAIN_NAV_TAB", tab: "writing_guide" }); dispatch({ type: "SET_ASSISTANT_TAB", tab: "resources" }); }}>拆卡/资料</button>
          <button className={state.mainNavTab === "history" ? "active" : ""} onClick={() => { dispatch({ type: "SET_MAIN_NAV_TAB", tab: "history" }); dispatch({ type: "SET_ASSISTANT_TAB", tab: "memory" }); }}>历史</button>
        </nav>
      </div>
      <div className="writing-agent-header-right">
        <form className="writing-agent-search" onSubmit={(e) => e.preventDefault()}>
          <span>⌕</span>
          <input value={state.query} onChange={(e) => dispatch({ type: "SET_QUERY", query: e.target.value })} placeholder="全文搜索 / RAG 召回" />
        </form>
        <div className="writing-agent-user">
          <span>AI</span>
          <strong>{selectedWritingModel?.label || "写作模型"}</strong>
        </div>
      </div>
    </header>
  );
}
