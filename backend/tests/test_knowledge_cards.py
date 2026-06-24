import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.config import get_settings
from novel_deconstructor.models import Base, KnowledgeBase, KnowledgeCard
from novel_deconstructor.services.knowledge_cards import (
    apply_knowledge_card_merges,
    content_fingerprint,
    delete_markdown_doc,
    import_knowledge_package,
    import_markdown_knowledge_source,
    preview_knowledge_card_merges,
    search_knowledge_cards,
    sync_card_from_markdown,
    unmerge_knowledge_card,
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
    assert card.is_canonical is True
    assert card.evidence_count == 1
    assert card.content_fingerprint
    assert "## Rule" in card.content
    assert "## Use When" in card.content
    assert Path(card.markdown_path).exists()
    assert 'card_id: "WR-001"' in Path(card.markdown_path).read_text(encoding="utf-8")
    assert "is_canonical: true" in Path(card.markdown_path).read_text(encoding="utf-8")


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
    assert all(card.retrievable for card in cards)
    assert all(Path(card.markdown_path).exists() for card in cards)
    assert (tmp_path / "knowledge" / kb.workspace_id / "1" / "knowledge_docs" / "_imports").exists()

    hidden_results, hidden_debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="concrete obstacles escalation",
        top_k=5,
    )
    assert hidden_results == []
    assert hidden_debug["filtered_by_status_count"] == 3

    raw_results, raw_debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="concrete obstacles escalation",
        top_k=5,
        include_raw=True,
    )
    assert raw_results
    assert raw_debug["selected_count"] > 0


def test_import_markdown_worldbuilding_is_retrievable_when_approved(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    markdown = """# Story Bible

## Rain district

The rain district oath beacon binds every courier to return before dawn.
"""

    import_markdown_knowledge_source(
        db,
        kb,
        markdown,
        source_name="story-bible.md",
        library_type="worldbuilding",
        status="approved",
    )

    card = db.query(KnowledgeCard).one()
    assert card.library_type == "worldbuilding"
    assert card.is_canonical is True
    assert card.retrievable is True

    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="rain district oath beacon",
        top_k=5,
        current_volume_index=1,
        current_chapter_index=1,
    )
    assert [item["id"] for item in results] == [card.card_id]
    assert debug["selected_count"] == 1


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


def test_search_knowledge_cards_expands_query_and_keeps_diverse_results(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    cards = [
        ("WR-0", "writing_rule", "Revision rule 0", "polish style and avoid exposition in revision", 20),
        ("WR-1", "writing_rule", "Revision rule 1", "polish style and avoid exposition with concrete action", 20),
        ("WR-2", "writing_rule", "Revision rule 2", "polish style and avoid exposition with scene pressure", 20),
        ("WR-3", "writing_rule", "Revision rule 3", "polish style and avoid exposition with dialogue", 20),
        ("SP-1", "style_pattern", "Sharper sentence rhythm", "polish style with sensory rhythm and clean verbs", 1),
        ("AP-1", "anti_pattern", "Avoid exposition dump", "avoid exposition and mechanical explanation during revision", 1),
        ("AP-2", "anti_pattern", "Avoid exposition dump duplicate", "avoid exposition and mechanical explanation during revision", 1),
    ]
    for card_id, card_type, title, content, evidence_count in cards:
        tags = [card_type, "revision", "style"]
        db.add(
            KnowledgeCard(
                knowledge_base_id=kb.id,
                card_id=card_id,
                library_type="writing_guide",
                card_type=card_type,
                title=title,
                content=content,
                summary=content,
                tags_json=json.dumps(tags),
                source_ref_json="{}",
                use_when_json='["revision"]',
                avoid="",
                confidence=0.8,
                status="approved",
                source_kind="test",
                package_id="",
                is_canonical=True,
                retrievable=True,
                evidence_count=evidence_count,
                content_fingerprint=content_fingerprint(title if card_id != "AP-2" else "Avoid exposition dump", content, "", tags),
            )
        )
    db.commit()

    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="revision",
        query="polish this scene and remove exposition",
        top_k=4,
    )

    assert debug["raw_query"] == "polish this scene and remove exposition"
    assert "revision" in debug["expanded_terms"]
    assert debug["filtered_duplicate_count"] >= 1
    assert debug["diversity_buckets"]
    assert len(results) == 4
    assert {item["card_type"] for item in results} & {"anti_pattern", "style_pattern"}
    assert sum(1 for item in results if item["card_type"] == "writing_rule") <= 2


def test_safe_merge_marks_duplicate_as_raw_evidence_and_keeps_canonical_search(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = {
        "package_id": "merge-demo",
        "writing_rules": [
            {
                "id": "WR-A",
                "title": "用状态变化推动章节",
                "rule": "每一章至少让主角在认知、关系、处境或目标中产生一项变化。",
                "use_when": ["outline", "draft"],
                "tags": ["章节结构", "状态变化"],
                "source_ref": {"chapter": "1"},
                "confidence": 0.9,
            },
            {
                "id": "WR-B",
                "title": "用状态变化推动章节",
                "rule": "每一章至少让主角在认知、关系、处境或目标中产生一项变化。",
                "use_when": ["outline", "draft"],
                "tags": ["章节结构", "状态变化"],
                "source_ref": {"chapter": "2"},
                "confidence": 0.7,
            },
        ],
    }
    import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved", merge_mode="off")

    preview = preview_knowledge_card_merges(db, kb)
    assert preview["exact_duplicate_count"] == 1

    result = apply_knowledge_card_merges(db, kb)

    assert result["merged_card_count"] == 1
    primary = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "WR-A").one()
    merged = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "WR-B").one()
    assert primary.is_canonical is True
    assert primary.evidence_count == 2
    assert merged.is_canonical is False
    assert merged.status == "merged"
    assert merged.merged_into_card_id == "WR-A"

    results, _ = search_knowledge_cards(db, [kb.id], stage="outline", query="状态变化 章节推进", top_k=10)
    assert [item["id"] for item in results] == ["WR-A"]

    restored = unmerge_knowledge_card(db, kb, "WR-B")
    assert restored.is_canonical is True
    assert restored.status == "approved"


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


