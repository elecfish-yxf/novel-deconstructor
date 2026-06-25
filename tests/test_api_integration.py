"""
API Integration Tests for Novel Deconstructor.
Tests core writing/knowledge/outline endpoints against a running backend.

Usage:
    # Start backend first, then:
    pytest tests/test_api_integration.py -v
    # Or specify a different backend:
    TEST_API_BASE=http://your-host:8000 pytest tests/test_api_integration.py -v
"""
import pytest
import httpx


class TestSystemEndpoints:
    """Test system/config endpoints."""

    def test_public_config(self, client: httpx.Client):
        resp = client.get("/api/config/public")
        assert resp.status_code == 200
        data = resp.json()
        assert "deepseek_model" in data
        assert "privacy_note" in data

    def test_health_check(self, client: httpx.Client):
        resp = client.get("/api/config/public")
        assert resp.status_code == 200


class TestKnowledgeBaseEndpoints:
    """Test knowledge base CRUD."""

    def test_list_knowledge_bases(self, client: httpx.Client, auth_headers: dict[str, str]):
        resp = client.get("/api/knowledge-bases", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    def test_create_knowledge_base(self, client: httpx.Client, auth_headers: dict[str, str]):
        resp = client.post("/api/knowledge-bases", json={
            "name": "Test KB Create",
            "description": "Test",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test KB Create"
        assert "id" in data

    def test_get_knowledge_base(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(f"/api/knowledge-bases/{test_kb_id}", headers=auth_headers)
        assert resp.status_code == 200

    def test_list_documents_empty(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(f"/api/knowledge-bases/{test_kb_id}/documents", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestWritingMemoryEndpoints:
    """Test writing memory CRUD."""

    def test_list_memories(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(f"/api/writing/memories?knowledge_base_id={test_kb_id}", headers=auth_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_create_and_delete_memory(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        # Create
        resp = client.post("/api/writing/memories", json={
            "knowledge_base_id": test_kb_id,
            "memory_type": "note",
            "title": "Test Memory",
            "content": "Test content for integration test.",
            "scope_level": "chapter",
            "volume_index": 1,
            "chapter_index": 1,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Memory"
        memory_id = data["id"]

        # Delete
        resp = client.delete(f"/api/writing/memories/{memory_id}", headers=auth_headers)
        assert resp.status_code == 200


class TestKnowledgeCardEndpoints:
    """Test knowledge card endpoints."""

    def test_list_cards(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(f"/api/writing/works/{test_kb_id}/knowledge/cards", headers=auth_headers)
        assert resp.status_code == 200
        cards = resp.json()
        assert isinstance(cards, list)

    def test_filter_cards_by_library_type(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(
            f"/api/writing/works/{test_kb_id}/knowledge/cards?library_type=writing_guide",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_filter_cards_by_status(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(
            f"/api/writing/works/{test_kb_id}/knowledge/cards?status=approved",
            headers=auth_headers,
        )
        assert resp.status_code == 200

    def test_merge_stats(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(f"/api/writing/works/{test_kb_id}/knowledge/merge/stats", headers=auth_headers)
        assert resp.status_code == 200
        stats = resp.json()
        assert "raw_card_count" in stats


class TestRAGSearch:
    """Test RAG retrieval."""

    def test_rag_search(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.post(f"/api/writing/works/{test_kb_id}/rag/search", json={
            "stage": "draft",
            "query": "test query for knowledge retrieval",
            "top_k": 5,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "retrieval_debug" in data


class TestOutlineEndpoints:
    """Test outline CRUD."""

    def test_list_outlines(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.get(f"/api/writing/works/{test_kb_id}/outlines", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "knowledge_base_id" in data

    def test_create_and_delete_outline(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        # Create
        resp = client.post(f"/api/writing/works/{test_kb_id}/outlines", json={
            "knowledge_base_id": test_kb_id,
            "level": "chapter",
            "seq": 1,
            "volume_index": 1,
            "chapter_index": 1,
            "title": "Test Chapter Outline",
            "content": "This is a test outline node.",
            "source": "manual",
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test Chapter Outline"
        node_id = data["id"]

        # Update
        resp = client.patch(f"/api/writing/works/{test_kb_id}/outlines/{node_id}", json={
            "title": "Updated Outline",
        }, headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["title"] == "Updated Outline"

        # Delete
        resp = client.delete(f"/api/writing/works/{test_kb_id}/outlines/{node_id}", headers=auth_headers)
        assert resp.status_code == 200

    def test_outline_sync_from_cards(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.post(f"/api/writing/works/{test_kb_id}/outlines/sync-from-cards", headers=auth_headers)
        assert resp.status_code == 200


class TestWritingAgentEndpoints:
    """Test writing agent generation endpoints (dry-run only)."""

    def test_generate_outline_dry_run(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        resp = client.post(f"/api/writing/works/{test_kb_id}/agent/outline", json={
            "knowledge_base_ids": [test_kb_id],
            "task": "生成第一章提纲",
            "mode": "fast",
            "knowledge_mode": "reference",
            "dry_run": True,
            "current_volume_index": 1,
            "current_chapter_index": 1,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "content" in data

    def test_generate_outline_strict_mode_no_cards(self, client: httpx.Client, auth_headers: dict[str, str], test_kb_id: int):
        """Strict mode should return diagnostic info when no cards match."""
        resp = client.post(f"/api/writing/works/{test_kb_id}/agent/outline", json={
            "knowledge_base_ids": [test_kb_id],
            "task": "xyzzy_nonexistent_query_12345",
            "mode": "fast",
            "knowledge_mode": "strict",
            "dry_run": True,
            "current_volume_index": 1,
            "current_chapter_index": 1,
        }, headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        # In strict mode with no matching cards, should return diagnostic content
        assert "content" in data
        # Should include debug info
        assert data.get("retrieval_debug") is not None
