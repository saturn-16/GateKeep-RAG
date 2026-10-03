import os
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

pytest.importorskip("qdrant_client")
pytest.importorskip("sqlalchemy")

from app.api.state import state
from app.config import get_settings
from app.core.permissions import ChunkACL
from app.db.models import Chunk, Document
from app.main import app
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres" or os.getenv("VECTOR_BACKEND") != "qdrant", reason="requires live PostgreSQL and Qdrant API backends")
def test_processing_and_failed_documents_are_not_retrievable() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    client = TestClient(app)
    token = client.post("/v1/auth/login", json={"username": "dave", "password": "dave"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    for status in ("processing", "failed"):
        document_id = f"status-{status}-{uuid4()}"
        chunk_id = f"{document_id}:0"
        with Session(engine) as session:
            session.add(Document(id=document_id, tenant_id="acme-corp", title="Salary status test", status=status, source="test", created_by="dave"))
            session.flush()
            session.add(Chunk(id=chunk_id, tenant_id="acme-corp", document_id=document_id, text="salary status secret", content_hash=sha256(document_id.encode()).hexdigest(), allowed_roles=["employee"], allowed_users=[], sensitivity="internal"))
            session.commit()
        state.vector_store.upsert([VectorChunk(ChunkACL("acme-corp", chunk_id, frozenset({"employee"}), sensitivity="internal"), "salary status secret", 1.0, document_id, status)])
        response = client.post("/v1/query", headers=headers, json={"question": "salary status secret"})
        assert response.status_code == 200
        assert all(item["doc_id"] != document_id for item in response.json()["citations"])
