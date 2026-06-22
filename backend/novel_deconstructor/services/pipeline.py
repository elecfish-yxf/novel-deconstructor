from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import SessionLocal
from ..models import AnalysisJob, AnalysisResult, ChapterChunk, DeconstructionSkill, JobLog, Project, PromptTemplate, SourceFile
from .llm_provider import DoubaoResponsesProvider, LLMProvider, LLMRequest, OpenAICompatibleProvider, is_deepseek_base_url, is_doubao_base_url
from .oh_story_adapter import (
    initialize_oh_story_workspace,
    write_chapter_analysis,
    write_progress,
    write_summary_outputs,
)
from .phase3_exporter import generate_phase3_outputs
from .prompt_renderer import PromptRenderer


def job_id_now() -> str:
    return datetime.now().strftime("job_%Y%m%d_%H%M%S")


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def add_log(db: Session, job_id: str, level: str, message: str) -> None:
    db.add(JobLog(job_id=job_id, level=level, message=message))
    db.commit()


def _load_template(db: Session, mode: str, skill: DeconstructionSkill | None = None) -> str:
    if skill and skill.prompt_template and mode == "chapter_structure":
        return skill.prompt_template
    template = (
        db.query(PromptTemplate)
        .filter(PromptTemplate.mode == mode)
        .order_by(PromptTemplate.source.desc(), PromptTemplate.id.desc())
        .first()
    )
    if template:
        return template.content
    return PromptRenderer().load_builtin(mode)


def _ensure_result(db: Session, job_id: str, chunk_id: str, mode: str) -> AnalysisResult:
    result = (
        db.query(AnalysisResult)
        .filter(AnalysisResult.job_id == job_id, AnalysisResult.chunk_id == chunk_id, AnalysisResult.mode == mode)
        .first()
    )
    if result:
        return result
    result = AnalysisResult(job_id=job_id, chunk_id=chunk_id, mode=mode, status="pending")
    db.add(result)
    db.commit()
    db.refresh(result)
    return result


def _job_results(db: Session, job_id: str) -> list[AnalysisResult]:
    return db.query(AnalysisResult).filter(AnalysisResult.job_id == job_id).order_by(AnalysisResult.id.asc()).all()


def resolve_api_key(base_url: str | None, runtime_api_key: str | None = None) -> str:
    cleaned_runtime_key = (runtime_api_key or "").strip()
    if cleaned_runtime_key:
        return cleaned_runtime_key
    if is_doubao_base_url(base_url):
        raise ValueError("缺少豆包 API Key。请在拆书任务配置页填写你自己的豆包 Ark API Key，或开启 dry-run。")
    if is_deepseek_base_url(base_url):
        raise ValueError("缺少 DeepSeek API Key。请在拆书任务配置页填写你自己的 DeepSeek API Key，或开启 dry-run。")
    raise ValueError("缺少 API Key。请在拆书任务配置页填写你自己的 API Key，或开启 dry-run。")


def resolve_model(base_url: str | None, configured_model: str | None = None) -> str:
    settings = get_settings()
    if configured_model:
        return configured_model
    if is_doubao_base_url(base_url):
        return settings.doubao_model
    if is_deepseek_base_url(base_url):
        return settings.deepseek_model
    return settings.openai_model


def resolve_provider(base_url: str | None, runtime_api_key: str | None = None) -> LLMProvider:
    api_key = resolve_api_key(base_url, runtime_api_key)
    if is_doubao_base_url(base_url):
        return DoubaoResponsesProvider(base_url or get_settings().doubao_base_url, api_key)
    return OpenAICompatibleProvider(base_url or get_settings().openai_base_url, api_key)


