from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import get_settings
from .embedding_service import EmbeddingService


@dataclass
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict[str, Any]


@dataclass
class VectorHit:
    id: str
    score: float
    payload: dict[str, Any]


class VectorStore:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.collection = self.settings.qdrant_collection
        self._client_cache = None
        self._models_cache = None

    def ensure_collection(self) -> None:
        client, models = self._client_and_models()
        if self._collection_exists(client):
            return
        client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=int(self.settings.qdrant_vector_size),
                distance=_qdrant_distance(models, self.settings.qdrant_distance),
            ),
        )

    def upsert_points(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        self.ensure_collection()
        client, models = self._client_and_models()
        client.upsert(
            collection_name=self.collection,
            points=[models.PointStruct(id=point.id, vector=point.vector, payload=point.payload) for point in points],
        )

    def delete_by_payload(self, filters: dict[str, Any]) -> None:
        client, models = self._client_and_models()
        qdrant_filter = _to_qdrant_filter(models, filters)
        client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(filter=qdrant_filter),
        )

    def search(self, vector: list[float], filters: dict[str, Any], limit: int) -> list[VectorHit]:
        client, models = self._client_and_models()
        qdrant_filter = _to_qdrant_filter(models, filters)
        try:
            raw_hits = client.search(
                collection_name=self.collection,
                query_vector=vector,
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
            )
        except AttributeError:
            response = client.query_points(
                collection_name=self.collection,
                query=vector,
                query_filter=qdrant_filter,
                limit=limit,
                with_payload=True,
            )
            raw_hits = getattr(response, "points", response)
        return [
            VectorHit(
                id=str(getattr(hit, "id", "")),
                score=float(getattr(hit, "score", 0.0) or 0.0),
                payload=dict(getattr(hit, "payload", {}) or {}),
            )
            for hit in raw_hits
        ]

    def healthcheck(self) -> dict[str, Any]:
        settings = get_settings()
        embedding_health = EmbeddingService().healthcheck()
        try:
            client, _models = self._client_and_models()
            collections = client.get_collections()
            names = [item.name for item in getattr(collections, "collections", [])]
            exists = self.collection in names
            points_count = 0
            vector_size = int(settings.qdrant_vector_size)
            distance = settings.qdrant_distance
            if exists:
                info = client.get_collection(self.collection)
                points_count = int(getattr(info, "points_count", 0) or 0)
                vectors_config = getattr(getattr(info, "config", None), "params", None)
                vectors = getattr(vectors_config, "vectors", None)
                if getattr(vectors, "size", None):
                    vector_size = int(vectors.size)
                if getattr(vectors, "distance", None):
                    distance = str(vectors.distance).split(".")[-1].title()
            return {
                "ok": True,
                "qdrant_available": True,
                "collection": self.collection,
                "collection_exists": exists,
                "points_count": points_count,
                "vector_size": vector_size,
                "distance": distance,
                **embedding_health,
                "retrieval_mode": settings.retrieval_mode,
            }
        except Exception as exc:  # noqa: BLE001 - health reports the integration boundary.
            return {
                "ok": False,
                "qdrant_available": False,
                "collection": self.collection,
                "collection_exists": False,
                "points_count": 0,
                "vector_size": int(settings.qdrant_vector_size),
                "distance": settings.qdrant_distance,
                **embedding_health,
                "retrieval_mode": settings.retrieval_mode,
                "error": str(exc),
            }

    def _client_and_models(self):
        if self._client_cache is not None and self._models_cache is not None:
            return self._client_cache, self._models_cache
        try:
            from qdrant_client import QdrantClient
            from qdrant_client.http import models
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("qdrant-client is not installed") from exc
        kwargs: dict[str, Any] = {"url": self.settings.qdrant_url, "timeout": self.settings.embedding_timeout_seconds}
        if self.settings.qdrant_api_key:
            kwargs["api_key"] = self.settings.qdrant_api_key
        self._client_cache = QdrantClient(**kwargs)
        self._models_cache = models
        return self._client_cache, self._models_cache

    def _collection_exists(self, client) -> bool:
        try:
            return bool(client.collection_exists(self.collection))
        except AttributeError:
            try:
                client.get_collection(self.collection)
                return True
            except Exception:  # noqa: BLE001
                return False


def stable_point_id(source_type: str, source_id: str | int) -> str:
    return f"{source_type}:{source_id}"


def _qdrant_distance(models, distance: str):
    mapping = {
        "cosine": "COSINE",
        "dot": "DOT",
        "euclid": "EUCLID",
        "manhattan": "MANHATTAN",
    }
    enum_name = mapping.get((distance or "Cosine").strip().lower(), "COSINE")
    return getattr(models.Distance, enum_name)


def _to_qdrant_filter(models, filters: dict[str, Any]):
    return models.Filter(
        must=[_condition(models, item) for item in filters.get("must", [])],
        should=[_condition(models, item) for item in filters.get("should", [])] or None,
        must_not=[_condition(models, item) for item in filters.get("must_not", [])] or None,
    )


def _condition(models, item: dict[str, Any]):
    if "must" in item or "should" in item or "must_not" in item:
        return _to_qdrant_filter(models, item)
    key = item["key"]
    if "any" in item:
        return models.FieldCondition(key=key, match=models.MatchAny(any=item["any"]))
    return models.FieldCondition(key=key, match=models.MatchValue(value=item.get("match")))
