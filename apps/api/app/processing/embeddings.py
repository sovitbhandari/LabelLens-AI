"""Embedding providers with dimension compatibility checks."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from functools import lru_cache

import numpy as np
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.models.entities import ChunkEmbedding, DocumentChunk

logger = get_logger(__name__)


class EmbeddingDimensionError(ValueError):
    """Raised when an embedding dimension does not match the configured model."""


class EmbeddingProvider(ABC):
    provider_name: str
    model_id: str
    dimension: int

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        raise NotImplementedError


class SentenceTransformerProvider(EmbeddingProvider):
    def __init__(self, model_id: str, dimension: int):
        self.provider_name = "sentence_transformers"
        self.model_id = model_id
        self.dimension = dimension
        self._model = None

    def _load(self):
        if self._model is None:
            import os

            from sentence_transformers import SentenceTransformer

            # Public models must not inherit a stale/invalid HF hub token from the host env.
            for key in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"):
                if os.environ.get(key):
                    logger.warning("clearing_hf_token_env", key=key)
                    os.environ.pop(key, None)

            logger.info("loading_sentence_transformer", model=self.model_id)
            self._model = SentenceTransformer(self.model_id, token=False)
            actual = int(self._model.get_sentence_embedding_dimension())
            if actual != self.dimension:
                raise EmbeddingDimensionError(
                    f"Model {self.model_id} produces dim={actual}, configured={self.dimension}"
                )
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        model = self._load()
        vectors = model.encode(list(texts), normalize_embeddings=True, show_progress_bar=False)
        arr = np.asarray(vectors, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if arr.shape[1] != self.dimension:
            raise EmbeddingDimensionError(
                f"Unexpected embedding shape {arr.shape}, expected dim={self.dimension}"
            )
        return arr.tolist()


class OpenAIEmbeddingProvider(EmbeddingProvider):
    def __init__(self, model_id: str, dimension: int, api_key: str):
        self.provider_name = "openai"
        self.model_id = model_id
        self.dimension = dimension
        if not api_key:
            raise ValueError("OPENAI_API_KEY required for OpenAI embeddings")
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.model_id, input=list(texts))
        vectors = [item.embedding for item in response.data]
        for vec in vectors:
            if len(vec) != self.dimension:
                raise EmbeddingDimensionError(
                    f"OpenAI embedding dim={len(vec)} != configured {self.dimension}"
                )
        return vectors


@lru_cache
def get_embedding_provider() -> EmbeddingProvider:
    settings = get_settings()
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingProvider(
            settings.embedding_model,
            settings.embedding_dimension,
            settings.openai_api_key,
        )
    return SentenceTransformerProvider(settings.embedding_model, settings.embedding_dimension)


def embed_chunks_for_version(
    db: Session,
    chunks: list[DocumentChunk],
    settings: Settings | None = None,
    provider: EmbeddingProvider | None = None,
    batch_size: int = 32,
) -> int:
    settings = settings or get_settings()
    provider = provider or get_embedding_provider()
    created = 0

    pending = []
    for chunk in chunks:
        exists = (
            db.query(ChunkEmbedding)
            .filter(
                ChunkEmbedding.chunk_id == chunk.id,
                ChunkEmbedding.embedding_model == provider.model_id,
            )
            .first()
        )
        if exists is None:
            pending.append(chunk)

    for i in range(0, len(pending), batch_size):
        batch = pending[i : i + batch_size]
        vectors = provider.embed([c.text_content for c in batch])
        for chunk, vector in zip(batch, vectors, strict=True):
            if len(vector) != provider.dimension:
                raise EmbeddingDimensionError("Batch embedding dimension mismatch")
            db.add(
                ChunkEmbedding(
                    chunk_id=chunk.id,
                    embedding_provider=provider.provider_name,
                    embedding_model=provider.model_id,
                    embedding_dimension=provider.dimension,
                    embedding=vector,
                )
            )
            created += 1
        db.commit()

    logger.info(
        "embeddings_created",
        created=created,
        model=provider.model_id,
        dimension=provider.dimension,
    )
    return created
