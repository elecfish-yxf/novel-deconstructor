import { Dispatch, FormEvent, useMemo } from "react";
import { WritingAction, WritingState, ParsedOutlineNode, OutlineScope } from "./types";
import { OUTLINE_SCOPE_OPTIONS, OUTLINE_SCOPE_HINTS, parseOptionalNumberInput } from "./utils";
import { KnowledgeBase } from "../../api";

interface Props {
  state: WritingState; dispatch: Dispatch<WritingAction>;
  selected: KnowledgeBase | null;
  writingModels: Array<{ id: string; label: string }>;
  selectedWritingModel: { id: string } | null;
  selectedWritingModelPayload: Record<string, unknown>;
  writingTaskPayload: string;
  parsedOutline: ParsedOutlineNode[];
  resolvedRagTopK: number; resolvedTargetChars: number;
  generationRetrievalPayload: Record<string, unknown>;
  outlineScopePayload: Record<string, unknown>;
  outlineScopeLabel: string; outlineScopePositionMissing: boolean;
  modelCallBlocked: boolean;
  generateOutline: (e: FormEvent) => Promise<void>;
  confirmOutline: (outlineContent?: string) => Promise<void>;
}

type OutlineChoice = {
  id: string;
  label: string;
  content: string;
  preview: string;
  depth: number;
};

function outlineNodeContent(node: ParsedOutlineNode): string {
  const headingPrefix = "#".repeat(Math.min(Math.max(node.level, 1), 6));
  return [
    `${headingPrefix} ${node.heading}`,
    node.body.join("\n").trim(),
    ...node.children.map(outlineNodeContent),
  ].filter(Boolean).join("\n\n");
}

function flattenOutlineChoices(nodes: ParsedOutlineNode[], path: string[] = []): OutlineChoice[] {
  return nodes.flatMap((node, index) => {
    const nodePath = [...path, String(index)];
    const content = outlineNodeContent(node);
    const childPreview = node.children[0]?.heading ? `包含：${node.children[0].heading}` : "";
    const bodyPreview = node.body.find((line) => line.trim())?.trim() || childPreview || "暂无正文";
    return [
      {
        id: `node-${nodePath.join("-")}`,
        label: node.heading,
        content,
        preview: bodyPreview.length > 80 ? `${bodyPreview.slice(0, 80).trim()}...` : bodyPreview,
        depth: nodePath.length,
      },
      ...flattenOutlineChoices(node.children, nodePath),
    ];
  });
}

