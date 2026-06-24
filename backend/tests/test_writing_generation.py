import asyncio
import json
from pathlib import Path

import novel_deconstructor.api.writing as writing_api
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.writing import (
    MAX_SECTION_SUPPLEMENTS,
    _char_stats,
    _generate_with_cards,
    _generate_long_draft_with_cards,
    _last_sentence,
    _maybe_supplement_section,
    _parse_target_chars_from_text,
    _plan_section_targets,
    _prompt_card_filter_reason,
    _tail_clip,
    bulk_delete_writing_scope,
    confirm_draft_memory,
    confirm_outline_memory,
    count_cjk_chars,
    count_non_space_chars,
)
from novel_deconstructor.config import get_settings
from novel_deconstructor.models import Base, KnowledgeBase, KnowledgeCard, UserAPIKey, WritingMemory
from novel_deconstructor.schemas import WritingChapterRef, WritingDraftRequest, WritingMemoryConfirmRequest, WritingRevisionRequest, WritingScopeBulkDeleteRequest
from novel_deconstructor.services.knowledge_cards import import_knowledge_package


EXAMPLE_PACKAGE = Path(__file__).resolve().parents[2] / "examples" / "sample_knowledge_package.json"


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    kb = KnowledgeBase(id=1, name="Work 1", description="", workspace_id="ws_a")
    db.add(kb)
    db.commit()
    return db, kb


def _add_card(
    db,
    kb,
    card_id,
    *,
    library_type="writing_guide",
    card_type="writing_rule",
    title="Test card",
    content="test beacon",
    status="approved",
    scope_level="global",
    volume_index=None,
    chapter_index=None,
    reveal_at_volume_index=None,
    reveal_at_chapter_index=None,
    valid_from_volume_index=None,
    valid_from_chapter_index=None,
    retrievable=True,
    is_canonical=True,
    priority=0,
):
    card = KnowledgeCard(
        knowledge_base_id=kb.id,
        card_id=card_id,
        library_type=library_type,
        card_type=card_type,
        title=title,
        content=content,
        summary=content[:240],
        tags_json="[]",
        source_ref_json="{}",
        use_when_json='["draft", "outline", "revision"]',
        avoid="",
        confidence=1.0,
        status=status,
        source_kind="test",
        package_id="",
        is_canonical=is_canonical,
        merged_into_card_id=None,
        merged_from_ids_json=f'["{card_id}"]',
        evidence_count=1,
        content_fingerprint=card_id,
        scope_level=scope_level,
        volume_index=volume_index,
        chapter_index=chapter_index,
        reveal_at_volume_index=reveal_at_volume_index,
        reveal_at_chapter_index=reveal_at_chapter_index,
        valid_from_volume_index=valid_from_volume_index,
        valid_from_chapter_index=valid_from_chapter_index,
        retrievable=retrievable,
        priority=priority,
    )
    db.add(card)
    db.commit()
    return card


def test_plan_section_targets_balances_long_text():
    targets = _plan_section_targets(5000, section_size=2000)

    assert len(targets) == 3
    assert sum(targets) == 5000
    assert max(targets) - min(targets) <= 1


def test_count_cjk_chars_counts_cjk_and_ascii_text():
    assert count_cjk_chars("第一章 Hello，世界！") >= 4
    assert count_non_space_chars("第一章 Hello，世界！") >= count_cjk_chars("第一章 Hello，世界！")
    stats = _char_stats("第一章 Hello，世界！")
    assert stats["cjk_chars"] >= 4
    assert stats["non_space_chars"] >= stats["cjk_chars"]
    assert stats["estimated_tokens"] > 0


def test_parse_target_chars_from_natural_language():
    assert _parse_target_chars_from_text("请写 10000 字正文") == 10000
    assert _parse_target_chars_from_text("写一万字左右") == 10000
    assert _parse_target_chars_from_text("约 8 千字") == 8000
    assert _parse_target_chars_from_text("写 1.2 万字") == 12000


