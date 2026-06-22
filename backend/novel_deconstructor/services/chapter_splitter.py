from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
from pathlib import Path
import re


CHAPTER_HEADING_RE = re.compile(
    r"^\s*("
    r"第[0-9零〇一二三四五六七八九十百千万两]+[章节回集卷部篇](?:\s*[:：、.-]?\s*.{0,50})?"
    r"|[序楔终尾]章(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|楔子(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|终章(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|尾声(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|卷[0-9零〇一二三四五六七八九十百千万两]+(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|Chapter\s+[0-9]+(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|CHAPTER\s+[0-9]+(?:\s*[:：、.-]?\s*.{0,50})?"
    r")\s*$",
    re.IGNORECASE,
)


@dataclass
class ChapterArtifact:
    stable_id: str
    chapter_index: int
    title: str
    text_path: Path
    metadata_path: Path
    char_start: int
    char_end: int
    char_count: int
    token_estimate: int
    metadata: dict
    preview: str


def is_chapter_heading(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > 80:
        return False
    return bool(CHAPTER_HEADING_RE.match(text))


def estimate_tokens(text: str) -> int:
    # 中文文本的粗略估算：多数汉字接近 1 token，英文按 4 字符约 1 token。
    chinese_chars = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    other_chars = max(len(text) - chinese_chars, 0)
    return chinese_chars + max(other_chars // 4, 1)


def _stable_id(source_file_id: int, title: str, char_start: int, char_end: int) -> str:
    digest = sha1(f"{source_file_id}:{title}:{char_start}:{char_end}".encode("utf-8")).hexdigest()[:16]
    return f"chunk_{digest}"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def _write_artifact(
    output_dir: Path,
    source_file_id: int,
    chapter_index: int,
    title: str,
    text: str,
    char_start: int,
    split_reason: str,
) -> ChapterArtifact:
    char_end = char_start + len(text)
    stable_id = _stable_id(source_file_id, title, char_start, char_end)
    filename = f"chunk_{chapter_index:04d}.txt"
    text_path = output_dir / filename
    metadata_path = output_dir / f"chunk_{chapter_index:04d}.metadata.json"
    metadata = {
        "id": stable_id,
        "chapter_index": chapter_index,
        "title": title,
        "char_start": char_start,
        "char_end": char_end,
        "char_count": len(text),
        "token_estimate": estimate_tokens(text),
        "split_reason": split_reason,
    }
    _atomic_write(text_path, text)
    _atomic_write(metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2))
    return ChapterArtifact(
        stable_id=stable_id,
        chapter_index=chapter_index,
        title=title,
        text_path=text_path,
        metadata_path=metadata_path,
        char_start=char_start,
        char_end=char_end,
        char_count=len(text),
        token_estimate=metadata["token_estimate"],
        metadata=metadata,
        preview=text.strip().replace("\n", " ")[:180],
    )


def _split_long_text(text: str, max_chars: int, overlap_chars: int) -> list[tuple[str, int]]:
    if len(text) <= max_chars:
        return [(text, 0)]
    chunks: list[tuple[str, int]] = []
    start = 0
    safe_step = max(max_chars - max(overlap_chars, 0), 1)
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append((text[start:end], start))
        if end >= len(text):
            break
        start += safe_step
    return chunks


def _count_headings(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as source:
        for line in source:
            if is_chapter_heading(line):
                count += 1
    return count


def split_text_file(
    raw_text_path: Path,
    output_dir: Path,
    source_file_id: int,
    max_chars: int,
    overlap_chars: int,
) -> list[ChapterArtifact]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("chunk_*.txt"):
        old.unlink(missing_ok=True)
    for old in output_dir.glob("chunk_*.metadata.json"):
        old.unlink(missing_ok=True)

    heading_count = _count_headings(raw_text_path)
    if heading_count:
        return _split_by_headings(raw_text_path, output_dir, source_file_id, max_chars, overlap_chars)
    return _split_by_size(raw_text_path, output_dir, source_file_id, max_chars, overlap_chars)


def _split_by_headings(
    raw_text_path: Path,
    output_dir: Path,
    source_file_id: int,
    max_chars: int,
    overlap_chars: int,
) -> list[ChapterArtifact]:
    artifacts: list[ChapterArtifact] = []
    chapter_lines: list[str] = []
    chapter_title = "开篇"
    chapter_start = 0
    absolute_pos = 0

    def flush(reason: str) -> None:
        nonlocal chapter_lines, chapter_title, chapter_start
        text = "".join(chapter_lines).strip("\n")
        if not text.strip():
            chapter_lines = []
            return
        for part_index, (part_text, offset) in enumerate(_split_long_text(text, max_chars, overlap_chars), start=1):
            title = chapter_title if part_index == 1 else f"{chapter_title}（续 {part_index}）"
            artifacts.append(
                _write_artifact(
                    output_dir,
                    source_file_id,
                    len(artifacts) + 1,
                    title,
                    part_text,
                    chapter_start + offset,
                    reason if part_index == 1 else "chapter_too_long",
                )
            )
        chapter_lines = []

    with raw_text_path.open("r", encoding="utf-8") as source:
        for line in source:
            if is_chapter_heading(line):
                flush("chapter_heading")
                chapter_title = line.strip()
                chapter_start = absolute_pos
            chapter_lines.append(line)
            absolute_pos += len(line)
    flush("chapter_heading")
    return artifacts


def _split_by_size(
    raw_text_path: Path,
    output_dir: Path,
    source_file_id: int,
    max_chars: int,
    overlap_chars: int,
) -> list[ChapterArtifact]:
    artifacts: list[ChapterArtifact] = []
    buffer = ""
    buffer_start = 0
    absolute_pos = 0
    safe_step = max(max_chars - max(overlap_chars, 0), 1)

    with raw_text_path.open("r", encoding="utf-8") as source:
        for line in source:
            buffer += line
            absolute_pos += len(line)
            while len(buffer) >= max_chars:
                text = buffer[:max_chars]
                artifacts.append(
                    _write_artifact(
                        output_dir,
                        source_file_id,
                        len(artifacts) + 1,
                        f"自动分块 {len(artifacts) + 1}",
                        text,
                        buffer_start,
                        "size_fallback",
                    )
                )
                keep_from = min(safe_step, len(buffer))
                buffer = buffer[keep_from:]
                buffer_start += keep_from

    if buffer.strip():
        artifacts.append(
            _write_artifact(
                output_dir,
                source_file_id,
                len(artifacts) + 1,
                f"自动分块 {len(artifacts) + 1}",
                buffer,
                buffer_start,
                "size_fallback",
            )
        )
    return artifacts
