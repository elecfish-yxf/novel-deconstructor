from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
import json
from pathlib import Path
import re


HEADING_NUMBER = r"[0-9０-９零〇一二三四五六七八九十百千万两壹贰叁肆伍陆柒捌玖拾佰仟]+"
CHAPTER_HEADING_RE = re.compile(
    r"^\s*("
    rf"第\s*{HEADING_NUMBER}\s*[章节回集卷部篇话幕](?:\s*[:：、.．\-—·]?\s*.{{0,80}})?"
    rf"|[章节回集卷部篇话幕]\s*{HEADING_NUMBER}(?:\s*[:：、.．\-—·]?\s*.{{0,80}})?"
    r"|[序楔终尾]章(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|楔子(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|终章(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|尾声(?:\s*[:：、.-]?\s*.{0,50})?"
    r"|番外(?:\s*[:：、.．\-—·]?\s*.{0,80})?"
    rf"|卷\s*{HEADING_NUMBER}(?:\s*[:：、.．\-—·]?\s*.{{0,80}})?"
    rf"|Chapter\s+{HEADING_NUMBER}(?:\s*[:：、.．\-—·]?\s*.{{0,80}})?"
    rf"|CHAPTER\s+{HEADING_NUMBER}(?:\s*[:：、.．\-—·]?\s*.{{0,80}})?"
    rf"|Act\.?\s*{HEADING_NUMBER}(?:\s*[:：、.．\-—·]?\s*.{{0,80}})?"
    r")\s*$",
    re.IGNORECASE,
)
DECORATION_RE = re.compile(r"^[\s#>*\-_=~★☆◆◇●○◎【\[\(（《〈「『]+|[\s#<*\-_=~★☆◆◇●○◎】\]\)）》〉」』]+$")
FRONT_MATTER_MARKERS = [
    "书名",
    "作者",
    "插画",
    "翻译",
    "校对",
    "润色",
    "书源",
    "轻之国",
    "下载后请在",
    "仅供个人",
    ".jpg",
    ".png",
]


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
    text = normalize_heading_text(line)
    if not text or len(text) > 120:
        return False
    return bool(CHAPTER_HEADING_RE.match(text))


def normalize_heading_text(line: str) -> str:
    text = line.strip().replace("\u3000", " ")
    text = DECORATION_RE.sub("", text).strip()
    return re.sub(r"\s+", " ", text)


def _heading_key(title: str) -> str:
    return re.sub(r"\s+", "", normalize_heading_text(title)).casefold()


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
    strict_chapter_split: bool = True,
) -> list[ChapterArtifact]:
    output_dir.mkdir(parents=True, exist_ok=True)
    for old in output_dir.glob("chunk_*.txt"):
        old.unlink(missing_ok=True)
    for old in output_dir.glob("chunk_*.metadata.json"):
        old.unlink(missing_ok=True)

    heading_count = _count_headings(raw_text_path)
    if heading_count:
        return _split_by_headings(raw_text_path, output_dir, source_file_id, max_chars, overlap_chars, strict_chapter_split)
    return _split_by_size(raw_text_path, output_dir, source_file_id, max_chars, overlap_chars)


def _split_by_headings(
    raw_text_path: Path,
    output_dir: Path,
    source_file_id: int,
    max_chars: int,
    overlap_chars: int,
    strict_chapter_split: bool,
) -> list[ChapterArtifact]:
    text = raw_text_path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    headings: list[tuple[int, str]] = []
    absolute_pos = 0
    for line in lines:
        if is_chapter_heading(line):
            headings.append((absolute_pos, normalize_heading_text(line)))
        absolute_pos += len(line)

    headings = _drop_front_matter_headings(text, headings)
    if not headings:
        return _split_by_size(raw_text_path, output_dir, source_file_id, max_chars, overlap_chars)

    artifacts: list[ChapterArtifact] = []

    def write_chapter(title: str, chapter_text: str, chapter_start: int, reason: str) -> None:
        chapter_text = chapter_text.strip("\n")
        if not chapter_text.strip():
            return
        parts = [(chapter_text, 0)] if strict_chapter_split else _split_long_text(chapter_text, max_chars, overlap_chars)
        for part_index, (part_text, offset) in enumerate(parts, start=1):
            part_title = title if part_index == 1 else f"{title}（续 {part_index}）"
            artifacts.append(
                _write_artifact(
                    output_dir,
                    source_file_id,
                    len(artifacts) + 1,
                    part_title,
                    part_text,
                    chapter_start + offset,
                    reason if part_index == 1 else "chapter_too_long",
                )
            )

    first_start = headings[0][0]
    preface = text[:first_start]
    if preface.strip() and not _looks_like_front_matter(preface):
        write_chapter("开篇", preface, 0, "preface")

    for index, (start, chapter_title) in enumerate(headings):
        end = headings[index + 1][0] if index + 1 < len(headings) else len(text)
        write_chapter(chapter_title, text[start:end], start, "chapter_heading")
    return artifacts


def _drop_front_matter_headings(text: str, headings: list[tuple[int, str]]) -> list[tuple[int, str]]:
    if len(headings) < 2:
        return headings
    first_start, first_title = headings[0]
    if first_start > 20:
        return headings

    first_key = _heading_key(first_title)
    for index, (start, title) in enumerate(headings[1:], start=1):
        if _heading_key(title) != first_key:
            continue
        front_matter = text[first_start:start]
        marker_hits = sum(1 for marker in FRONT_MATTER_MARKERS if marker in front_matter)
        if start <= 12000 and marker_hits >= 2:
            return headings[index:]
        break
    return headings


def _looks_like_front_matter(text: str) -> bool:
    if not text.strip():
        return False
    marker_hits = sum(1 for marker in FRONT_MATTER_MARKERS if marker in text)
    first_nonempty = next((line for line in text.splitlines() if line.strip()), "")
    return marker_hits >= 2 and is_chapter_heading(first_nonempty)


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
