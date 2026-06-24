from pathlib import Path
import json

from novel_deconstructor.models import AnalysisJob, AnalysisResult, ChapterChunk, Project, SourceFile
from novel_deconstructor.services.phase3_exporter import generate_phase3_outputs


def test_phase3_exports_kb_obsidian_and_graph(tmp_path: Path):
    project = Project(id=1, name="测试小说", description="测试")
    source_file = SourceFile(id=1, project_id=1, original_filename="novel.txt", stored_path="novel.txt", file_type="txt", size_bytes=100)
    chunk = ChapterChunk(
        id="chunk_1",
        project_id=1,
        source_file_id=1,
        chapter_index=1,
        title="第一章",
        text_path="chunk.txt",
        char_start=0,
        char_end=100,
        char_count=100,
        token_estimate=100,
        metadata_json="{}",
    )
    analysis = tmp_path / "analysis.md"
    analysis.write_text(
        """# 第一章

## 11. 可学习规律

- 先建立期待缺口，再用行动释放。

## 12. 不建议模仿

- 不要照搬具体桥段。
""",
        encoding="utf-8",
    )
    job = AnalysisJob(
        id="job_test",
        project_id=1,
        source_file_id=1,
        status="completed",
        output_dir=str(tmp_path),
        generate_kb=True,
        generate_obsidian=True,
        generate_graph=True,
    )
    result = AnalysisResult(job_id=job.id, chunk_id=chunk.id, mode="chapter_structure", status="completed", markdown_path=str(analysis))

    written = generate_phase3_outputs(tmp_path, project, source_file, [chunk], job, [result])

    assert written
    assert (tmp_path / "final_reports" / "overall_summary.md").exists()
    assert (tmp_path / "knowledge_base" / "writing_rules.md").exists()
    assert (tmp_path / "knowledge_base" / "knowledge_package.json").exists()
    assert (tmp_path / "knowledge_base_obsidian" / "index.md").exists()
    assert (tmp_path / "graph_outputs" / "entities.json").exists()
    summary = (tmp_path / "final_reports" / "overall_summary.md").read_text(encoding="utf-8")
    assert "总汇总报告" in summary
    assert "第一章" in summary
    assert "期待缺口" in summary
    assert "期待缺口" in (tmp_path / "knowledge_base" / "writing_rules.md").read_text(encoding="utf-8")
    package = json.loads((tmp_path / "knowledge_base" / "knowledge_package.json").read_text(encoding="utf-8"))
    assert package["schema_version"] == "0.2.0"
    assert package["chapter_analysis"][0]["chapter_title"] == "第一章"
    assert package["writing_rules"][0]["type"] == "writing_rule"
    assert package["chapter_analysis"][0]["scope_level"] == "chapter"
    assert package["chapter_analysis"][0]["retrievable"] is False
    assert package["writing_rules"][0]["scope_level"] == "global"
    assert package["writing_rules"][0]["retrievable"] is False
    assert package["anti_patterns"][0]["type"] == "anti_pattern"
    assert package["agent_retrieval_protocol"]["outline"] == ["structure_pattern", "conflict_pattern", "emotion_module"]
