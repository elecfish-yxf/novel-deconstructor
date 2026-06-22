# Novel Deconstructor

长篇小说拆书与 AI 写作工作台。Phase 3 已实现：项目管理、TXT/MD/DOCX/PDF 上传、大文件保存、文本解析、章节识别/分块、本机文件夹选择器、Skill 管理、OpenAI-compatible 多维逐章分析、oh-story 风格拆文库输出、知识库/Obsidian/轻量图谱导出、AI 写作 Agent、任务进度页面和 Docker 启动。

## 功能列表

- Web 项目管理与文件上传
- TXT / MD 解析，支持 UTF-8、GBK、GB18030 等常见编码
- DOCX / PDF 文本提取；扫描版 PDF 请先 OCR
- 章节标题识别：第1章、第一章、卷一、序章、楔子、终章、Chapter 1 等
- 默认严格按章节标题切分，能跳过轻小说开头目录/版权信息中的重复章节标题
- 无章节时按最大字符数分块；关闭“严格按章切分”后，超长章节会二次分块并支持 overlap
- 模型调用支持 DeepSeek Flash / Pro、豆包 Seed 2.0 Pro 和 OpenAI-compatible 服务
- Skill 管理：可选择内置 oh-story Phase 2 Skill，也可自定义主拆书 Prompt、System Prompt 和默认分析模式
- Phase 2 多模式逐章分析：章节结构、冲突推进、人物成长、信息投放、语言风格、AI 味检查
- Phase 3 导出：GPT Builder 知识库、Obsidian Markdown、轻量 GraphRAG JSON/Markdown
- AI 写作 Agent：创建本地知识库、上传 TXT/MD/DOCX/PDF、检索测试、三对话框写作生成、长期 Memory 承接
- 写作知识库分为两类：`writing_guide` 写作技巧指南、`worldbuilding` 世界观设定
- 支持把已完成拆书任务一键导入知识库；默认只导入 `final_reports/` 与 `knowledge_base/` 中的写作技巧指南，不默认沿用原书世界观
- 支持生成世界观草案，用户确认后才会导入为 `worldbuilding`
- 浏览器会自动生成工作区 ID；项目、任务进度和知识库按工作区隔离，其他访客默认不会看到你的进程
- 写作生成会自动启用内置 oh-story Skill 作为写作内核：用户发送请求 -> 生成章节提纲 -> 用户确认 -> 生成小说正文，并给召回片段编号为 `[资料1]`、`[资料2]`
- 默认输出路径和任务输出路径支持点击按钮打开本机文件夹选择器
- 内嵌 oh-story-codex 长篇拆文输出协议：`概要.md`、`_progress.md`、`快速预览.md`、`拆文报告.md`、`章节/*.md`
- dry-run 模式，用于不配置 API Key 时验证完整流程
- 后台任务、进度轮询、日志查看、Markdown 结果下载
- Phase 3 已支持本地 Skill 导入转换；Microsoft GraphRAG 等外部重型适配仍保留接口

## 技术栈

后端：Python 3.11、FastAPI、SQLite、SQLAlchemy、Pydantic、aiofiles、httpx、python-docx、pypdf。
前端：React、Vite、TypeScript、普通 CSS。
部署：Dockerfile、docker-compose。

## 快速开始

```bash
cd novel-deconstructor
copy .env.example .env
docker compose up --build
```

打开：

- 前端：http://localhost:5173
- 后端健康检查：http://localhost:8000/health

## Render 部署

仓库根目录提供了 `Dockerfile` 和 `render.yaml`，Render 会构建一个单 Web Service：FastAPI 后端托管 API 与前端静态页面。云端数据写入 `/data` 持久磁盘：

- `/data/storage`：SQLite 数据库
- `/data/uploads`：上传文件
- `/data/outputs`：拆书输出

部署步骤：

1. 把本项目推送到 GitHub。
2. 打开 Render Dashboard，选择 New -> Blueprint。
3. 选择该 GitHub 仓库，Render 会读取 `render.yaml`。
4. 创建服务即可。公开部署不需要配置站长自己的模型 API Key；使用者会在页面里填写自己的 Key。
5. 创建服务并等待构建完成。
6. 打开 Render 分配的服务地址，访问 `/health` 应返回 `{"ok":true,...}`。

Render 云端没有桌面文件夹选择器，任务输出路径请留空，系统会自动写入 `/data/outputs`。如果使用 SQLite，请保留持久磁盘；否则重新部署或服务重启后数据可能丢失。

## 本地开发启动

