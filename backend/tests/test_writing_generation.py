import asyncio
import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.writing import _generate_with_cards, _plan_section_targets, count_cjk_chars
from novel_deconstructor.config import get_settings
from novel_deconstructor.models import Base, KnowledgeBase
from novel_deconstructor.schemas import WritingDraftRequest
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
    assert result.warnings
    assert result.retrieval_debug is not None
    assert result.used_knowledge
    assert all(section.status == "completed" for section in result.sections)
