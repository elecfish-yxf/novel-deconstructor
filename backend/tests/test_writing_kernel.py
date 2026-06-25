import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.writing import (
    AGENT_RETRIEVAL_PROTOCOL,
    create_memory,
    _draft_prompt,
    _oh_story_writing_kernel,
    _outline_output_rule,
    _outline_prompt,
    _retrieval_queries,
    _resolve_writing_model,
    _system_prompt,
    _user_prompt,
    _worldbuilding_prompt,
    list_memories,
)
from novel_deconstructor.models import Base, DeconstructionSkill, KnowledgeBase
from novel_deconstructor.schemas import WritingDraftRequest, WritingGenerateRequest, WritingMemoryCreate, WritingOutlineRequest, WorldbuildingDraftRequest
from novel_deconstructor.services.llm_provider import DoubaoResponsesProvider


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
    assert "不要写正文" in user_prompt
    assert "完整作品/多卷章节提纲" in user_prompt


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

    assert "不要写正文" in outline_prompt
    assert "当前章节提纲" in outline_prompt
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


def test_agent_retrieval_queries_are_task_specific():
    outline_queries = _retrieval_queries("outline", "生成第一章提纲")
    draft_queries = _retrieval_queries("draft", "生成第一章正文")
    worldbuilding_queries = _retrieval_queries("worldbuilding_draft", "雨夜异常街区")

    assert AGENT_RETRIEVAL_PROTOCOL["outline"][:3] == ["structure_pattern", "conflict_pattern", "emotion_module"]
    assert any("冲突推进" in query for query in outline_queries)
    assert any("世界观" in query for query in outline_queries)
    assert any("语言风格" in query for query in draft_queries)
    assert any("AI味" in query for query in draft_queries)
    assert any("不建议照搬" in query for query in worldbuilding_queries)


def test_resolve_writing_model_supports_doubao():
    class Settings:
        doubao_api_key = "ark-key"
        ark_api_key = ""
        doubao_base_url = "https://ark.cn-beijing.volces.com/api/v3"
        doubao_model = "doubao-seed-2-0-pro-260215"
        deepseek_api_key = ""
        deepseek_base_url = "https://api.deepseek.com"
        deepseek_model = "deepseek-v4-pro"
        openai_api_key = ""
        openai_base_url = "https://api.openai.com/v1"
        openai_model = ""

    provider, model = _resolve_writing_model(
        WritingOutlineRequest(
            task="生成提纲",
            model_provider="doubao",
            model="doubao-seed-2-0-pro-260215",
            api_key="user-ark-key",
        ),
        Settings(),
    )

    assert isinstance(provider, DoubaoResponsesProvider)
    assert model == "doubao-seed-2-0-pro-260215"


def test_resolve_writing_model_maps_doubao_display_alias_to_endpoint():
    class Settings:
        doubao_api_key = ""
        ark_api_key = ""
        doubao_base_url = "https://ark.cn-beijing.volces.com/api/v3"
        doubao_model = "doubao-seed-2-0-pro-260215"
        deepseek_api_key = ""
        deepseek_base_url = "https://api.deepseek.com"
        deepseek_model = "deepseek-v4-pro"
        openai_api_key = ""
        openai_base_url = "https://api.openai.com/v1"
        openai_model = ""

    provider, model = _resolve_writing_model(
        WritingOutlineRequest(
            task="generate outline",
            model_provider="doubao",
            model="doubao-seed-pro-2.0",
            api_key="user-ark-key",
        ),
        Settings(),
    )

    assert isinstance(provider, DoubaoResponsesProvider)
    assert model == "doubao-seed-2-0-pro-260215"


def test_outline_output_rule_respects_full_novel_scope():
    payload = WritingOutlineRequest(task="请生成一份原创长篇小说章节提纲，设计三卷以上结构，每卷写明主题，每章包含章尾钩子。")

    rule = _outline_output_rule(payload)

    assert "complete novel outline" in rule
    assert "not just the current chapter" in rule


def test_resolve_writing_model_requires_user_key_even_when_server_key_exists():
    class Settings:
        doubao_api_key = "server-key"
        ark_api_key = ""
        doubao_base_url = "https://ark.cn-beijing.volces.com/api/v3"
        doubao_model = "doubao-seed-2-0-pro-260215"
        deepseek_api_key = "server-deepseek"
        deepseek_base_url = "https://api.deepseek.com"
        deepseek_model = "deepseek-v4-pro"
        openai_api_key = ""
        openai_base_url = "https://api.openai.com/v1"
        openai_model = ""

    with pytest.raises(HTTPException) as exc_info:
        _resolve_writing_model(WritingOutlineRequest(task="生成提纲", model_provider="doubao"), Settings())
    assert "Agent 写作页填写你自己的" in exc_info.value.detail


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
