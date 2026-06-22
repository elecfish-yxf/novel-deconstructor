from fastapi import Header, Query
import re


DEFAULT_WORKSPACE_ID = "anonymous"
WORKSPACE_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def normalize_workspace_id(value: str | None) -> str:
    cleaned = WORKSPACE_RE.sub("", (value or "").strip())[:80]
    return cleaned or DEFAULT_WORKSPACE_ID


def get_workspace_id(
    x_workspace_id: str | None = Header(default=None, alias="X-Workspace-Id"),
    workspace_id: str | None = Query(default=None),
) -> str:
    return normalize_workspace_id(x_workspace_id or workspace_id)
