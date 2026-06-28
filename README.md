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
  -> Raw Knowledge Cards
  -> Canonical Cards / Markdown Sync
  -> writing_guide / worldbuilding / memory
  -> Lightweight RAG
  -> AI Writing Agent
  -> Outline / Draft / Revision / Long Draft Job
  -> Memory Confirmation / Continuation
```

## Features

- TXT / MD / DOCX / PDF 上传与文本解析，扫描版 PDF 需要先 OCR。
- 长文本章节识别与切分，支持中文章回标题、卷、序章、终章和 `Chapter 1`。
- 无章节标题时按字符数分块，超长章节可按配置二次分块。
- 多维拆书分析：章节结构、冲突推进、人物变化、信息投放、语言风格、AI 味检查。
- oh-story 风格拆书流程：黄金三章、爽点循环、情绪触动点、可复现模块、章尾牵引。
- 知识包分层：`writing_guide` 保存写作技巧，`worldbuilding` 保存用户确认的原创设定，`memory` 保存写作连续性。
- KnowledgeCard 工作流：先导入 Raw Card，再通过预览合并为 Canonical Card，并保留来源证据。
- Canonical Markdown：可把可复用知识写成可编辑 Markdown，再同步回结构化卡片。
- 轻量知识检索：本地 SQLite 文档分块 + 关键词召回，保留后续替换向量检索的服务层位置。
- AI 写作 Agent：先生成可确认提纲，再基于确认提纲生成正文、修订建议或长文本分段任务，并承接长期 Memory。
- RAG 可解释性：返回 `used_knowledge` 与 `retrieval_debug`，用于检查本次输出实际用了哪些知识。
- 导出 Markdown / JSON / Obsidian 友好文档和轻量图谱 JSON。
- Docker 本地启动，支持 dry-run 模式，不配置 API Key 也能验证流程。

## Project Scope

这是一个个人轻量级开源项目和作品集项目，重点是把“长文本拆书 -> 写作知识抽取 -> Agent 调用”做清楚、做扎实、能演示。

当前边界：

- 主要面向本地个人使用、学习和项目演示。
- 不是企业级 SaaS，也不是多租户商业平台。
- 本地匿名模式下，浏览器 workspace 是轻量隔离机制；云端可开启个人项目级账号登录，但不是企业级 RBAC。
- 当前 RAG 是 SQLite 文档分块 + 本地关键词召回，不是完整向量数据库。
- 当前图谱导出是轻量 JSON/Markdown，不是生产级 GraphRAG。
- 拆书输出应抽象写作方法，不应生成可替代原作阅读的大段内容。

## Architecture

```text
frontend/
  React + Vite + TypeScript demo UI

backend/
  FastAPI API
  SQLite / MySQL + SQLAlchemy storage
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
- `APP_DATABASE_URL`：数据库地址；本地默认 SQLite，ECS 正式部署建议使用阿里云 RDS MySQL 内网地址。
- `APP_REQUIRE_AUTH`：云端建议设为 `true`，本地演示可以保持 `false`。
- `CORS_ORIGINS`：允许访问后端的前端域名；ECS 同域 Nginx 反代时通常只需写正式域名。
- `MAX_UPLOAD_SIZE_MB`：上传大小限制，默认示例值适合本地演示。
- `APP_UPLOAD_DIR` / `APP_OUTPUT_DIR` / `APP_KNOWLEDGE_DIR`：运行时文件目录。
- `ALLOW_ABSOLUTE_OUTPUT_PATH`：是否允许本机绝对输出路径。

公开部署时，建议设置 `APP_REQUIRE_AUTH=true`。后端不会默认使用站长自己的 API Key；关闭 dry-run 后，使用者需要在页面中填写自己的 Key，Key 只随本次请求发送给后端，不保存到数据库或浏览器偏好。

## Demo Flow

仓库提供 copyright-safe 示例，位于 `examples/`：

