from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

from ..models import AnalysisJob, AnalysisResult, ChapterChunk, Project, SourceFile
from .path_safety import secure_slug


SCHEMA_VERSION = 2
LIBRARY_DIR_NAME = "拆文库"


@dataclass(frozen=True)
class OhStoryLayout:
    root: Path
    book_dir: Path
    chapters_dir: Path
    plot_dir: Path
    characters_dir: Path
    settings_dir: Path
    metadata_dir: Path


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def build_layout(output_dir: Path, project_name: str) -> OhStoryLayout:
    book_name = secure_slug(project_name, "novel")
    book_dir = output_dir / LIBRARY_DIR_NAME / book_name
    return OhStoryLayout(
        root=output_dir / LIBRARY_DIR_NAME,
        book_dir=book_dir,
        chapters_dir=book_dir / "章节",
        plot_dir=book_dir / "剧情",
        characters_dir=book_dir / "角色",
        settings_dir=book_dir / "设定",
        metadata_dir=book_dir / "_metadata",
    )


def ensure_layout(layout: OhStoryLayout) -> None:
    for path in [
        layout.root,
        layout.book_dir,
        layout.chapters_dir,
        layout.plot_dir,
        layout.characters_dir,
        layout.settings_dir,
        layout.metadata_dir,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def initialize_oh_story_workspace(
    output_dir: Path,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
) -> OhStoryLayout:
    layout = build_layout(output_dir, project.name)
    ensure_layout(layout)
    write_overview(layout, project, source_file, chunks)
    write_progress(layout, project, source_file, chunks, job, [])
    write_reserved_phase_files(layout, project)
    return layout


def write_overview(
    layout: OhStoryLayout,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
) -> None:
    total_chars = _total_chars(chunks)
    total_tokens = sum(chunk.token_estimate for chunk in chunks)
    sections = _chapter_sections(chunks)
    index_rows = "\n".join(
        f"| {chunk.chapter_index} | {chunk.title} | {chunk.char_count} | {chunk.token_estimate} |"
        for chunk in chunks
    )
    section_rows = "\n".join(
        f"| {name} | 第{start}-{end}章 | {count} | {chars} |" for name, start, end, count, chars in sections
    )
    content = f"""# 概要：{project.name}

> Phase 2 自动生成。当前概要来自上传文件的章节边界、字数与任务配置；完整 plot-aware 概要将在 Phase 2/3 聚合分析后覆盖本段。

## 基本信息

| 项目 | 内容 |
|---|---|
| 项目名 | {project.name} |
| 源文件 | {source_file.original_filename} |
| 总章数/分块数 | {len(chunks)} |
| 总字数 | {total_chars} |
| token 粗估 | {total_tokens} |
| 输出协议 | oh-story-codex long analyze schema v{SCHEMA_VERSION}，Phase 2 适配版 |

## 卷段概览

| 卷/段 | 章节范围 | 章数 | 预估字数 |
|---|---|---:|---:|
{section_rows or "| 默认段 | 第1-0章 | 0 | 0 |"}

## 章节索引

| 章节 | 标题 | 字数 | token 粗估 |
|---:|---|---:|---:|
{index_rows}

## 当前阶段说明

- 已完成：文件归一化、章节识别/大分块、Phase 2 多维逐章分析接口。
- 已内嵌：黄金三章、爽点循环、情绪触动点、关键信息扩写、可复现模块等拆书视角。
- 未启用：Stage 2-6 的全书聚合、角色合并、世界观抽取、GraphRAG、Obsidian/GPT Builder 知识库导出。
"""
    atomic_write(layout.book_dir / "概要.md", content)


def write_progress(
    layout: OhStoryLayout,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: Iterable[AnalysisResult],
) -> None:
    result_by_chunk = _first_result_by_chunk(results)
    completed = sum(1 for result in result_by_chunk.values() if result.status == "completed")
    failed = sum(1 for result in result_by_chunk.values() if result.status == "failed")
    final_status = _final_status(job.status, failed)
    stage1_status = _stage1_status(job.status, completed, failed, len(chunks))
    boundary_rows = "\n".join(
        f"| {chunk.chapter_index} | {chunk.title} | {chunk.char_start} | {chunk.char_count} |"
        for chunk in chunks
    )
    block_rows = "\n".join(
        f"| {chunk.chapter_index} | {chunk.title} | {_chunk_status(chunk, result_by_chunk)} |" for chunk in chunks
    )
    failed_rows = "\n".join(
        f"| chapter_structure | {chunk.title} | {result_by_chunk[chunk.id].error_message or 'unknown'} | pending |"
        for chunk in chunks
        if chunk.id in result_by_chunk and result_by_chunk[chunk.id].status == "failed"
    )
    content = f"""# 深度拆解进度：{project.name}

- 小说：{project.name} | 源文件：{source_file.original_filename} | 总章数：{len(chunks)} | 输出目录：{layout.book_dir} | 开始：{job.created_at}
- 最终状态：{final_status}
- schema_version: {SCHEMA_VERSION}

## 管道进度

| 阶段 | 状态 | 进度 | 备注 |
|---|---|---|---|
| Stage 0 概要与章节边界 | completed | {len(chunks)}/{len(chunks)} | 由上传解析与切章结果生成 |
| Stage 1 黄金三章/逐章结构 | {stage1_status} | {completed}/{len(chunks)} | Phase 2 当前启用 |
| Stage 2 逐章摘要与情节点 | reserved | 0/{len(chunks)} | Phase 2 接入 |
| Stage 3 剧情/节奏/情绪聚合 | reserved | 0/1 | Phase 2/3 接入 |
| Stage 4 设定/角色/关系 | reserved | 0/1 | Phase 2/3 接入 |
| Stage 5 拆文报告 | reserved | 0/1 | Phase 3 接入；Phase 2 生成阶段报告 |
| Stage 6 文风 | reserved | 0/1 | Phase 3 接入 |

## 章节边界（Stage 0.5 产物，唯一权威）

| 章号 | 标题 | 起始字符 | 字数 |
|---:|---|---:|---:|
{boundary_rows}

## 分块进度

| 块 | 章节 | 状态 |
|---:|---|---|
{block_rows}

## 失败记录

| 类型 | 章节/阶段 | 错误信息 | 重试状态 |
|---|---|---|---|
{failed_rows or "| - | - | - | - |"}

## 质量检查

| 检查项 | 阶段 | 结果 | 修正 |
|---|---|---|---|
| 不输出大段原文 | Phase 2 | enabled | Prompt 内置短引用限制 |
| 大文件输入 | Phase 2 | enabled | 上传流式保存，逐章送模 |
| 断点恢复 | Phase 2 | enabled | 已完成 result 会被跳过 |

## 断点

- 最后处理：{job.current_chunk_title or '无'} | 当前模式：{job.current_mode or '无'} | 下一操作：继续未完成章节或查看失败记录
"""
    atomic_write(layout.book_dir / "_progress.md", content)


MODE_LABELS = {
    "chapter_structure": "深度拆解",
    "conflict_analysis": "冲突分析",
    "character_growth": "人物成长",
    "information_delivery": "信息投放",
    "language_style": "语言风格",
    "ai_bad_patterns": "AI味检查",
    "volume_summary": "卷段总结",
    "final_knowledge_base": "知识库规则",
    "obsidian_export": "Obsidian导出",
}


def write_chapter_analysis(layout: OhStoryLayout, chunk: ChapterChunk, mode: str, markdown: str) -> Path:
    suffix = MODE_LABELS.get(mode, mode)
    if mode == "chapter_structure" and chunk.chapter_index > 3:
        suffix = "结构拆解"
    path = layout.chapters_dir / f"第{chunk.chapter_index:04d}章_{suffix}.md"
    atomic_write(path, markdown)
    return path


def write_summary_outputs(
    layout: OhStoryLayout,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> None:
    write_progress(layout, project, source_file, chunks, job, results)
    write_quick_preview(layout, project, source_file, chunks, job, results)
    write_phase1_report(layout, project, source_file, chunks, job, results)


def write_quick_preview(
    layout: OhStoryLayout,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> None:
    result_by_chunk = _first_result_by_chunk(results)
    golden_rows = "\n".join(
        f"| 第{chunk.chapter_index}章 | {chunk.title} | {_chapter_output_name(chunk)} | {_chunk_status(chunk, result_by_chunk)} |"
        for chunk in chunks[:3]
    )
    content = f"""# 快速预览：{project.name}

> 基于 Phase 2 多维逐章分析生成。它是 oh-story Stage 1 停靠点的部署版骨架，完整拆解会在后续 Stage 2-6 扩展。
> 状态：{job.status}

## 基本信息

| 书名/项目 | 源文件 | 总章数/分块数 | 总字数 | 目标 |
|---|---|---:|---:|---|
| {project.name} | {source_file.original_filename} | {len(chunks)} | {_total_chars(chunks)} | 结构拆书、规则提炼、知识库准备 |

## 黄金三章

| 章节 | 标题 | 产物 | 状态 |
|---|---|---|---|
{golden_rows or "| - | - | - | - |"}

## 早期判断

- Phase 2 已把前三章按“黄金三章”优先级输出到 `章节/`。
- 每章分析关注：开头状态、结尾状态、冲突、信息投放、语言自然度、可学习规律。
- 当前版本不做全书剧情归因判断，避免在没有 Stage 2-3 聚合证据时过度推断。

## 下一步

继续 Phase 2/3 后，本目录可继续生成：逐章摘要、情节点、剧情/节奏/情绪模块、角色档案、世界观设定、完整拆文报告、文风报告。
"""
    atomic_write(layout.book_dir / "快速预览.md", content)


def write_phase1_report(
    layout: OhStoryLayout,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> None:
    result_by_chunk = _first_result_by_chunk(results)
    completed = sum(1 for result in result_by_chunk.values() if result.status == "completed")
    failed = sum(1 for result in result_by_chunk.values() if result.status == "failed")
    chapter_rows = "\n".join(
        f"| {chunk.chapter_index} | {chunk.title} | {_chapter_output_name(chunk)} | {_chunk_status(chunk, result_by_chunk)} |"
        for chunk in chunks
    )
    content = f"""# 拆文报告：{project.name}

> Phase 2 报告。当前文件聚合任务状态与产物索引；真正的全书剧情/角色/设定结论将在 Phase 2/3 基于逐章证据生成。

## 基本信息

| 项目 | 内容 |
|---|---|
| 项目名 | {project.name} |
| 源文件 | {source_file.original_filename} |
| 任务 ID | {job.id} |
| 任务状态 | {job.status} |
| 总章数/分块数 | {len(chunks)} |
| 已完成 | {completed} |
| 失败 | {failed} |
| dry-run | {job.dry_run} |

## 已生成产物

| 文件 | 用途 |
|---|---|
| `概要.md` | 章节边界、字数、Phase 2 范围说明 |
| `_progress.md` | 断点恢复、失败记录、阶段状态 |
| `快速预览.md` | 黄金三章停靠点骨架 |
| `章节/*.md` | 逐章结构拆解结果 |
| `剧情/README.md` | Stage 3 接口预留 |
| `角色/README.md` | Stage 4 角色接口预留 |
| `设定/README.md` | Stage 4 设定接口预留 |

## 章节产物索引

| 章号 | 标题 | 产物 | 状态 |
|---:|---|---|---|
{chapter_rows}

## Phase 2 内嵌的 oh-story 拆解视角

- 黄金三章：优先观察开篇钩子、主角立人设、世界观铺设、章尾悬念。
- 爽点循环：铺垫层、释放层、反应层、衔接层。
- 信息投放：新增信息、回收信息、悬念、硬讲设定风险。
- 情绪触动：期待、压抑、爽、甜、心疼、紧张、热血等读者情绪。
- 可复现模块：只抽象情绪链和功能位，不搬运原文桥段。

## 不建议模仿

- 不把 dry-run 当真实结论。
- 不把拆书输出当文风复刻器。
- 不输出或传播可替代原作阅读的大段原文。
- 不在缺少全书聚合证据时强行判断角色弧线、世界观体系或完整主线。
"""
    atomic_write(layout.book_dir / "拆文报告.md", content)


def write_reserved_phase_files(layout: OhStoryLayout, project: Project) -> None:
    reserved_files = {
        layout.plot_dir / "README.md": f"""# 剧情目录索引：{project.name}

> Phase 2/3 预留。后续会拆分为 `故事线.md`、`节奏.md`、`情绪模块.md`，并以节奏/情绪模块作为下游写作知识的权威索引。

| 文件 | 权威范围 | 当前状态 |
|---|---|---|
| `故事线.md` | 故事框架与故事线摘要 | reserved |
| `节奏.md` | 关键信息推进、爽点循环、情绪触动点 | reserved |
| `情绪模块.md` | 读者需求、情绪引擎、可复现模块卡 | reserved |
""",
        layout.characters_dir / "README.md": f"""# 角色档案：{project.name}

> Phase 2/3 预留。后续会根据逐章出场、台词、关系变化和推动剧情能力生成角色分级与角色关系表。
""",
        layout.settings_dir / "README.md": f"""# 设定档案：{project.name}

> Phase 2/3 预留。后续会拆分世界观、力量体系、地理、势力、金手指等文件；原文未明确的硬事实不会编造。
""",
        layout.metadata_dir / "method_pack.md": f"""# oh-story Phase 2 内嵌方法包

本项目已把 `oh-story-codex` 的长篇拆文思路适配为后端可部署管线：

- Stage 0：概要、章节边界、进度表。
- Stage 1：黄金三章 + 逐章结构分析。
- Stage 2-6：逐章摘要、剧情聚合、角色设定、拆文报告、文风报告，当前保留接口。

Phase 2 的原则是：稳定处理大文件，按 Skill 进行多维逐章输出，并为 Phase 3 全书聚合保留结构化证据。
""",
    }
    for path, content in reserved_files.items():
        if not path.exists():
            atomic_write(path, content)


def _first_result_by_chunk(results: Iterable[AnalysisResult]) -> dict[str, AnalysisResult]:
    result_by_chunk: dict[str, AnalysisResult] = {}
    for result in results:
        result_by_chunk.setdefault(result.chunk_id, result)
    return result_by_chunk


def _chunk_status(chunk: ChapterChunk, result_by_chunk: dict[str, AnalysisResult]) -> str:
    result = result_by_chunk.get(chunk.id)
    return result.status if result else "pending"


def _final_status(job_status: str, failed: int) -> str:
    if job_status == "completed":
        return "completed_with_errors" if failed else "completed"
    if job_status in {"paused", "cancelled", "failed"}:
        return job_status
    return "pending"


def _stage1_status(job_status: str, completed: int, failed: int, total: int) -> str:
    if job_status == "completed" and completed >= total and failed == 0:
        return "completed"
    if job_status == "failed" or failed:
        return "completed_with_errors"
    if completed:
        return "running"
    return "pending"


def _chapter_output_name(chunk: ChapterChunk) -> str:
    suffix = "深度拆解" if chunk.chapter_index <= 3 else "结构拆解"
    return f"章节/第{chunk.chapter_index:04d}章_{suffix}.md"


def _total_chars(chunks: list[ChapterChunk]) -> int:
    return sum(chunk.char_count for chunk in chunks)


def _chapter_sections(chunks: list[ChapterChunk]) -> list[tuple[str, int, int, int, int]]:
    if not chunks:
        return []
    sections: list[tuple[str, int, int, int, int]] = []
    section_size = 20
    for index in range(0, len(chunks), section_size):
        group = chunks[index : index + section_size]
        start = group[0].chapter_index
        end = group[-1].chapter_index
        count = len(group)
        chars = sum(chunk.char_count for chunk in group)
        sections.append((f"第{len(sections) + 1}段", start, end, count, chars))
    return sections