def _add_scoped_card(
    db,
    kb,
    card_id: str,
    *,
    library_type: str = "writing_guide",
    card_type: str = "writing_rule",
    content: str = "scope beacon",
    scope_level: str = "global",
    volume_index: int | None = None,
    chapter_index: int | None = None,
    status: str = "approved",
    is_canonical: bool = True,
    retrievable: bool = True,
    reveal_at_chapter_index: int | None = None,
) -> KnowledgeCard:
    card = KnowledgeCard(
        knowledge_base_id=kb.id,
        card_id=card_id,
        library_type=library_type,
        card_type=card_type,
        title=card_id,
        content=content,
        summary=content,
        tags_json=json.dumps(["scope", "beacon", library_type]),
        source_ref_json="{}",
        use_when_json='["draft"]',
        avoid="",
        confidence=0.9,
        status=status,
        source_kind="test",
        package_id="",
        is_canonical=is_canonical,
        retrievable=retrievable,
        scope_level=scope_level,
        volume_index=volume_index,
        chapter_index=chapter_index,
        reveal_at_volume_index=volume_index if reveal_at_chapter_index is not None else None,
        reveal_at_chapter_index=reveal_at_chapter_index,
        evidence_count=1,
        content_fingerprint=content_fingerprint(card_id, content, "", ["scope", "beacon", library_type]),
    )
    db.add(card)
    db.commit()
    return card


def test_scoped_rag_blocks_future_chapters_and_volumes(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    _add_scoped_card(db, kb, "GUIDE", content="scope beacon guide", scope_level="global")
    _add_scoped_card(db, kb, "MEM-004", library_type="memory", card_type="memory", content="scope beacon memory", scope_level="chapter", volume_index=1, chapter_index=4)
    _add_scoped_card(db, kb, "MEM-006", library_type="memory", card_type="memory", content="scope beacon future chapter", scope_level="chapter", volume_index=1, chapter_index=6)
    _add_scoped_card(db, kb, "MEM-V2", library_type="memory", card_type="memory", content="scope beacon future volume", scope_level="chapter", volume_index=2, chapter_index=1)

    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="draft",
        query="scope beacon memory guide",
        top_k=10,
        current_volume_index=1,
        current_chapter_index=5,
    )

    ids = {item["id"] for item in results}
    assert "GUIDE" in ids
    assert "MEM-004" in ids
    assert "MEM-006" not in ids
    assert "MEM-V2" not in ids
    assert debug["filtered_by_future_count"] >= 2


def test_scoped_rag_hides_raw_and_inactive_statuses_by_default(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    _add_scoped_card(db, kb, "RAW", content="blocked beacon raw", status="raw_extracted", is_canonical=False, retrievable=True)
    for status in ["deprecated", "superseded", "deleted", "merged"]:
        _add_scoped_card(db, kb, f"BAD-{status}", content="blocked beacon status", status=status)

    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="draft",
        query="blocked beacon",
        top_k=10,
        current_volume_index=1,
        current_chapter_index=5,
    )

    assert results == []
    assert debug["filtered_by_status_count"] == 5


def test_reveal_at_hides_worldbuilding_until_reveal_chapter(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    _add_scoped_card(
        db,
        kb,
        "WB-SECRET",
        library_type="worldbuilding",
        card_type="worldbuilding",
        content="secret city reveal beacon",
        scope_level="global",
        volume_index=1,
        reveal_at_chapter_index=8,
    )

    early, _ = search_knowledge_cards(
        db,
        [kb.id],
        stage="worldbuilding_check",
        query="secret city reveal beacon",
        top_k=5,
        current_volume_index=1,
        current_chapter_index=5,
    )
    revealed, _ = search_knowledge_cards(
        db,
        [kb.id],
        stage="worldbuilding_check",
        query="secret city reveal beacon",
        top_k=5,
        current_volume_index=1,
        current_chapter_index=8,
    )

    assert early == []
    assert [item["id"] for item in revealed] == ["WB-SECRET"]


def test_missing_position_only_returns_global_writing_guide(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    _add_scoped_card(db, kb, "GUIDE", content="missing position beacon", scope_level="global")
    _add_scoped_card(db, kb, "MEM-GLOBAL", library_type="memory", card_type="memory", content="missing position beacon", scope_level="global")
    _add_scoped_card(db, kb, "WB-GLOBAL", library_type="worldbuilding", card_type="worldbuilding", content="missing position beacon", scope_level="global")

    results, debug = search_knowledge_cards(db, [kb.id], stage="draft", query="missing position beacon", top_k=10)

    assert [item["id"] for item in results] == ["GUIDE"]
    assert debug["filtered_by_scope_count"] == 2