- `demo_story.md`：自写短篇文本；
- `sample_chapter_analysis.md`：示例章节拆解输出；
- `sample_knowledge_package.json`：示例 Agent 可消费知识包；
- `sample_canonical_cards.json`：示例 Raw Card 合并后的 Canonical Card 形态；
- `sample_agent_call.md`：示例 Agent 召回与生成过程；
- `comparison_without_vs_with_rag.md`：同一请求在无 RAG、仅 `writing_guide`、`writing_guide + worldbuilding + memory` 下的差异。

推荐演示路径：

1. 启动项目，保持 dry-run 也可以完整演示。
2. 注册并登录；本地匿名模式也可先跳过登录。
3. 进入“项目”，新建 Demo 拆书项目。
4. 进入“上传”，上传 `examples/demo_story.md`。
5. 进入“章节”，检查切章结果。
6. 进入“任务”，勾选章节结构、冲突推进、信息投放和语言风格。
7. 查看“结果”中的 Markdown、知识包和轻量图谱输出。
8. 进入“写作 Agent”，新建作品。
9. 导入 `examples/sample_knowledge_package.json` 为 `writing_guide`。
10. 查看 Raw / Canonical 统计，预览并执行安全合并。
11. 编辑一份 Canonical Markdown 并同步回卡片。
12. 用 outline 阶段 RAG 预览召回结果，检查 `used_knowledge`。
13. dry-run 查看 Prompt 和检索调试信息，再按需填写自己的模型 Key 调用模型。
14. 确认提纲进入 Memory。
15. 请求较长正文，查看分段进度、每段知识和补写次数。
16. 确认正文进入 Memory。
17. 发起续写或 revision，验证 Memory 被召回。

## Knowledge Package

知识包的目标不是保存剧情复述，而是保存 Agent 能消费的写作知识。

当前分层：

- `writing_guide`：拆书沉淀出的结构、节奏、冲突、情绪链、语言规则和反模式。
- `worldbuilding`：用户上传或确认导入的原创世界观、人物、地点与规则。
- `memory`：已确认提纲、正文片段、人物状态、伏笔和连续性备注。

KnowledgeCard / Markdown / Canonical Card 的关系：

- Raw Evidence / Raw Card：从知识包或 Markdown 中导入的原始卡片，保留来源和证据，默认 `status=raw_extracted`、`is_canonical=false`、`retrievable=false`。
- Canonical Knowledge / Canonical Card：人工确认或安全合并后的主卡片；只有 `reviewed` / `approved`、`is_canonical=true`、`retrievable=true` 的卡片默认参与 RAG 检索。
- Markdown Doc：给人编辑的知识文档，可同步回结构化卡片。
- disabled / deleted / deprecated / superseded / merged-away 卡片默认不参与检索。

在写作 Agent 的知识面板中上传或按路径导入 Markdown 时，默认按 `approved` 导入。这适合用户已经整理好的世界观设定库和写作指南，导入后可直接参与常规 RAG；如果需要人工审核式流程，可以在接口层显式传 `status=raw_extracted`。

每张 KnowledgeCard 都有明确作用域，不再用 `source_ref` 判断召回范围：

- `scope_level=global`：全局知识，通常适合 `writing_guide`。
- `scope_level=volume`：当前卷及之前卷可见。
- `scope_level=chapter`：当前章节及之前章节可见。
- `volume_index` / `chapter_index` 描述卡片所属位置。
- `reveal_at_*` / `valid_from_*` / `valid_until_*` 控制何时可见、何时过期。

`source_ref` 只用于证据追踪。它说明知识来自哪里，但不再决定 RAG 能不能召回这张卡。写第 1 卷第 5 章时，RAG 会在关键词评分前先硬过滤第 1 卷第 6 章、第 2 卷以及未来才揭示的 worldbuilding / memory，避免未来章节泄漏。

拆书结果默认应进入 `writing_guide`。只有用户原创或明确确认的新作品事实，才应进入 `worldbuilding`。已经确认的提纲、正文片段和连续性备注，才应进入 `memory`。

建议的知识卡片类型：

