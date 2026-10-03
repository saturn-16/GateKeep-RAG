import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

pytest.importorskip("qdrant_client")
pytest.importorskip("sqlalchemy")

from app.config import get_settings
from app.db.models import Chunk, Document
from app.main import app

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(
    os.getenv("RUN_REAL_STACK") != "1"
    or os.getenv("PERSISTENCE_BACKEND") != "postgres"
    or os.getenv("VECTOR_BACKEND") != "qdrant",
    reason="requires live PostgreSQL and Qdrant API backends",
)
def test_tenant_id_safety_and_cross_tenant_tamper_resistance() -> None:
    client = TestClient(app)
    alice_token = client.post("/v1/auth/login", json={"username": "alice", "password": "alice"}).json()["access_token"]
    frank_token = client.post("/v1/auth/login", json={"username": "frank", "password": "frank"}).json()["access_token"]
    alice_headers = {"Authorization": f"Bearer {alice_token}"}
    frank_headers = {"Authorization": f"Bearer {frank_token}"}

    # 1. Tenant A (Alice, acme-corp) ingests a sensitive document
    ingest_resp = client.post(
        "/v1/documents/text",
        headers=alice_headers,
        json={
            "title": "Acme Confidential Strategy 2026",
            "text": "Acme strategic roadmap details quantum encryption deployment.",
            "allowed_roles": ["admin"],
            "sensitivity": "restricted",
        },
    )
    assert ingest_resp.status_code == 200
    doc_a_id = ingest_resp.json()["id"]
    from uuid import UUID
    UUID(doc_a_id)

    # Tenant A can see status and query the document
    status_a = client.get(f"/v1/documents/{doc_a_id}", headers=alice_headers)
    assert status_a.status_code == 200
    assert status_a.json()["status"] == "ready"

    query_a = client.post("/v1/query", headers=alice_headers, json={"question": "quantum encryption deployment"})
    assert query_a.status_code == 200
    assert any(citation["doc_id"] == doc_a_id for citation in query_a.json()["citations"])

    # 2. Tenant B (Frank, globex-inc) attempts cross-tenant inspection and mutation
    # Read status: must receive 404 (no information leakage)
    status_b = client.get(f"/v1/documents/{doc_a_id}", headers=frank_headers)
    assert status_b.status_code == 404

    # Update ACL: must receive 404 (no signal, no effect)
    patch_b = client.patch(
        f"/v1/documents/{doc_a_id}/acl",
        headers=frank_headers,
        json={"allowed_roles": ["admin"], "allowed_users": [], "sensitivity": "internal"},
    )
    assert patch_b.status_code == 404

    # Delete document: must receive 404 (no signal, no effect)
    delete_b = client.delete(f"/v1/documents/{doc_a_id}", headers=frank_headers)
    assert delete_b.status_code == 404

    # Attempt to supply document_id / chunk_id during ingestion to overwrite Tenant A's document
    ingest_b_spoof = client.post(
        "/v1/documents/text",
        headers=frank_headers,
        json={
            "title": "Globex Attempted Overwrite",
            "text": "Malicious content trying to hijack Acme document.",
            "allowed_roles": ["admin"],
            "sensitivity": "restricted",
            "id": doc_a_id,
            "document_id": doc_a_id,
        },
    )
    assert ingest_b_spoof.status_code == 200
    doc_b_id = ingest_b_spoof.json()["id"]
    # Server generates server-side UUID scoped to Tenant B, ignoring client-supplied IDs
    assert doc_b_id != doc_a_id
    UUID(doc_b_id)

    # 3. Verify PostgreSQL and Qdrant state integrity
    engine = create_engine(get_settings().database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with Session(engine) as session:
        doc_b_db = session.get(Document, doc_b_id)
        assert doc_b_db is not None
        assert doc_b_db.tenant_id == "globex-inc"

        doc_a_db = session.get(Document, doc_a_id)
        assert doc_a_db is not None
        assert doc_a_db.tenant_id == "acme-corp"
        assert doc_a_db.title == "Acme Confidential Strategy 2026"
        assert doc_a_db.created_by == "alice"
        assert doc_a_db.status == "ready"

        chunks_a_db = list(session.scalars(select(Chunk).where(Chunk.document_id == doc_a_id)))
        assert len(chunks_a_db) >= 1
        for chunk in chunks_a_db:
            assert chunk.tenant_id == "acme-corp"
            assert chunk.allowed_roles == ["admin"]
            assert chunk.sensitivity == "restricted"

    # Tenant A still retrieves their document intact
    query_a_after = client.post("/v1/query", headers=alice_headers, json={"question": "quantum encryption deployment"})
    assert query_a_after.status_code == 200
    assert any(citation["doc_id"] == doc_a_id for citation in query_a_after.json()["citations"])

    # Tenant B cannot retrieve Tenant A's document under any circumstances
    query_b = client.post("/v1/query", headers=frank_headers, json={"question": "quantum encryption deployment"})
    assert query_b.status_code == 200
    assert all(citation["doc_id"] != doc_a_id for citation in query_b.json()["citations"])
