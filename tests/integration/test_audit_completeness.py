import os
from collections import Counter
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

pytest.importorskip("qdrant_client")
pytest.importorskip("sqlalchemy")

from app.api.state import state
from app.config import get_settings
from app.core.security import hash_password
from app.db.models import AuditLog, Tenant, User
from app.main import app

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres" or os.getenv("VECTOR_BACKEND") != "qdrant", reason="requires live PostgreSQL and Qdrant API backends")
def test_audit_completeness_for_all_required_actions() -> None:
    settings = get_settings()
    tenant_id = f"audit-complete-{uuid4()}"
    user_id = f"audit-admin-{uuid4()}"
    password = f"fixture-{uuid4().hex}"
    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with Session(engine) as session:
        session.add(Tenant(id=tenant_id, name=tenant_id))
        session.flush()
        session.add(User(id=user_id, tenant_id=tenant_id, password_hash=hash_password(password), clearance="restricted", active=True, roles=["admin"]))
        session.commit()

    client = TestClient(app)
    original_attempts = settings.login_max_attempts
    settings.login_max_attempts = 2
    try:
        login = client.post("/v1/auth/login", json={"username": user_id, "password": password})
        assert login.status_code == 200
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        assert client.post("/v1/auth/login", json={"username": user_id, "password": "wrong"}).status_code == 401
        assert client.post("/v1/auth/login", json={"username": user_id, "password": password}).status_code == 429
        ingested = client.post("/v1/documents/text", headers=headers, json={"title": "Audit document", "text": "audit completeness content", "allowed_roles": ["admin"], "sensitivity": "internal"})
        assert ingested.status_code == 200
        document_id = ingested.json()["id"]
        assert client.post("/v1/query", headers=headers, json={"question": "audit completeness"}).status_code == 200
        assert client.patch(f"/v1/documents/{document_id}/acl", headers=headers, json={"allowed_roles": ["admin"], "allowed_users": [], "sensitivity": "internal"}).status_code == 200
        assert client.delete(f"/v1/documents/{document_id}", headers=headers).status_code == 200
        managed_id = f"managed-{uuid4()}"
        assert client.post("/v1/admin/users", headers=headers, json={"user_id": managed_id, "password": "fixture-password", "roles": []}).status_code == 200
        assert client.post(f"/v1/admin/users/{managed_id}/roles", headers=headers, json={"role": "viewer"}).status_code == 200
        assert client.delete(f"/v1/admin/users/{managed_id}/roles/viewer", headers=headers).status_code == 200
        verified = client.get("/v1/audit/verify", headers=headers)
        assert verified.status_code == 200
        assert verified.json()["valid"] is True
    finally:
        settings.login_max_attempts = original_attempts

    with Session(engine) as session:
        actions = Counter(session.scalars(select(AuditLog.action).where(AuditLog.tenant_id == tenant_id)).all())
    assert actions["login"] == 1
    assert actions["login_failed"] == 1
    assert actions["lockout"] == 1
    assert actions["ingest"] == 1
    assert actions["query"] == 1
    assert actions["acl_update"] == 1
    assert actions["delete"] == 1
    assert actions["role_assign"] == 1
    assert actions["role_revoke"] == 1