- `ChapterAnalysis`：章节结构、状态变化、章节功能、钩子和复用模块。
- `WritingRule`：可迁移写作规则，包含适用场景、避免事项、来源和置信度。
- `EmotionModule`：情绪链、释放方式、适用场景和不可照搬内容。
- `ConflictPattern`：冲突触发、升级、释放和后续牵引。
- `AntiPattern`：不建议模仿的问题、原因和修复策略。

## Agent Retrieval Protocol

Writing Agent requests now share one explicit writing position across outline, draft, revision, RAG preview, and Memory confirmation. Confirmed outlines are persisted as `ChapterOutline` cards at the current volume/chapter. Confirmed drafts are distilled into `ChapterHandoff` cards that become visible from the next chapter, so continuation can inherit the prior ending without exposing future chapters. Raw Evidence remains off by default and is intended only for debug inspection.

Current writing position is a core context field:

- `current_volume_index` and `current_chapter_index` must travel from the page payload into the writing API, RAG retrieval, retrieval debug, and final prompt.
- The final prompt includes `[CURRENT WRITING POSITION]` and `[RETRIEVAL POLICY]`, explicitly forbidding future volume or future chapter knowledge.
- If the position is missing, scoped story knowledge is not treated as safe by default; only global `writing_guide` can be used safely and retrieval debug returns a warning.
- Outline scope is explicit: `scope_level=chapter` keeps the request as a current-chapter outline, `scope_level=volume` generates the current-volume outline, and `scope_level=global` / `book` allows full-story planning. Mentioning a long-form writing guide such as `AI中文长篇小说写作指南` does not by itself expand a chapter outline into a full novel outline.
- Draft prompts treat `章尾落点`、`结尾状态` and `章尾钩子` as the final scene of the current chapter. Once the draft reaches that beat, it should stop instead of continuing into the next-chapter conflict, rescue aftermath, or author-style summary.

Chapter memory inheritance:

- Confirmed outlines are saved as approved, canonical, retrievable `ChapterOutline` Memory cards visible from their own chapter.
- Confirmed drafts are summarized into approved, canonical, retrievable `ChapterHandoff` Memory cards. A Chapter 1 handoff becomes visible from Chapter 2, so Chapter 1 cannot see its own ending handoff.
- Before outline or draft generation, the context builder prioritizes current chapter outline, previous chapter handoff, active character state, active relationship state, active foreshadowing, current volume summary, global worldbuilding, global writing guide, and anti-patterns.

Raw Evidence and scope-safe RAG:

- Raw Evidence defaults to `status=raw_extracted`, `is_canonical=false`, and `retrievable=false`.
- Normal writing RAG only uses canonical, retrievable, reviewed/approved cards.
- `include_raw` / `include_raw_knowledge` is for explicit debug inspection. Raw cards are allowed into the final writing prompt only in dry-run debug mode.
- Final prompt assembly performs a second safety pass and drops future chapter, future volume, blocked, inactive, noncanonical, and raw cards that are not allowed for the current request.

Agent 不应简单读取所有知识，而应按任务类型优先召回不同内容：

| Task | Preferred Knowledge |
|---|---|
| 生成大纲 | structure pattern, conflict pattern, emotion module |
| 生成正文 | style pattern, dialogue rule, emotion module, anti pattern |
| 检查设定 | worldbuilding, memory |
| 润色修改 | language style, anti pattern, user preference |
| 续写章节 | memory, previous ending, character state, foreshadowing, writing guide |

当前实现保留轻量关键词召回；后续可以在 `services/knowledge_base.py` 替换为向量检索，而不改变前端和 Agent 的主要使用方式。

Lightweight RAG Writing Agent Loop：

```text
user task
  -> task_type / phase
  -> query expansion
  -> knowledge base + library filter
  -> reviewed/approved + canonical + retrievable filter
  -> global / volume / chapter scope hard filter
  -> keyword + tag + card_type scoring
  -> duplicate/diversity filtering
  -> prompt assembly
  -> model or dry-run
  -> used_knowledge + retrieval_debug
  -> confirmed output writes Memory
```

