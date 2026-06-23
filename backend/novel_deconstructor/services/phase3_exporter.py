from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path
import json
import re

from ..models import AnalysisJob, AnalysisResult, ChapterChunk, Project, SourceFile


SECTION_HEAD_RE = re.compile(r"^##\s+\d*\.?\s*(.+?)\s*$", re.MULTILINE)
RULE_HINTS = ("可学习规律", "可加入知识库", "可复现", "写作规则", "复现提示")
ANTI_HINTS = ("不建议模仿", "AI 味", "硬讲设定", "风险", "问题")
MODE_LABELS = {
    "chapter_structure": "章节结构",
    "conflict_analysis": "冲突推进",
    "character_growth": "人物成长",
    "information_delivery": "信息投放",
    "language_style": "语言风格",
    "ai_bad_patterns": "AI 味检查",
}
KNOWLEDGE_PACKAGE_SCHEMA_VERSION = "0.1.0"
AGENT_RETRIEVAL_PROTOCOL = {
    "outline": ["structure_pattern", "conflict_pattern", "emotion_module"],
    "draft": ["style_pattern", "dialogue_rule", "emotion_module", "anti_pattern"],
    "worldbuilding_check": ["worldbuilding", "memory"],
    "revision": ["language_style", "anti_pattern", "user_preference"],
    "continuation": ["memory", "previous_ending", "character_state", "foreshadowing", "writing_guide"],
}


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def generate_phase3_outputs(
    output_dir: Path,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> list[Path]:
    completed = [result for result in results if result.status == "completed" and result.markdown_path]
    written: list[Path] = []
    written.extend(write_overall_summary(output_dir / "final_reports", project, source_file, chunks, job, completed))
    if job.generate_kb:
        written.extend(write_knowledge_base(output_dir / "knowledge_base", project, source_file, chunks, job, completed))
    if job.generate_obsidian:
        written.extend(write_obsidian_export(output_dir / "knowledge_base_obsidian", project, source_file, chunks, job, completed))
    if job.generate_graph:
        written.extend(write_graph_outputs(output_dir / "graph_outputs", project, source_file, chunks, job, completed))
    return written


def write_overall_summary(
    target_dir: Path,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    base_dir = target_dir.parent
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    mode_groups = _group_results_by_mode(results)
    results_by_chunk = _group_results_by_chunk(results)
    rule_blocks = _collect_rule_blocks(results)[:30]
    anti_blocks = _collect_anti_blocks(results)[:30]
    mode_summaries = _collect_mode_summaries(results, chunks_by_id)
    generated_at = datetime.now().isoformat(timespec="seconds")

    mode_rows = "\n".join(
        f"| {MODE_LABELS.get(mode, mode)} | `{mode}` | {len(items)} |"
        for mode, items in mode_groups.items()
    )
    chapter_rows = "\n".join(
        _chapter_summary_row(chunk, results_by_chunk.get(chunk.id, []))
        for chunk in chunks
    )
    mode_sections = "\n\n".join(
        f"### {MODE_LABELS.get(mode, mode)}\n\n{summary}"
        for mode, summary in mode_summaries.items()
    )
    doc_index = _analysis_document_index(results, chunks_by_id, base_dir)

    content = f"""# 总汇总报告：{project.name}

> Phase 3 自动汇总。来源：{source_file.original_filename}；任务：{job.id}；生成时间：{generated_at}。
> 本报告汇总所有已完成的逐章分析 Markdown，用于快速查看全书拆解结论、可复用规律、风险点和全部产物索引。

## 1. 处理概况

| 项目 | 内容 |
|---|---|
| 项目名 | {project.name} |
| 源文件 | {source_file.original_filename} |
| 任务 ID | {job.id} |
| 任务状态 | {job.status} |
| dry-run | {job.dry_run} |
| 章节/分块数 | {len(chunks)} |
| 已完成分析文档 | {len(results)} |
| 分析模式数 | {len(mode_groups)} |

## 2. 分析维度覆盖

| 维度 | 模式 Key | 完成文档数 |
|---|---|---:|
{mode_rows or "| - | - | 0 |"}

## 3. 章节覆盖总览

| 章号 | 标题 | 字数 | 已完成维度 | 产物数 |
|---:|---|---:|---|---:|
{chapter_rows or "| - | - | 0 | - | 0 |"}

## 4. 全书综合观察

{mode_sections or "- 暂无可提取的综合观察；请先完成非 dry-run 分析。"}

## 5. 可复用写作规律汇总

{_format_blocks(rule_blocks, "暂无可提取规律；请检查逐章分析是否已完成。")}

## 6. 风险与不建议模仿

{_format_blocks(anti_blocks, "暂无风险清单；请检查逐章分析是否已完成。")}

## 7. 全部分析文档索引

{doc_index or "- 暂无完成的分析文档。"}
"""
    return [_write(target_dir / "overall_summary.md", content)]


def write_knowledge_base(
    target_dir: Path,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    mode_groups = _group_results_by_mode(results)
    rule_blocks = _collect_rule_blocks(results)
    anti_blocks = _collect_anti_blocks(results)
    written: list[Path] = []

    index = f"""# {project.name} GPT Builder 知识库

> Phase 3 自动导出。来源：{source_file.original_filename}；任务：{job.id}；生成时间：{datetime.now().isoformat(timespec="seconds")}。
> 用途：把拆书分析压缩成可复用写作规则，不包含可替代原作阅读的大段原文。

## 文件说明

| 文件 | 内容 |
|---|---|
| `writing_rules.md` | 可复用写作规则与模块 |
| `anti_patterns.md` | 不建议模仿、AI 味和风险清单 |
| `mode_index.md` | 各分析模式与产物索引 |
| `knowledge_package.json` | Agent 可消费的轻量结构化知识包 |

## 覆盖范围

- 章节/分块数：{len(chunks)}
- 已完成分析项：{len(results)}
- 分析模式：{", ".join(mode_groups) if mode_groups else "无"}
"""
    written.append(_write(target_dir / "README.md", index))

    rules = "# 可复用写作规则\n\n"
    rules += "\n\n".join(rule_blocks) if rule_blocks else "- 暂无可提取规则；请先完成非 dry-run 分析。\n"
    written.append(_write(target_dir / "writing_rules.md", rules))

    anti = "# 不建议模仿与风险清单\n\n"
    anti += "\n\n".join(anti_blocks) if anti_blocks else "- 暂无风险清单；请先完成非 dry-run 分析。\n"
    written.append(_write(target_dir / "anti_patterns.md", anti))

    mode_index = "# 分析模式索引\n\n"
    for mode, items in mode_groups.items():
        mode_index += f"## {mode}\n\n"
        for item in items:
            mode_index += f"- {Path(item.markdown_path or '').name}\n"
        mode_index += "\n"
    written.append(_write(target_dir / "mode_index.md", mode_index))

    package = build_knowledge_package(project, source_file, chunks, job, results)
    written.append(_write(target_dir / "knowledge_package.json", json.dumps(package, ensure_ascii=False, indent=2)))
    return written


def build_knowledge_package(
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> dict:
    chunks_by_id = {chunk.id: chunk for chunk in chunks}
    results_by_chunk = _group_results_by_chunk(results)
    generated_at = datetime.now().isoformat(timespec="seconds")
    return {
        "schema_version": KNOWLEDGE_PACKAGE_SCHEMA_VERSION,
        "package_id": f"{_safe_filename(project.name)}_{job.id}",
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
        },
        "source": {
            "file_id": source_file.id,
            "filename": source_file.original_filename,
            "file_type": source_file.file_type,
        },
        "job": {
            "id": job.id,
            "dry_run": job.dry_run,
            "modes": sorted(_group_results_by_mode(results).keys()),
        },
        "generated_at": generated_at,
        "agent_retrieval_protocol": AGENT_RETRIEVAL_PROTOCOL,
        "chapter_analysis": [_chapter_analysis_card(chunk, results_by_chunk.get(chunk.id, []), source_file) for chunk in chunks],
        "writing_rules": _writing_rule_cards(results, chunks_by_id, project.name),
        "emotion_modules": _emotion_module_cards(chunks, results_by_chunk, source_file),
        "conflict_patterns": _conflict_pattern_cards(chunks, results_by_chunk, source_file),
        "anti_patterns": _anti_pattern_cards(results, chunks_by_id, project.name),
    }


def write_obsidian_export(
    target_dir: Path,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    frontmatter = _frontmatter(project, source_file, job, ["novel-deconstructor", "phase3", "index"])
    index = f"""{frontmatter}
# {project.name} 拆书知识库

[[写作规则]] | [[风险清单]] | [[图谱摘要]]

## 来源

- 源文件：{source_file.original_filename}
- 任务：{job.id}
- 章节/分块：{len(chunks)}
"""
    written.append(_write(target_dir / "index.md", index))

    rules_text = (target_dir.parent / "knowledge_base" / "writing_rules.md").read_text(encoding="utf-8") if (target_dir.parent / "knowledge_base" / "writing_rules.md").exists() else "# 写作规则\n\n暂无。"
    anti_text = (target_dir.parent / "knowledge_base" / "anti_patterns.md").read_text(encoding="utf-8") if (target_dir.parent / "knowledge_base" / "anti_patterns.md").exists() else "# 风险清单\n\n暂无。"
    written.append(_write(target_dir / "写作规则.md", f"{_frontmatter(project, source_file, job, ['writing-rules'])}\n{rules_text}"))
    written.append(_write(target_dir / "风险清单.md", f"{_frontmatter(project, source_file, job, ['anti-patterns'])}\n{anti_text}"))

    chapter_dir = target_dir / "章节分析索引"
    for result in results:
        path = Path(result.markdown_path or "")
        if not path.exists():
            continue
        title = f"{result.mode}-{path.stem}"
        content = path.read_text(encoding="utf-8", errors="ignore")
        note = f"{_frontmatter(project, source_file, job, ['chapter-analysis', result.mode])}\n# {title}\n\n来源文件：`{path.name}`\n\n{content}\n"
        written.append(_write(chapter_dir / f"{_safe_filename(title)}.md", note))
    return written


def write_graph_outputs(
    target_dir: Path,
    project: Project,
    source_file: SourceFile,
    chunks: list[ChapterChunk],
    job: AnalysisJob,
    results: list[AnalysisResult],
) -> list[Path]:
    target_dir.mkdir(parents=True, exist_ok=True)
    entities: list[dict] = [
        {"id": f"project:{project.id}", "name": project.name, "type": "Project", "description": project.description},
        {"id": f"source:{source_file.id}", "name": source_file.original_filename, "type": "SourceFile", "description": source_file.file_type},
    ]
    relationships: list[dict] = [
        {"source": f"project:{project.id}", "target": f"source:{source_file.id}", "type": "HAS_SOURCE", "evidence": source_file.original_filename}
    ]
    for chunk in chunks:
        chunk_id = f"chapter:{chunk.id}"
        entities.append({"id": chunk_id, "name": chunk.title, "type": "Chapter", "description": f"{chunk.char_count} chars"})
        relationships.append({"source": f"source:{source_file.id}", "target": chunk_id, "type": "CONTAINS", "evidence": chunk.title})
        if chunk.chapter_index > 1:
            previous = next((item for item in chunks if item.chapter_index == chunk.chapter_index - 1), None)
            if previous:
                relationships.append({"source": f"chapter:{previous.id}", "target": chunk_id, "type": "NEXT_CHAPTER", "evidence": "chapter order"})

    for result in results:
        mode_id = f"mode:{result.mode}"
        if not any(entity["id"] == mode_id for entity in entities):
            entities.append({"id": mode_id, "name": result.mode, "type": "AnalysisMode", "description": "Phase 2/3 analysis mode"})
        relationships.append({"source": f"chapter:{result.chunk_id}", "target": mode_id, "type": "ANALYZED_BY", "evidence": Path(result.markdown_path or "").name})

    summary = f"""# 图谱摘要：{project.name}

> 轻量 GraphRAG 兼容导出。当前版本不依赖外部图数据库，先输出实体和关系 JSON，Phase 3 后续可接 Microsoft GraphRAG 或 Neo4j。

- 实体数：{len(entities)}
- 关系数：{len(relationships)}
- 项目：{project.name}
- 源文件：{source_file.original_filename}
"""
    written = [
        _write(target_dir / "entities.json", json.dumps(entities, ensure_ascii=False, indent=2)),
        _write(target_dir / "relationships.json", json.dumps(relationships, ensure_ascii=False, indent=2)),
        _write(target_dir / "graph_summary.md", summary),
    ]
    return written


def _group_results_by_chunk(results: list[AnalysisResult]) -> dict[str, list[AnalysisResult]]:
    grouped: dict[str, list[AnalysisResult]] = defaultdict(list)
    for result in results:
        grouped[result.chunk_id].append(result)
    return {
        chunk_id: sorted(items, key=lambda item: item.mode)
        for chunk_id, items in grouped.items()
    }


def _group_results_by_mode(results: list[AnalysisResult]) -> dict[str, list[AnalysisResult]]:
    grouped: dict[str, list[AnalysisResult]] = defaultdict(list)
    for result in results:
        grouped[result.mode].append(result)
    return dict(sorted(grouped.items()))


def _chapter_summary_row(chunk: ChapterChunk, results: list[AnalysisResult]) -> str:
    modes = ", ".join(MODE_LABELS.get(result.mode, result.mode) for result in results) or "-"
    return f"| {chunk.chapter_index} | {chunk.title} | {chunk.char_count} | {modes} | {len(results)} |"


def _collect_mode_summaries(results: list[AnalysisResult], chunks_by_id: dict[str, ChapterChunk]) -> dict[str, str]:
    summaries: dict[str, list[str]] = defaultdict(list)
    for result in sorted(results, key=lambda item: (chunks_by_id.get(item.chunk_id).chapter_index if chunks_by_id.get(item.chunk_id) else 999999, item.mode)):
        path = Path(result.markdown_path or "")
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        highlights = _extract_document_highlights(text)
        if not highlights:
            continue
        chunk = chunks_by_id.get(result.chunk_id)
        chapter_name = f"第{chunk.chapter_index}章 {chunk.title}" if chunk else result.chunk_id
        for highlight in highlights[:3]:
            summaries[result.mode].append(f"- **{chapter_name}**：{highlight}")
    return {mode: "\n".join(items[:24]) for mode, items in sorted(summaries.items())}


def _analysis_document_index(results: list[AnalysisResult], chunks_by_id: dict[str, ChapterChunk], base_dir: Path) -> str:
    lines: list[str] = []
    sorted_results = sorted(
        results,
        key=lambda item: (chunks_by_id.get(item.chunk_id).chapter_index if chunks_by_id.get(item.chunk_id) else 999999, item.mode),
    )
    for result in sorted_results:
        path = Path(result.markdown_path or "")
        chunk = chunks_by_id.get(result.chunk_id)
        chapter_name = f"第{chunk.chapter_index}章 {chunk.title}" if chunk else result.chunk_id
        display_path = _display_path(path, base_dir)
        lines.append(f"- {chapter_name} / {MODE_LABELS.get(result.mode, result.mode)}：`{display_path}`")
    return "\n".join(lines)


def _display_path(path: Path, base_dir: Path) -> str:
    try:
        return path.relative_to(base_dir).as_posix()
    except ValueError:
        return path.as_posix()


def _format_blocks(blocks: list[str], fallback: str) -> str:
    return "\n\n".join(block.strip() for block in blocks if block.strip()) if blocks else f"- {fallback}"


def _collect_rule_blocks(results: list[AnalysisResult]) -> list[str]:
    return _collect_sections(results, RULE_HINTS)


def _collect_anti_blocks(results: list[AnalysisResult]) -> list[str]:
    return _collect_sections(results, ANTI_HINTS)


def _collect_sections(results: list[AnalysisResult], hints: tuple[str, ...]) -> list[str]:
    blocks: list[str] = []
    for result in results:
        path = Path(result.markdown_path or "")
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        sections = _extract_matching_sections(text, hints)
        for section in sections[:3]:
            blocks.append(f"## {result.mode} / {path.stem}\n\n{section.strip()}")
    return blocks[:200]


def _extract_matching_sections(text: str, hints: tuple[str, ...]) -> list[str]:
    matches = list(SECTION_HEAD_RE.finditer(text))
    sections: list[str] = []
    for index, match in enumerate(matches):
        title = match.group(1)
        if not any(hint in title for hint in hints):
            continue
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append(text[start:end])
    if sections:
        return sections
    bullets = [line for line in text.splitlines() if line.strip().startswith(("-", "*", "1.", "2.", "3."))]
    return ["\n".join(bullets[:12])] if bullets else []


def _chapter_analysis_card(chunk: ChapterChunk, results: list[AnalysisResult], source_file: SourceFile) -> dict:
    texts = {result.mode: _read_result_text(result) for result in results}
    primary = texts.get("chapter_structure") or "\n\n".join(texts.values())
    conflict_text = _section(primary, ("冲突",)) or texts.get("conflict_analysis", "")
    emotion_text = _section(primary, ("情绪", "爽点", "可复现模块"))
    information_text = _section(primary, ("信息投放",)) or texts.get("information_delivery", "")
    character_text = _section(primary, ("人物", "关系变化")) or texts.get("character_growth", "")
    return {
        "chapter_id": chunk.id,
        "chapter_title": chunk.title,
        "summary": _first_highlight(primary, fallback=f"{chunk.title} 的逐章拆解结果。"),
        "opening_state": _compact(_section(primary, ("开头状态",)), 360),
        "ending_state": _compact(_section(primary, ("结尾状态",)), 360),
        "state_change": _compact(_section(primary, ("状态变化",)), 360),
        "chapter_function": _compact(_section(primary, ("一句话结构功能", "结构功能")), 260),
        "conflict_units": _list_items(conflict_text, 8),
        "emotion_chain": _list_items(emotion_text, 8),
        "information_delivery": _list_items(information_text, 8),
        "character_changes": _list_items(character_text, 8),
        "ending_hook": _compact(_section(primary, ("章尾钩子", "结尾状态")), 220),
        "reusable_patterns": _list_items("\n\n".join(_extract_matching_sections(primary, RULE_HINTS)), 8),
        "anti_patterns": _list_items("\n\n".join(_extract_matching_sections(primary, ANTI_HINTS)), 8),
        "source_ref": {
            "source_file": source_file.original_filename,
            "chapter_index": chunk.chapter_index,
            "chapter_id": chunk.id,
            "analysis_modes": sorted(texts.keys()),
            "markdown_paths": [Path(result.markdown_path or "").name for result in results if result.markdown_path],
        },
    }


def _writing_rule_cards(results: list[AnalysisResult], chunks_by_id: dict[str, ChapterChunk], project_name: str) -> list[dict]:
    cards: list[dict] = []
    for result in results:
        text = _read_result_text(result)
        for section in _extract_matching_sections(text, RULE_HINTS)[:3]:
            index = len(cards) + 1
            chunk = chunks_by_id.get(result.chunk_id)
            cards.append(
                {
                    "id": f"WR-{index:03d}",
                    "type": "writing_rule",
                    "title": _card_title(section, f"{MODE_LABELS.get(result.mode, result.mode)} 写作规则"),
                    "rule": _compact(section, 900),
                    "use_when": _use_when_for_mode(result.mode),
                    "avoid": "不要照搬原文专名、桥段、角色关系或独特设定；只复用结构功能和写作方法。",
                    "source": _card_source(project_name, result, chunk),
                    "confidence": 0.72,
                    "status": "raw_extracted",
                    "tags": _tags_for_mode(result.mode),
                }
            )
    return cards[:120]


def _emotion_module_cards(
    chunks: list[ChapterChunk],
    results_by_chunk: dict[str, list[AnalysisResult]],
    source_file: SourceFile,
) -> list[dict]:
    cards: list[dict] = []
    for chunk in chunks:
        texts = {result.mode: _read_result_text(result) for result in results_by_chunk.get(chunk.id, [])}
        primary = texts.get("chapter_structure") or "\n\n".join(texts.values())
        section = _section(primary, ("情绪触动", "爽点循环", "可复现模块"))
        if not section:
            continue
        index = len(cards) + 1
        cards.append(
            {
                "id": f"EM-{index:03d}",
                "type": "emotion_module",
                "name": _card_title(section, f"{chunk.title} 情绪模块"),
                "emotion_chain": _compact(section, 500),
                "scene_function": f"来源章节：{chunk.title}；适合复用其情绪推进功能，不复用具体素材。",
                "reusable_steps": _list_items(section, 6),
                "do_not_copy": ["原作专名", "原作桥段顺序", "标志性台词", "独特设定"],
                "tags": ["情绪链", "爽点循环", "可复现模块"],
                "source_ref": {
                    "source_file": source_file.original_filename,
                    "chapter_id": chunk.id,
                    "chapter_title": chunk.title,
                },
            }
        )
    return cards[:80]


def _conflict_pattern_cards(
    chunks: list[ChapterChunk],
    results_by_chunk: dict[str, list[AnalysisResult]],
    source_file: SourceFile,
) -> list[dict]:
    cards: list[dict] = []
    for chunk in chunks:
        texts = {result.mode: _read_result_text(result) for result in results_by_chunk.get(chunk.id, [])}
        section = texts.get("conflict_analysis") or _section(texts.get("chapter_structure", ""), ("冲突",))
        if not section:
            continue
        index = len(cards) + 1
        cards.append(
            {
                "id": f"CP-{index:03d}",
                "type": "conflict_pattern",
                "name": _card_title(section, f"{chunk.title} 冲突模式"),
                "conflict_type": _compact(_first_matching_line(section, ("外部冲突", "内部冲突", "关系冲突", "信息", "资源")), 160),
                "trigger": _compact(_first_matching_line(section, ("触发", "开端", "目标", "主要冲突")), 220),
                "escalation": _compact(_first_matching_line(section, ("升级", "推进", "加压")), 220),
                "payoff": _compact(_first_matching_line(section, ("释放", "结果", "解决")), 220),
                "next_hook": _compact(_first_matching_line(section, ("钩子", "牵引", "新问题")), 220),
                "tags": ["冲突推进", "章节结构"],
                "source_ref": {
                    "source_file": source_file.original_filename,
                    "chapter_id": chunk.id,
                    "chapter_title": chunk.title,
                },
            }
        )
    return cards[:80]


def _anti_pattern_cards(results: list[AnalysisResult], chunks_by_id: dict[str, ChapterChunk], project_name: str) -> list[dict]:
    cards: list[dict] = []
    for result in results:
        text = _read_result_text(result)
        for section in _extract_matching_sections(text, ANTI_HINTS)[:3]:
            index = len(cards) + 1
            chunk = chunks_by_id.get(result.chunk_id)
            cards.append(
                {
                    "id": f"AP-{index:03d}",
                    "type": "anti_pattern",
                    "name": _card_title(section, f"{MODE_LABELS.get(result.mode, result.mode)} 反模式"),
                    "problem": _compact(section, 500),
                    "why_bad": "机械模仿会削弱原创性，或把拆书结果误用为原作复刻。",
                    "fix_strategy": "保留功能位、冲突链和情绪链，替换人物、设定、场景、台词和具体桥段。",
                    "tags": _tags_for_mode(result.mode) + ["反模式"],
                    "source": _card_source(project_name, result, chunk),
                }
            )
    return cards[:120]


def _read_result_text(result: AnalysisResult) -> str:
    path = Path(result.markdown_path or "")
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def _section(text: str, hints: tuple[str, ...]) -> str:
    sections = _extract_matching_sections(text, hints)
    return sections[0].strip() if sections else ""


def _compact(text: str, max_chars: int = 400) -> str:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def _list_items(text: str, limit: int) -> list[str]:
    items: list[str] = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("- ", "* ")):
            value = stripped[2:].strip()
        elif re.match(r"^\d+[.)]\s+", stripped):
            value = re.sub(r"^\d+[.)]\s+", "", stripped).strip()
        elif "|" in stripped or stripped.startswith("#"):
            continue
        else:
            continue
        if value and value not in items:
            items.append(_compact(value, 220))
        if len(items) >= limit:
            break
    if items:
        return items
    fallback = _compact(text, 260)
    return [fallback] if fallback else []


def _first_highlight(text: str, fallback: str) -> str:
    highlights = _extract_document_highlights(text)
    return highlights[0] if highlights else fallback


def _card_title(text: str, fallback: str) -> str:
    for item in _list_items(text, 1):
        title = re.sub(r"[:：].*$", "", item).strip()
        if title:
            return _compact(title, 80)
    first = _compact(text, 80)
    return first or fallback


def _first_matching_line(text: str, hints: tuple[str, ...]) -> str:
    for line in (text or "").splitlines():
        stripped = line.strip(" -|")
        if any(hint in stripped for hint in hints):
            return stripped
    return ""


def _use_when_for_mode(mode: str) -> list[str]:
    mapping = {
        "chapter_structure": ["提纲生成", "续写章节", "结构检查"],
        "conflict_analysis": ["提纲生成", "正文生成", "冲突检查"],
        "character_growth": ["提纲生成", "续写章节", "人物连续性检查"],
        "information_delivery": ["提纲生成", "正文生成", "设定投放检查"],
        "language_style": ["正文生成", "润色修改"],
        "ai_bad_patterns": ["润色修改", "AI 味检查"],
    }
    return mapping.get(mode, ["提纲生成", "正文生成"])


def _tags_for_mode(mode: str) -> list[str]:
    label = MODE_LABELS.get(mode, mode)
    return [label, mode]


def _card_source(project_name: str, result: AnalysisResult, chunk: ChapterChunk | None) -> dict:
    return {
        "book": project_name,
        "chapter": chunk.id if chunk else result.chunk_id,
        "chapter_title": chunk.title if chunk else "",
        "analysis_mode": result.mode,
    }


def _extract_document_highlights(text: str) -> list[str]:
    highlights: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith(("# ", "---", "```", "|")):
            continue
        if stripped.startswith("## "):
            stripped = stripped.lstrip("#").strip()
        elif stripped.startswith(("- ", "* ")):
            stripped = stripped[2:].strip()
        elif re.match(r"^\d+[.)]\s+", stripped):
            stripped = re.sub(r"^\d+[.)]\s+", "", stripped).strip()
        else:
            continue
        stripped = re.sub(r"\s+", " ", stripped)
        if len(stripped) > 180:
            stripped = stripped[:177].rstrip() + "..."
        if stripped and stripped not in highlights:
            highlights.append(stripped)
        if len(highlights) >= 8:
            break
    return highlights


def _frontmatter(project: Project, source_file: SourceFile, job: AnalysisJob, tags: list[str]) -> str:
    tag_text = ", ".join(tags)
    return f"""---
project: "{project.name}"
source: "{source_file.original_filename}"
job: "{job.id}"
tags: [{tag_text}]
generated: "{datetime.now().isoformat(timespec="seconds")}"
---"""


def _write(path: Path, content: str) -> Path:
    atomic_write(path, content)
    return path


def _safe_filename(value: str) -> str:
    return re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", value).strip("._ ") or "note"