function buildOutlineChoices(nodes: ParsedOutlineNode[], outline: string): OutlineChoice[] {
  const full = outline.trim();
  const fullPreview = full.split(/\r?\n/).find((line) => line.trim())?.trim().replace(/^#+\s*/, "") || "完整生成结果";
  const nodeChoices = flattenOutlineChoices(nodes).filter((choice) => choice.content.trim());
  return [
    {
      id: "full",
      label: "完整生成结果",
      content: full,
      preview: fullPreview.length > 80 ? `${fullPreview.slice(0, 80).trim()}...` : fullPreview,
      depth: 0,
    },
    ...nodeChoices,
  ];
}

function OutlineNodeList({ nodes }: { nodes: ParsedOutlineNode[] }) {
  if (!nodes.length) return null;
  return (
    <div className="outline-node-list">
      {nodes.map((node, i) => (
        <article key={`${node.heading}-${i}`}>
          <details open>
            <summary>{node.heading}{node.body.length ? "" : "（暂无正文）"}</summary>
            {!!node.body.length && <pre>{node.body.join("\n").trim()}</pre>}
            <OutlineNodeList nodes={node.children} />
          </details>
        </article>
      ))}
    </div>
  );
}

export function OutlinePanel({ state, dispatch, selected, writingModels, selectedWritingModel, selectedWritingModelPayload, writingTaskPayload, parsedOutline, resolvedRagTopK, resolvedTargetChars, generationRetrievalPayload, outlineScopePayload, outlineScopeLabel, outlineScopePositionMissing, modelCallBlocked, generateOutline, confirmOutline }: Props) {
  const outlineChoices = useMemo(() => buildOutlineChoices(parsedOutline, state.outline), [parsedOutline, state.outline]);
  const selectedOutlineChoice = outlineChoices.find((choice) => choice.id === state.selectedOutlineId) || outlineChoices[0] || null;
  const selectedOutlineContent = selectedOutlineChoice?.content || state.outline;

  return (
    <>
      <form className="writing-side-card" onSubmit={generateOutline}>
        <div className="writing-side-card-head"><strong>发送请求</strong><span>{state.dryRun ? "dry-run" : "model"}</span></div>
        <label>写作请求 <textarea rows={4} value={state.outlineTask} onChange={(e) => dispatch({ type: "SET_OUTLINE_TASK", task: e.target.value })} /></label>
        <div className="mode-grid">
          <label>提纲范围
            <select value={state.outlineScope} onChange={(e) => dispatch({ type: "SET_OUTLINE_SCOPE", scope: e.target.value as OutlineScope })}>
              {OUTLINE_SCOPE_OPTIONS.map((o) => (<option key={o.value} value={o.value}>{o.label}</option>))}
            </select>
            <small className="writing-field-hint">{OUTLINE_SCOPE_HINTS[state.outlineScope]}</small>
          </label>
          <label>目标字数 <input type="number" min={500} max={50000} step={500} value={state.targetChars} onChange={(e) => dispatch({ type: "SET_TARGET_CHARS", chars: parseOptionalNumberInput(e.target.value, 500, 50000) })} /></label>
          <label>RAG top_k <input type="number" min={1} max={200} value={state.ragTopK} onChange={(e) => dispatch({ type: "SET_RAG_TOP_K", k: parseOptionalNumberInput(e.target.value, 1, 200) })} /></label>
        </div>
        <div className="mode-grid">
          <label>模型 <select value={state.writingModelId} onChange={(e) => dispatch({ type: "SET_WRITING_MODEL_ID", id: e.target.value })}>{writingModels.map((o) => (<option key={o.id} value={o.id}>{o.label}</option>))}</select></label>
          <label>API Key <input type="password" value={state.writingApiKey} onChange={(e) => dispatch({ type: "SET_WRITING_API_KEY", key: e.target.value })} placeholder="本次请求使用" /></label>
          <label>生成模式 <select value={state.mode} onChange={(e) => dispatch({ type: "SET_MODE", mode: e.target.value })}><option value="fast">快速</option><option value="standard">标准</option><option value="deep">深度</option></select></label>
          <label>知识模式 <select value={state.knowledgeMode} onChange={(e) => dispatch({ type: "SET_KNOWLEDGE_MODE", mode: e.target.value })}><option value="reference">参考知识</option><option value="strict">严格知识</option></select></label>
        </div>
        <label className="check-row"><input type="checkbox" checked={state.dryRun} onChange={(e) => dispatch({ type: "SET_DRY_RUN", dry: e.target.checked })} />dry-run</label>
        <label className="check-row"><input type="checkbox" checked={state.debugRawKnowledge} onChange={(e) => dispatch({ type: "SET_DEBUG_RAW_KNOWLEDGE", debug: e.target.checked })} />知识库原文</label>
        <button className="primary" disabled={state.busy === "outline" || !selected || modelCallBlocked || outlineScopePositionMissing}>生成提纲</button>
      </form>

      {state.outline && (
        <div className="writing-side-card">
          <div className="writing-side-card-head"><strong>确认提纲</strong><span>{state.confirmedOutline ? "已确认" : "待确认"}</span></div>
          <div className="outline-choice-list" role="listbox" aria-label="可确认的提纲范围">
            {outlineChoices.map((choice) => (
              <button
                key={choice.id}
                type="button"
                className={choice.id === (selectedOutlineChoice?.id || "full") ? "active" : ""}
                style={{ marginLeft: choice.id === "full" ? 0 : Math.min(choice.depth, 3) * 10 }}
                aria-selected={choice.id === (selectedOutlineChoice?.id || "full")}
                onClick={() => dispatch({ type: "SET_SELECTED_OUTLINE_ID", id: choice.id })}
              >
                <span>{choice.label}</span>
                <small>{choice.preview}</small>
              </button>
            ))}
          </div>
          {selectedOutlineChoice?.id === "full" ? (
            <OutlineNodeList nodes={parsedOutline} />
          ) : (
            <pre className="outline-selected-preview">{selectedOutlineContent}</pre>
          )}
          <div className="writing-card-actions">
            <button type="button" className="primary" onClick={() => void confirmOutline(selectedOutlineContent)} disabled={!selected || state.busy === "confirm-outline" || !!state.confirmedOutline || !selectedOutlineContent.trim()}>确认选中提纲</button>
          </div>
        </div>
      )}
    </>
  );
}