后端：

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn novel_deconstructor.main:app --reload --host 0.0.0.0 --port 8000
```

前端：

```bash
cd frontend
npm install
npm run dev
```

## .env 配置

模型配置不写死用户密钥。DeepSeek 可在前端选择 `DeepSeek Flash` 或 `DeepSeek Pro`，base_url 使用 `https://api.deepseek.com`，模型名分别为 `deepseek-v4-flash`、`deepseek-v4-pro`。豆包方舟使用 `DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3`，`DOUBAO_MODEL=doubao-seed-2-0-pro-260215`。公开部署时，拆书任务和写作 Agent 都要求当前使用者在页面填写自己的 API Key；后端不会自动使用服务器环境变量中的站长 Key。若只想验证流程，前端任务配置或写作 Agent 中保持 `dry-run` 即可。默认输出限制在 `APP_OUTPUT_DIR` 内，避免路径穿越；只有 `ALLOW_ABSOLUTE_OUTPUT_PATH=true` 时才允许绝对路径。本机文件夹选择器会返回绝对路径，因此本地桌面使用建议开启该项。

知识库相关配置：

- `APP_KNOWLEDGE_DIR`：知识库文件与解析文本保存目录，默认 `./storage/knowledge`
- `KNOWLEDGE_CHUNK_SIZE`：知识库分块目标大小，默认 900 字符
- `KNOWLEDGE_CHUNK_OVERLAP`：知识库分块重叠，默认 120 字符
- `RETRIEVAL_TOP_K`：检索默认返回数量，默认 6

## Web 使用流程

1. 新建项目。
2. 点击“选择文件夹”设置默认输出路径，或留空使用 `outputs/`。
3. 上传 TXT、MD、DOCX 或 PDF。
4. 设置每章最大字符数与 overlap，完成解析/切章。
5. 默认开启“识别到章节标题时严格按章切分”；如果单章太长需要控制模型输入，可关闭它来启用二次分块。
6. 在章节预览页检查标题、字符数和 token 估算。
7. 配置任务，选择 Skill、分析模式和 Phase 3 导出项。
8. 使用 dry-run，或选择 DeepSeek / 豆包 / OpenAI-compatible 并填写你自己的 API Key。
9. 启动任务，在进度页查看日志。
10. 到结果页预览或下载 Markdown。

## AI 写作 Agent 使用流程

1. 打开左侧 `写作 Agent`。
2. 新建一个作品，例如“作品 1”。每个作品拥有独立文件树、Memory 和生成上下文。
3. 在作品下上传 TXT、MD、DOCX 或 PDF 文件；文件会按 `writing_guide` 写作技巧指南、`worldbuilding` 世界观设定两类管理。
4. 如果当前已选择一个完成的拆书任务，可以点击“导入当前拆书结果”，系统会导入：
   - `final_reports/overall_summary.md`
   - `knowledge_base/*.md`
5. 拆书导入的内容会标记为 `writing_guide`，只用于指导节奏、冲突、人物弧线、信息投放等写法。
6. 世界观设定请由用户上传，或在“世界观设定草案”中生成候选稿，确认后导入为 `worldbuilding`。
7. 在“检索测试”中输入问题，查看召回片段和来源路径。
8. 在第一个对话框“发送请求”中选择写作模型，并输入写作请求和补充上下文。Agent 会自动调用内置 `oh-story 长篇拆文 Phase 2` Skill 作为写作内核，把黄金三章、冲突推进、爽点循环、信息投放、情绪触动和章尾牵引写进提纲。
9. 在第二个对话框“生成并确认提纲”中查看和编辑提纲，点击“确认提纲”后，提纲会写入长期 Memory，并解锁正文生成。
10. 在第三个对话框“生成正文”中点击按钮生成正文。正文阶段会把提纲内化为连续叙事，并明确禁止输出提纲、表格、结构核对或写作说明。
11. dry-run 可先验证检索与引用；关闭 dry-run 后，按模型选择调用 DeepSeek 或豆包 Seed 2.0 Pro，并使用页面里填写的当前用户 Key。

写故事时，Agent 会把 `worldbuilding` 当作故事事实基础；`writing_guide` 和 oh-story 内核只作为技巧指南。长期 Memory 用于承接已确认提纲、正文片段、人物状态和伏笔，但不能覆盖世界观硬设定。系统提示会明确禁止默认沿用被拆解作品的世界观、角色、势力、地名、专名或独特设定。

## 工作区隔离

公开部署时，不同访客打开同一个网页会各自生成一个浏览器工作区 ID，并通过 `X-Workspace-Id` 发送给后端。后端会按工作区过滤：

- 项目列表
- 上传文件
- 拆书任务和进度
- 结果预览与下载
- 知识库、文档和检索
- 写作 Agent 生成

这不是账号登录系统，但能解决“别人访问同一个网页看到我的项目和进程”的问题。清空浏览器 LocalStorage 会生成新工作区，旧工作区数据仍保存在服务器数据库中。

隐私说明：应用和知识库存储在服务器。使用模型调用时，检索到的相关知识片段及写作内容会发送给你选择的模型服务处理。API Key 只随本次请求发送给后端，不会写入浏览器 LocalStorage 或数据库。