def test_section_supplement_has_retry_limit():
    class FakeProvider:
        def __init__(self):
            self.calls = 0

        async def complete(self, request):
            self.calls += 1
            return "补写内容" * 10

    settings = get_settings()
    payload = WritingDraftRequest(task="写一段正文", confirmed_outline="开场，受阻，选择。", dry_run=False)
    provider = FakeProvider()

    content, supplement_count = asyncio.run(
        _maybe_supplement_section(
            provider,
            "test-model",
            settings,
            "system",
            "短",
            payload,
            "开场",
            1,
            3,
            2000,
        )
    )

    assert supplement_count == MAX_SECTION_SUPPLEMENTS
    assert provider.calls == MAX_SECTION_SUPPLEMENTS
    assert "补写内容" in content


def test_long_draft_dry_run_returns_sections_and_generation_metadata(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))
    import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")
    payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="生成一章有明确冲突升级、人物行动和情绪释放的正文。",
        confirmed_outline="开场建立目标，中段连续受阻，结尾留下选择压力。",
        dry_run=True,
        target_chars=5000,
        top_k=3,
    )

    result = asyncio.run(_generate_with_cards(db, kb, payload, stage="draft", confirmed_outline=payload.confirmed_outline))

    assert result.stage == "draft"
    assert result.target_chars == 5000
    assert result.section_count == 3
    assert len(result.sections) == 3
    assert result.actual_chars and result.actual_chars > 0
    assert result.completion_ratio and result.completion_ratio > 0
    assert result.warnings
    assert result.retrieval_debug is not None
    assert result.used_knowledge
    assert all(section.status == "completed" for section in result.sections)
    assert all(section.supplement_count == 0 for section in result.sections)
    assert all(section.cjk_chars >= 0 and section.non_space_chars > 0 and section.estimated_tokens > 0 for section in result.sections)
    assert all(section.continuity_state for section in result.sections)


def test_long_generation_tail_clip_uses_recent_ending_not_opening():
    text = "开头不应作为续写依据。\n\n" + ("中段推进。" * 600) + "她把铜钥匙攥进掌心，走廊尽头的灯忽然灭了。"

    tail = _tail_clip(text, 220)

    assert "开头不应作为续写依据" not in tail
    assert "走廊尽头的灯忽然灭了" in tail
    assert _last_sentence(text) == "她把铜钥匙攥进掌心，走廊尽头的灯忽然灭了。"


def test_long_generation_next_section_prompt_inherits_previous_final_sentence(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()

    class ContinuityProvider:
        def __init__(self):
            self.prompts = []
            self.calls = 0

        async def complete(self, request):
            self.calls += 1
            self.prompts.append(request.user_prompt)
            if self.calls == 1:
                return "开头不应作为第二段续写依据。\n\n" + ("她沿着档案馆长廊向前，听见墙内的齿轮一层层咬合。" * 140) + "她把铜钥匙攥进掌心，走廊尽头的灯忽然灭了。"
            if self.calls == 2:
                return ("黑暗没有停在门口，而是贴着她的肩膀继续往里压。" * 150) + "门后有人叫出了她的名字。"
            return ("她没有回答，只把钥匙推入锁孔，听见另一侧传来更急的脚步声。" * 150) + "这一声让她意识到选择已经来不及撤回。"

    provider = ContinuityProvider()
    monkeypatch.setattr(writing_api, "_resolve_writing_model", lambda payload, settings: (provider, "fake-model"))

    payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="写一章连续的档案馆潜入戏，要求每段自然承接。",
        confirmed_outline="开场进入档案馆，目标是找到旧钥匙的记录。\n中段灯光熄灭，墙内机关开始运转。\n结尾门后有人叫出主角名字，迫使她做选择。",
        dry_run=False,
        target_chars=5200,
        current_volume_index=1,
        current_chapter_index=2,
        top_k=3,
    )

    result = asyncio.run(
        _generate_long_draft_with_cards(
            db,
            kb,
            payload,
            confirmed_outline=payload.confirmed_outline,
            target_chars=payload.target_chars or 5200,
        )
    )

    assert result.section_count == 3
    assert len(provider.prompts) == 3
    second_prompt = provider.prompts[1]
    assert "[SECTION CONTINUITY LOCK]" in second_prompt
    assert "[LAST SENTENCE TO CONTINUE]" in second_prompt
    assert "她把铜钥匙攥进掌心，走廊尽头的灯忽然灭了。" in second_prompt
    assert "开头不应作为第二段续写依据" not in second_prompt
    assert "第一句必须承接 [LAST SENTENCE TO CONTINUE]" in second_prompt
    assert result.sections[1].continuity_state


