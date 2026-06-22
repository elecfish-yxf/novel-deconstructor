from novel_deconstructor.modes import ignored_aggregate_modes, sanitize_chapter_modes


def test_sanitize_chapter_modes_drops_aggregate_modes():
    modes = sanitize_chapter_modes(["chapter_structure", "final_knowledge_base", "obsidian_export"])

    assert modes == ["chapter_structure"]


def test_sanitize_chapter_modes_uses_default_when_only_aggregate_modes():
    modes = sanitize_chapter_modes(["volume_summary", "final_knowledge_base"])

    assert modes == ["chapter_structure"]


def test_ignored_aggregate_modes_reports_filtered_modes():
    modes = ignored_aggregate_modes(["chapter_structure", "volume_summary", "final_knowledge_base"])

    assert modes == ["volume_summary", "final_knowledge_base"]
