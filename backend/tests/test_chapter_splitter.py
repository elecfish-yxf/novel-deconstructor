from pathlib import Path

from novel_deconstructor.services.chapter_splitter import is_chapter_heading, split_text_file


def test_chinese_heading_detection():
    assert is_chapter_heading("第1章 初入江湖")
    assert is_chapter_heading("第一章")
    assert is_chapter_heading("卷一 风起")
    assert is_chapter_heading("楔子")
    assert is_chapter_heading("CHAPTER 01")
    assert not is_chapter_heading("她看着窗外，觉得今天有点奇怪。")


def test_split_by_headings(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text("第一章\n内容一\n第二章\n内容二\n", encoding="utf-8")

    artifacts = split_text_file(raw, tmp_path / "chunks", source_file_id=1, max_chars=100, overlap_chars=10)

    assert len(artifacts) == 2
    assert artifacts[0].title == "第一章"
    assert artifacts[1].title == "第二章"
    assert artifacts[0].text_path.exists()


def test_split_by_size_when_no_headings(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text("甲" * 2500, encoding="utf-8")

    artifacts = split_text_file(raw, tmp_path / "chunks", source_file_id=1, max_chars=1000, overlap_chars=100)

    assert len(artifacts) == 3
    assert artifacts[0].title.startswith("自动分块")