def test_revision_dry_run_returns_prompt_preview_and_aligned_used_knowledge(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))
    import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")
    payload = WritingRevisionRequest(
        knowledge_base_ids=[kb.id],
        task="润色当前正文，减少解释腔并增强动作和情绪连续性。",
        confirmed_outline="主角进入陌生城市，误判局势后暂时脱身。",
        current_content="主角来到城市。他觉得这里很危险。这里有很多规则需要解释。",
        dry_run=True,
        top_k=4,
    )

    result = asyncio.run(_generate_with_cards(db, kb, payload, stage="revision", confirmed_outline=payload.confirmed_outline))

    assert result.stage == "revision"
    assert result.prompt_preview
    assert "[CURRENT TASK]" in result.prompt_preview
    assert result.retrieval_debug is not None
    assert result.retrieval_debug.raw_query
    assert result.retrieval_debug.expanded_terms
    assert result.used_knowledge
    assert all(item.content_preview for item in result.used_knowledge)


def test_agent_runtime_api_key_is_not_persisted_or_echoed(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))
    import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")
    runtime_key = "runtime-only-test-key"
    payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="生成一段有规则压力的正文。",
        confirmed_outline="主角带着私人目标进入陌生场域，并被规则阻挡。",
        dry_run=True,
        api_key=runtime_key,
        top_k=3,
    )

    result = asyncio.run(_generate_with_cards(db, kb, payload, stage="draft", confirmed_outline=payload.confirmed_outline))

    assert db.query(UserAPIKey).count() == 0
    assert runtime_key not in (result.prompt_preview or "")
    assert runtime_key not in result.content


def test_prompt_preview_includes_current_writing_position(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="Draft the current scene.",
        confirmed_outline="Goal, pressure, choice.",
        dry_run=True,
        current_volume_index=1,
        current_chapter_index=2,
        top_k=3,
    )

    result = asyncio.run(_generate_with_cards(db, kb, payload, stage="draft", confirmed_outline=payload.confirmed_outline))

    assert result.prompt_preview
    assert "[CURRENT WRITING POSITION]" in result.prompt_preview
    assert "Current volume: 1" in result.prompt_preview
    assert "Current chapter: 2" in result.prompt_preview
    assert "[RETRIEVAL POLICY]" in result.prompt_preview


def test_writing_request_schema_receives_current_position():
    payload = WritingDraftRequest.model_validate(
        {
            "knowledge_base_ids": [1],
            "task": "Draft with synced position.",
            "confirmed_outline": "Goal, pressure, choice.",
            "current_volume_index": 1,
            "current_chapter_index": 2,
        }
    )

    assert payload.current_volume_index == 1
    assert payload.current_chapter_index == 2
    assert payload.include_raw_knowledge is False
    assert payload.include_future_knowledge is False


def test_confirm_outline_writes_chapter_outline_memory_and_card(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    memory = confirm_outline_memory(
        1,
        WritingMemoryConfirmRequest(
            title="Approved outline",
            content="Goal: enter the archive.\nConflict: the gate rejects the key.\nEmotion: pressure becomes resolve.",
            tags=["test"],
            volume_index=1,
            chapter_index=2,
            priority=3,
        ),
        workspace_id="ws_a",
        db=db,
    )

    card = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id == kb.id, KnowledgeCard.card_id == f"MEM-{memory.id:03d}").one()
    data = json.loads(memory.content)

    assert memory.memory_type == "ChapterOutline"
    assert data["planned_events"]
    assert memory.scope_level == "chapter"
    assert memory.reveal_at_volume_index == 1
    assert memory.reveal_at_chapter_index == 2
    assert memory.valid_from_volume_index == 1
    assert memory.valid_from_chapter_index == 2
    assert memory.priority == 60
    assert card.card_type == "ChapterOutline"
    assert card.retrievable is True
    assert card.status == "approved"


