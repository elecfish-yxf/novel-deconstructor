import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.writing import (
    MAX_SECTION_SUPPLEMENTS,
    _char_stats,
    _generate_with_cards,
    _maybe_supplement_section,
    _parse_target_chars_from_text,
    _plan_section_targets,
    count_cjk_chars,
    count_non_space_chars,
)
from novel_deconstructor.config import get_settings
from novel_deconstructor.models import Base, KnowledgeBase, UserAPIKey
from novel_deconstructor.schemas import WritingDraftRequest, WritingRevisionRequest
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
