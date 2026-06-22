from pathlib import Path

from novel_deconstructor.models import AnalysisJob, AnalysisResult, ChapterChunk, Project, SourceFile
from novel_deconstructor.services.oh_story_adapter import (
    initialize_oh_story_workspace,
    write_chapter_analysis,
    write_summary_outputs,
)


def _chunk(index: int, title: str) -> ChapterChunk:
    return ChapterChunk(
        id=f"chunk_{index}",
        project_id=1,
        source_file_id=1,
        chapter_index=index,
        title=title,
        text_path=f"chunk_{index}.txt",
        char_start=(index - 1) * 100,
        char_end=index * 100,
        char_count=100,
        token_estimate=100,
        metadata_json="{}",
    )


def test_oh_story_workspace_outputs_phase2_files(tmp_path: Path):
    project = Project(id=1, name="测试小说")
    source_file = SourceFile(id=1, project_id=1, original_filename="novel.txt", stored_path="novel.txt", file_type="txt", size_bytes=300)
    job = AnalysisJob(id="job_test", project_id=1, source_file_id=1, status="completed", output_dir=str(tmp_path), dry_run=True)
    chunks = [_chunk(1, "第一章 风起"), _chunk(2, "第二章 入局")]
    results = [
        AnalysisResult(job_id=job.id, chunk_id="chunk_1", mode="chapter_structure", status="completed"),
        AnalysisResult(job_id=job.id, chunk_id="chunk_2", mode="chapter_structure", status="completed"),
    ]

    layout = initialize_oh_story_workspace(tmp_path, project, source_file, chunks, job)
    chapter_path = write_chapter_analysis(layout, chunks[0], "chapter_structure", "# 第一章\n\n测试")
    write_summary_outputs(layout, project, source_file, chunks, job, results)

    assert (layout.book_dir / "概要.md").exists()
    assert (layout.book_dir / "_progress.md").exists()
    assert (layout.book_dir / "快速预览.md").exists()
    assert (layout.book_dir / "拆文报告.md").exists()
    assert (layout.plot_dir / "README.md").exists()
    assert chapter_path.name == "第0001章_深度拆解.md"
    assert "schema_version: 2" in (layout.book_dir / "_progress.md").read_text(encoding="utf-8")
    assert "Phase 2 内嵌的 oh-story 拆解视角" in (layout.book_dir / "拆文报告.md").read_text(encoding="utf-8")
