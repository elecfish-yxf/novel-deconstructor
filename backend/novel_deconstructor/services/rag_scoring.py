from __future__ import annotations

from collections import Counter
from typing import Any

from ..config import get_settings


def merge_and_rank_candidates(
    candidates: list[dict[str, Any]],
    *,
    top_k: int,
    debug: dict[str, Any],
) -> list[dict[str, Any]]:
    settings = get_settings()
    merged: dict[str, dict[str, Any]] = {}
    dropped = debug.setdefault("dropped", [])
    for candidate in candidates:
        key = _logical_key(candidate)
        existing = merged.get(key)
        if not existing:
            item = dict(candidate)
            item["_duplicate_count"] = 0
            item["source_modes"] = _source_modes(candidate)
            merged[key] = item
            continue
        existing["vector_score"] = max(float(existing.get("vector_score") or 0), float(candidate.get("vector_score") or 0))
        existing["keyword_score"] = max(float(existing.get("keyword_score") or 0), float(candidate.get("keyword_score") or 0))
        existing["_duplicate_count"] = int(existing.get("_duplicate_count", 0)) + 1
        existing["source_modes"] = sorted({*existing.get("source_modes", []), *_source_modes(candidate)})
        if _candidate_strength(candidate) > _candidate_strength(existing):
            for key_name, value in candidate.items():
                if key_name not in {"vector_score", "keyword_score"}:
                    existing[key_name] = value
        dropped.append({"id": candidate.get("id") or key, "reason": "duplicate_merged", "kept": existing.get("id") or key})

    scored = []
    stage = str(debug.get("stage") or "").lower()
    for candidate in merged.values():
        candidate["type_bonus"] = _type_bonus(candidate, stage)
        candidate["priority_bonus"] = _priority_bonus(candidate)
        candidate["duplication_penalty"] = min(0.15, 0.05 * int(candidate.get("_duplicate_count", 0)))
        vector_score = _normalize_score(float(candidate.get("vector_score") or 0))
        keyword_score = _normalize_score(float(candidate.get("keyword_score") or 0))
        candidate["final_score"] = round(
            vector_score * settings.retrieval_vector_weight
            + keyword_score * settings.retrieval_keyword_weight
            + candidate["type_bonus"]
            + candidate["priority_bonus"]
            - candidate["duplication_penalty"],
            6,
        )
        scored.append(candidate)
    scored.sort(key=lambda item: item["final_score"], reverse=True)

    if not settings.retrieval_diversity_enabled:
        return [_public_candidate(item) for item in scored[:top_k]]

    selected: list[dict[str, Any]] = []
    source_counts: Counter[str] = Counter()
    card_type_counts: Counter[str] = Counter()
    for candidate in scored:
        source_key = _source_key(candidate)
        card_type = str(candidate.get("card_type") or "")
        if source_key and source_counts[source_key] >= settings.retrieval_max_per_source:
            dropped.append({"id": candidate.get("id"), "reason": "source_cap", "source": source_key})
            continue
        if card_type and card_type_counts[card_type] >= settings.retrieval_max_per_card_type:
            dropped.append({"id": candidate.get("id"), "reason": "card_type_cap", "card_type": card_type})
            continue
        selected.append(candidate)
        if source_key:
            source_counts[source_key] += 1
        if card_type:
            card_type_counts[card_type] += 1
        if len(selected) >= top_k:
            break
    debug["diversity_buckets"] = dict(card_type_counts)
    return [_public_candidate(item) for item in selected]


def _logical_key(candidate: dict[str, Any]) -> str:
    if candidate.get("card_id"):
        return f"card:{candidate['card_id']}"
    if candidate.get("memory_id"):
        return f"memory:{candidate['memory_id']}"
    if candidate.get("chunk_id"):
        return f"chunk:{candidate['chunk_id']}"
    return str(candidate.get("id") or id(candidate))


def _source_modes(candidate: dict[str, Any]) -> list[str]:
    modes = []
    if candidate.get("vector_score"):
        modes.append("vector")
    if candidate.get("keyword_score"):
        modes.append("keyword")
    return modes


def _candidate_strength(candidate: dict[str, Any]) -> float:
    return float(candidate.get("vector_score") or 0) + float(candidate.get("keyword_score") or 0)


def _normalize_score(score: float) -> float:
    if score <= 0:
        return 0.0
    if score <= 1:
        return score
    return score / (score + 4.0)


def _type_bonus(candidate: dict[str, Any], stage: str) -> float:
    bonus = 0.0
    if candidate.get("retrieval_level") == "pinned":
        bonus += 0.25
    if candidate.get("library_type") == "memory" or candidate.get("source_type") == "memory":
        bonus += 0.18
    if candidate.get("library_type") == "worldbuilding":
        bonus += 0.12
    if candidate.get("source_type") == "card":
        bonus += 0.05
    library_type = candidate.get("library_type")
    card_type = candidate.get("card_type")
    if stage == "outline":
        if library_type in {"writing_guide", "worldbuilding"}:
            bonus += 0.12
    elif stage == "draft":
        if library_type in {"writing_guide", "worldbuilding", "memory"}:
            bonus += 0.12
    elif stage == "revision":
        if library_type in {"writing_guide", "memory"} or card_type == "anti_pattern":
            bonus += 0.14
    elif stage in {"continuation", "continue"}:
        if library_type == "memory" or card_type in {"character_state", "previous_ending", "foreshadowing", "ChapterHandoff"}:
            bonus += 0.18
    return bonus


def _priority_bonus(candidate: dict[str, Any]) -> float:
    try:
        priority = int(candidate.get("priority") or 0)
    except (TypeError, ValueError):
        priority = 0
    return min(max(priority, 0), 100) / 500.0


def _source_key(candidate: dict[str, Any]) -> str:
    if candidate.get("document_id"):
        return f"document:{candidate['document_id']}"
    source_ref = candidate.get("source_ref")
    if isinstance(source_ref, dict):
        source = source_ref.get("source_path") or source_ref.get("source_file") or source_ref.get("source")
        if source:
            return f"{candidate.get('library_type', '')}:{source}"
    return str(candidate.get("source_key") or "")


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in candidate.items() if not key.startswith("_")}