这套 RAG 的重点是可解释和轻量：你能看到召回了哪些卡片、scope 过滤前后候选数、哪些未来知识被过滤、哪些重复内容被过滤。它仍然不是生产级向量 RAG，没有集成 Qdrant、Chroma、Milvus 或 pgvector；本轮实现的是 scope-safe lightweight RAG。

## Long Text Generation

当正文目标较长时，Agent 会把任务拆成多个 section，每段单独检索知识、生成内容并统计字数。当前机制包括：

- 从自然语言或字段中解析目标字数，例如“写 10000 字正文”。
- 对长正文进行分段计划，逐段组装 Prompt 和 RAG 知识。
- 每段统计 CJK 字数、非空白字符数和粗略 token 估算。
- 如果单段明显低于目标，会尝试补写；默认补写上限为 2 次。
- 最后一段和补写都会被约束在提纲指定的章尾落点内，避免为了凑字数提前写下一章。
- 最终结果低于目标较多时会返回 warning，避免假装已经满足字数。
- 长文本可通过后台 draft job 轮询进度，也可取消；页面刷新后只要后端进程还在，可恢复最近一次 job 状态。

限制：当前 draft job 是内存态，不是数据库持久队列；如果后端进程重启，未完成 job 不会恢复。长文本质量仍取决于模型上下文窗口、输出上限和用户确认的知识质量。

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

## Deployment

推荐正式部署路径是 **ECS + Docker + Nginx + 阿里云 RDS MySQL**。根目录 `Dockerfile` 会构建前端并由 FastAPI 同容器托管静态页面，ECS 上只需要把容器绑定到 `127.0.0.1:8000`，再由 Nginx 提供公网域名、HTTPS 和反向代理。

当前仓库也支持 Docker Compose 双容器部署：`backend` 监听 `8000`，`frontend` 通过 Nginx 静态托管到 `5173`。这条路径适合 ECS 临时验证、内网测试或没有单容器反代配置时快速上线。

```bash
cd /srv/novel-deconstructor
docker compose build backend frontend
docker compose up -d backend frontend
docker compose ps
curl -sS http://127.0.0.1:8000/health
curl -sS -I http://127.0.0.1:5173/ | head -n 5
```

如果 ECS 内部健康检查正常，但公网访问 `http://<ecs-ip>:8000/health` 或 `http://<ecs-ip>:5173/` 超时，优先检查阿里云安全组入站规则。服务器本机还可用下面的命令确认是否是本机防火墙或监听问题：

```bash
ufw status
ss -lntp | grep -E ':8000|:5173'
```

`ufw` 为 inactive 且端口监听在 `0.0.0.0` 时，公网超时通常是云侧安全组未放行对应 TCP 端口。正式公开部署更推荐只放行 `80/443`，由 Nginx 反代到应用端口。

部署细节见 [`deploy/ecs.md`](deploy/ecs.md)，包括：

- ECS Docker 启动命令；
- RDS 内网连接串；
- 必要环境变量；
- Nginx 反代配置；
- ECS 与 RDS 安全组配置；
- 本地 Docker Compose 与 ECS 单容器部署的差异。

ECS 作为正式部署。Render 暂时保留 1-3 天作为回滚备份；确认 ECS 稳定后，暂停或删除 Render 服务，避免双站点运行和额外费用。

### ECS Environment Sketch

```env
APP_DATABASE_URL=mysql+pymysql://<user>:<url_encoded_password>@<rds-internal-host>:3306/<database>?charset=utf8mb4
APP_STORAGE_DIR=/app/backend/storage
APP_UPLOAD_DIR=/app/backend/uploads
APP_OUTPUT_DIR=/app/backend/outputs
APP_KNOWLEDGE_DIR=/app/backend/storage/knowledge
APP_REQUIRE_AUTH=true
ENABLE_DIRECTORY_PICKER=false
CORS_ORIGINS=https://your-domain.example
```

RDS/MySQL deployments should run the startup and scoped RAG checks in
[`docs/rds-smoke-test.md`](docs/rds-smoke-test.md). The backend uses a lightweight,
idempotent schema upgrade today; new KnowledgeCard columns and indexes are checked
before being added, and MySQL initialization failures do not fall back to SQLite.

