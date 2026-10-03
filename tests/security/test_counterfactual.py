"""Counterfactual existence and invariance security test.

Verifies that for unauthorized principals, the presence or absence of restricted documents
in the corpus produces mathematically identical responses, citations, and error behaviors.
"""

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.permissions import ChunkACL
from app.core.security import create_access_token
from app.db.models import Chunk, Document, Role, Tenant, User
from app.main import app
from app.rag.vectorstore.qdrant_store import QdrantVectorStore
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(
    os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres" or os.getenv("VECTOR_BACKEND") != "qdrant",
    reason="requires live PostgreSQL and Qdrant backends",
)
def test_counterfactual_restricted_document_invariance() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    vector_store = QdrantVectorStore(settings)
    client = TestClient(app)

    tenant_id = f"tenant-cf-{uuid4().hex[:8]}"
    dave_id = f"dave-{uuid4().hex[:6]}"
    bob_id = f"bob-{uuid4().hex[:6]}"
    doc_id = f"{tenant_id}:salary-restricted"
    chunk_id = f"{doc_id}:chunk-0"

    # Setup tenant, roles, users, and public/internal documents
    with Session(engine) as session:
        session.merge(Tenant(id=tenant_id, name=f"CF Test Tenant {tenant_id}"))
        session.flush()
        session.add(Role(tenant_id=tenant_id, name="admin", implies=[]))
        session.add(Role(tenant_id=tenant_id, name="hr", implies=[]))
        session.add(Role(tenant_id=tenant_id, name="employee", implies=[]))
        session.flush()

        # Dave is employee (internal clearance, no HR/admin role)
        session.merge(User(id=dave_id, tenant_id=tenant_id, password_hash="!", clearance="internal", active=True, roles=["employee"]))
        # Bob is HR (restricted clearance, hr role)
        session.merge(User(id=bob_id, tenant_id=tenant_id, password_hash="!", clearance="restricted", active=True, roles=["hr"]))
        session.flush()

        # Seed ordinary internal document
        internal_doc_id = f"{tenant_id}:handbook"
        session.merge(Document(id=internal_doc_id, tenant_id=tenant_id, title="Employee Handbook", status="ready", source="test", created_by="admin"))
        session.flush()
        session.merge(Chunk(
            id=f"{internal_doc_id}:0",
            tenant_id=tenant_id,
            document_id=internal_doc_id,
            text="Employee standard guidelines and office hours.",
            content_hash="h" * 64,
            allowed_roles=["employee", "hr", "admin"],
            allowed_users=[],
            sensitivity="internal",
        ))
        session.commit()

    vector_store.upsert([
        VectorChunk(ChunkACL(tenant_id, f"{internal_doc_id}:0", frozenset({"employee", "hr", "admin"}), sensitivity="internal"), "Employee standard guidelines and office hours.", doc_id=internal_doc_id),
    ])

    dave_token = create_access_token(
        {"sub": dave_id, "tenant_id": tenant_id, "roles": ["employee"]},
        settings.jwt_secret,
        3600,
    )
    bob_token = create_access_token(
        {"sub": bob_id, "tenant_id": tenant_id, "roles": ["hr"]},
        settings.jwt_secret,
        3600,
    )

    query_payload = {"question": "compensation benchmark executive salary band"}

    # -----------------------------------------------------------------------
    # World 1: Restricted document is NOT present in the system at all
    # -----------------------------------------------------------------------
    dave_world1 = client.post("/v1/query", headers={"Authorization": f"Bearer {dave_token}"}, json=query_payload)
    bob_world1 = client.post("/v1/query", headers={"Authorization": f"Bearer {bob_token}"}, json=query_payload)

    assert dave_world1.status_code == 200
    assert bob_world1.status_code == 200
    dave_world1_data = dave_world1.json()
    bob_world1_data = bob_world1.json()

    assert dave_world1_data["citations"] == []
    assert bob_world1_data["citations"] == []

    # -----------------------------------------------------------------------
    # World 2: Restricted document IS present with restricted ACLs and Canary
    # -----------------------------------------------------------------------
    canary = f"CANARY_{uuid4().hex[:12]}_SECRET"
    restricted_text = f"Executive compensation benchmark executive salary band is 350000 base pay. {canary}"
    with Session(engine) as session:
        session.merge(Document(id=doc_id, tenant_id=tenant_id, title="Restricted Salaries", status="ready", source="test", created_by="admin"))
        session.flush()
        session.merge(Chunk(
            id=chunk_id,
            tenant_id=tenant_id,
            document_id=doc_id,
            text=restricted_text,
            content_hash="r" * 64,
            allowed_roles=["hr", "admin"],
            allowed_users=[],
            sensitivity="restricted",
        ))
        session.commit()

    vector_store.upsert([
        VectorChunk(ChunkACL(tenant_id, chunk_id, frozenset({"hr", "admin"}), sensitivity="restricted"), restricted_text, doc_id=doc_id),
    ])

    try:
        dave_world2 = client.post("/v1/query", headers={"Authorization": f"Bearer {dave_token}"}, json=query_payload)
        bob_world2 = client.post("/v1/query", headers={"Authorization": f"Bearer {bob_token}"}, json=query_payload)

        assert dave_world2.status_code == 200
        assert bob_world2.status_code == 200
        dave_world2_data = dave_world2.json()
        bob_world2_data = bob_world2.json()

        # Authorized HR Bob retrieves the restricted chunk in World 2
        bob_retrieved_chunk_ids = [c["chunk_id"] for c in bob_world2_data["citations"]]
        assert chunk_id in bob_retrieved_chunk_ids

        # COUNTERFACTUAL INVARIANCE ASSERTION:
        # For unauthorized Dave, World 1 and World 2 MUST BE IDENTICAL in shape, citations, and answer
        assert dave_world2_data["citations"] == dave_world1_data["citations"] == []
        assert dave_world2_data["answer"] == dave_world1_data["answer"]
        assert canary not in str(dave_world2_data)

    finally:
        # Cleanup
        with Session(engine) as session:
            session.execute(text("DELETE FROM chunks WHERE tenant_id=:t"), {"t": tenant_id})
            session.execute(text("DELETE FROM documents WHERE tenant_id=:t"), {"t": tenant_id})
            session.execute(text("DELETE FROM users WHERE tenant_id=:t"), {"t": tenant_id})
            session.execute(text("DELETE FROM roles WHERE tenant_id=:t"), {"t": tenant_id})
            session.commit()
        from qdrant_client.http import models as rest_models
        vector_store.client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=rest_models.FilterSelector(
                filter=rest_models.Filter(
                    must=[rest_models.FieldCondition(key="tenant_id", match=rest_models.MatchValue(value=tenant_id))]
                )
            ),
            wait=True,
        )
