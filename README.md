# Novel Deconstructor

Novel Deconstructor is a lightweight tool for extracting reusable writing knowledge from long-form fiction and turning it into knowledge packages for AI writing agents.

一个面向 AI 写作 Agent 的长篇小说拆书与知识提取工具。它用于从长文本中提取章节结构、冲突模式、情绪节奏、人物变化、信息投放和语言规则，并导出为可复用的写作知识包。

## What It Solves

直接让大模型总结长篇小说，结果很容易变成剧情复述。写作 Agent 真正需要的是结构化、可检索、可复用的写作知识，例如：

- 一章如何完成开头状态到结尾状态的变化；
- 冲突如何触发、升级、释放并牵引下一章；
- 情绪链如何形成期待、加压、释放和余波；
- 设定和信息如何分层投放，而不是一次性硬讲；
- 哪些写法可以迁移，哪些只是原书专属内容，不能照搬。

本项目把长文本拆成章节，再提取写作规律。拆书结果用于指导原创写作，不用于复制原书世界观、人物、专名、桥段或表达。

## Core Workflow

```text
Upload Novel
  -> Chapter Splitter
  -> Multi-mode Analysis
  -> Knowledge Extraction
  -> writing_guide / worldbuilding / memory
  -> Lightweight Retrieval
  -> AI Writing Agent
  -> Outline / Draft / Revision Suggestions
```

## Features

- TXT / MD / DOCX / PDF 上传与文本解析，扫描版 PDF 需要先 OCR。
- 长文本章节识别与切分，支持中文章回标题、卷、序章、终章和 `Chapter 1`。
- 无章节标题时按字符数分块，超长章节可按配置二次分块。
- 多维拆书分析：章节结构、冲突推进、人物变化、信息投放、语言风格、AI 味检查。
- oh-story 风格拆书流程：黄金三章、爽点循环、情绪触动点、可复现模块、章尾牵引。
- 知识包分层：`writing_guide` 保存写作技巧，`worldbuilding` 保存用户确认的原创设定，`memory` 保存写作连续性。
- 轻量知识检索：本地 SQLite 文档分块 + 关键词召回，保留后续替换向量检索的服务层位置。
- AI 写作 Agent：先生成可确认提纲，再基于确认提纲生成正文，并承接长期 Memory。
- 导出 Markdown / JSON / Obsidian 友好文档和轻量图谱 JSON。
- Docker 本地启动，支持 dry-run 模式，不配置 API Key 也能验证流程。

## Project Scope

这是一个个人轻量级开源项目和作品集项目，重点是把“长文本拆书 -> 写作知识抽取 -> Agent 调用”做清楚、做扎实、能演示。

当前边界：

- 主要面向本地个人使用、学习和项目演示。
- 不是企业级 SaaS，也不是多租户商业平台。
- 浏览器 workspace 只是轻量隔离机制，不是正式账号系统。
- 当前 RAG 是 SQLite 文档分块 + 本地关键词召回，不是完整向量数据库。
- 当前图谱导出是轻量 JSON/Markdown，不是生产级 GraphRAG。
- 拆书输出应抽象写作方法，不应生成可替代原作阅读的大段内容。

## Architecture

```text
frontend/
  React + Vite + TypeScript demo UI

backend/
  FastAPI API
  SQLite + SQLAlchemy local storage
  file parser, chapter splitter, prompt workflow
  knowledge base and writing Agent services

examples/
  copyright-safe demo text and sample outputs

outputs/ storage/ uploads/
  local runtime data, ignored by Git
```

后端关键模块：

- `services/file_parser.py`：TXT / MD / DOCX / PDF 文本归一化。
- `services/chapter_splitter.py`：章节标题识别与长文本分块。
- `services/pipeline.py`：拆书任务、Prompt 渲染、LLM 调用和输出落盘。
- `services/phase3_exporter.py`：知识包、Obsidian 和轻量图谱导出。
- `services/knowledge_base.py`：本地知识库分块、导入、检索。
- `api/writing.py`：AI 写作 Agent、提纲、正文、世界观草案和 Memory。

## Quick Start

```bash
git clone https://github.com/elecfish-yxf/novel-deconstructor.git
cd novel-deconstructor
copy .env.example .env
docker compose up --build
```

打开：

- Frontend: http://localhost:5173
- Backend health: http://localhost:8000/health

首次体验建议保持 dry-run 开启，这样不会调用外部模型，也不需要 API Key。

## Local Development

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

## Environment

复制 `.env.example` 为 `.env` 后按需修改。模型 Key 不应该写入代码或提交到仓库。

常用配置：

