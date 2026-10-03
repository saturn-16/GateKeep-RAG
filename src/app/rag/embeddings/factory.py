from __future__ import annotations

from typing import Protocol

from app.config import Settings
from app.rag.embeddings.hash import HashEmbeddingProvider
from app.rag.embeddings.sentence_transformer import SentenceTransformerEmbeddingProvider


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]:
        ...


def get_embedding_provider(settings: Settings) -> EmbeddingProvider:
    if settings.embedding_provider == "hash":
        return HashEmbeddingProvider(settings.qdrant_vector_size)
    return SentenceTransformerEmbeddingProvider(getattr(settings, "embedding_model_name", "all-MiniLM-L6-v2"))
