import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

pytest.importorskip("qdrant_client")
pytest.importorskip("sqlalchemy")

from app.api.state import state
from app.config import get_settings
from app.db.models import Chunk, Document
from app.main import app

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres" or os.getenv("VECTOR_BACKEND") != "qdrant", reason="requires live PostgreSQL and Qdrant API backends")
def test_acl_narrowing_delete_and_partial_failure_safety() -> None:
    client = TestClient(app)
    alice = client.post("/v1/auth/login", json={"username": "alice", "password": "alice"}).json()["access_token"]
    dave = client.post("/v1/auth/login", json={"username": "dave", "password": "dave"}).json()["access_token"]
    admin_headers = {"Authorization": f"Bearer {alice}"}
    user_headers = {"Authorization": f"Bearer {dave}"}
    salary_id = "acme-corp:salary-bands-2026"

    narrowed = client.patch(f"/v1/documents/{salary_id}/acl", headers=admin_headers, json={"allowed_roles": ["admin"], "allowed_users": [], "sensitivity": "restricted"})
    assert narrowed.status_code == 200
    next_query = client.post("/v1/query", headers=user_headers, json={"question": "salary band engineers"})
    assert next_query.status_code == 200
    assert all(salary_id not in citation["doc_id"] for citation in next_query.json()["citations"])

    engine = create_engine(get_settings().database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with Session(engine) as session:
        before = session.scalar(select(Chunk.allowed_roles).where(Chunk.document_id == salary_id))
        original_update = state.vector_store.update_document_acl
        state.vector_store.update_document_acl = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("simulated qdrant failure"))
        failed = client.patch(f"/v1/documents/{salary_id}/acl", headers=admin_headers, json={"allowed_roles": ["employee"], "allowed_users": [], "sensitivity": "internal"})
        state.vector_store.update_document_acl = original_update
        assert failed.status_code == 503
        after = session.scalar(select(Chunk.allowed_roles).where(Chunk.document_id == salary_id))
        document = session.get(Document, salary_id)
        assert after == before
        assert document is not None and document.repair_required is True

    delete_id = "acme-corp:legal-nda-templates"
    deleted = client.delete(f"/v1/documents/{delete_id}", headers=admin_headers)
    assert deleted.status_code == 200
    assert client.get(f"/v1/documents/{delete_id}", headers=admin_headers).status_code == 404
