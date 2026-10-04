"""Threshold independence security test.

Verifies that security invariants (pre-filtering, canary isolation, counterfactual invariance)
do not depend on the similarity score threshold. When threshold is set to 0.0, every query
returns the top-k of the user's permitted documents, but unauthorized documents and canary
tokens are never leaked, and counterfactual invariance remains strictly preserved.
"""

import os
import secrets
from hashlib import sha256
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.state import state
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
def test_threshold_independence_counterfactual_and_canary() -> None:
    """Sets similarity score threshold to 0.0 and asserts counterfactual invariance and zero canary leaks."""
    settings = get_settings()
    original_thresh = settings.retrieval_score_threshold
    settings.retrieval_score_threshold = 0.0  # Zero threshold: every query returns top-k permitted chunks

    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    vector_store = QdrantVectorStore(settings)
    client = TestClient(app)

    tenant_id = f"tenant-ti-{uuid4().hex[:8]}"
    dave_id = f"dave-{uuid4().hex[:6]}"
    bob_id = f"bob-{uuid4().hex[:6]}"

    doc_perm_id = f"{tenant_id}:handbook"
    chunk_perm_id = f"{doc_perm_id}:0"

    doc_rest_id = f"{tenant_id}:restricted-salaries"
    chunk_rest_id = f"{doc_rest_id}:0"

    canary = f"CANARY_{secrets.token_hex(16).upper()}_RESTRICTED_TOKEN"
    restricted_text = f"Executive compensation benchmark executive salary band is 350000 base pay. {canary}"
    permitted_text = "Employee handbook office guidelines: standard core hours are ten am to four pm."

    tokens = {}
    try:
        # Setup tenant, roles, users
        with Session(engine) as session:
            session.merge(Tenant(id=tenant_id, name=f"TI Test Tenant {tenant_id}"))
            session.flush()
            session.add(Role(tenant_id=tenant_id, name="admin", implies=[]))
            session.add(Role(tenant_id=tenant_id, name="hr", implies=[]))
            session.add(Role(tenant_id=tenant_id, name="employee", implies=[]))
            session.flush()

            session.merge(User(id=dave_id, tenant_id=tenant_id, password_hash="!", clearance="internal", active=True, roles=["employee"]))
            session.merge(User(id=bob_id, tenant_id=tenant_id, password_hash="!", clearance="restricted", active=True, roles=["hr"]))
            session.flush()

            # Seed permitted handbook
            session.merge(Document(id=doc_perm_id, tenant_id=tenant_id, title="Employee Handbook", status="ready", source="test", created_by="admin"))
            session.flush()
            session.merge(Chunk(
                id=chunk_perm_id,
                tenant_id=tenant_id,
                document_id=doc_perm_id,
                text=permitted_text,
                content_hash=sha256(permitted_text.encode()).hexdigest(),
                allowed_roles=["employee", "hr", "admin"],
                allowed_users=[],
                sensitivity="internal",
            ))
            session.commit()

        vector_store.upsert([
            VectorChunk(ChunkACL(tenant_id, chunk_perm_id, frozenset({"employee", "hr", "admin"}), sensitivity="internal"), permitted_text, doc_id=doc_perm_id),
        ])

        tokens[dave_id] = create_access_token({"sub": dave_id, "tenant_id": tenant_id, "roles": ["employee"]}, settings.jwt_secret, 3600)
        tokens[bob_id] = create_access_token({"sub": bob_id, "tenant_id": tenant_id, "roles": ["hr"]}, settings.jwt_secret, 3600)

        queries = [
            {"question": "compensation benchmark executive salary band"},           # Target restricted query
            {"question": "What are the standard office hours?"},                     # Direct permitted query
            {"question": "company workplace guidelines and code of conduct"},       # Broad company query
        ]

        # -------------------------------------------------------------------
        # World 1 (Baseline): Restricted document is NOT present in the system
        # -------------------------------------------------------------------
        w1_responses = {}
        for q in queries:
            resp = client.post("/v1/query", headers={"Authorization": f"Bearer {tokens[dave_id]}"}, json=q)
            assert resp.status_code == 200
            data = resp.json()
            # With threshold 0.0, every query returns top-k of permitted set
            assert len(data["citations"]) > 0, "Threshold 0.0 must return top-k from permitted set"
            assert all(c["chunk_id"] == chunk_perm_id for c in data["citations"])
            assert canary not in str(data)
            w1_responses[q["question"]] = data

        # -------------------------------------------------------------------
        # World 2: Restricted document IS ingested with 128-bit Canary token
        # -------------------------------------------------------------------
        with Session(engine) as session:
            session.merge(Document(id=doc_rest_id, tenant_id=tenant_id, title="Restricted Salaries", status="ready", source="test", created_by="admin"))
            session.flush()
            session.merge(Chunk(
                id=chunk_rest_id,
                tenant_id=tenant_id,
                document_id=doc_rest_id,
                text=restricted_text,
                content_hash=sha256(restricted_text.encode()).hexdigest(),
                allowed_roles=["hr", "admin"],
                allowed_users=[],
                sensitivity="restricted",
            ))
            session.commit()

        vector_store.upsert([
            VectorChunk(ChunkACL(tenant_id, chunk_rest_id, frozenset({"hr", "admin"}), sensitivity="restricted"), restricted_text, doc_id=doc_rest_id),
        ])

        # Assert unauthorized Dave under World 2 with threshold = 0.0
        for q in queries:
            resp_w2 = client.post("/v1/query", headers={"Authorization": f"Bearer {tokens[dave_id]}"}, json=q)
            assert resp_w2.status_code == 200
            w2_data = resp_w2.json()
            w1_data = w1_responses[q["question"]]

            # Canary isolation: canary must NEVER leak into answer or citations
            assert canary not in w2_data["answer"], "Canary leaked into answer text at threshold 0.0"
            assert canary not in str(w2_data["citations"]), "Canary leaked into citations at threshold 0.0"
            assert all(c["chunk_id"] != chunk_rest_id for c in w2_data["citations"]), "Restricted chunk returned to unauthorized user"

            # Counterfactual invariance: exactly identical answer, citations, ordering, and scores
            assert w2_data["answer"] == w1_data["answer"]
            assert [c["chunk_id"] for c in w2_data["citations"]] == [c["chunk_id"] for c in w1_data["citations"]]
            for c1, c2 in zip(w1_data["citations"], w2_data["citations"]):
                assert abs(float(c1["score"]) - float(c2["score"])) < 1e-4
            assert set(w2_data.keys()) == set(w1_data.keys()) == {"answer", "citations", "audit_id"}

        # Authorized HR Bob DOES retrieve the restricted chunk and canary
        bob_resp = client.post("/v1/query", headers={"Authorization": f"Bearer {tokens[bob_id]}"}, json={"question": "executive salary band"})
        assert bob_resp.status_code == 200
        bob_citations = [c["chunk_id"] for c in bob_resp.json()["citations"]]
        assert chunk_rest_id in bob_citations

    finally:
        # Revert threshold
        settings.retrieval_score_threshold = original_thresh

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