def test_bulk_delete_writing_scope_physically_deletes_chapter_memory_and_cards(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    memory = confirm_outline_memory(
        1,
        WritingMemoryConfirmRequest(
            title="Approved outline",
            content="Goal: enter the archive.\nConflict: the gate rejects the key.",
            volume_index=1,
            chapter_index=2,
        ),
        workspace_id="ws_a",
        db=db,
    )
    _add_card(db, kb, "CH-KEEP", title="Keep", scope_level="chapter", volume_index=1, chapter_index=3)
    _add_card(db, kb, "CH-DELETE", title="Delete", scope_level="chapter", volume_index=1, chapter_index=2)

    result = bulk_delete_writing_scope(
        1,
        WritingScopeBulkDeleteRequest(chapters=[WritingChapterRef(volume_index=1, chapter_index=2)]),
        workspace_id="ws_a",
        db=db,
    )

    assert result.deleted_chapters == 1
    assert result.deleted_memories == 1
    assert result.deleted_cards == 2
    assert db.get(WritingMemory, memory.id) is None
    assert db.query(KnowledgeCard).filter(KnowledgeCard.card_id == f"MEM-{memory.id:03d}").first() is None
    assert db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "CH-DELETE").first() is None
    assert db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "CH-KEEP").one()


def test_confirm_draft_writes_handoff_visible_next_chapter(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    draft_text = "The scene ends with the archive door open and the marker burning. " * 80
    memory = confirm_draft_memory(
        1,
        WritingMemoryConfirmRequest(
            title="Confirmed draft",
            content=draft_text,
            volume_index=1,
            chapter_index=1,
            priority=5,
        ),
        workspace_id="ws_a",
        db=db,
    )

    card = db.query(KnowledgeCard).filter(KnowledgeCard.knowledge_base_id == kb.id, KnowledgeCard.card_id == f"MEM-{memory.id:03d}").one()
    data = json.loads(memory.content)

    assert memory.memory_type == "ChapterHandoff"
    assert "ending_state" in data
    assert data["source_position"]["volume_index"] == 1
    assert data["source_position"]["chapter_index"] == 1
    assert data["target_position"]["volume_index"] == 1
    assert data["target_position"]["chapter_index"] == 2
    assert data["last_sentence"]
    assert data["ending_snapshot"]
    assert data["must_continue"]
    assert data["do_not_reset"]
    assert any("最后一句" in item or "last" in item.lower() for item in data["continuity_requirements"])
    assert draft_text not in memory.content
    assert len(memory.content) < len(draft_text)
    assert memory.reveal_at_volume_index == 1
    assert memory.reveal_at_chapter_index == 2
    assert memory.valid_from_volume_index == 1
    assert memory.valid_from_chapter_index == 2
    assert memory.priority == 90
    assert card.card_type == "ChapterHandoff"
    assert card.reveal_at_chapter_index == 2
    assert card.valid_from_chapter_index == 2


def test_confirm_draft_updates_volume_continuity_memory(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()

    confirm_draft_memory(
        1,
        WritingMemoryConfirmRequest(
            title="Chapter one draft",
            content="第一章结尾，林澈拿到黑色钥匙，但她发现钥匙正在发烫。下一章必须处理钥匙反应。",
            volume_index=1,
            chapter_index=1,
            chapter_title="黑钥",
        ),
        workspace_id="ws_a",
        db=db,
    )

    volume_memory = db.query(WritingMemory).filter(WritingMemory.memory_type == "volume_summary").one()
    volume_data = json.loads(volume_memory.content)
    volume_card = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == f"MEM-{volume_memory.id:03d}").one()

    assert volume_memory.source == "auto_volume_continuity"
    assert volume_memory.scope_level == "volume"
    assert volume_memory.volume_index == 1
    assert volume_memory.valid_from_chapter_index == 2
    assert volume_card.card_type == "volume_summary"
    assert volume_data["chapter_handoff_count"] == 1
    assert volume_data["continuity_chain"][0]["chapter_index"] == 1

    confirm_draft_memory(
        1,
        WritingMemoryConfirmRequest(
            title="Chapter two draft",
            content="第二章中黑色钥匙打开地下门，林澈失去通讯。章尾她听见门内有人叫出她的真名。",
            volume_index=1,
            chapter_index=2,
            chapter_title="地下门",
        ),
        workspace_id="ws_a",
        db=db,
    )

    volume_memories = db.query(WritingMemory).filter(WritingMemory.memory_type == "volume_summary").all()
    assert len(volume_memories) == 1
    db.refresh(volume_memories[0])
    updated_data = json.loads(volume_memories[0].content)
    assert volume_memories[0].id == volume_memory.id
    assert volume_memories[0].valid_from_chapter_index == 3
    assert updated_data["chapter_handoff_count"] == 2
    assert [item["chapter_index"] for item in updated_data["continuity_chain"]] == [1, 2]
    assert any("不得只承接上一章" in item for item in updated_data["volume_continuity_requirements"])

    payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="写第三章，继续处理门内声音。",
        confirmed_outline="林澈进入地下门并追查叫出真名的人。",
        dry_run=True,
        current_volume_index=1,
        current_chapter_index=3,
        top_k=10,
    )
    result = asyncio.run(_generate_with_cards(db, kb, payload, stage="draft", confirmed_outline=payload.confirmed_outline))

    assert any(item.card_type == "volume_summary" for item in result.used_knowledge)
    assert result.prompt_preview and "CURRENT VOLUME SUMMARY" in result.prompt_preview
    assert "VolumeContinuity" in result.prompt_preview
    assert "chapter_handoff_count" in result.prompt_preview