async def run_analysis_job(job_id: str, runtime_api_key: str | None = None) -> None:
    settings = get_settings()
    db = SessionLocal()
    job: AnalysisJob | None = None
    try:
        job = db.get(AnalysisJob, job_id)
        if not job:
            return
        project = db.get(Project, job.project_id)
        source_file = db.get(SourceFile, job.source_file_id)
        skill = db.get(DeconstructionSkill, job.skill_id) if job.skill_id else None
        if not project or not source_file:
            job.status = "failed"
            job.error_message = "项目或源文件不存在"
            db.commit()
            return

        modes = json.loads(job.modes_json)
        job.status = "running"
        job.error_message = None
        db.commit()
        add_log(db, job.id, "info", "任务开始运行")

        chunks = (
            db.query(ChapterChunk)
            .filter(ChapterChunk.source_file_id == job.source_file_id)
            .order_by(ChapterChunk.chapter_index.asc())
            .all()
        )
        if not chunks:
            raise ValueError("源文件还没有章节切分结果")

        output_dir = Path(job.output_dir)
        calls_dir = output_dir / "metadata" / "llm_calls"
        analysis_dir = output_dir / "chapter_analysis"
        oh_layout = initialize_oh_story_workspace(output_dir, project, source_file, chunks, job)
        add_log(db, job.id, "info", "已生成 oh-story 兼容拆文目录骨架")

        renderer = PromptRenderer()
        system_prompt = skill.system_prompt if skill and skill.system_prompt else renderer.load_builtin("system_base")
        base_url = job.base_url or settings.openai_base_url
        provider = resolve_provider(base_url, runtime_api_key) if not job.dry_run else OpenAICompatibleProvider(base_url, "")

        total_units = len(chunks) * len(modes)
        job.total_chunks = total_units
        job.completed_chunks = db.query(AnalysisResult).filter(
            AnalysisResult.job_id == job.id, AnalysisResult.status == "completed"
        ).count()
        db.commit()
        write_progress(oh_layout, project, source_file, chunks, job, _job_results(db, job.id))

        total_chars = sum(chunk.char_count for chunk in chunks)
        for chunk in chunks:
            for mode in modes:
                db.refresh(job)
                if job.status in {"paused", "cancelled"}:
                    add_log(db, job.id, "info", f"任务已{job.status}，后台停止推进")
                    write_summary_outputs(oh_layout, project, source_file, chunks, job, _job_results(db, job.id))
                    return

                result = _ensure_result(db, job.id, chunk.id, mode)
                if result.status == "completed":
                    add_log(db, job.id, "info", f"跳过已完成: {chunk.title} / {mode}")
                    continue

                job.current_chunk_title = chunk.title
                job.current_mode = mode
                result.status = "running"
                result.error_message = None
                db.commit()
                write_progress(oh_layout, project, source_file, chunks, job, _job_results(db, job.id))
                add_log(db, job.id, "info", f"开始分析: {chunk.title}")

                try:
                    chapter_text = Path(chunk.text_path).read_text(encoding="utf-8")
                    template = _load_template(db, mode, skill)
                    user_prompt = renderer.render(
                        template,
                        {
                            "project_name": project.name,
                            "source_filename": source_file.original_filename,
                            "chapter_index": chunk.chapter_index,
                            "chapter_title": chunk.title,
                            "chapter_count": len(chunks),
                            "chapter_char_count": chunk.char_count,
                            "total_chars": total_chars,
                            "chapter_role": "黄金三章深度拆解" if chunk.chapter_index <= 3 else "逐章结构拆解",
                            "chapter_text": chapter_text,
                            "previous_summary": "",
                            "analysis_goal": "输出可复用的长篇中文小说写作规律，不复述原文，不生成可替代原作阅读的内容。",
                            "allow_short_quotes": "允许" if job.allow_short_quotes else "不允许",
                            "output_format": "Markdown",
                            "language": "中文",
                            "skill_name": skill.name if skill else "默认内置模板",
                            "skill_description": skill.description if skill else "",
                        },
                    )
                    prompt_path = calls_dir / f"{job.id}_{chunk.id}_{mode}_prompt.md"
                    response_path = calls_dir / f"{job.id}_{chunk.id}_{mode}_response.md"
                    markdown_path = analysis_dir / f"{chunk.chapter_index:04d}_{mode}.md"
                    atomic_write(prompt_path, f"{system_prompt}\n\n---\n\n{user_prompt}")

                    response = await provider.complete(
                        LLMRequest(
                            system_prompt=system_prompt,
                            user_prompt=user_prompt,
                            model=resolve_model(base_url, job.model),
                            temperature=job.temperature,
                            max_tokens=job.max_tokens,
                            timeout_seconds=settings.llm_timeout_seconds,
                            retry_count=settings.llm_retry_count,
                            dry_run=job.dry_run,
                        )
                    )
                    oh_story_path = write_chapter_analysis(oh_layout, chunk, mode, response)
                    atomic_write(response_path, response)
                    atomic_write(markdown_path, response)

                    result.status = "completed"
                    result.prompt_path = str(prompt_path)
                    result.response_path = str(response_path)
                    result.markdown_path = str(oh_story_path)
                    job.completed_chunks = db.query(AnalysisResult).filter(
                        AnalysisResult.job_id == job.id, AnalysisResult.status == "completed"
                    ).count()
                    db.commit()
                    write_progress(oh_layout, project, source_file, chunks, job, _job_results(db, job.id))
                    add_log(db, job.id, "info", f"完成分析: {chunk.title}")
                except Exception as exc:  # noqa: BLE001 - persisted into DB and shown in UI.
                    result.status = "failed"
                    result.error_message = str(exc)
                    job.failed_chunks = db.query(AnalysisResult).filter(
                        AnalysisResult.job_id == job.id, AnalysisResult.status == "failed"
                    ).count()
                    db.commit()
                    write_progress(oh_layout, project, source_file, chunks, job, _job_results(db, job.id))
                    add_log(db, job.id, "error", f"分析失败: {chunk.title}: {exc}")

        job.failed_chunks = db.query(AnalysisResult).filter(
            AnalysisResult.job_id == job.id, AnalysisResult.status == "failed"
        ).count()
        job.completed_chunks = db.query(AnalysisResult).filter(
            AnalysisResult.job_id == job.id, AnalysisResult.status == "completed"
        ).count()
        job.current_chunk_title = None
        job.current_mode = None
        job.status = "completed" if job.failed_chunks == 0 else "failed"
        job.error_message = None if job.status == "completed" else "部分章节分析失败，请查看日志和 _progress.md"
        db.commit()
        final_results = _job_results(db, job.id)
        write_summary_outputs(oh_layout, project, source_file, chunks, job, final_results)
        exported = generate_phase3_outputs(output_dir, project, source_file, chunks, job, final_results)
        if exported:
            add_log(db, job.id, "info", f"Phase 3 导出完成: {len(exported)} 个文件")
        add_log(db, job.id, "info", f"任务结束: {job.status}")
    except Exception as exc:  # noqa: BLE001 - top-level background failure guard.
        job = job or db.get(AnalysisJob, job_id)
        if job:
            job.status = "failed"
            job.error_message = str(exc)
            db.commit()
            add_log(db, job.id, "error", f"任务失败: {exc}")
    finally:
        db.close()
