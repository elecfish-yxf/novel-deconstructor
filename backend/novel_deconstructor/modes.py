CHAPTER_ANALYSIS_MODES = {
    "chapter_structure",
    "conflict_analysis",
    "character_growth",
    "information_delivery",
    "language_style",
    "ai_bad_patterns",
}

AGGREGATE_MODES = {
    "volume_summary",
    "final_knowledge_base",
    "obsidian_export",
}

RESERVED_PROMPT_MODES = {"system_base"}
DEFAULT_CHAPTER_MODE = "chapter_structure"


def normalize_mode_list(modes: list[str] | None) -> list[str]:
    clean: list[str] = []
    for mode in modes or []:
        value = (mode or "").strip()
        if value and value not in clean:
            clean.append(value)
    return clean


def sanitize_chapter_modes(modes: list[str] | None) -> list[str]:
    clean = [mode for mode in normalize_mode_list(modes) if mode in CHAPTER_ANALYSIS_MODES]
    return clean or [DEFAULT_CHAPTER_MODE]


def ignored_aggregate_modes(modes: list[str] | None) -> list[str]:
    return [mode for mode in normalize_mode_list(modes) if mode in AGGREGATE_MODES]