def test_chapter_delete_rebuilds_volume_continuity_memory(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, _kb = _session()

    confirm_draft_memory(
        1,
        WritingMemoryConfirmRequest(title="Chapter one", content="第一章结尾，主角保留蓝色信物。", volume_index=1, chapter_index=1),
        workspace_id="ws_a",
        db=db,
    )
    confirm_draft_memory(
        1,
        WritingMemoryConfirmRequest(title="Chapter two", content="第二章结尾，蓝色信物裂开，露出地图。", volume_index=1, chapter_index=2),
        workspace_id="ws_a",
        db=db,
    )

    bulk_delete_writing_scope(
        1,
        WritingScopeBulkDeleteRequest(chapters=[WritingChapterRef(volume_index=1, chapter_index=2)]),
        workspace_id="ws_a",
        db=db,
    )

    volume_memory = db.query(WritingMemory).filter(WritingMemory.memory_type == "volume_summary").one()
    data = json.loads(volume_memory.content)
    assert data["chapter_handoff_count"] == 1
    assert [item["chapter_index"] for item in data["continuity_chain"]] == [1]
    assert "地图" not in volume_memory.content

    bulk_delete_writing_scope(
        1,
        WritingScopeBulkDeleteRequest(chapters=[WritingChapterRef(volume_index=1, chapter_index=1)]),
        workspace_id="ws_a",
        db=db,
    )

    assert db.query(WritingMemory).filter(WritingMemory.memory_type == "volume_summary").count() == 0


def test_raw_evidence_is_hidden_by_default_and_debug_only_in_prompt(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    raw_card = _add_card(
        db,
        kb,
        "RAW-001",
        content="raw evidence beacon should only appear in debug dry-run",
        status="raw_extracted",
        retrievable=False,
        is_canonical=False,
    )
    hidden_payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="Use raw evidence beacon.",
        confirmed_outline="Check raw handling.",
        dry_run=True,
        current_volume_index=1,
        current_chapter_index=1,
        include_raw_knowledge=False,
        top_k=10,
    )
    debug_payload = hidden_payload.model_copy(update={"include_raw_knowledge": True})
    unsafe_payload = hidden_payload.model_copy(update={"include_raw_knowledge": True, "dry_run": False})

    hidden_result = asyncio.run(_generate_with_cards(db, kb, hidden_payload, stage="draft", confirmed_outline=hidden_payload.confirmed_outline))
    debug_result = asyncio.run(_generate_with_cards(db, kb, debug_payload, stage="draft", confirmed_outline=debug_payload.confirmed_outline))

    assert all(item.id != "RAW-001" for item in hidden_result.used_knowledge)
    assert any(item.id == "RAW-001" for item in debug_result.used_knowledge)
    assert "raw evidence beacon" in (debug_result.prompt_preview or "")
    assert _prompt_card_filter_reason(raw_card, unsafe_payload) == "raw_debug_only"


def test_prompt_safety_drops_future_handoff_even_when_future_retrieval_requested(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    confirm_draft_memory(
        1,
        WritingMemoryConfirmRequest(
            title="Chapter one draft",
            content="The ending handoff says the sealed map is discovered. " * 40,
            volume_index=1,
            chapter_index=1,
        ),
        workspace_id="ws_a",
        db=db,
    )
    early_payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="Continue with continuity handoff.",
        confirmed_outline="The current chapter must not know the next chapter handoff.",
        dry_run=True,
        current_volume_index=1,
        current_chapter_index=1,
        include_future_knowledge=True,
        top_k=10,
    )
    next_payload = early_payload.model_copy(update={"current_chapter_index": 2, "include_future_knowledge": False})

    early_result = asyncio.run(_generate_with_cards(db, kb, early_payload, stage="draft", confirmed_outline=early_payload.confirmed_outline))
    next_result = asyncio.run(_generate_with_cards(db, kb, next_payload, stage="draft", confirmed_outline=next_payload.confirmed_outline))

    assert all(item.card_type != "ChapterHandoff" for item in early_result.used_knowledge)
    assert early_result.retrieval_debug is not None
    assert any("prompt_dropped" in warning and "future" in warning for warning in early_result.retrieval_debug.warnings)
    assert any(item.card_type == "ChapterHandoff" for item in next_result.used_knowledge)
    assert next_result.prompt_preview and "[PREVIOUS CHAPTER HANDOFF]" in next_result.prompt_preview
    assert "[HANDOFF CONTINUITY LOCK]" in next_result.prompt_preview
    assert "Last sentence to continue" in next_result.prompt_preview
    assert "Do not reset" in next_result.prompt_preview


def test_future_worldbuilding_is_dropped_before_final_prompt(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    _add_card(
        db,
        kb,
        "WB-FUTURE",
        library_type="worldbuilding",
        card_type="worldbuilding",
        title="Future city",
        content="future city leak beacon should not enter the current prompt",
        scope_level="global",
        reveal_at_volume_index=1,
        reveal_at_chapter_index=3,
        priority=100,
    )
    payload = WritingDraftRequest(
        knowledge_base_ids=[kb.id],
        task="Mention future city leak beacon.",
        confirmed_outline="Current chapter cannot know future worldbuilding.",
        dry_run=True,
        current_volume_index=1,
        current_chapter_index=2,
        include_future_knowledge=True,
        top_k=10,
    )

    result = asyncio.run(_generate_with_cards(db, kb, payload, stage="draft", confirmed_outline=payload.confirmed_outline))

    assert all(item.id != "WB-FUTURE" for item in result.used_knowledge)
    assert result.prompt_preview and "future city leak beacon should not enter the current prompt" not in result.prompt_preview
    assert result.retrieval_debug is not None
    assert any("WB-FUTURE" in warning and "future_reveal" in warning for warning in result.retrieval_debug.warnings)
