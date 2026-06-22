import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, DeconstructionSkill, PromptTemplate } from "../api";

const MODE_LABELS: Record<string, string> = {
  chapter_structure: "章节结构",
  conflict_analysis: "冲突推进",
  character_growth: "人物成长",
  information_delivery: "信息投放",
  language_style: "语言风格",
  ai_bad_patterns: "AI 味检查",
  volume_summary: "卷段总结",
  final_knowledge_base: "知识库",
  obsidian_export: "Obsidian",
};

function parseModes(skill?: DeconstructionSkill | null) {
  if (!skill) return ["chapter_structure"];
  try {
    const parsed = JSON.parse(skill.default_modes_json);
    return Array.isArray(parsed) && parsed.length ? parsed : ["chapter_structure"];
  } catch {
    return ["chapter_structure"];
  }
}

function defaultKey() {
  return `custom_${Date.now().toString(36)}`;
}

export default function SkillManager() {
  const [skills, setSkills] = useState<DeconstructionSkill[]>([]);
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [selected, setSelected] = useState<DeconstructionSkill | null>(null);
  const [key, setKey] = useState(defaultKey());
  const [name, setName] = useState("自定义拆书 Skill");
  const [description, setDescription] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [modes, setModes] = useState<string[]>(["chapter_structure"]);
  const [systemPrompt, setSystemPrompt] = useState("");
  const [promptTemplate, setPromptTemplate] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const modeOptions = useMemo(() => {
    const names = prompts.map((item) => item.mode).filter((mode) => mode !== "system_base");
    return Array.from(new Set(["chapter_structure", ...names]));
  }, [prompts]);

  async function load() {
    const [nextSkills, nextPrompts] = await Promise.all([api.listSkills(), api.listPrompts()]);
    setSkills(nextSkills);
    setPrompts(nextPrompts);
    if (!selected && nextSkills.length) {
      selectSkill(nextSkills[0]);
    }
  }

  function selectSkill(skill: DeconstructionSkill) {
    setSelected(skill);
    setKey(skill.key);
    setName(skill.name);
    setDescription(skill.description);
    setEnabled(skill.enabled);
    setModes(parseModes(skill));
    setSystemPrompt(skill.system_prompt || "");
    setPromptTemplate(skill.prompt_template || "");
    setMessage("");
    setError("");
  }

  function newSkill() {
    setSelected(null);
    setKey(defaultKey());
    setName("自定义拆书 Skill");
    setDescription("");
    setEnabled(true);
    setModes(["chapter_structure"]);
    setSystemPrompt("");
    setPromptTemplate("");
    setMessage("");
    setError("");
  }

  function toggleMode(mode: string) {
    setModes((current) => (current.includes(mode) ? current.filter((item) => item !== mode) : [...current, mode]));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    setMessage("");
    const payload = {
      key,
      name,
      description,
      source: selected?.source || "custom",
      phase: 2,
      enabled,
      default_modes: modes,
      system_prompt: systemPrompt || null,
      prompt_template: promptTemplate || null,
      metadata: { phase3_ready: true },
    };
    try {
      const saved = selected ? await api.updateSkill(selected.id, payload) : await api.createSkill(payload);
      setMessage("Skill 已保存");
      await load();
      selectSkill(saved);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!selected) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await api.deleteSkill(selected.id);
      setMessage(result.disabled ? "内置 Skill 已禁用" : "Skill 已删除");
      setSelected(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load().catch((err) => setError(err.message));
  }, []);

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">Phase 2</p>
          <h1>Skill 管理</h1>
        </div>
        <p>管理拆书时使用的 Skill。选择 Skill 后，任务页会带出它的默认分析模式和主拆书 Prompt。</p>
      </div>
      {error && <div className="alert">{error}</div>}
      {message && <div className="panel notice">{message}</div>}

      <div className="results-layout">
        <div className="file-tree">
          <div className="button-row">
            <button className="primary" onClick={newSkill}>
              新建 Skill
            </button>
            <button onClick={() => load()}>刷新</button>
          </div>
          <div className="file-group skill-list">
            {skills.map((skill) => (
              <button key={skill.id} className={selected?.id === skill.id ? "active-file" : ""} onClick={() => selectSkill(skill)}>
                <span>
                  <strong>{skill.name}</strong>
                  <small>
                    {skill.enabled ? "启用" : "禁用"} · {skill.builtin ? "内置" : "自定义"} · {parseModes(skill).length} 模式
                  </small>
                </span>
              </button>
            ))}
          </div>
        </div>

        <form className="panel skill-editor" onSubmit={submit}>
          <label>
            Skill Key
            <input value={key} onChange={(event) => setKey(event.target.value)} />
          </label>
          <label>
            名称
            <input value={name} onChange={(event) => setName(event.target.value)} />
          </label>
          <label className="full-row">
            描述
            <textarea value={description} onChange={(event) => setDescription(event.target.value)} rows={3} />
          </label>
          <label className="check-row">
            <input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
            启用这个 Skill
          </label>

          <div className="prompt-note full-row">
            <strong>默认分析模式</strong>
            <div className="mode-grid">
              {modeOptions.map((mode) => (
                <label className="check-row" key={mode}>
                  <input type="checkbox" checked={modes.includes(mode)} onChange={() => toggleMode(mode)} />
                  {MODE_LABELS[mode] || mode}
                </label>
              ))}
            </div>
          </div>

          <label className="full-row">
            System Prompt 覆盖
            <textarea value={systemPrompt} onChange={(event) => setSystemPrompt(event.target.value)} rows={5} placeholder="留空使用内置 system_base" />
          </label>

          <label className="full-row">
            主拆书 Prompt 覆盖
            <textarea
              value={promptTemplate}
              onChange={(event) => setPromptTemplate(event.target.value)}
              rows={18}
              placeholder="留空使用内置 chapter_structure；可使用 {{project_name}}、{{chapter_title}}、{{chapter_text}} 等变量"
            />
          </label>

          <div className="button-row full-row">
            <button className="primary" type="submit" disabled={busy || !modes.length}>
              {busy ? "保存中..." : "保存 Skill"}
            </button>
            {selected && (
              <button className="danger" type="button" onClick={remove} disabled={busy}>
                {selected.builtin ? "禁用内置 Skill" : "删除"}
              </button>
            )}
          </div>
        </form>
      </div>
    </section>
  );
}
