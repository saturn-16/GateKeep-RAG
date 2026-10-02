"""Live integration checks for Qdrant and PostgreSQL.

Run with Docker services and RUN_REAL_STACK=1 after `alembic upgrade head`.
"""

import os
from datetime import datetime, timezone

import pytest
pytest.importorskip("qdrant_client")
pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text

from app.config import get_settings
from app.core.permissions import ChunkACL
from app.core.principal import Principal
from app.db.models import AuditLog, Base
from app.rag.vectorstore.qdrant_store import QdrantVectorStore
from app.rag.vectorstore.tenant_scoped_retriever import TenantScopedRetriever, VectorChunk

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(os.getenv("RUN_REAL_STACK") != "1", reason="requires live Docker Qdrant and PostgreSQL")
def test_real_qdrant_and_postgres_isolation() -> None:
    settings = get_settings()
    store = QdrantVectorStore(settings)
    chunks = [
        VectorChunk(ChunkACL("acme", "real-acme", frozenset({"employee"}), sensitivity="internal"), "shared salary policy", doc_id="acme-doc"),
        VectorChunk(ChunkACL("globex", "real-globex", frozenset({"employee"}), sensitivity="internal"), "shared salary policy", doc_id="globex-doc"),
    ]
    store.upsert(chunks)
    retriever = TenantScopedRetriever(backend=store)
    result = retriever.search(Principal("dave", "acme", frozenset({"employee"}), "internal"), "shared salary policy")
    assert [item.acl.tenant_id for item in result] == ["acme"]

    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with engine.begin() as connection:
        assert connection.execute(text("SELECT to_regclass('public.audit_logs')")).scalar() == "audit_logs"
        connection.execute(text("INSERT INTO audit_logs (id, tenant_id, user_id, action, details, timestamp, prev_hash, row_hash) VALUES (:id, :tenant, :user, 'query', '{}'::json, :timestamp, '', 'integration-hash')"), {"id": "integration-real-stack", "tenant": "acme", "user": "dave", "timestamp": datetime.now(timezone.utc)})
        with pytest.raises(Exception):
            connection.execute(text("UPDATE audit_logs SET action='tampered' WHERE id='integration-real-stack'"))
