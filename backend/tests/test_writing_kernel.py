import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.writing import (
    create_memory,
    _draft_prompt,
    _oh_story_writing_kernel,
    _outline_prompt,
    _system_prompt,
    _user_prompt,
    _worldbuilding_prompt,
    list_memories,
)
from novel_deconstructor.models import Base, DeconstructionSkill, KnowledgeBase
from novel_deconstructor.schemas import WritingDraftRequest, WritingGenerateRequest, WritingMemoryCreate, WritingOutlineRequest, WorldbuildingDraftRequest


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
    assert "oh-story 写作内核（生成提纲时必须显式应用）" in user_prompt
    assert "不要沿用拆书原作世界观" in user_prompt
    assert "只输出“章节提纲”，不要写正文" in user_prompt


def test_outline_and_draft_prompts_are_separated():
    kernel = "oh-story 写作内核：黄金三章 / 冲突推进 / 信息投放"
    outline_payload = WritingOutlineRequest(task="生成第一章提纲", mode="standard", knowledge_mode="reference")
    draft_payload = WritingDraftRequest(
        task="生成第一章正文",
        confirmed_outline="## 第一章提纲\n- 开头状态\n- 章尾牵引",
        mode="standard",
        knowledge_mode="reference",
    )

    outline_prompt = _outline_prompt(outline_payload, [], [], kernel)
    draft_prompt = _draft_prompt(draft_payload, [], [], kernel)
    draft_system = _system_prompt("reference", kernel, stage="draft")

    assert "只输出“章节提纲”，不要写正文" in outline_prompt
    assert "oh-story 结构功能核对" in outline_prompt
    assert "已确认章节提纲（必须作为正文蓝图）" in draft_prompt
    assert "只输出小说正文，不要输出提纲" in draft_prompt
    assert "不要输出表格，不要列 bullet" in draft_prompt
    assert "正文里不要写 [资料1]" in draft_system


def test_worldbuilding_draft_prompt_uses_oh_story_as_structure_kernel():
    kernel = "oh-story 写作内核：黄金三章 / 爽点循环"
    payload = WorldbuildingDraftRequest(story_seed="边境城市里的见习修理师")

    prompt = _worldbuilding_prompt(payload, [], [], kernel)

    assert kernel in prompt
    assert "原创世界观设定草案" in prompt
    assert "支撑黄金三章、冲突推进、信息投放和情绪触动" in prompt
    assert "禁止沿用拆书原作专名和独特设定" in prompt


def test_writing_memory_is_scoped_to_workspace():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(KnowledgeBase(id=1, name="KB", description="", workspace_id="ws_a"))
    db.commit()

    created = create_memory(
        WritingMemoryCreate(knowledge_base_id=1, memory_type="outline", title="第一章提纲", content="已确认提纲"),
        "ws_a",
        db,
    )
    memories = list_memories(1, "ws_a", db)

    assert created.title == "第一章提纲"
    assert len(memories) == 1
    assert memories[0].workspace_id == "ws_a"
    with pytest.raises(HTTPException):
        list_memories(1, "ws_b", db)
