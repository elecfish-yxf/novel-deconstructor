from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ..config import get_settings
from .embedding_service import EmbeddingService

POINT_ID_NAMESPACE = "novel-deconstructor:qdrant-point"


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
            status = _collection_config_status(client.get_collection(self.collection), self.settings)
            errors = _collection_config_errors(status, self.settings)
            if errors:
                raise RuntimeError("Qdrant collection config mismatch: " + " ".join(errors))
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
        self._validate_point_vectors(points)
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
            collection_status = _collection_config_status(None, settings)
            if exists:
                info = client.get_collection(self.collection)
                points_count = int(getattr(info, "points_count", 0) or 0)
                collection_status = _collection_config_status(info, settings)
                if collection_status["collection_vector_size"] is not None:
                    vector_size = int(collection_status["collection_vector_size"])
                if collection_status["collection_distance"]:
                    distance = str(collection_status["collection_distance"])
            qdrant_embedding_status = _qdrant_embedding_status(
                collection_exists=exists,
                collection_status=collection_status,
                embedding_health=embedding_health,
                settings=settings,
            )
            return {
                "ok": True,
                "qdrant_available": True,
                "collection": self.collection,
                "collection_exists": exists,
                "points_count": points_count,
                "vector_size": vector_size,
                "distance": distance,
                **embedding_health,
                **qdrant_embedding_status,
                "retrieval_mode": settings.retrieval_mode,
            }
        except Exception as exc:  # noqa: BLE001 - health reports the integration boundary.
            qdrant_embedding_status = _qdrant_embedding_status(
                collection_exists=False,
                collection_status=_collection_config_status(None, settings),
                embedding_health=embedding_health,
                settings=settings,
            )
            return {
                "ok": False,
                "qdrant_available": False,
                "collection": self.collection,
                "collection_exists": False,
                "points_count": 0,
                "vector_size": int(settings.qdrant_vector_size),
                "distance": settings.qdrant_distance,
                **embedding_health,
                **qdrant_embedding_status,
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

    def _validate_point_vectors(self, points: list[VectorPoint]) -> None:
        expected_size = int(self.settings.qdrant_vector_size)
        for point in points:
            actual_size = len(point.vector)
            if actual_size != expected_size:
                raise RuntimeError(
                    f"Vector dimension mismatch for point {point.id}: "
                    f"expected QDRANT_VECTOR_SIZE={expected_size}, got {actual_size}"
                )


def stable_point_id(source_type: str, source_id: str | int) -> str:
    raw = f"{POINT_ID_NAMESPACE}:{source_type}:{source_id}"
    return str(uuid5(NAMESPACE_URL, raw))


def _qdrant_distance(models, distance: str):
    mapping = {
        "cosine": "COSINE",
        "dot": "DOT",
        "euclid": "EUCLID",
        "euclidean": "EUCLID",
        "manhattan": "MANHATTAN",
    }
    enum_name = mapping.get((distance or "Cosine").strip().lower(), "COSINE")
    return getattr(models.Distance, enum_name)


def _collection_config_status(info: Any | None, settings: Any) -> dict[str, Any]:
    vector_size, distance = _collection_vector_config(info)
    expected_distance = _normalize_distance_name(settings.qdrant_distance)
    return {
        "collection_vector_size": vector_size,
        "collection_distance": distance,
        "collection_vector_size_matches_config": (
            None if vector_size is None else int(vector_size) == int(settings.qdrant_vector_size)
        ),
        "collection_distance_matches_config": (
            None if distance is None else _distance_key(distance) == _distance_key(expected_distance)
        ),
    }


def _collection_vector_config(info: Any | None) -> tuple[int | None, str | None]:
    if info is None:
        return None, None
    vectors_config = getattr(getattr(info, "config", None), "params", None)
    vectors = _get_value(vectors_config, "vectors")
    if isinstance(vectors, dict) and vectors:
        vectors = next(iter(vectors.values()))
    size = _get_value(vectors, "size")
    distance = _get_value(vectors, "distance")
    return (int(size) if size is not None else None, _normalize_distance_name(distance) if distance else None)


def _qdrant_embedding_status(
    *,
    collection_exists: bool,
    collection_status: dict[str, Any],
    embedding_health: dict[str, Any],
    settings: Any,
) -> dict[str, Any]:
    embedding_vector_size = embedding_health.get("embedding_vector_size")
    embedding_qdrant_size_match = (
        None if embedding_vector_size is None else int(embedding_vector_size) == int(settings.qdrant_vector_size)
    )
    warnings = []
    if embedding_qdrant_size_match is False:
        warnings.append(
            f"EMBEDDING_VECTOR_SIZE={embedding_vector_size} does not match "
            f"QDRANT_VECTOR_SIZE={settings.qdrant_vector_size}."
        )
    if collection_exists:
        warnings.extend(_collection_config_errors(collection_status, settings))
    return {
        "embedding_qdrant_size_match": embedding_qdrant_size_match,
        "collection_vector_size_matches_config": collection_status.get("collection_vector_size_matches_config"),
        "collection_distance_matches_config": collection_status.get("collection_distance_matches_config"),
        "warnings": warnings,
    }


def _collection_config_errors(status: dict[str, Any], settings: Any) -> list[str]:
    errors = []
    if status.get("collection_vector_size_matches_config") is False:
        errors.append(
            f"collection vector size {status.get('collection_vector_size')} does not match "
            f"QDRANT_VECTOR_SIZE={settings.qdrant_vector_size}; use a new QDRANT_COLLECTION or recreate it, then rebuild."
        )
    if status.get("collection_distance_matches_config") is False:
        errors.append(
            f"collection distance {status.get('collection_distance')} does not match "
            f"QDRANT_DISTANCE={_normalize_distance_name(settings.qdrant_distance)}; use a new QDRANT_COLLECTION "
            "or recreate it, then rebuild."
        )
    return errors


def _normalize_distance_name(distance: Any) -> str:
    raw = str(distance or "Cosine").split(".")[-1].strip()
    mapping = {
        "cosine": "Cosine",
        "dot": "Dot",
        "euclid": "Euclid",
        "euclidean": "Euclid",
        "manhattan": "Manhattan",
    }
    return mapping.get(raw.lower(), raw.title())


def _distance_key(distance: Any) -> str:
    return _normalize_distance_name(distance).lower()


def _get_value(source: Any, key: str) -> Any:
    if source is None:
        return None
    if isinstance(source, dict):
        return source.get(key)
    return getattr(source, key, None)


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
