from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.models import Base, KnowledgeBase, KnowledgeChunk, KnowledgeDocument
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
        source_path="final_reports/overall_summary.md",
        structure_path="final_reports/overall_summary.md",
    )

    chunks = split_knowledge_text("# 总汇总报告\n\n## 可复用写作规律\n\n- 先建立期待缺口，再释放情绪。", document)

    assert chunks
    assert chunks[0].heading == "可复用写作规律"
    assert "期待缺口" in chunks[0].text
    assert "final_reports/overall_summary.md" in chunks[0].metadata_json


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
    assert hits[0]["structure_path"] == "knowledge_base/writing_rules.md"
    assert "期待缺口" in hits[0]["text"]
