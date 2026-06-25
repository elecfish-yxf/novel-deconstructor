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
    _resolved_outline_scope,
    _outline_prompt,
    _outline_scope_block,
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
            name="oh-story 闀跨瘒鎷嗘枃 Phase 2",
            description="鍐呯疆鎷嗕功涓庡啓浣滄柟娉?,
            source="builtin:oh-story-codex",
            builtin=True,
            default_modes_json='["chapter_structure","conflict_analysis"]',
            prompt_template="Skill prompt: analyze chapter hooks, reader expectation, and reusable writing methods.",
        )
    )
    db.commit()

    kernel = _oh_story_writing_kernel(db)

    assert "oh-story 闀跨瘒鎷嗘枃 Phase 2" in kernel
    assert "chapter_structure" in kernel
    assert "Skill prompt: analyze chapter hooks" in kernel
    assert "榛勯噾涓夌珷" in kernel
    assert "鐖界偣寰幆" in kernel


def test_writing_prompts_use_oh_story_without_mixing_worldbuilding():
    kernel = "oh-story 鍐欎綔鍐呮牳锛氶粍閲戜笁绔?/ 鍐茬獊鎺ㄨ繘 / 淇℃伅鎶曟斁"
    payload = WritingGenerateRequest(task="鍐欑涓€绔犲紑澶?, mode="standard", knowledge_mode="reference")

    system_prompt = _system_prompt(payload.knowledge_mode, kernel)
    user_prompt = _user_prompt(payload, [], kernel)

    assert "鎷嗕功鍜屽啓浣滈兘浣跨敤鍚屼竴濂?oh-story 鍐呮牳" in system_prompt
    assert "worldbuilding 璐熻矗鏁呬簨浜嬪疄" in system_prompt
    assert kernel in user_prompt
    assert "oh-story 鍐欎綔鍐呮牳锛堢敓鎴愭彁绾叉椂蹇呴』鏄惧紡搴旂敤锛? in user_prompt
    assert "涓嶈娌跨敤鎷嗕功鍘熶綔涓栫晫瑙? in user_prompt
    assert "涓嶈鍐欐鏂? in user_prompt
    assert "瀹屾暣浣滃搧/澶氬嵎绔犺妭鎻愮翰" in user_prompt


def test_outline_and_draft_prompts_are_separated():
    kernel = "oh-story 鍐欎綔鍐呮牳锛氶粍閲戜笁绔?/ 鍐茬獊鎺ㄨ繘 / 淇℃伅鎶曟斁"
    outline_payload = WritingOutlineRequest(task="鐢熸垚绗竴绔犳彁绾?, mode="standard", knowledge_mode="reference")
    draft_payload = WritingDraftRequest(
        task="鐢熸垚绗竴绔犳鏂?,
        confirmed_outline="## 绗竴绔犳彁绾瞈n- 寮€澶寸姸鎬乗n- 绔犲熬鐗靛紩",
        mode="standard",
        knowledge_mode="reference",
    )

    outline_prompt = _outline_prompt(outline_payload, [], [], kernel)
    draft_prompt = _draft_prompt(draft_payload, [], [], kernel)
    draft_system = _system_prompt("reference", kernel, stage="draft")

    assert "涓嶈鍐欐鏂? in outline_prompt
    assert "褰撳墠绔犺妭鎻愮翰" in outline_prompt
    assert "oh-story 缁撴瀯鍔熻兘鏍稿" in outline_prompt
    assert "宸茬‘璁ょ珷鑺傛彁绾诧紙蹇呴』浣滀负姝ｆ枃钃濆浘锛? in draft_prompt
    assert "鍙緭鍑哄皬璇存鏂囷紝涓嶈杈撳嚭鎻愮翰" in draft_prompt
    assert "涓嶈杈撳嚭琛ㄦ牸锛屼笉瑕佸垪 bullet" in draft_prompt
    assert "姝ｆ枃閲屼笉瑕佸啓 [璧勬枡1]" in draft_system


def test_worldbuilding_draft_prompt_uses_oh_story_as_structure_kernel():
    kernel = "oh-story 鍐欎綔鍐呮牳锛氶粍閲戜笁绔?/ 鐖界偣寰幆"
    payload = WorldbuildingDraftRequest(story_seed="杈瑰鍩庡競閲岀殑瑙佷範淇悊甯?)

    prompt = _worldbuilding_prompt(payload, [], [], kernel)

    assert kernel in prompt
    assert "鍘熷垱涓栫晫瑙傝瀹氳崏妗? in prompt
    assert "鏀拺榛勯噾涓夌珷銆佸啿绐佹帹杩涖€佷俊鎭姇鏀惧拰鎯呯华瑙﹀姩" in prompt
    assert "绂佹娌跨敤鎷嗕功鍘熶綔涓撳悕鍜岀嫭鐗硅瀹? in prompt


def test_agent_retrieval_queries_are_task_specific():
    outline_queries = _retrieval_queries("outline", "鐢熸垚绗竴绔犳彁绾?)
    draft_queries = _retrieval_queries("draft", "鐢熸垚绗竴绔犳鏂?)
    worldbuilding_queries = _retrieval_queries("worldbuilding_draft", "闆ㄥ寮傚父琛楀尯")

    assert AGENT_RETRIEVAL_PROTOCOL["outline"][:3] == ["structure_pattern", "conflict_pattern", "emotion_module"]
    assert any("鍐茬獊鎺ㄨ繘" in query for query in outline_queries)
    assert any("涓栫晫瑙? in query for query in outline_queries)
    assert any("璇█椋庢牸" in query for query in draft_queries)
    assert any("AI鍛? in query for query in draft_queries)
    assert any("涓嶅缓璁収鎼? in query for query in worldbuilding_queries)


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
            task="鐢熸垚鎻愮翰",
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
    chapter_payload = WritingOutlineRequest(task="生成当前章节开头提纲")
    global_payload = WritingOutlineRequest(task="生成全书大纲")
    volume_payload = WritingOutlineRequest(task="生成当前卷大纲")

    assert _resolved_outline_scope(chapter_payload) == "chapter"
    assert "CURRENT_CHAPTER" in _outline_scope_block(chapter_payload)
    assert _resolved_outline_scope(global_payload) == "global"
    assert "FULL_NOVEL" in _outline_scope_block(global_payload)
    assert _resolved_outline_scope(volume_payload) == "volume"
    assert "CURRENT_VOLUME" in _outline_scope_block(volume_payload)

    assert "Only output the current chapter outline" in _outline_output_rule(chapter_payload)
    assert "full-book outline" in _outline_output_rule(global_payload)

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
        _resolve_writing_model(WritingOutlineRequest(task="鐢熸垚鎻愮翰", model_provider="doubao"), Settings())
    assert "Agent 鍐欎綔椤靛～鍐欎綘鑷繁鐨? in exc_info.value.detail


def test_writing_memory_is_scoped_to_workspace():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    db.add(KnowledgeBase(id=1, name="KB", description="", workspace_id="ws_a"))
    db.commit()

    created = create_memory(
        WritingMemoryCreate(knowledge_base_id=1, memory_type="outline", title="绗竴绔犳彁绾?, content="宸茬‘璁ゆ彁绾?),
        "ws_a",
        db,
    )
    memories = list_memories(1, "ws_a", db)

    assert created.title == "绗竴绔犳彁绾?
    assert len(memories) == 1
    assert memories[0].workspace_id == "ws_a"
    with pytest.raises(HTTPException):
        list_memories(1, "ws_b", db)

