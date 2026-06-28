import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.writing import (
    AGENT_RETRIEVAL_PROTOCOL,
    _draft_prompt,
    _oh_story_writing_kernel,
    _outline_output_rule,
    _outline_prompt,
    _outline_scope_block,
    _resolve_writing_model,
    _retrieval_queries,
    _system_prompt,
    _user_prompt,
    _worldbuilding_prompt,
    create_memory,
    list_memories,
)
from novel_deconstructor.models import Base, DeconstructionSkill, KnowledgeBase
from novel_deconstructor.schemas import (
    WorldbuildingDraftRequest,
    WritingDraftRequest,
    WritingGenerateRequest,
    WritingMemoryCreate,
    WritingOutlineRequest,
)
from novel_deconstructor.services.llm_provider import DoubaoResponsesProvider


def _memory_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)
    return session()


def test_oh_story_kernel_reads_builtin_skill():
    db = _memory_db()
    db.add(
        DeconstructionSkill(
            key="oh_story_long_analyze_phase2",
            name="oh-story long analyze Phase 2",
            description="Built-in deconstruction and writing method.",
            source="builtin:oh-story-codex",
            builtin=True,
            default_modes_json='["chapter_structure","conflict_analysis"]',
            prompt_template="Skill prompt: analyze chapter hooks, reader expectation, and reusable writing methods.",
        )
    )
    db.commit()

    kernel = _oh_story_writing_kernel(db)

    assert "oh-story long analyze Phase 2" in kernel
    assert "chapter_structure" in kernel
    assert "Skill prompt: analyze chapter hooks" in kernel
    assert "oh-story" in kernel


def test_writing_prompts_use_oh_story_without_mixing_worldbuilding():
    kernel = "oh-story kernel: golden three chapters / conflict / information delivery"
    payload = WritingGenerateRequest(task="write chapter opening", mode="standard", knowledge_mode="reference")

    system_prompt = _system_prompt(payload.knowledge_mode, kernel)
    user_prompt = _user_prompt(payload, [], kernel)

    assert kernel in system_prompt
    assert kernel in user_prompt
    assert "oh-story" in system_prompt
    assert "worldbuilding" in system_prompt
    assert "writing_guide" in system_prompt
    assert "CURRENT_CHAPTER" in user_prompt


def test_outline_and_draft_prompts_are_separated():
    kernel = "oh-story kernel: golden three chapters / conflict / information delivery"
    outline_payload = WritingOutlineRequest(task="generate chapter outline", mode="standard", knowledge_mode="reference")
    draft_payload = WritingDraftRequest(
        task="generate chapter draft",
        confirmed_outline="## Chapter outline\n- Opening state\n- Ending hook",
        mode="standard",
        knowledge_mode="reference",
    )

    outline_prompt = _outline_prompt(outline_payload, [], [], kernel)
    draft_prompt = _draft_prompt(draft_payload, [], [], kernel)
    draft_system = _system_prompt("reference", kernel, stage="draft")

    assert "CURRENT_CHAPTER" in outline_prompt
    assert "oh-story" in outline_prompt
    assert "Chapter outline" in draft_prompt
    assert "bullet" in draft_prompt
    assert "章尾落点" in draft_prompt
    assert "不要替下一章推进或解决" in draft_prompt
    assert "citations" in draft_system


def test_worldbuilding_draft_prompt_uses_oh_story_as_structure_kernel():
    kernel = "oh-story kernel: golden three chapters / momentum loop"
    payload = WorldbuildingDraftRequest(story_seed="A border city apprentice repairer")

    prompt = _worldbuilding_prompt(payload, [], [], kernel)

    assert kernel in prompt
    assert payload.story_seed in prompt
    assert "oh-story" in prompt


def test_agent_retrieval_queries_are_task_specific():
    outline_queries = _retrieval_queries("outline", "generate chapter outline")
    draft_queries = _retrieval_queries("draft", "generate chapter draft")
    worldbuilding_queries = _retrieval_queries("worldbuilding_draft", "rainy night district")

    assert AGENT_RETRIEVAL_PROTOCOL["outline"][:3] == ["structure_pattern", "conflict_pattern", "emotion_module"]
    assert any("structure pattern" in query for query in outline_queries)
    assert any("worldbuilding" in query for query in outline_queries)
    assert any("style pattern" in query for query in draft_queries)
    assert any("anti pattern" in query for query in draft_queries)
    assert any("writing guide" in query for query in worldbuilding_queries)


def test_resolve_writing_model_supports_doubao():
    class Settings:
        doubao_api_key = "server-ark-key"
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


def test_outline_output_rule_scopes_outline_levels():
    chapter_payload = WritingOutlineRequest(task="generate current chapter opening outline")
    volume_payload = WritingOutlineRequest(task="generate outline", scope_level="volume")
    global_payload = WritingOutlineRequest(task="generate full novel outline", scope_level="global")

    assert "CURRENT_CHAPTER" in _outline_scope_block(chapter_payload)
    assert "CURRENT_VOLUME" in _outline_scope_block(volume_payload)
    assert "FULL_NOVEL" in _outline_scope_block(global_payload)

    assert "Only output a current-chapter outline" in _outline_output_rule(chapter_payload)
    assert "current-volume outline" in _outline_output_rule(volume_payload)
    assert "complete novel outline" in _outline_output_rule(global_payload)


def test_chapter_outline_scope_ignores_long_form_guide_title():
    payload = WritingOutlineRequest(
        task="请结合《AI中文长篇小说写作指南》，生成第一卷第001章章节提纲。",
        scope_level="chapter",
        current_volume_index=1,
        current_chapter_index=1,
    )

    assert "CURRENT_CHAPTER" in _outline_scope_block(payload)
    assert "FULL_NOVEL" not in _outline_scope_block(payload)
    assert "Only output a current-chapter outline" in _outline_output_rule(payload)


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
        _resolve_writing_model(WritingOutlineRequest(task="generate outline", model_provider="doubao"), Settings())
    assert "API Key" in exc_info.value.detail


def test_writing_memory_is_scoped_to_workspace():
    db = _memory_db()
    db.add(KnowledgeBase(id=1, name="KB", description="", workspace_id="ws_a"))
    db.commit()

    created = create_memory(
        WritingMemoryCreate(knowledge_base_id=1, memory_type="outline", title="Chapter one outline", content="Confirmed outline"),
        "ws_a",
        db,
    )
    memories = list_memories(1, "ws_a", db)

    assert created.title == "Chapter one outline"
    assert len(memories) == 1
    assert memories[0].workspace_id == "ws_a"
    with pytest.raises(HTTPException):
        list_memories(1, "ws_b", db)
