from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.api.knowledge import bulk_delete_documents
from novel_deconstructor.models import Base, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
from novel_deconstructor.schemas import KnowledgeDocumentBulkDeleteRequest
from novel_deconstructor.services.knowledge_base import search_knowledge, split_knowledge_text


def test_split_knowledge_text_preserves_heading():
    document = KnowledgeDocument(
        id=1,
        knowledge_base_id=1,
        original_filename="overall_summary.md",
        file_type="md",
        size_bytes=100,
        file_hash="abc",
        document_title="总汇总报告",
        source_kind="deconstruction_job",
        knowledge_type="writing_guide",
        source_path="final_reports/overall_summary.md",
        structure_path="final_reports/overall_summary.md",
    )

    chunks = split_knowledge_text("# 总汇总报告\n\n## 可复用写作规律\n\n- 先建立期待缺口，再释放情绪。", document)

    assert chunks
    assert chunks[0].heading == "可复用写作规律"
    assert "期待缺口" in chunks[0].text
    assert "final_reports/overall_summary.md" in chunks[0].metadata_json
    assert "writing_guide" in chunks[0].metadata_json


def test_search_knowledge_returns_source_metadata():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    kb = KnowledgeBase(id=1, name="拆书知识库", description="")
    document = KnowledgeDocument(
        id=1,
        knowledge_base_id=1,
        original_filename="knowledge_base/writing_rules.md",
        stored_path="writing_rules.md",
        normalized_path="normalized.txt",
        file_type="md",
        size_bytes=100,
        file_hash="abc",
        document_title="写作规则",
        source_kind="deconstruction_job",
        knowledge_type="writing_guide",
        source_path="knowledge_base/writing_rules.md",
        structure_path="knowledge_base/writing_rules.md",
        status="completed",
        chunk_count=1,
    )
    chunk = KnowledgeChunk(
        id="chunk_1",
        knowledge_base_id=1,
        document_id=1,
        chunk_index=1,
        heading="可复用写作规律",
        text="先建立期待缺口，再用行动释放情绪。",
        metadata_json="{}",
    )
    db.add_all([kb, document, chunk])
    db.commit()

    hits = search_knowledge(db, [1], "期待缺口", 3)

    assert len(hits) == 1
    assert hits[0]["citation_id"] == "资料1"
    assert hits[0]["knowledge_type"] == "writing_guide"
    assert hits[0]["structure_path"] == "knowledge_base/writing_rules.md"
    assert "期待缺口" in hits[0]["text"]


def test_bulk_delete_documents_scopes_to_work_and_type(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    guide_dir = tmp_path / "guide"
    world_dir = tmp_path / "world"
    other_dir = tmp_path / "other"
    for folder in [guide_dir, world_dir, other_dir]:
        folder.mkdir()
        (folder / "source.md").write_text("content", encoding="utf-8")

    db.add_all(
        [
            KnowledgeBase(id=1, name="作品 1", description="", workspace_id="ws_a"),
            KnowledgeBase(id=2, name="作品 2", description="", workspace_id="ws_a"),
            KnowledgeDocument(
                id=1,
                knowledge_base_id=1,
                original_filename="guide.md",
                stored_path=str(guide_dir / "source.md"),
                normalized_path=str(guide_dir / "normalized.txt"),
                file_type="md",
                size_bytes=10,
                file_hash="guide",
                document_title="写作技巧",
                source_kind="upload",
                knowledge_type="writing_guide",
                source_path="guide.md",
                structure_path="guide.md",
                status="completed",
            ),
            KnowledgeDocument(
                id=2,
                knowledge_base_id=1,
                original_filename="world.md",
                stored_path=str(world_dir / "source.md"),
                normalized_path=str(world_dir / "normalized.txt"),
                file_type="md",
                size_bytes=10,
                file_hash="world",
                document_title="世界观",
                source_kind="upload",
                knowledge_type="worldbuilding",
                source_path="world.md",
                structure_path="world.md",
                status="completed",
            ),
            KnowledgeDocument(
                id=3,
                knowledge_base_id=2,
                original_filename="other.md",
                stored_path=str(other_dir / "source.md"),
                normalized_path=str(other_dir / "normalized.txt"),
                file_type="md",
                size_bytes=10,
                file_hash="other",
                document_title="其他作品",
                source_kind="upload",
                knowledge_type="writing_guide",
                source_path="other.md",
                structure_path="other.md",
                status="completed",
            ),
        ]
    )
    db.commit()
    deleted_vectors = []

    from novel_deconstructor.api import knowledge as knowledge_api

    monkeypatch.setattr(
        knowledge_api,
        "delete_document_vectors",
        lambda document: deleted_vectors.append(document.id) or {"deleted": True},
    )

    result = bulk_delete_documents(
        1,
        KnowledgeDocumentBulkDeleteRequest(knowledge_type="writing_guide", delete_all=True),
        workspace_id="ws_a",
        db=db,
    )

    assert result.deleted == 1
    assert {document.id for document in db.query(KnowledgeDocument).order_by(KnowledgeDocument.id).all()} == {2, 3}
    assert deleted_vectors == [1]
    assert not guide_dir.exists()
    assert world_dir.exists()
    assert other_dir.exists()
