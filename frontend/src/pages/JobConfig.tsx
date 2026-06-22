import { FormEvent, useEffect, useMemo, useState } from "react";
import { api, DeconstructionSkill, Job, Project, PromptTemplate, SourceFile } from "../api";

const MODE_LABELS: Record<string, string> = {
  chapter_structure: "章节结构",
  conflict_analysis: "冲突推进",
  character_growth: "人物成长",
  information_delivery: "信息投放",
  language_style: "语言风格",
  ai_bad_patterns: "AI 味检查",
};

const AGGREGATE_MODES = new Set(["volume_summary", "final_knowledge_base", "obsidian_export"]);
const DEFAULT_MODE = "chapter_structure";

function sanitizeModes(values?: string[]) {
  const modes = (values || []).filter((mode) => mode && mode !== "system_base" && !AGGREGATE_MODES.has(mode));
  return Array.from(new Set(modes)).length ? Array.from(new Set(modes)) : [DEFAULT_MODE];
}

const PROVIDER_PRESETS = {
  deepseekFlash: {
    label: "DeepSeek Flash",
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-v4-flash",
    note: "速度优先，适合大文件逐章批量拆书。",
  },
  deepseekPro: {
    label: "DeepSeek Pro",
    baseUrl: "https://api.deepseek.com",
    model: "deepseek-v4-pro",
    note: "质量优先，适合重点章节和深度分析。",
  },
  openai: {
    label: "OpenAI-compatible",
    baseUrl: "https://api.openai.com/v1",
    model: "",
    note: "用于 OpenAI 或其他兼容 /v1/chat/completions 的服务。",
  },
  custom: {
    label: "自定义",
    baseUrl: "",
    model: "",
    note: "手动填写 base_url、模型名和 API Key。",
  },
} as const;

type ProviderPresetKey = keyof typeof PROVIDER_PRESETS;
type JobConfigPrefs = {
  skillId?: number | "";
  modes?: string[];
  providerPreset?: ProviderPresetKey;
  baseUrl?: string;
  model?: string;
  temperature?: number;
  maxTokens?: number;
  dryRun?: boolean;
  allowShortQuotes?: boolean;
  generateKb?: boolean;
  generateObsidian?: boolean;
  generateGraph?: boolean;
};

const JOB_CONFIG_PREFS_KEY = "novel-deconstructor.job-config";

function isProviderPreset(value: unknown): value is ProviderPresetKey {
  return typeof value === "string" && value in PROVIDER_PRESETS;
}

