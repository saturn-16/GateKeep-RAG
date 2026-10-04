"""Counterfactual existence and invariance security test.

Verifies that for unauthorized principals, the presence or absence of restricted documents
in the corpus produces mathematically identical responses, citations, and error behaviors.
"""

import os
import secrets
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

    # Setup tenant, roles, users, and permitted internal document
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

        # Seed ordinary internal document (permitted for employee Dave and HR Bob)
        internal_doc_id = f"{tenant_id}:handbook"
        session.merge(Document(id=internal_doc_id, tenant_id=tenant_id, title="Employee Handbook", status="ready", source="test", created_by="admin"))
        session.flush()
        session.merge(Chunk(
            id=f"{internal_doc_id}:0",
            tenant_id=tenant_id,
            document_id=internal_doc_id,
            text="Employee standard guidelines and office hours: core hours are ten am to four pm.",
            content_hash="h" * 64,
            allowed_roles=["employee", "hr", "admin"],
            allowed_users=[],
            sensitivity="internal",
        ))
        session.commit()

    vector_store.upsert([
        VectorChunk(ChunkACL(tenant_id, f"{internal_doc_id}:0", frozenset({"employee", "hr", "admin"}), sensitivity="internal"), "Employee standard guidelines and office hours: core hours are ten am to four pm.", doc_id=internal_doc_id),
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

    permitted_query = {"question": "What are the core employee office hours?"}
    restricted_query = {"question": "compensation benchmark executive salary band"}

    # -----------------------------------------------------------------------
    # World 1 (TRUE REMOVAL / Baseline): Restricted document NEVER created
    # -----------------------------------------------------------------------
    # 1. Permitted query: Dave DOES receive citations from permitted handbook
    dave_w1_perm = client.post("/v1/query", headers={"Authorization": f"Bearer {dave_token}"}, json=permitted_query)
    assert dave_w1_perm.status_code == 200
    dave_w1_perm_data = dave_w1_perm.json()
    assert len(dave_w1_perm_data["citations"]) > 0, "Unauthorized user must receive citations for permitted query"
    assert dave_w1_perm_data["citations"][0]["chunk_id"] == f"{internal_doc_id}:0"
    assert set(dave_w1_perm_data.keys()) == {"answer", "citations", "audit_id"}

    # 2. Restricted query: Dave receives standard refusal and []
    dave_w1_rest = client.post("/v1/query", headers={"Authorization": f"Bearer {dave_token}"}, json=restricted_query)
    assert dave_w1_rest.status_code == 200
    dave_w1_rest_data = dave_w1_rest.json()
    assert dave_w1_rest_data["citations"] == []

    # Bob also receives [] because restricted doc does not exist yet
    bob_w1_rest = client.post("/v1/query", headers={"Authorization": f"Bearer {bob_token}"}, json=restricted_query)
    assert bob_w1_rest.json()["citations"] == []

    # -----------------------------------------------------------------------
    # World 2: Restricted document IS ingested into PostgreSQL and Qdrant
    # -----------------------------------------------------------------------
    canary = f"CANARY_{secrets.token_hex(16).upper()}_RESTRICTED"
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
        # 1. Permitted query under World 2:
        # Dave MUST receive identical answer, identical citations (ID and order), scores within tolerance, and identical shape
        dave_w2_perm = client.post("/v1/query", headers={"Authorization": f"Bearer {dave_token}"}, json=permitted_query)
        assert dave_w2_perm.status_code == 200
        dave_w2_perm_data = dave_w2_perm.json()

        assert dave_w2_perm_data["answer"] == dave_w1_perm_data["answer"]
        w1_chunk_ids = [c["chunk_id"] for c in dave_w1_perm_data["citations"]]
        w2_chunk_ids = [c["chunk_id"] for c in dave_w2_perm_data["citations"]]
        assert w1_chunk_ids == w2_chunk_ids == [f"{internal_doc_id}:0"]

        w1_score = dave_w1_perm_data["citations"][0]["score"]
        w2_score = dave_w2_perm_data["citations"][0]["score"]
        assert abs(w1_score - w2_score) < 1e-4, f"Score difference exceeded tolerance: {w1_score} vs {w2_score}"
        assert set(dave_w2_perm_data.keys()) == set(dave_w1_perm_data.keys()) == {"answer", "citations", "audit_id"}

        # 2. Restricted query under World 2:
        dave_w2_rest = client.post("/v1/query", headers={"Authorization": f"Bearer {dave_token}"}, json=restricted_query)
        assert dave_w2_rest.status_code == 200
        dave_w2_rest_data = dave_w2_rest.json()

        assert dave_w2_rest_data["citations"] == dave_w1_rest_data["citations"] == []
        assert dave_w2_rest_data["answer"] == dave_w1_rest_data["answer"]
        assert set(dave_w2_rest_data.keys()) == {"answer", "citations", "audit_id"}
        assert canary not in str(dave_w2_rest_data)

        # 3. Authorized Bob query under World 2: Bob DOES retrieve the restricted chunk
        bob_w2_rest = client.post("/v1/query", headers={"Authorization": f"Bearer {bob_token}"}, json=restricted_query)
        assert bob_w2_rest.status_code == 200
        bob_retrieved_ids = [c["chunk_id"] for c in bob_w2_rest.json()["citations"]]
        assert chunk_id in bob_retrieved_ids

        # -------------------------------------------------------------------
        # World 3: TRUE REMOVAL - delete restricted doc/chunk from DB & Qdrant
        # -------------------------------------------------------------------
        with Session(engine) as session:
            session.execute(text("DELETE FROM chunks WHERE id=:cid"), {"cid": chunk_id})
            session.execute(text("DELETE FROM documents WHERE id=:did"), {"did": doc_id})
            session.commit()

        from qdrant_client.http import models as rest_models
        vector_store.client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=rest_models.FilterSelector(
                filter=rest_models.Filter(
                    must=[rest_models.FieldCondition(key="chunk_id", match=rest_models.MatchValue(value=chunk_id))]
                )
            ),
            wait=True,
        )

        # After TRUE removal, Bob receives [] and Dave maintains identical permitted results
        bob_w3_rest = client.post("/v1/query", headers={"Authorization": f"Bearer {bob_token}"}, json=restricted_query)
        assert bob_w3_rest.json()["citations"] == []

        dave_w3_perm = client.post("/v1/query", headers={"Authorization": f"Bearer {dave_token}"}, json=permitted_query)
        assert [c["chunk_id"] for c in dave_w3_perm.json()["citations"]] == [f"{internal_doc_id}:0"]

    finally:
        # Full tenant cleanup
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

