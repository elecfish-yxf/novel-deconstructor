from __future__ import annotations

import hashlib
import math
from typing import Any

import httpx

from ..config import get_settings


OPENAI_COMPATIBLE_PROVIDERS = {
    "openai",
    "openai-compatible",
    "compatible",
    "doubao",
    "ark",
    "volcengine",
    "dashscope",
    "qwen",
    "aliyun",
    "siliconflow",
}

PROVIDER_DEFAULT_BASE_URLS = {
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "aliyun": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
}


class EmbeddingService:
    """Embedding facade with fake and OpenAI-compatible providers."""

    def __init__(self, provider: str | None = None, vector_size: int | None = None) -> None:
        settings = get_settings()
        self.provider = (provider or settings.embedding_provider or "fake").strip().lower()
        self.vector_size = max(1, int(vector_size or settings.embedding_vector_size))
        self.model = settings.embedding_model
        self.base_url = _embedding_base_url(self.provider, settings)
        self.api_key = _embedding_api_key(self.provider, settings)
        self.timeout_seconds = settings.embedding_timeout_seconds

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if self.provider == "fake":
            return [_fake_embedding(text or "", self.vector_size) for text in texts]
        if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
            return self._embed_openai_compatible(texts)
        raise NotImplementedError(f"Unsupported embedding provider: {self.provider}")

    def embed_query(self, query: str) -> list[float]:
        return self.embed_texts([query])[0]

    def healthcheck(self) -> dict[str, Any]:
        configured = self.provider == "fake" or bool(self.base_url and self.model)
        missing: list[str] = []
        if self.provider != "fake":
            if not self.base_url:
                missing.append("EMBEDDING_BASE_URL")
            if not self.model:
                missing.append("EMBEDDING_MODEL")
        return {
            "embedding_provider": self.provider,
            "embedding_model": self.model,
            "embedding_base_url": self.base_url,
            "embedding_configured": configured,
            "embedding_vector_size": self.vector_size,
            "embedding_missing": missing,
        }

    def _embed_openai_compatible(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.base_url:
            raise RuntimeError("EMBEDDING_BASE_URL is required for OpenAI-compatible embeddings")
        if not self.model:
            raise RuntimeError("EMBEDDING_MODEL is required for OpenAI-compatible embeddings")
        url = f"{self.base_url.rstrip('/')}/embeddings"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        payload = {"model": self.model, "input": texts}
        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Embedding request failed: {exc}") from exc
        vectors = _parse_openai_embeddings(data)
        if len(vectors) != len(texts):
            raise RuntimeError(f"Embedding response count mismatch: expected {len(texts)}, got {len(vectors)}")
        for vector in vectors:
            if len(vector) != self.vector_size:
                raise RuntimeError(f"Embedding vector dimension mismatch: expected {self.vector_size}, got {len(vector)}")
        return vectors


def _parse_openai_embeddings(data: dict[str, Any]) -> list[list[float]]:
    rows = data.get("data")
    if not isinstance(rows, list):
        raise RuntimeError("Embedding response missing data list")
    ordered = sorted(rows, key=lambda item: int(item.get("index", 0)) if isinstance(item, dict) else 0)
    vectors: list[list[float]] = []
    for item in ordered:
        if not isinstance(item, dict) or not isinstance(item.get("embedding"), list):
            raise RuntimeError("Embedding response item missing embedding")
        vectors.append([float(value) for value in item["embedding"]])
    return vectors


def _embedding_base_url(provider: str, settings: Any) -> str:
    explicit = (settings.embedding_base_url or "").strip()
    if explicit:
        return explicit
    if provider == "openai":
        return settings.openai_base_url
    if provider in {"doubao", "ark", "volcengine"}:
        return settings.doubao_base_url
    return PROVIDER_DEFAULT_BASE_URLS.get(provider, "")


def _embedding_api_key(provider: str, settings: Any) -> str:
    explicit = (settings.embedding_api_key or "").strip()
    if explicit:
        return explicit
    if provider == "openai":
        return settings.openai_api_key
    if provider in {"doubao", "ark", "volcengine"}:
        return settings.ark_api_key or settings.doubao_api_key
    return ""


def _fake_embedding(text: str, vector_size: int) -> list[float]:
    seed = text.encode("utf-8", errors="ignore")
    values: list[float] = []
    counter = 0
    while len(values) < vector_size:
        digest = hashlib.blake2b(seed + counter.to_bytes(4, "big"), digest_size=64).digest()
        counter += 1
        for offset in range(0, len(digest), 4):
            raw = int.from_bytes(digest[offset : offset + 4], "big", signed=False)
            values.append((raw / 0xFFFFFFFF) * 2.0 - 1.0)
            if len(values) >= vector_size:
                break
    norm = math.sqrt(sum(value * value for value in values)) or 1.0
    return [round(value / norm, 8) for value in values]
