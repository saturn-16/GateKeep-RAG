"""Counterfactual existence and invariance security test.

Verifies that for unauthorized principals, the presence or absence of restricted documents
in the corpus produces mathematically identical responses, citations, and error behaviors.
"""

import os
import secrets
from uuid import uuid4

from hashlib import sha256

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.api.state import state
from app.config import get_settings
from app.core.permissions import ChunkACL, can_access
from app.core.principal import Principal
from app.core.security import create_access_token
from app.db.models import AuditLog, Chunk, Document, Role, Tenant, User
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
        for t in [tenant_id]:
            vector_store.client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=rest_models.FilterSelector(
                    filter=rest_models.Filter(
                        must=[rest_models.FieldCondition(key="tenant_id", match=rest_models.MatchValue(value=t))]
                    )
                ),
                wait=True,
            )


@pytest.mark.skipif(
    os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres" or os.getenv("VECTOR_BACKEND") != "qdrant",
    reason="requires live PostgreSQL and Qdrant backends",
)
def test_counterfactual_every_principal_invariance() -> None:
    """Verifies counterfactual invariance across multiple principals and cross-tenant boundaries.

    For each principal, removing ONLY the documents they cannot access produces mathematically
    identical answers, citation IDs, citation ordering, and scores within tolerance.
    """
    from qdrant_client.http import models as rest_models

    settings = get_settings()
    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    vector_store = QdrantVectorStore(settings)
    client = TestClient(app)

    t_a = f"tenant-cfa-{uuid4().hex[:8]}"
    t_b = f"tenant-cfb-{uuid4().hex[:8]}"

    users_spec = [
        ("emp_a", t_a, ["employee"], "internal"),
        ("hr_a", t_a, ["hr"], "restricted"),
        ("admin_a", t_a, ["admin"], "restricted"),
        ("emp_b", t_b, ["employee"], "internal"),
        ("admin_b", t_b, ["admin"], "restricted"),
    ]

    docs_spec = [
        ("doc_a_public", t_a, "Public Safety Regulations", ["employee", "hr", "admin"], "public", "General workplace safety regulations and emergency evacuation routes."),
        ("doc_a_eng", t_a, "Engineering Architecture", ["engineering", "admin"], "internal", "Engineering microservice architecture and deployment pipelines."),
        ("doc_a_salary", t_a, "Executive Salary Bands", ["hr", "admin"], "restricted", "Executive salary band benchmarks and equity compensation structures."),
        ("doc_b_handbook", t_b, "Client Onboarding Handbook", ["employee", "admin"], "internal", "Tenant B proprietary client onboarding procedures and compliance handbook."),
    ]

    tokens: dict[str, str] = {}
    with Session(engine) as session:
        session.merge(Tenant(id=t_a, name=f"CF Tenant A {t_a}"))
        session.merge(Tenant(id=t_b, name=f"CF Tenant B {t_b}"))
        session.flush()
        for t in [t_a, t_b]:
            for r in ["admin", "hr", "engineering", "employee"]:
                session.add(Role(tenant_id=t, name=r, implies=[]))
        session.flush()

        for u_id, t_id, roles, clearance in users_spec:
            session.merge(User(id=u_id, tenant_id=t_id, password_hash="!", clearance=clearance, active=True, roles=roles))
            tokens[u_id] = create_access_token({"sub": u_id, "tenant_id": t_id, "roles": roles}, settings.jwt_secret, 3600)
        session.commit()

    def _seed_all_docs() -> None:
        points = []
        with Session(engine) as session:
            for d_slug, t_id, title, roles, sens, text_val in docs_spec:
                d_id = f"{t_id}:{d_slug}"
                session.merge(Document(id=d_id, tenant_id=t_id, title=title, status="ready", source="test", created_by="admin"))
                session.flush()
                c_id = f"{d_id}:0"
                session.merge(Chunk(
                    id=c_id,
                    tenant_id=t_id,
                    document_id=d_id,
                    text=text_val,
                    content_hash=sha256(text_val.encode()).hexdigest(),
                    allowed_roles=sorted(roles),
                    allowed_users=[],
                    sensitivity=sens,
                ))
                points.append(VectorChunk(ChunkACL(t_id, c_id, frozenset(roles), sensitivity=sens), text_val, doc_id=d_id))
            session.commit()
        vector_store.upsert(points)

    _seed_all_docs()

    queries = [
        {"question": "workplace safety evacuation routes"},
        {"question": "engineering architecture deployment pipelines"},
        {"question": "salary band benchmarks compensation"},
        {"question": "client onboarding procedures compliance"},
    ]

    try:
        for u_id, t_id, roles, clearance in users_spec:
            principal = Principal(u_id, t_id, frozenset(roles), clearance)

            # Baseline: Run all queries in World 1 (all documents present)
            w1_responses = {}
            for q in queries:
                # Security Invariant 2: Qdrant pre-filter must never leak unauthorized chunks
                raw_chunks = state.retriever.search(principal, q["question"], top_k=5)
                for rc in raw_chunks:
                    assert can_access(principal, rc.acl), f"Qdrant pre-filter leaked chunk {rc.acl.chunk_id} to unauthorized principal {u_id}"

                resp = client.post("/v1/query", headers={"Authorization": f"Bearer {tokens[u_id]}"}, json=q)
                assert resp.status_code == 200
                w1_responses[q["question"]] = resp.json()

            # Security Invariant 3: Zero post-retrieval security alerts triggered during normal query
            with Session(engine) as s:
                alerts = s.scalars(select(AuditLog).where(AuditLog.tenant_id == t_id, AuditLog.action == "security_alert")).all()
                assert len(alerts) == 0, f"Post-retrieval security alert triggered for {u_id}: {alerts}"

            # Identify documents this principal CANNOT access
            unauthorized_doc_ids = []
            for d_slug, doc_tenant, _, doc_roles, sens, _ in docs_spec:
                full_doc_id = f"{doc_tenant}:{d_slug}"
                acl = ChunkACL(doc_tenant, f"{full_doc_id}:0", frozenset(doc_roles), sensitivity=sens)
                if not can_access(principal, acl):
                    unauthorized_doc_ids.append(full_doc_id)

            # World 2 (True Removal of unauthorized documents for this principal)
            with Session(engine) as session:
                for doc_id in unauthorized_doc_ids:
                    session.execute(text("DELETE FROM chunks WHERE document_id=:did"), {"did": doc_id})
                    session.execute(text("DELETE FROM documents WHERE id=:did"), {"did": doc_id})
                session.commit()

            for doc_id in unauthorized_doc_ids:
                vector_store.client.delete(
                    collection_name=settings.qdrant_collection,
                    points_selector=rest_models.FilterSelector(
                        filter=rest_models.Filter(
                            must=[rest_models.FieldCondition(key="doc_id", match=rest_models.MatchValue(value=doc_id))]
                        )
                    ),
                    wait=True,
                )

            # Run queries in World 2 and assert mathematical invariance
            for q in queries:
                resp_w2 = client.post("/v1/query", headers={"Authorization": f"Bearer {tokens[u_id]}"}, json=q)
                assert resp_w2.status_code == 200
                w2_data = resp_w2.json()
                w1_data = w1_responses[q["question"]]

                # Identical answer
                assert w2_data["answer"] == w1_data["answer"]
                # Identical citation IDs and order
                w1_ids = [c["chunk_id"] for c in w1_data["citations"]]
                w2_ids = [c["chunk_id"] for c in w2_data["citations"]]
                assert w2_ids == w1_ids, f"Mismatch for user {u_id} on query {q['question']}: {w2_ids} != {w1_ids}"
                # Scores within 1e-4 tolerance
                for c1, c2 in zip(w1_data["citations"], w2_data["citations"]):
                    assert abs(float(c1["score"]) - float(c2["score"])) < 1e-4
                # Response shape
                assert set(w2_data.keys()) == set(w1_data.keys()) == {"answer", "citations", "audit_id"}

            # Restore full corpus for the next principal
            _seed_all_docs()

    finally:
        # Full cleanup of test tenants
        with Session(engine) as session:
            for t in [t_a, t_b]:
                session.execute(text("DELETE FROM chunks WHERE tenant_id=:t"), {"t": t})
                session.execute(text("DELETE FROM documents WHERE tenant_id=:t"), {"t": t})
                session.execute(text("DELETE FROM users WHERE tenant_id=:t"), {"t": t})
                session.execute(text("DELETE FROM roles WHERE tenant_id=:t"), {"t": t})
            session.commit()
        for t in [t_a, t_b]:
            vector_store.client.delete(
                collection_name=settings.qdrant_collection,
                points_selector=rest_models.FilterSelector(
                    filter=rest_models.Filter(
                        must=[rest_models.FieldCondition(key="tenant_id", match=rest_models.MatchValue(value=t))]
                    )
                ),
                wait=True,
            )


