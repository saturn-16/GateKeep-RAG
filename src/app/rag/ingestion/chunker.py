import hashlib
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextChunk:
    chunk_id: str
    text: str
    page: int | None
    content_hash: str


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[TextChunk]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("overlap must be non-negative and smaller than chunk_size")
    words = text.split()
    chunks: list[TextChunk] = []
    step = chunk_size - overlap
    for index in range(0, len(words), step):
        value = " ".join(words[index:index + chunk_size]).strip()
        if not value:
            continue
        digest = hashlib.sha256(value.encode()).hexdigest()
        chunks.append(TextChunk(f"chunk-{len(chunks)}", value, None, digest))
        if index + chunk_size >= len(words):
            break
    return chunks
