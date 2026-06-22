from novel_deconstructor.services.prompt_renderer import PromptRenderer


def test_prompt_render_replaces_variables():
    renderer = PromptRenderer()
    rendered = renderer.render("项目：{{project_name}}，章节：{{ chapter_title }}", {"project_name": "测试", "chapter_title": "第一章"})

    assert rendered == "项目：测试，章节：第一章"


def test_analysis_prompts_include_chapter_text():
    renderer = PromptRenderer()
    modes = [
        "chapter_structure",
        "conflict_analysis",
        "character_growth",
        "information_delivery",
        "language_style",
        "ai_bad_patterns",
    ]

    for mode in modes:
        template = renderer.load_builtin(mode)
        assert "{{chapter_text}}" in template, f"{mode} must include chapter text"
