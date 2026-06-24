from pathlib import Path
import json

from novel_deconstructor.services.chapter_splitter import is_chapter_heading, is_volume_heading, split_text_file


def test_chinese_heading_detection():
    assert is_chapter_heading("第1章 初入江湖")
    assert is_chapter_heading("第一章")
    assert is_chapter_heading("第 01 章 初入江湖")
    assert is_chapter_heading("第七话 夏日祭")
    assert is_chapter_heading("【第三章 憧憬的模样】")
    assert is_chapter_heading("卷一 风起")
    assert is_chapter_heading("楔子")
    assert is_chapter_heading("CHAPTER 01")
    assert is_volume_heading("Volume 1")
    assert is_volume_heading("Book 2")
    assert is_volume_heading("上卷")
    assert not is_chapter_heading("她看着窗外，觉得今天有点奇怪。")


def test_split_by_headings(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text("第一章\n内容一\n第二章\n内容二\n", encoding="utf-8")

    artifacts = split_text_file(raw, tmp_path / "chunks", source_file_id=1, max_chars=100, overlap_chars=10)

    assert len(artifacts) == 2
    assert artifacts[0].title == "第一章"
    assert artifacts[1].title == "第二章"
    assert artifacts[0].text_path.exists()


def test_duplicate_front_matter_heading_is_skipped(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text(
        "\n".join(
            [
                "第一章 天使大人的苏醒",
                "书名：测试书第六卷",
                "作者：作者名",
                "6_1.jpg",
                "藤宫周",
                "人物介绍。",
                "第一章 天使大人的苏醒",
                "正文一",
                "第二章 完全淋湿是一件好事",
                "正文二",
            ]
        ),
        encoding="utf-8",
    )

    artifacts = split_text_file(raw, tmp_path / "chunks", source_file_id=1, max_chars=100, overlap_chars=10)

    assert [item.title for item in artifacts] == ["第一章 天使大人的苏醒", "第二章 完全淋湿是一件好事"]
    assert "书名" not in artifacts[0].text_path.read_text(encoding="utf-8")


def test_strict_chapter_split_keeps_long_chapter_together(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text("第一章\n" + "甲" * 1500 + "\n第二章\n乙\n", encoding="utf-8")

    artifacts = split_text_file(raw, tmp_path / "chunks", source_file_id=1, max_chars=1000, overlap_chars=100)

    assert len(artifacts) == 2
    assert artifacts[0].title == "第一章"
    assert artifacts[0].char_count > 1000


def test_non_strict_chapter_split_can_split_long_chapters(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text("第一章\n" + "甲" * 1500 + "\n第二章\n乙\n", encoding="utf-8")

    artifacts = split_text_file(
        raw,
        tmp_path / "chunks",
        source_file_id=1,
        max_chars=1000,
        overlap_chars=100,
        strict_chapter_split=False,
    )

    assert len(artifacts) == 3
    assert artifacts[1].title == "第一章（续 2）"


def test_split_by_size_when_no_headings(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text("甲" * 2500, encoding="utf-8")

    artifacts = split_text_file(raw, tmp_path / "chunks", source_file_id=1, max_chars=1000, overlap_chars=100)

    assert len(artifacts) == 3
    assert artifacts[0].title.startswith("自动分块")
    assert artifacts[0].metadata["volume_index"] == 1
    assert artifacts[0].metadata["volume_title"] == "Volume 1"


def test_volume_heading_adds_metadata_without_empty_chapter(tmp_path: Path):
    raw = tmp_path / "raw.txt"
    raw.write_text("Volume 1\n\nChapter 1\nBody one\nVolume 2\n\nChapter 1\nBody two\n", encoding="utf-8")

    artifacts = split_text_file(raw, tmp_path / "chunks", source_file_id=1, max_chars=1000, overlap_chars=100)

    assert len(artifacts) == 2
    assert [item.title for item in artifacts] == ["Chapter 1", "Chapter 1"]
    assert artifacts[0].metadata["volume_index"] == 1
    assert artifacts[0].metadata["volume_title"] == "Volume 1"
    assert artifacts[1].metadata["volume_index"] == 2
    assert artifacts[1].metadata["volume_title"] == "Volume 2"
    metadata = json.loads(artifacts[0].metadata_path.read_text(encoding="utf-8"))
    assert metadata["chapter_title"] == "Chapter 1"