function loadJobConfigPrefs(): JobConfigPrefs {
  try {
    const raw = window.localStorage.getItem(JOB_CONFIG_PREFS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as JobConfigPrefs;
    return {
      ...parsed,
      providerPreset: isProviderPreset(parsed.providerPreset) ? parsed.providerPreset : undefined,
      modes: Array.isArray(parsed.modes) ? sanitizeModes(parsed.modes.filter((item) => typeof item === "string")) : undefined,
    };
  } catch {
    return {};
  }
}

function parseModes(skill?: DeconstructionSkill | null) {
  if (!skill) return [DEFAULT_MODE];
  try {
    const parsed = JSON.parse(skill.default_modes_json);
    return Array.isArray(parsed) ? sanitizeModes(parsed) : [DEFAULT_MODE];
  } catch {
    return [DEFAULT_MODE];
  }
}

export default function JobConfig({
  project,
  sourceFile,
  onJobCreated,
}: {
  project: Project;
  sourceFile: SourceFile;
  onJobCreated: (job: Job) => void;
}) {
  const [initialPrefs] = useState<JobConfigPrefs>(() => loadJobConfigPrefs());
  const initialProviderPreset = initialPrefs.providerPreset || "deepseekFlash";
  const [prompts, setPrompts] = useState<PromptTemplate[]>([]);
  const [skills, setSkills] = useState<DeconstructionSkill[]>([]);
  const [skillId, setSkillId] = useState<number | "">("");
  const [modes, setModes] = useState<string[]>(initialPrefs.modes?.length ? sanitizeModes(initialPrefs.modes) : [DEFAULT_MODE]);
  const [outputDir, setOutputDir] = useState("");
  const [providerPreset, setProviderPreset] = useState<ProviderPresetKey>(initialProviderPreset);
  const [baseUrl, setBaseUrl] = useState<string>(initialPrefs.baseUrl || PROVIDER_PRESETS[initialProviderPreset].baseUrl);
  const [model, setModel] = useState<string>(initialPrefs.model ?? PROVIDER_PRESETS[initialProviderPreset].model);
  const [apiKey, setApiKey] = useState("");
  const [temperature, setTemperature] = useState(initialPrefs.temperature ?? 0.3);
  const [maxTokens, setMaxTokens] = useState(initialPrefs.maxTokens ?? 8192);
  const [dryRun, setDryRun] = useState(initialPrefs.dryRun ?? true);
  const [allowShortQuotes, setAllowShortQuotes] = useState(initialPrefs.allowShortQuotes ?? false);
  const [generateKb, setGenerateKb] = useState(initialPrefs.generateKb ?? true);
  const [generateObsidian, setGenerateObsidian] = useState(initialPrefs.generateObsidian ?? true);
  const [generateGraph, setGenerateGraph] = useState(initialPrefs.generateGraph ?? true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const selectedSkill = skills.find((item) => item.id === skillId) || null;
  const modeOptions = useMemo(() => {
    const names = prompts.map((item) => item.mode).filter((mode) => mode !== "system_base" && !AGGREGATE_MODES.has(mode));
    return Array.from(new Set([DEFAULT_MODE, ...names]));
  }, [prompts]);

  useEffect(() => {
    Promise.all([api.listPrompts(), api.listSkills()])
      .then(([nextPrompts, nextSkills]) => {
        setPrompts(nextPrompts);
        const enabled = nextSkills.filter((item) => item.enabled);
        setSkills(enabled);
        const preferredSkill = typeof initialPrefs.skillId === "number" ? enabled.find((item) => item.id === initialPrefs.skillId) : null;
        const first = preferredSkill || enabled[0];
        if (first) {
          setSkillId(first.id);
          setModes(initialPrefs.modes?.length ? sanitizeModes(initialPrefs.modes) : parseModes(first));
        } else if (initialPrefs.modes?.length) {
          setModes(sanitizeModes(initialPrefs.modes));
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : "加载配置失败"));
  }, [initialPrefs]);

  useEffect(() => {
    const payload: JobConfigPrefs = {
      skillId,
      modes: sanitizeModes(modes),
      providerPreset,
      baseUrl,
      model,
      temperature,
      maxTokens,
      dryRun,
      allowShortQuotes,
      generateKb,
      generateObsidian,
      generateGraph,
    };
    window.localStorage.setItem(JOB_CONFIG_PREFS_KEY, JSON.stringify(payload));
  }, [
    skillId,
    modes,
    providerPreset,
    baseUrl,
    model,
    temperature,
    maxTokens,
    dryRun,
    allowShortQuotes,
    generateKb,
    generateObsidian,
    generateGraph,
  ]);

  function chooseSkill(id: number | "") {
    setSkillId(id);
    const skill = skills.find((item) => item.id === id);
    setModes(parseModes(skill));
  }

  function toggleMode(mode: string) {
    setModes((current) => (current.includes(mode) ? current.filter((item) => item !== mode) : [...current, mode]));
  }

  function chooseProvider(nextPreset: ProviderPresetKey) {
    const preset = PROVIDER_PRESETS[nextPreset];
    setProviderPreset(nextPreset);
    if (preset.baseUrl) setBaseUrl(preset.baseUrl);
    setModel(preset.model);
  }

  async function pickOutputDir() {
    setError("");
    try {
      const result = await api.pickDirectory({ initial_dir: outputDir || project.root_output_dir || undefined });
      if (result.path) setOutputDir(result.path);
    } catch (err) {
      setError(err instanceof Error ? err.message : "无法打开文件夹选择器");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const job = await api.createJob({
        project_id: project.id,
        source_file_id: sourceFile.id,
        skill_id: skillId || undefined,
        output_dir: outputDir || undefined,
        modes: sanitizeModes(modes),
        base_url: baseUrl,
        model: model || undefined,
        api_key: apiKey || undefined,
        temperature,
        max_tokens: maxTokens,
        concurrency: 1,
        allow_short_quotes: allowShortQuotes,
        generate_kb: generateKb,
        generate_obsidian: generateObsidian,
        generate_graph: generateGraph,
        dry_run: dryRun,
      });
      onJobCreated(job);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建任务失败");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section>
      <div className="page-head">
        <div>
          <p className="eyebrow">{project.name}</p>
          <h1>拆书任务配置</h1>
        </div>
        <p>支持选择 Skill、多维逐章分析，以及知识库、Obsidian、轻量图谱导出。</p>
      </div>
      {error && <div className="alert">{error}</div>}

      <form className="panel config-form" onSubmit={submit}>
        <label>
          输入文件
          <input value={sourceFile.original_filename} disabled />
        </label>
        <label>
          输出路径
          <div className="path-picker-row">
            <input value={outputDir} onChange={(event) => setOutputDir(event.target.value)} placeholder="留空使用项目默认路径或 outputs/{project}/{job_id}" />
            <button type="button" onClick={pickOutputDir}>
              选择文件夹
            </button>
          </div>
        </label>
        <label>
          使用 Skill
          <select value={skillId} onChange={(event) => chooseSkill(event.target.value ? Number(event.target.value) : "")}>
            <option value="">默认内置模板</option>
            {skills.map((skill) => (
              <option key={skill.id} value={skill.id}>
                {skill.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          模型服务
          <select value={providerPreset} onChange={(event) => chooseProvider(event.target.value as ProviderPresetKey)}>
            {Object.entries(PROVIDER_PRESETS).map(([key, preset]) => (
              <option key={key} value={key}>
                {preset.label}
              </option>
            ))}
          </select>
          <small className="muted">{PROVIDER_PRESETS[providerPreset].note}</small>
        </label>
        <label>
          base_url
          <input
            value={baseUrl}
            onChange={(event) => {
              setBaseUrl(event.target.value);
              setProviderPreset("custom");
            }}
          />
        </label>

        <div className="prompt-note">
          <strong>分析模式</strong>
          <div className="mode-grid">
            {modeOptions.map((mode) => (
              <label className="check-row" key={mode}>
                <input type="checkbox" checked={modes.includes(mode)} onChange={() => toggleMode(mode)} />
                {MODE_LABELS[mode] || mode}
              </label>
            ))}
          </div>
          <small>
            当前 Skill：{selectedSkill?.name || "默认内置模板"}；每个章节会按勾选模式分别生成 Markdown。知识库、Obsidian、图谱由 Phase 3 导出生成。
          </small>
        </div>

        <label>
          模型名称
          <input
            value={model}
            onChange={(event) => {
              setModel(event.target.value);
              setProviderPreset("custom");
            }}
            placeholder="例如 deepseek-v4-flash 或 deepseek-v4-pro"
          />
        </label>
        <label>
          API Key
          <input value={apiKey} onChange={(event) => setApiKey(event.target.value)} type="password" placeholder="仅用于本次任务请求" />
          <small className="muted">DeepSeek 请填写 DeepSeek API Key；也可以写入后端 DEEPSEEK_API_KEY。</small>
        </label>
        <label>
          temperature
          <input type="number" step="0.1" min="0" max="2" value={temperature} onChange={(event) => setTemperature(Number(event.target.value))} />
        </label>
        <label>
          max_tokens
          <input type="number" min="512" value={maxTokens} onChange={(event) => setMaxTokens(Number(event.target.value))} />
          <small className="muted">控制单次模型输出长度；如果模型提示超限，可以降到 4096 或减少分析模式。</small>
        </label>
        <label className="check-row">
          <input type="checkbox" checked={dryRun} onChange={(event) => setDryRun(event.target.checked)} />
          dry-run：不调用外部模型，只验证完整流程
        </label>
        <label className="check-row">
          <input type="checkbox" checked={allowShortQuotes} onChange={(event) => setAllowShortQuotes(event.target.checked)} />
          允许极短引用原文
        </label>
        <div className="prompt-note">
          <strong>Phase 3 导出</strong>
          <div className="mode-grid">
            <label className="check-row">
              <input type="checkbox" checked={generateKb} onChange={(event) => setGenerateKb(event.target.checked)} />
              GPT Builder 知识库
            </label>
            <label className="check-row">
              <input type="checkbox" checked={generateObsidian} onChange={(event) => setGenerateObsidian(event.target.checked)} />
              Obsidian Markdown
            </label>
            <label className="check-row">
              <input type="checkbox" checked={generateGraph} onChange={(event) => setGenerateGraph(event.target.checked)} />
              轻量 GraphRAG 图谱
            </label>
          </div>
        </div>
        <div className="prompt-note">
          已加载 Prompt 模板：{prompts.length ? prompts.map((item) => item.mode).join(" / ") : "等待后端启动后加载"}
        </div>
        <button className="primary" type="submit" disabled={busy || !modes.length}>
          {busy ? "启动中..." : "启动拆书任务"}
        </button>
      </form>
    </section>
  );
}

