import json
from pathlib import Path

from sqlalchemy.dialects import mysql
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.schema import CreateIndex

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


def test_user_package_purges_demo_cards_and_respects_selected_library(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    demo_package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))
    import_knowledge_package(db, kb, demo_package, library_type="writing_guide", status="approved")

    user_package = {
        "package_id": "user-story-bible",
        "writing_rules": [
            {
                "title": "Rain court oath",
                "content": {"rule": "Every courier must answer the rain court oath before crossing the gate."},
            }
        ],
    }

    result = import_knowledge_package(db, kb, user_package, library_type="worldbuilding", status="approved")

    cards = db.query(KnowledgeCard).order_by(KnowledgeCard.card_id).all()
    assert result["imported_count"] == 1
    assert len(cards) == 1
    assert cards[0].package_id == "user-story-bible"
    assert cards[0].library_type == "worldbuilding"
    assert cards[0].retrievable is True


def test_package_import_allocates_new_id_for_auto_id_collision(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    first_package = {
        "package_id": "first-guide",
        "writing_rules": [{"title": "First rule", "content": {"rule": "Use a concrete personal goal."}}],
    }
    second_package = {
        "package_id": "second-guide",
        "writing_rules": [{"title": "Second rule", "content": {"rule": "Turn the gate rule into an immediate cost."}}],
    }

    first = import_knowledge_package(db, kb, first_package, library_type="writing_guide", status="approved", merge_mode="off")
    second = import_knowledge_package(db, kb, second_package, library_type="writing_guide", status="approved", merge_mode="off")

    cards = db.query(KnowledgeCard).order_by(KnowledgeCard.card_id).all()
    assert first["imported_count"] == 1
    assert second["imported_count"] == 1
    assert [card.card_id for card in cards] == ["WR-001", "WR-002"]
    assert {card.package_id for card in cards} == {"first-guide", "second-guide"}


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
    assert all(card.status == "raw_extracted" for card in cards)
    assert all(card.is_canonical is False for card in cards)
    assert all(card.retrievable is False for card in cards)
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


def test_markdown_import_compacts_large_card_groups_for_rag(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    sections = "\n\n".join(
        f"## Technique {index}\n\nUse pressure rhythm beacon {index} to make the scene specific and searchable."
        for index in range(1, 10)
    )

    result = import_markdown_knowledge_source(
        db,
        kb,
        f"# Large Guide\n\n{sections}",
        source_name="large-guide.md",
        library_type="writing_guide",
        status="approved",
    )

    compact = db.query(KnowledgeCard).filter(KnowledgeCard.source_kind == "rag_compact").one()
    merged = db.query(KnowledgeCard).filter(KnowledgeCard.status == "merged").all()
    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="draft",
        query="pressure rhythm beacon",
        top_k=200,
        current_volume_index=1,
        current_chapter_index=1,
        include_raw=True,
    )

    assert result["imported_count"] == 9
    assert result["compacted_card_count"] == 1
    assert result["compacted_evidence_count"] == 9
    assert compact.is_canonical is True
    assert compact.retrievable is True
    assert compact.evidence_count == 9
    source_ref = json.loads(compact.source_ref_json)
    source_refs = json.loads(compact.source_refs_json)
    assert source_ref["source_kind"] == "rag_compact"
    assert source_ref["source_count"] == 9
    assert len(source_ref["sample_source_refs"]) <= 12
    assert len(source_refs) == 1
    assert source_refs[0]["source_kind"] == "rag_compact"
    assert len(merged) == 9
    assert [item["id"] for item in results] == [compact.card_id]
    assert debug["top_k"] == 200


def test_markdown_import_scopes_h5_chapter_outlines_and_blocks_future(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    markdown = """# Volume One Outline

#### Unit One

##### 第001章　Rain Road Wake

Location: Rain Ridge north slope.
Event: Chen Du wakes with cold coffee and hears the salt caravan bell.

##### 第087章　Archive Future

Location: Ash Archive.
Event: The forbidden archive beacon must not appear in chapter one retrieval.
"""

    result = import_markdown_knowledge_source(
        db,
        kb,
        markdown,
        source_name="volume-one-outline.md",
        library_type="memory",
        status="approved",
    )

    cards = db.query(KnowledgeCard).order_by(KnowledgeCard.chapter_index).all()
    current = next(card for card in cards if card.chapter_index == 1)
    future = next(card for card in cards if card.chapter_index == 87)
    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="Rain Ridge cold coffee salt caravan forbidden archive beacon",
        top_k=10,
        current_volume_index=1,
        current_chapter_index=1,
        include_future=False,
    )

    assert result["imported_count"] == 2
    assert {card.card_type for card in cards} == {"ChapterOutline"}
    assert current.scope_level == "chapter"
    assert current.volume_index == 1
    assert current.reveal_at_chapter_index == 1
    assert future.scope_level == "chapter"
    assert future.reveal_at_chapter_index == 87
    assert current.card_id in {item["id"] for item in results}
    assert future.card_id not in {item["id"] for item in results}
    assert debug["filtered_by_future_count"] >= 1


def test_rag_exact_query_outranks_generic_preferred_compact_card(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    exact = _add_scoped_card(
        db,
        kb,
        "LC-RAIN-RIDGE",
        library_type="worldbuilding",
        card_type="location",
        title="Rain Ridge north road",
        content="Rain Ridge salt caravan Roggo Benan cold coffee road sign.",
        source_ref={"source": "story-bible.md", "heading_path": ["Rain Ridge"]},
    )
    generic = _add_scoped_card(
        db,
        kb,
        "CP-COMPACT",
        library_type="writing_guide",
        card_type="conflict_pattern",
        title="RAG compact writing guide conflict",
        content="outline conflict structure pressure turning point hook worldbuilding memory",
        source_ref={"source": "rag_compact", "source_kind": "rag_compact"},
    )
    generic.source_kind = "rag_compact"
    generic.evidence_count = 20
    db.commit()

    results, _ = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="Rain Ridge salt caravan Roggo Benan",
        top_k=5,
        current_volume_index=1,
        current_chapter_index=1,
    )

    assert results[0]["id"] == exact.card_id


def test_rag_compaction_preserves_entity_cards_as_search_surfaces(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    sections = "\n\n".join(
        f"## Location {index}\n\nLocation beacon {index} is a precise road, town, or bridge fact."
        for index in range(1, 10)
    )

    result = import_markdown_knowledge_source(
        db,
        kb,
        f"# Story Bible\n\n{sections}",
        source_name="locations.md",
        library_type="worldbuilding",
        status="approved",
    )

    cards = db.query(KnowledgeCard).order_by(KnowledgeCard.card_id).all()
    results, _ = search_knowledge_cards(
        db,
        [kb.id],
        stage="worldbuilding_check",
        query="Location beacon 7 bridge fact",
        top_k=5,
        current_volume_index=1,
        current_chapter_index=1,
    )

    assert result["imported_count"] == 9
    assert result["compacted_card_count"] == 0
    assert all(card.card_type == "location" for card in cards)
    assert all(card.source_kind == "markdown_import" for card in cards)
    assert results[0]["title"] == "Location 7"


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


def test_delete_markdown_doc_removes_file_and_physically_deletes_card(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = json.loads(EXAMPLE_PACKAGE.read_text(encoding="utf-8"))
    import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")
    card = db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "WR-001").one()
    path = Path(card.markdown_path)
    assert path.exists()

    result = delete_markdown_doc(db, kb, "WR-001")

    assert result["status"] == "deleted"
    assert db.query(KnowledgeCard).filter(KnowledgeCard.card_id == "WR-001").first() is None
    assert not path.exists()


def _add_scoped_card(
    db,
    kb,
    card_id: str,
    *,
    library_type: str = "writing_guide",
    card_type: str = "writing_rule",
    title: str | None = None,
    content: str = "scope beacon",
    scope_level: str = "global",
    volume_index: int | None = None,
    chapter_index: int | None = None,
    status: str = "approved",
    is_canonical: bool = True,
    retrievable: bool = True,
    reveal_at_chapter_index: int | None = None,
    source_ref: dict | None = None,
) -> KnowledgeCard:
    card = KnowledgeCard(
        knowledge_base_id=kb.id,
        card_id=card_id,
        library_type=library_type,
        card_type=card_type,
        title=title or card_id,
        content=content,
        summary=content,
        tags_json=json.dumps(["scope", "beacon", library_type]),
        source_ref_json=json.dumps(source_ref or {}),
        source_refs_json=json.dumps([source_ref] if source_ref else []),
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
        content_fingerprint=content_fingerprint(title or card_id, content, "", ["scope", "beacon", library_type]),
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


def test_scoped_rag_limits_non_memory_chapter_cards_to_current_chapter(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    _add_scoped_card(db, kb, "GUIDE", content="chapter strict beacon", scope_level="global")
    _add_scoped_card(db, kb, "FACT-C4", library_type="worldbuilding", card_type="worldbuilding", content="chapter strict beacon past fact", scope_level="chapter", volume_index=1, chapter_index=4)
    _add_scoped_card(db, kb, "FACT-C5", library_type="worldbuilding", card_type="worldbuilding", content="chapter strict beacon current fact", scope_level="chapter", volume_index=1, chapter_index=5)
    _add_scoped_card(db, kb, "MEM-C4", library_type="memory", card_type="memory", content="chapter strict beacon past memory", scope_level="chapter", volume_index=1, chapter_index=4)

    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="draft",
        query="chapter strict beacon",
        top_k=10,
        current_volume_index=1,
        current_chapter_index=5,
    )

    ids = {item["id"] for item in results}
    assert "GUIDE" in ids
    assert "FACT-C5" in ids
    assert "MEM-C4" in ids
    assert "FACT-C4" not in ids
    assert debug["filtered_by_scope_count"] >= 1


def test_rag_source_cap_prevents_one_source_from_filling_top_k(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    source_ref = {"source": "same-guide.md"}
    for index, card_type in enumerate(["writing_rule", "conflict_pattern", "emotion_module", "style_pattern", "anti_pattern"], start=1):
        _add_scoped_card(
            db,
            kb,
            f"SRC-{index}",
            card_type=card_type,
            content=f"source cap beacon {card_type}",
            source_ref=source_ref,
        )

    results, debug = search_knowledge_cards(
        db,
        [kb.id],
        stage="draft",
        query="source cap beacon",
        top_k=10,
        current_volume_index=1,
        current_chapter_index=1,
    )

    assert len(results) == 2
    assert debug["source_cap_excluded_count"] == 3
    assert {item["source_ref"].get("source") for item in results} == {"same-guide.md"}


def test_duplicate_title_scope_merge_preserves_source_refs_and_single_retrievable_card(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "app_knowledge_dir", str(tmp_path / "knowledge"))
    db, kb = _session()
    package = {
        "package_id": "title-merge-demo",
        "writing_rules": [
            {
                "id": "WR-T1",
                "title": "Escalate the promise",
                "rule": "Escalate the promise through a visible cost in every scene.",
                "source_ref": {"source": "guide-a.md"},
            },
            {
                "id": "WR-T2",
                "title": "Escalate the promise",
                "rule": "Escalate the promise by making the cost harder to dodge.",
                "source_ref": {"source": "guide-b.md"},
            },
        ],
    }

    result = import_knowledge_package(db, kb, package, library_type="writing_guide", status="approved")

    canonical = db.query(KnowledgeCard).filter(KnowledgeCard.is_canonical.is_(True), KnowledgeCard.status == "approved").all()
    merged = db.query(KnowledgeCard).filter(KnowledgeCard.status == "merged").all()
    source_refs = json.loads(canonical[0].source_refs_json)
    results, _ = search_knowledge_cards(
        db,
        [kb.id],
        stage="outline",
        query="escalate promise cost",
        top_k=10,
        current_volume_index=1,
        current_chapter_index=1,
    )

    assert result["merged_card_count"] == 1
    assert len(canonical) == 1
    assert len(merged) == 1
    assert canonical[0].retrievable is True
    assert canonical[0].evidence_count == 2
    assert {ref["source"] for ref in source_refs} == {"guide-a.md", "guide-b.md"}
    assert [item["id"] for item in results] == [canonical[0].card_id]


def test_knowledge_card_indexes_compile_for_mysql_without_text_columns():
    text_columns = {
        "content",
        "summary",
        "tags_json",
        "source_ref_json",
        "source_refs_json",
        "use_when_json",
        "avoid",
        "markdown_path",
    }
    expected = {
        "idx_card_kb_library_status",
        "idx_card_scope_position",
        "idx_card_visibility_window",
        "idx_card_type_priority",
        "idx_card_content_hash",
        "idx_card_title_group",
    }

    index_names = {index.name for index in KnowledgeCard.__table__.indexes}
    assert expected <= index_names
    for index in KnowledgeCard.__table__.indexes:
        if index.name not in expected:
            continue
        assert not ({column.name for column in index.columns} & text_columns)
        ddl = str(CreateIndex(index).compile(dialect=mysql.dialect()))
        assert "CREATE INDEX" in ddl