- `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `DOUBAO_API_KEY` / `ARK_API_KEY`：模型服务 Key。
- `APP_DATABASE_URL`：本地 SQLite 数据库地址。
- `MAX_UPLOAD_SIZE_MB`：上传大小限制，默认示例值适合本地演示。
- `APP_UPLOAD_DIR` / `APP_OUTPUT_DIR` / `APP_KNOWLEDGE_DIR`：运行时文件目录。
- `ALLOW_ABSOLUTE_OUTPUT_PATH`：是否允许本机绝对输出路径。

公开部署时，后端不会默认使用站长自己的 API Key。关闭 dry-run 后，使用者需要在页面中填写自己的 Key；Key 只随本次请求发送给后端，不保存到数据库或浏览器偏好。

## Demo Flow

仓库提供 copyright-safe 示例，位于 `examples/`：

- `demo_story.md`：自写短篇文本；
- `sample_chapter_analysis.md`：示例章节拆解输出；
- `sample_knowledge_package.json`：示例 Agent 可消费知识包；
- `sample_agent_call.md`：示例 Agent 召回与生成过程。

推荐演示路径：

1. 进入“项目”，新建项目。
2. 进入“上传”，上传 `examples/demo_story.md`。
3. 进入“章节”，检查切章结果。
4. 进入“任务”，保持 dry-run，勾选章节结构、冲突推进、信息投放和语言风格。
5. 查看“结果”中的 Markdown、知识包和轻量图谱输出。
6. 进入“写作 Agent”，新建作品。
7. 导入拆书技巧为 `writing_guide`，再上传或确认原创 `worldbuilding`。
8. 生成提纲，确认后生成正文。

## Knowledge Package

知识包的目标不是保存剧情复述，而是保存 Agent 能消费的写作知识。

当前分层：

- `writing_guide`：拆书沉淀出的结构、节奏、冲突、情绪链、语言规则和反模式。
- `worldbuilding`：用户上传或确认导入的原创世界观、人物、地点与规则。
- `memory`：已确认提纲、正文片段、人物状态、伏笔和连续性备注。

建议的知识卡片类型：

- `ChapterAnalysis`：章节结构、状态变化、章节功能、钩子和复用模块。
- `WritingRule`：可迁移写作规则，包含适用场景、避免事项、来源和置信度。
- `EmotionModule`：情绪链、释放方式、适用场景和不可照搬内容。
- `ConflictPattern`：冲突触发、升级、释放和后续牵引。
- `AntiPattern`：不建议模仿的问题、原因和修复策略。

## Agent Retrieval Protocol

Agent 不应简单读取所有知识，而应按任务类型优先召回不同内容：

| Task | Preferred Knowledge |
|---|---|
| 生成大纲 | structure pattern, conflict pattern, emotion module |
| 生成正文 | style pattern, dialogue rule, emotion module, anti pattern |
| 检查设定 | worldbuilding, memory |
| 润色修改 | language style, anti pattern, user preference |
| 续写章节 | memory, previous ending, character state, foreshadowing, writing guide |

当前实现保留轻量关键词召回；后续可以在 `services/knowledge_base.py` 替换为向量检索，而不改变前端和 Agent 的主要使用方式。

## Web Usage

拆书流程：

1. 新建项目。
2. 上传 TXT、MD、DOCX 或 PDF。
3. 解析并切分章节。
4. 选择 Skill、分析模式和导出项。
5. 使用 dry-run 验证流程，或填写自己的 API Key 调用模型。
6. 在进度页查看日志，在结果页预览或下载 Markdown。

写作 Agent 流程：

1. 新建作品。
2. 上传写作技巧指南或世界观设定。
3. 从已完成拆书任务导入 `writing_guide`。
4. 生成或上传原创 `worldbuilding`。
5. 先生成并确认提纲。
6. 基于确认提纲生成正文。
7. 将确认后的提纲、正文片段、人物状态和伏笔写入 Memory。

## Data And Cleanup

默认运行数据会写入：

```text
storage/
uploads/
outputs/
backend/storage/
backend/uploads/
backend/outputs/
```

这些目录已被 Git 忽略。需要清理本地演示数据时，可以在停止服务后删除上述目录。请不要删除 `examples/`，它是可提交的演示素材。

## Render Deployment

仓库根目录提供 `Dockerfile` 和 `render.yaml`，可作为单 Web Service 部署。Render 云端数据写入 `/data` 持久磁盘：

- `/data/storage`：SQLite 数据库；
- `/data/uploads`：上传文件；
- `/data/outputs`：拆书输出。

如果使用公开部署，请在 README 或页面中明确：应用存储在服务器；模型调用会把相关知识片段和写作请求发送给使用者选择的模型服务；当前 workspace 不是账号系统。

## CLI

当前 CLI 提供章节切分命令：

```bash
cd backend
python -m novel_deconstructor split --input "./novel.txt" --output "./outputs/test"
```

Web UI 是主要演示入口。

## Tests

后端：

```bash
cd backend
python -m pytest --basetemp .pytest-tmp --cache-clear -o cache_dir=.pytest-cache-local
```

前端类型检查：

```bash
cd frontend
npm exec tsc -- --noEmit -p tsconfig.json
```

在 Windows 上如果默认临时目录权限异常，建议使用上面的 `--basetemp .pytest-tmp`。

## Compliance

请只分析你有权处理的文本，或在合理授权范围内使用。本工具默认用于结构分析、写作规律归纳、检查清单和方法论生成，不应输出大段原文，不应生成可替代原作阅读的内容，也不应当作“文风复刻器”。

## FAQ

**没有 API Key 能用吗？**
可以。保持 dry-run 开启即可验证上传、切章、任务、导出和 Agent 流程。

**知识库是向量库吗？**
当前是 SQLite 分块 + 本地关键词召回。项目刻意保持轻量，并保留后续替换向量检索的服务层位置。

**workspace 是账号系统吗？**
不是。workspace 是浏览器生成的轻量 ID，用来隔离项目、任务、知识库和写作上下文。清空浏览器 LocalStorage 会生成新 workspace。

**拆书结果能直接当世界观用吗？**
不建议。拆书导入默认应作为 `writing_guide`，只提供写作技巧。新故事事实应来自用户上传或确认导入的 `worldbuilding`。