## CLI 使用

Phase 2 提供章节切分命令：

```bash
cd backend
python -m novel_deconstructor split --input "./novel.txt" --output "./outputs/test"
```

`analyze`、`resume`、`export`、`import-skills`、`list-jobs` 命令已预留，将在后续 Phase 补全。

## 输出目录

默认结构：

```text
outputs/
  {project_name}/
    raw/
    chunks/
    {job_id}/
      chapter_analysis/
      拆文库/
        {project_name}/
          概要.md
          _progress.md
          快速预览.md
          拆文报告.md
          章节/
          剧情/
          角色/
          设定/
      knowledge_base/
        README.md
        writing_rules.md
        anti_patterns.md
        mode_index.md
      knowledge_base_obsidian/
        index.md
        写作规则.md
        风险清单.md
        章节分析索引/
      graph_outputs/
        entities.json
        relationships.json
        graph_summary.md
      logs/
      metadata/
        llm_calls/
storage/
  knowledge/
    {knowledge_base_id}/
      {document_id}/
        原始文件
        normalized.txt
```

每次 LLM 调用都会保存 prompt 与 response。`chapter_analysis/` 保留兼容旧版的逐章 Markdown，`拆文库/` 使用 oh-story-codex 风格目录；Phase 3 导出会额外生成 `knowledge_base/`、`knowledge_base_obsidian/` 和 `graph_outputs/`。

## Prompt 模板

内置模板位于 `backend/novel_deconstructor/prompts/`。Phase 2 可调用 `chapter_structure.md`、`conflict_analysis.md`、`character_growth.md`、`information_delivery.md`、`language_style.md`、`ai_bad_patterns.md`。`system_base.md` 作为系统提示，不作为逐章模式。

## Skill 管理

Web 中的 `Skill 管理` 页面可创建、编辑、禁用 Skill。Skill 用来决定拆书任务的默认模式和主拆书 Prompt：

- `default_modes`：任务页自动带出的分析模式
- `prompt_template`：覆盖 `chapter_structure` 的主拆书 Prompt
- `system_prompt`：留空时使用内置 `system_base`
- `metadata`：保留 Phase 3 扩展信息

内置 Skill：`oh-story 长篇拆文 Phase 2`，默认启用六个逐章分析维度。自定义 Skill 不会影响原始上传文件。

## oh-story-codex 集成

本项目已把 `HeRiki/oh-story-codex` 的长篇拆文思路适配到后端 Phase 2：黄金三章、爽点循环、情绪触动点、可复现模块、进度恢复表和拆文库目录骨架都已内嵌。AI 写作 Agent 也会复用同一个内置 Skill 作为写作内核，负责结构、节奏、情绪和技法；故事事实仍只来自用户确认的 `worldbuilding`。参考仓库存放在：

```text
third_party_references/oh-story-codex/
```

当前 Web 中的 Prompt 导入页可扫描本地目录，并把 `skills/*/SKILL.md` 转换为可编辑 Skill。GitHub 在线拉取仍保留到后续增强。使用前请自行确认来源项目 license。

## GraphRAG 预留

`graph_outputs/` 当前生成轻量实体/关系 JSON 与摘要 Markdown；`backend/novel_deconstructor/graph/` 仍保留 Microsoft GraphRAG 或 Neo4j 适配位。

## Obsidian 与 GPT Builder

Phase 3 会在 `knowledge_base/` 与 `knowledge_base_obsidian/` 生成可导入 GPT Builder 和 Obsidian 的规则文档。

## 版权与合规

本工具默认用于结构分析、写作规律归纳、检查清单和方法论生成，不应输出大段原文，也不应生成可替代原作阅读的内容。请只分析你有权处理的文本，或在合理授权范围内使用。不要把本工具当作“文风复刻器”。

## 测试

```bash
cd backend
pip install -r requirements.txt
pytest
```

## 常见问题

- 没有 API Key 能用吗？可以，任务配置中开启 dry-run。
- DeepSeek 怎么填？模型服务选 `DeepSeek Flash` 或 `DeepSeek Pro`，API Key 填 DeepSeek 控制台生成的 Key，然后关闭 dry-run。
- 豆包怎么填？模型服务选 `豆包 Seed 2.0 Pro`，API Key 填火山方舟控制台生成的 Ark API Key，然后关闭 dry-run。
- 能上传很大的小说吗？后端按块保存上传文件，切章前不会把整本书送入模型；单次模型调用只处理一个章节/分块。
- 为什么 PDF 解析为空？多半是扫描版 PDF，请先 OCR 成可选中文本后再上传。
- 写作 Agent 的知识库是向量库吗？当前版本先使用 SQLite 分块 + 本地轻量关键词召回，已保留检索服务层接口；后续可替换为 Chroma / sentence-transformers 而不改前端使用方式。
