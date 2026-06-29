import hashlib
import json
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from novel_deconstructor.config import get_settings
from novel_deconstructor.models import Base, KnowledgeBase, KnowledgeCard, KnowledgeChunk, KnowledgeDocument, RetrievalIndexEvent, WritingMemory
from novel_deconstructor.schemas import RAGPreviewRequest, RAGRebuildRequest
from novel_deconstructor.services.embedding_service import EmbeddingService
from novel_deconstructor.services.rag_scoring import merge_and_rank_candidates
from novel_deconstructor.services.retrieval_service import index_knowledge_card, retrieve_for_writing
from novel_deconstructor.services.vector_store import (
    VectorPoint,
    VectorStore,
    _collection_config_status,
    _qdrant_embedding_status,
    stable_point_id,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    kb = KnowledgeBase(id=1, name="RAG Work", description="", workspace_id="ws_rag")
    db.add(kb)
    db.commit()
    return db, kb


def _add_card(
    db,
    kb,
    card_id: str,
    *,
    library_type: str = "writing_guide",
    card_type: str = "writing_rule",
    content: str = "scope beacon",
    status: str = "approved",
    is_canonical: bool = True,
    retrievable: bool = True,
    scope_level: str = "global",
    volume_index: int | None = None,
    chapter_index: int | None = None,
    reveal_at_volume_index: int | None = None,
    reveal_at_chapter_index: int | None = None,
    priority: int = 0,
) -> KnowledgeCard:
    tags = ["rag", "beacon", library_type]
    card = KnowledgeCard(
        knowledge_base_id=kb.id,
        card_id=card_id,
        library_type=library_type,
        card_type=card_type,
        title=card_id,
        content=content,
        summary=content,
        tags_json=json.dumps(tags),
        source_ref_json="{}",
        source_refs_json="[]",
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
        reveal_at_volume_index=reveal_at_volume_index,
        reveal_at_chapter_index=reveal_at_chapter_index,
        priority=priority,
        evidence_count=1,
        content_fingerprint=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
    db.add(card)
    db.commit()
    return card


def test_fake_embedding_is_deterministic_and_uses_configured_size(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_vector_size", 16)

    service = EmbeddingService()
    first = service.embed_query("rain oath beacon")
    second = service.embed_query("rain oath beacon")

    assert first == second
    assert len(first) == 16


def test_stable_point_id_is_deterministic_uuid():
    first = stable_point_id("card", "WR-INDEX")
    second = stable_point_id("card", "WR-INDEX")

    assert first == second
    assert UUID(first).version == 5
    assert first != stable_point_id("chunk", "WR-INDEX")


def test_vector_store_rejects_wrong_point_dimension(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "qdrant_vector_size", 8)

    store = VectorStore()
    point = VectorPoint(id=stable_point_id("card", "WR-BAD"), vector=[0.0] * 7, payload={})

    with pytest.raises(RuntimeError, match="Vector dimension mismatch"):
        store.upsert_points([point])


def test_qdrant_health_flags_collection_and_embedding_mismatch(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "qdrant_vector_size", 1536)
    monkeypatch.setattr(settings, "qdrant_distance", "Cosine")
    info = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=1024, distance="Distance.COSINE")))
    )

    collection_status = _collection_config_status(info, settings)
    status = _qdrant_embedding_status(
        collection_exists=True,
        collection_status=collection_status,
        embedding_health={"embedding_vector_size": 768},
        settings=settings,
    )

    assert collection_status["collection_vector_size_matches_config"] is False
    assert collection_status["collection_distance_matches_config"] is True
    assert status["embedding_qdrant_size_match"] is False
    assert len(status["warnings"]) == 2


def test_openai_compatible_embedding_batches_and_validates_dimension(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_base_url", "https://embedding.example/v1")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-test")
    monkeypatch.setattr(settings, "embedding_api_key", "test-key")
    monkeypatch.setattr(settings, "embedding_timeout_seconds", 7)
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": [
                    {"index": 1, "embedding": [0.0, 1.0, 0.0]},
                    {"index": 0, "embedding": [1.0, 0.0, 0.0]},
                ]
            }

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": self.timeout})
            return FakeResponse()

    from novel_deconstructor.services import embedding_service

    monkeypatch.setattr(embedding_service.httpx, "Client", FakeClient)

    vectors = EmbeddingService(provider="openai-compatible", vector_size=3).embed_texts(["alpha", "beta"])

    assert vectors == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]
    assert calls[0]["url"] == "https://embedding.example/v1/embeddings"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["json"] == {"model": "text-embedding-test", "input": ["alpha", "beta"]}
    assert calls[0]["timeout"] == 7


