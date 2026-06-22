from pathlib import Path
import argparse
import sys

from .config import get_settings
from .services.chapter_splitter import split_text_file
from .services.file_parser import normalize_text_file, validate_extension


def cmd_split(args: argparse.Namespace) -> int:
    source = Path(args.input)
    if not source.exists():
        print(f"输入文件不存在: {source}", file=sys.stderr)
        return 2
    validate_extension(source.name)
    output = Path(args.output)
    raw_path = output / "raw" / f"{source.stem}.txt"
    chunks_dir = output / "chunks"
    normalize_text_file(source, raw_path)
    artifacts = split_text_file(raw_path, chunks_dir, 0, args.max_chars, args.overlap)
    print(f"已切分 {len(artifacts)} 个章节/分块，输出目录: {chunks_dir}")
    return 0


def cmd_placeholder(name: str) -> int:
    print(f"{name} 命令已预留，将在后续 Phase 完整实现。Phase 2 请优先使用 Web；CLI 当前仅提供 split。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    settings = get_settings()
    parser = argparse.ArgumentParser(prog="novel_deconstructor")
    sub = parser.add_subparsers(dest="command", required=True)

    split = sub.add_parser("split", help="解析 TXT/MD 并切分章节")
    split.add_argument("--input", required=True)
    split.add_argument("--output", required=True)
    split.add_argument("--max-chars", type=int, default=settings.max_chapter_chars)
    split.add_argument("--overlap", type=int, default=settings.chunk_overlap_chars)
    split.set_defaults(func=cmd_split)

    for name in ["analyze", "resume", "export", "import-skills", "list-jobs"]:
        command = sub.add_parser(name)
        command.set_defaults(func=lambda _args, n=name: cmd_placeholder(n))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
