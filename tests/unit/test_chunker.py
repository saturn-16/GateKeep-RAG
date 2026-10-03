import pytest

from app.rag.ingestion.chunker import chunk_text


def test_chunker_is_deterministic_and_overlapping() -> None:
    chunks = chunk_text("one two three four five six", chunk_size=4, overlap=1)
    assert [chunk.text for chunk in chunks] == ["one two three four", "four five six"]
    assert chunks[0].content_hash == chunks[0].content_hash


def test_chunker_rejects_invalid_overlap() -> None:
    with pytest.raises(ValueError):
        chunk_text("text", chunk_size=2, overlap=2)
