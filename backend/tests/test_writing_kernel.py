from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.writing import (
    _oh_story_writing_kernel,
    _system_prompt,
    _user_prompt,
    _worldbuilding_prompt,
)
from novel_deconstructor.models import Base, DeconstructionSkill
from novel_deconstructor.schemas import WritingGenerateRequest, WorldbuildingDraftRequest


def test_oh_story_kernel_reads_builtin_skill():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(
        DeconstructionSkill(
            key="oh_story_long_analyze_phase2",
            name="oh-story 长篇拆文 Phase 2",
            description="内置拆书与写作方法",
            source="builtin:oh-story-codex",
            builtin=True,
            default_modes_json='["chapter_structure","conflict_analysis"]',
            prompt_template="Skill prompt: analyze chapter hooks, reader expectation, and reusable writing methods.",
        )
    )
    db.commit()

    kernel = _oh_story_writing_kernel(db)

    assert "oh-story 长篇拆文 Phase 2" in kernel
    assert "chapter_structure" in kernel
    assert "Skill prompt: analyze chapter hooks" in kernel
    assert "黄金三章" in kernel
    assert "爽点循环" in kernel


def test_writing_prompts_use_oh_story_without_mixing_worldbuilding():
    kernel = "oh-story 写作内核：黄金三章 / 冲突推进 / 信息投放"
    payload = WritingGenerateRequest(task="写第一章开头", mode="standard", knowledge_mode="reference")

    system_prompt = _system_prompt(payload.knowledge_mode, kernel)
    user_prompt = _user_prompt(payload, [], kernel)

    assert "拆书和写作都使用同一套 oh-story 内核" in system_prompt
    assert "worldbuilding 负责故事事实" in system_prompt
    assert kernel in user_prompt
    assert "oh-story 写作内核（生成时必须应用）" in user_prompt
    assert "不要沿用拆书原作世界观" in user_prompt
    assert "章节功能、冲突推进、信息投放、情绪触动与章尾牵引" in user_prompt


def test_worldbuilding_draft_prompt_uses_oh_story_as_structure_kernel():
    kernel = "oh-story 写作内核：黄金三章 / 爽点循环"
    payload = WorldbuildingDraftRequest(story_seed="边境城市里的见习修理师")

    prompt = _worldbuilding_prompt(payload, [], kernel)

    assert kernel in prompt
    assert "原创世界观设定草案" in prompt
    assert "支撑黄金三章、冲突推进、信息投放和情绪触动" in prompt
    assert "禁止沿用拆书原作专名和独特设定" in prompt
