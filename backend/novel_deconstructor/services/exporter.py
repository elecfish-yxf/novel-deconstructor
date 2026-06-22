from datetime import datetime
from pathlib import Path

from ..modes import AGGREGATE_MODES
from ..schemas import FileListItem


RESULT_DIRS = {
    "chapter_analysis",
    "拆文库",
    "volume_analysis",
    "final_reports",
    "knowledge_base",
    "knowledge_base_obsidian",
    "graph_outputs",
    "logs",
    "metadata",
}


def should_include_result_file(relative_path: str) -> bool:
    path = Path(relative_path)
    if len(path.parts) < 2:
        return True
    top = path.parts[0]
    name = path.name
    if top == "chapter_analysis" and any(name.endswith(f"_{mode}.md") for mode in AGGREGATE_MODES):
        return False
    if top == "metadata" and "llm_calls" in path.parts and any(f"_{mode}_" in name for mode in AGGREGATE_MODES):
        return False
    return True


def list_result_files(job_output_dir: Path) -> list[FileListItem]:
    if not job_output_dir.exists():
        return []
    files: list[FileListItem] = []
    for path in job_output_dir.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(job_output_dir).as_posix()
        if not should_include_result_file(relative):
            continue
        first = relative.split("/", 1)[0]
        files.append(
            FileListItem(
                path=relative,
                name=path.name,
                size_bytes=path.stat().st_size,
                kind=first if first in RESULT_DIRS else "other",
                modified_at=datetime.fromtimestamp(path.stat().st_mtime),
            )
        )
    return sorted(files, key=lambda item: (item.kind, item.path))
