import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.config import get_settings
from novel_deconstructor.models import Base, KnowledgeBase, KnowledgeCard
from novel_deconstructor.services.knowledge_cards import (
    delete_markdown_doc,
    import_knowledge_package,
    import_markdown_knowledge_source,
    search_knowledge_cards,
    sync_card_from_markdown,
    write_card_markdown,
)


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


def test_import_knowledge_package_generates_cards_and_markdown(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))

    result = import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")

    assert result["imported_count"] == 5
    assert result["generated_markdown_count"] == 5
    assert result["card_types"]["writing_rule"] == 1
    card = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "WR-001").one()
    assert card.library_type == "writing_guide"
    assert card.card_type == "writing_rule"
    assert "## Rule" in card.content
    assert "## Use When" in card.content
    assert Path(card.markdown_path).exists()
    assert 'card_id: "WR-001"' in Path(card.markdown_path).read_text(encoding="utf-8")


def test_import_markdown_knowledge_source_splits_and_archives_cards(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    markdown = """# External Writing Guide

## Conflict ladder

Use concrete obstacles, reversals, and escalation before the payoff.

## Anti pattern: exposition dump

Avoid explaining rules in a static block before a character has pressure.

## Emotion release

Build expectation, delay it, then release the emotion through action.
"""

    result = import_markdown_knowledge_source(
        db,
        kb,
        markdown,
        source_name="external-guide.md",
        library_type="writing_guide",
        status="raw_extracted",
    )

    assert result["imported_count"] == 3
    assert result["generated_markdown_count"] == 3
    assert result["card_types"]["conflict_pattern"] == 1
    assert result["card_types"]["anti_pattern"] == 1
    cards = db.query(KnowledgeCard).order_by(KnowledgeCard.card_id).all()
    assert {card.card_type for card in cards} == {"conflict_pattern", "anti_pattern", "emotion_module"}
    assert all(Path(card.markdown_path).exists() for card in cards)
    assert (tmp_path / "knowledge" / kb.workspace_id / "1" / "knowledge_docs" / "_imports").exists()


def test_search_knowledge_cards_uses_stage_preferences_and_status_filter(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))
    import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")

    outline_results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="chapter outline with goal pressure and conflict",
        top_k=4,
    )

    assert debug["preferred_card_types"][:3] == ["writing_rule", "conflict_pattern", "emotion_module"]
    assert outline_results
    assert {item["card_type"] for item in outline_results} & {"writing_rule", "conflict_pattern", "emotion_module"}

    card = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "WR-001").one()
    card.status = "disabled"
    db.commit()
    filtered_results, _ = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="writing rule",
        top_k=5,
    )

    assert all(item["id"] != "WR-001" for item in filtered_results)


def test_sync_markdown_frontmatter_updates_card(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    card = KnowledgeCard(
        knowledge_base_id=kb.id,
        card_id="WR-MANUAL",
        library_type="writing_guide",
        card_type="writing_rule",
        title="Old Rule",
        content="Old content",
        summary="Old content",
        tags_json='["writing_rule"]',
        source_ref_json="{}",
        use_when_json='["draft"]',
        avoid="",
        confidence=0.7,
        status="approved",
        source_kind="manual",
        package_id="",
    )
    card.markdown_path = str(tmp_path / "knowledge" / "1" / "knowledge_docs" / "writing_guide" / "writing_rule" / "WR-MANUAL.md")
    db.add(card)
    db.flush()
    write_card_markdown(kb, card)
    db.commit()
    path = Path(card.markdown_path)
    path.write_text(
        """---
card_id: "WR-MANUAL"
library_type: "writing_guide"
card_type: "writing_rule"
title: "Updated Rule"
status: "disabled"
confidence: 0.9
tags:
  - writing_rule
  - edited
use_when:
  - draft
source_ref:
  source: "test"
---
# Updated Rule

Updated body
""",
        encoding="utf-8",
    )

    result = sync_card_from_markdown(db, kb, "WR-MANUAL")

    db.refresh(card)
    assert result["status"] == "updated"
    assert card.title == "Updated Rule"
    assert card.status == "disabled"
    assert card.content == "Updated body"


def test_delete_markdown_doc_removes_file_and_soft_deletes_card(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))
    import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")
    card = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "WR-001").one()
    path = Path(card.markdown_path)
    assert path.exists()

    result = delete_markdown_doc(db, kb, "WR-001")

    db.refresh(card)
    assert result["status"] == "deleted"
    assert card.status == "deleted"
    assert not path.exists()