def test_embedding_provider_alias_uses_runtime_defaults(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_provider", "doubao")
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "embedding_model", "doubao-embedding-test")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "doubao_base_url", "https://ark.example/api/v3")
    monkeypatch.setattr(settings, "ark_api_key", "ark-key")
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            calls.append({"url": url, "headers": headers, "json": json})
            return FakeResponse()

    from novel_deconstructor.services import embedding_service

    monkeypatch.setattr(embedding_service.httpx, "Client", FakeClient)

    service = EmbeddingService(vector_size=3)
    vector = service.embed_query("alpha")
    health = service.healthcheck()

    assert vector == [1.0, 0.0, 0.0]
    assert calls[0]["url"] == "https://ark.example/api/v3/embeddings"
    assert calls[0]["headers"]["Authorization"] == "Bearer ark-key"
    assert calls[0]["json"]["model"] == "doubao-embedding-test"
    assert health["embedding_configured"] is True
    assert health["embedding_base_url"] == "https://ark.example/api/v3"


def test_openai_compatible_embedding_rejects_dimension_mismatch(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_base_url", "https://embedding.example/v1")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-test")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"index": 0, "embedding": [1.0, 0.0]}]}

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, *args, **kwargs):
            return FakeResponse()

    from novel_deconstructor.services import embedding_service

    monkeypatch.setattr(embedding_service.httpx, "Client", FakeClient)

    with pytest.raises(RuntimeError, match="dimension mismatch"):
        EmbeddingService(provider="openai-compatible", vector_size=3).embed_query("alpha")


def test_retrieve_falls_back_to_keyword_when_qdrant_fails(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "retrieval_mode", "hybrid")
    db, kb = _session()
    _add_card(db, kb, "WR-FALLBACK", content="rain oath beacon pressure")

    from novel_deconstructor.services import retrieval_service

    def boom(*args, **kwargs):
        raise RuntimeError("qdrant offline")

    monkeypatch.setattr(retrieval_service.VectorStore, "search", boom)

    result = retrieve_for_writing(
        db,
        workspace_id=kb.workspace_id,
        knowledge_base_ids=[kb.id],
        query="rain oath beacon",
        phase="draft",
        target_volume_index=1,
        target_chapter_index=1,
        top_k=5,
    )

    assert result["retrieval_debug"]["fallback"].startswith("qdrant_unavailable")
    assert result["retrieval_debug"]["effective_mode"] == "keyword"
    assert "WR-FALLBACK" in {hit["id"] for hit in result["hits"]}


def test_rag_preview_api_falls_back_when_embedding_provider_is_unavailable(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "retrieval_mode", "vector")
    monkeypatch.setattr(settings, "embedding_provider", "openai-compatible")
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "embedding_model", "text-embedding-test")
    db, kb = _session()
    _add_card(db, kb, "WR-PREVIEW", content="rain oath beacon preview")

    from novel_deconstructor.api import rag as rag_api

    result = rag_api.rag_preview(
        RAGPreviewRequest(
            query="rain oath beacon",
            phase="draft",
            knowledge_base_ids=[kb.id],
            target_volume_index=1,
            target_chapter_index=1,
            top_k=5,
        ),
        workspace_id=kb.workspace_id,
        db=db,
    )

    assert result.retrieval_debug.effective_mode == "keyword"
    assert result.retrieval_debug.fallback.startswith("qdrant_unavailable")
    assert "WR-PREVIEW" in {hit["id"] for hit in result.hits}
    assert result.used_knowledge[0].concise_content


