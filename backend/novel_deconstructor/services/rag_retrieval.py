from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from .knowledge_cards import build_expanded_rag_query, search_knowledge_cards, select_preferred_card_types


def search_rag_cards(
    db: Session,
    knowledge_base_ids: list[int],
    *,
    stage: str,
    query: str,
    top_k: int = 8,
    library_type: str | None = None,
    include_inactive: bool = False,
    current_volume_index: int | None = None,
    current_chapter_index: int | None = None,
    include_future: bool = False,
    include_raw: bool = False,
    allowed_scope_levels: list[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return search_knowledge_cards(
        db,
        knowledge_base_ids,
        stage=stage,
        query=query,
        top_k=top_k,
        library_type=library_type,
        include_inactive=include_inactive,
        current_volume_index=current_volume_index,
        current_chapter_index=current_chapter_index,
        include_future=include_future,
        include_raw=include_raw,
        allowed_scope_levels=allowed_scope_levels,
    )


__all__ = ["build_expanded_rag_query", "search_rag_cards", "select_preferred_card_types"]
