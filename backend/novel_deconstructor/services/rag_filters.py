from __future__ import annotations

from typing import Any


ACTIVE_VECTOR_STATUSES = {"approved", "reviewed", "completed"}
GLOBAL_SCOPE_LEVELS = {"global", "book", "", None}


def build_scope_filter(
    *,
    workspace_id: str,
    knowledge_base_ids: list[int],
    library_types: list[str] | None,
    target_volume_index: int | None,
    target_chapter_index: int | None,
    include_future: bool = False,
) -> dict[str, Any]:
    kb_ids = [int(item) for item in knowledge_base_ids if item is not None]
    normalized_library_types = [item for item in (library_types or []) if item]
    must: list[dict[str, Any]] = [
        {"key": "workspace_id", "match": workspace_id},
        {"key": "knowledge_base_id", "any": kb_ids},
        {"key": "retrievable", "match": True},
        {"key": "is_canonical", "match": True},
        {"key": "status", "any": sorted(ACTIVE_VECTOR_STATUSES)},
    ]
    if normalized_library_types:
        must.append({"key": "library_type", "any": normalized_library_types})

    return {
        "workspace_id": workspace_id,
        "knowledge_base_ids": kb_ids,
        "library_types": normalized_library_types,
        "target_volume_index": target_volume_index,
        "target_chapter_index": target_chapter_index,
        "include_future": include_future,
        "must": must,
        "filters_applied": [
            "workspace",
            "knowledge_base",
            "retrievable",
            "canonical",
            "status",
            "library_type" if normalized_library_types else "",
            "reveal_at" if not include_future else "",
            "valid_until",
            "scope",
        ],
    }


def matches_scope_filter(payload: dict[str, Any], scope_filter: dict[str, Any]) -> bool:
    return scope_filter_reason(payload, scope_filter) is None


def scope_filter_reason(payload: dict[str, Any], scope_filter: dict[str, Any]) -> str | None:
    if not payload:
        return "empty_payload"
    if str(payload.get("workspace_id") or "") != str(scope_filter.get("workspace_id") or ""):
        return "workspace"
    kb_ids = {int(item) for item in scope_filter.get("knowledge_base_ids", []) if item is not None}
    if kb_ids and _int_value(payload.get("knowledge_base_id")) not in kb_ids:
        return "knowledge_base"
    library_types = {str(item) for item in scope_filter.get("library_types", []) if item}
    if library_types and str(payload.get("library_type") or "") not in library_types:
        return "library_type"
    if payload.get("retrievable") is False:
        return "not_retrievable"
    if payload.get("source_type") == "card" and payload.get("is_canonical") is False:
        return "not_canonical"
    status = str(payload.get("status") or "").strip()
    if status and status not in ACTIVE_VECTOR_STATUSES:
        return "inactive_status"

    target_volume = _int_value(scope_filter.get("target_volume_index"))
    target_chapter = _int_value(scope_filter.get("target_chapter_index"))
    include_future = bool(scope_filter.get("include_future"))
    if target_volume is None or target_chapter is None:
        return None if _scope_level(payload) in GLOBAL_SCOPE_LEVELS else "missing_position_scope"

    if not include_future:
        reveal_volume = _int_value(payload.get("reveal_at_volume_index"))
        reveal_chapter = _int_value(payload.get("reveal_at_chapter_index"))
        if reveal_volume is not None and _is_after(reveal_volume, reveal_chapter, target_volume, target_chapter):
            return "future_scope"
        valid_from_volume = _int_value(payload.get("valid_from_volume_index"))
        valid_from_chapter = _int_value(payload.get("valid_from_chapter_index"))
        if valid_from_volume is not None and _is_after(valid_from_volume, valid_from_chapter, target_volume, target_chapter):
            return "future_scope"

    valid_until_volume = _int_value(payload.get("valid_until_volume_index"))
    valid_until_chapter = _int_value(payload.get("valid_until_chapter_index"))
    if valid_until_volume is not None and _is_before(valid_until_volume, valid_until_chapter, target_volume, target_chapter):
        return "expired_scope"

    scope_level = _scope_level(payload)
    if scope_level in GLOBAL_SCOPE_LEVELS:
        return None
    volume_index = _int_value(payload.get("volume_index"))
    chapter_index = _int_value(payload.get("chapter_index"))
    if scope_level == "volume":
        if include_future or volume_index == target_volume:
            return None
        return "future_scope" if volume_index and volume_index > target_volume else "scope"
    if scope_level == "chapter":
        if volume_index != target_volume or chapter_index is None:
            return "future_scope" if volume_index and volume_index > target_volume else "scope"
        if include_future:
            return None
        if payload.get("library_type") == "memory" or payload.get("source_type") == "memory":
            return None if chapter_index <= target_chapter else "future_scope"
        return None if chapter_index == target_chapter else "future_scope" if chapter_index > target_chapter else "scope"
    return "scope"


def _scope_level(payload: dict[str, Any]) -> str:
    value = str(payload.get("scope_level") or "global").strip().lower()
    return "global" if value == "book" else value


def _int_value(value: Any) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_after(
    volume_a: int | None,
    chapter_a: int | None,
    volume_b: int | None,
    chapter_b: int | None,
) -> bool:
    if volume_a is None or volume_b is None:
        return False
    if volume_a > volume_b:
        return True
    if volume_a == volume_b and chapter_a is not None and chapter_b is not None:
        return chapter_a > chapter_b
    return False


def _is_before(
    volume_a: int | None,
    chapter_a: int | None,
    volume_b: int | None,
    chapter_b: int | None,
) -> bool:
    if volume_a is None or volume_b is None:
        return False
    if volume_a < volume_b:
        return True
    if volume_a == volume_b and chapter_a is not None and chapter_b is not None:
        return chapter_a < chapter_b
    return False
