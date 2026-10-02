from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.permissions import ChunkACL
from app.db.models import Chunk, Document
from app.rag.ingestion.chunker import chunk_text
from app.rag.vectorstore.qdrant_store import QdrantVectorStore
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk


def ingest_text(session: Session, vector_store: QdrantVectorStore, tenant_id: str, user_id: str, title: str, text: str, allowed_roles: set[str], sensitivity: str) -> str:
    document = Document(id=str(uuid4()), tenant_id=tenant_id, title=title, status="processing", source=title, created_by=user_id)
    session.add(document)
    session.commit()
    try:
        chunks = chunk_text(text)
        vector_chunks: list[VectorChunk] = []
        for item in chunks:
            chunk_id = f"{document.id}:{item.chunk_id}"
            acl = ChunkACL(tenant_id, chunk_id, frozenset(allowed_roles), sensitivity=sensitivity)
            session.add(Chunk(id=chunk_id, tenant_id=tenant_id, document_id=document.id, text=item.text, content_hash=item.content_hash, allowed_roles=sorted(allowed_roles), allowed_users=[], sensitivity=sensitivity, page=item.page))
            vector_chunks.append(VectorChunk(acl, item.text, 0.0, document.id))
        vector_store.upsert(vector_chunks)
        document.status = "ready"
        session.commit()
    except Exception as exc:
        session.rollback()
        document.status = "failed"
        document.error = str(exc)
        session.commit()
        raise
    return document.id