def test_index_knowledge_card_only_upserts_canonical_retrievable_active_cards(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_vector_size", 8)
    db, kb = _session()
    good = _add_card(db, kb, "WR-INDEX", content="indexable beacon", priority=25)
    hidden = _add_card(db, kb, "WR-HIDDEN", content="hidden beacon", retrievable=False)
    upserts = []
    deletes = []

    from novel_deconstructor.services import retrieval_service

    monkeypatch.setattr(retrieval_service.VectorStore, "upsert_points", lambda self, points: upserts.extend(points))
    monkeypatch.setattr(retrieval_service.VectorStore, "delete_by_payload", lambda self, filters: deletes.append(filters))

    good_result = index_knowledge_card(db, good)
    hidden_result = index_knowledge_card(db, hidden)

    assert good_result["indexed"] == 1
    assert upserts[0].id == stable_point_id("card", "WR-INDEX")
    assert UUID(upserts[0].id).version == 5
    assert upserts[0].payload["workspace_id"] == "ws_rag"
    assert upserts[0].payload["priority"] == 25
    assert hidden_result["deleted"] is True
    assert len(upserts) == 1
    assert deletes


def test_retrieval_index_event_queue_processes_card_upsert_and_delete(monkeypatch):
    db, kb = _session()
    card = _add_card(db, kb, "WR-QUEUE", content="queued index beacon")
    indexed = []
    deleted = []

    from novel_deconstructor.services import retrieval_index_queue

    def fake_index(db_arg, card_arg):
        indexed.append(card_arg.card_id)
        return {"indexed": 1, "source_type": "card", "card_id": card_arg.card_id}

    def fake_delete(card_arg):
        deleted.append(str(card_arg))
        return {"deleted": True, "source_type": "card", "card_id": str(card_arg)}

    monkeypatch.setattr(retrieval_index_queue, "index_knowledge_card", fake_index)
    monkeypatch.setattr(retrieval_index_queue, "delete_card_vector", fake_delete)

    retrieval_index_queue.enqueue_card_index(db, card, process_now=False)
    retrieval_index_queue.enqueue_card_delete(db, "WR-QUEUE", process_now=False)
    db.commit()

    result = retrieval_index_queue.process_pending_index_events(db, limit=10)
    db.commit()

    events = db.query(RetrievalIndexEvent).order_by(RetrievalIndexEvent.id).all()
    assert result == {"processed": 2, "failed": 0, "done": 2}
    assert [event.status for event in events] == ["done", "done"]
    assert indexed == ["WR-QUEUE"]
    assert deleted == ["WR-QUEUE"]


def test_rag_health_api_reports_vector_store(monkeypatch):
    from novel_deconstructor.api import rag as rag_api

    class FakeVectorStore:
        def healthcheck(self):
            return {
                "qdrant_available": True,
                "collection": "novel_vectors",
                "collection_exists": True,
                "points_count": 12,
                "vector_size": 8,
                "distance": "Cosine",
                "embedding_provider": "fake",
                "embedding_model": "",
                "embedding_base_url": "",
                "embedding_configured": True,
                "embedding_vector_size": 8,
                "embedding_missing": [],
                "embedding_qdrant_size_match": True,
                "collection_vector_size_matches_config": True,
                "collection_distance_matches_config": True,
                "retrieval_mode": "hybrid",
                "warnings": [],
            }

    monkeypatch.setattr(rag_api, "VectorStore", FakeVectorStore)

    response = rag_api.rag_health()

    assert response.qdrant_available is True
    assert response.collection == "novel_vectors"
    assert response.points_count == 12
    assert response.embedding_provider == "fake"
    assert response.embedding_qdrant_size_match is True


def test_rag_rebuild_api_dry_run_and_force_indexes_scope(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "embedding_vector_size", 8)
    db, kb = _session()
    document = KnowledgeDocument(
        id=1,
        knowledge_base_id=kb.id,
        original_filename="guide.md",
        stored_path="guide.md",
        normalized_path="guide.txt",
        file_type="md",
        size_bytes=10,
        file_hash="doc",
        document_title="Guide",
        source_kind="upload",
        knowledge_type="writing_guide",
        source_path="guide.md",
        structure_path="guide.md",
        status="completed",
        chunk_count=1,
    )
    chunk = KnowledgeChunk(
        id="chunk_1",
        knowledge_base_id=kb.id,
        document_id=1,
        chunk_index=1,
        heading="Rule",
        text="rain oath beacon chunk",
        metadata_json="{}",
    )
    memory = WritingMemory(
        id=1,
        knowledge_base_id=kb.id,
        workspace_id=kb.workspace_id,
        memory_type="note",
        title="Memory",
        content="rain oath beacon memory",
        tags_json='["rain"]',
        source_ref_json="{}",
        scope_level="chapter",
        volume_index=1,
        chapter_index=1,
        retrievable=True,
        priority=5,
    )
    _add_card(db, kb, "WR-REBUILD", content="rain oath beacon card", priority=15)
    db.add_all([document, chunk, memory])
    db.commit()
    upserts = []
    deletes = []

    from novel_deconstructor.api import rag as rag_api
    from novel_deconstructor.services import retrieval_service

    monkeypatch.setattr(retrieval_service.VectorStore, "upsert_points", lambda self, points: upserts.extend(points))
    monkeypatch.setattr(retrieval_service.VectorStore, "delete_by_payload", lambda self, filters: deletes.append(filters))

    dry_run = rag_api.rag_rebuild(
        RAGRebuildRequest(knowledge_base_ids=[kb.id], dry_run=True, force=False),
        workspace_id=kb.workspace_id,
        db=db,
    )

    assert dry_run.planned == {"documents": 1, "chunks": 1, "cards": 1, "memories": 1}
    assert dry_run.indexed == {"chunks": 0, "cards": 0, "memories": 0}
    assert not upserts
    assert not deletes

    live = rag_api.rag_rebuild(
        RAGRebuildRequest(knowledge_base_ids=[kb.id], dry_run=False, force=True),
        workspace_id=kb.workspace_id,
        db=db,
    )

    assert live.indexed == {"chunks": 1, "cards": 1, "memories": 1}
    assert {point.payload["source_type"] for point in upserts} == {"chunk", "card", "memory"}
    assert any(item["must"][0]["key"] == "workspace_id" for item in deletes)


def test_retrieve_scope_safe_blocks_future_and_other_volume_cards(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "retrieval_mode", "keyword")
    db, kb = _session()
    _add_card(db, kb, "GUIDE", content="scope beacon guide", scope_level="global")
    _add_card(db, kb, "BOOK", content="scope beacon book", scope_level="book")
    _add_card(
        db,
        kb,
        "CURRENT",
        library_type="worldbuilding",
        card_type="worldbuilding",
        content="scope beacon current chapter",
        scope_level="chapter",
        volume_index=1,
        chapter_index=1,
    )
    _add_card(
        db,
        kb,
        "FUTURE",
        library_type="worldbuilding",
        card_type="worldbuilding",
        content="scope beacon future reveal",
        scope_level="global",
        reveal_at_volume_index=1,
        reveal_at_chapter_index=2,
    )
    _add_card(
        db,
        kb,
        "OTHER-VOLUME",
        library_type="worldbuilding",
        card_type="worldbuilding",
        content="scope beacon other volume",
        scope_level="chapter",
        volume_index=2,
        chapter_index=1,
    )

    result = retrieve_for_writing(
        db,
        workspace_id=kb.workspace_id,
        knowledge_base_ids=[kb.id],
        query="scope beacon",
        phase="draft",
        target_volume_index=1,
        target_chapter_index=1,
        top_k=10,
    )

    ids = {hit["id"] for hit in result["hits"]}
    assert {"GUIDE", "BOOK", "CURRENT"} <= ids
    assert "FUTURE" not in ids
    assert "OTHER-VOLUME" not in ids


def test_hybrid_merge_dedupes_and_records_drop_reasons(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "retrieval_max_per_source", 2)
    monkeypatch.setattr(settings, "retrieval_max_per_card_type", 5)
    debug = {"dropped": []}
    candidates = [
        {"id": "A", "source_type": "card", "card_id": "A", "card_type": "writing_rule", "library_type": "writing_guide", "keyword_score": 4.0, "document_id": 1},
        {"id": "A", "source_type": "card", "card_id": "A", "card_type": "writing_rule", "library_type": "writing_guide", "vector_score": 0.9, "document_id": 1},
        {"id": "B", "source_type": "card", "card_id": "B", "card_type": "writing_rule", "library_type": "writing_guide", "keyword_score": 3.0, "document_id": 1},
        {"id": "C", "source_type": "card", "card_id": "C", "card_type": "writing_rule", "library_type": "writing_guide", "keyword_score": 2.0, "document_id": 1},
    ]

    ranked = merge_and_rank_candidates(candidates, top_k=4, debug=debug)

    assert [item["id"] for item in ranked][:2] == ["A", "B"]
    assert len(ranked) == 2
    assert any(item["reason"] == "duplicate_merged" for item in debug["dropped"])
    assert any(item["reason"] == "source_cap" for item in debug["dropped"])
