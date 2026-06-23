from pathlib import Path
import re

from fastapi import HTTPException

from ..config import get_settings


def secure_slug(value: str, fallback: str = "project") -> str:
    normalized = re.sub(r"[^\w\-\u4e00-\u9fff]+", "_", value.strip(), flags=re.UNICODE)
    normalized = normalized.strip("._ ")
    return normalized or fallback


def ensure_inside(base: Path, candidate: Path) -> Path:
    base_resolved = base.resolve()
    candidate_resolved = candidate.resolve()
    if not candidate_resolved.is_relative_to(base_resolved):
        raise HTTPException(status_code=400, detail="输出路径不允许越过 APP_OUTPUT_DIR")
    return candidate_resolved


def ensure_writable_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / ".write_test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"输出路径不可写: {path}") from exc
    return path


def resolve_output_root(requested_root: str | None = None) -> Path:
    settings = get_settings()
    base = settings.output_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)

    if not requested_root:
        return ensure_writable_dir(base)

    candidate = Path(requested_root).expanduser()
    if candidate.is_absolute():
        if not settings.allow_absolute_output_path:
            raise HTTPException(status_code=400, detail="默认不允许绝对输出路径，请设置 ALLOW_ABSOLUTE_OUTPUT_PATH=true")
        return ensure_writable_dir(candidate)

    return ensure_writable_dir(ensure_inside(base, base / candidate))


def project_output_dir(project_name: str, requested_root: str | None = None, workspace_id: str | None = None) -> Path:
    root = resolve_output_root(requested_root)
    if workspace_id:
        root = root / secure_slug(workspace_id, "workspace")
    return ensure_writable_dir(root / secure_slug(project_name))


def job_output_dir(project_name: str, job_id: str, requested_root: str | None = None, workspace_id: str | None = None) -> Path:
    return ensure_writable_dir(project_output_dir(project_name, requested_root, workspace_id=workspace_id) / job_id)


def safe_relative_file(base: Path, relative_path: str) -> Path:
    if Path(relative_path).is_absolute():
        raise HTTPException(status_code=400, detail="下载路径必须是相对路径")
    candidate = ensure_inside(base, base / relative_path)
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    return candidate