本地开发仍可使用 SQLite 和 Docker Compose：

```bash
copy .env.example .env
docker compose up --build
```

### Optional Render Deployment

`render.yaml` 保留为 Render 专用配置，只在 Render 平台部署时生效，不影响 ECS、Docker Compose 或阿里云服务器运行。Render 可作为 optional deployment 或短期回滚备份。

仓库根目录提供 `Dockerfile` 和 `render.yaml`，可作为 Render 单 Web Service 部署。Render 云端数据写入 `/data` 持久磁盘：

- `/data/storage`：SQLite 数据库；
- `/data/uploads`：上传文件；
- `/data/outputs`：拆书输出。

如果使用公开部署，请在 README 或页面中明确：应用数据存储在服务器；模型调用会把相关知识片段和写作请求发送给使用者选择的模型服务；workspace 是数据隔离标识，云端建议配合 `APP_REQUIRE_AUTH=true` 使用。

## CLI

当前 CLI 提供章节切分命令：

```bash
cd backend
python -m novel_deconstructor split --input "./novel.txt" --output "./outputs/test"
```

Web UI 是主要演示入口。

## Route Contract

P1 front-end/back-end route alignment is recorded in [`docs/p1-route-audit.md`](docs/p1-route-audit.md). The contract is also covered by `backend/tests/test_p1_route_contract.py`, including the new `/api/writing/works/{work_id}/agent/revision` route, draft job routes and deprecated legacy writing endpoints.

P5 release verification references:

- [`docs/test-matrix.md`](docs/test-matrix.md)：核心闭环测试矩阵；
- [`docs/security-release-checklist.md`](docs/security-release-checklist.md)：ECS/Render 发布前安全检查；
- [`docs/code-quality-boundaries.md`](docs/code-quality-boundaries.md)：当前服务边界与后续可拆分目标；
- [`docs/prompt-coverage-audit.md`](docs/prompt-coverage-audit.md)：90 分完整 Prompt 覆盖对照；
- [`docs/final-delivery-report.md`](docs/final-delivery-report.md)：阶段性交付报告与已知限制。

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

前端生产构建：

```bash
cd frontend
npm run build
```

提交前空白检查：

```bash
git diff --check
```

在 Windows 上如果默认临时目录权限异常，建议使用上面的 `--basetemp .pytest-tmp`。

## Limitations

- 当前是个人项目级账号与 workspace，不是企业级多租户 RBAC。
- 当前检索是轻量 keyword / tag / card_type scoring，不是生产级向量数据库。
- 当前图谱导出是轻量 JSON/Markdown，不是生产级 GraphRAG。
- Canonical 合并采用启发式和可选人工确认，可能存在误合并风险。
- 长文本质量仍取决于模型能力、上下文窗口、输出限制和用户确认的知识质量。
- 后台 draft job 当前为内存态，后端进程重启后未完成任务不会恢复。
- 拆书知识用于抽象写法，不用于复制原作内容、专名、角色或桥段。

## Compliance

请只分析你有权处理的文本，或在合理授权范围内使用。本工具默认用于结构分析、写作规律归纳、检查清单和方法论生成，不应输出大段原文，不应生成可替代原作阅读的内容，也不应当作“文风复刻器”。

## FAQ

**没有 API Key 能用吗？**
可以。保持 dry-run 开启即可验证上传、切章、任务、导出和 Agent 流程。

**知识库是向量库吗？**
当前是 SQLite 分块 + 本地关键词召回。项目刻意保持轻量，并保留后续替换向量检索的服务层位置。

**workspace 是账号系统吗？**
不是企业级账号系统。本地匿名模式下，workspace 是浏览器生成的轻量 ID，用来隔离项目、任务、知识库和写作上下文；云端建议开启 `APP_REQUIRE_AUTH=true`，登录后由后端通过 Bearer token 推导用户 workspace。

**拆书结果能直接当世界观用吗？**
不建议。拆书导入默认应作为 `writing_guide`，只提供写作技巧。新故事事实应来自用户上传或确认导入的 `worldbuilding`。
