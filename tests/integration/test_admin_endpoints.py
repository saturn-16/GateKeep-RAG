import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("sqlalchemy")

from app.main import app

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres", reason="requires live PostgreSQL API backend")
def test_tenant_admin_create_assign_and_revoke_role() -> None:
    client = TestClient(app)
    admin_token = client.post("/v1/auth/login", json={"username": "alice", "password": "alice"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {admin_token}"}
    user_id = f"managed-{uuid4()}"
    created = client.post("/v1/admin/users", headers=headers, json={"user_id": user_id, "password": "managed-pass", "roles": ["viewer"]})
    assert created.status_code == 200
    assert client.post(f"/v1/admin/users/{user_id}/roles", headers=headers, json={"role": "employee"}).status_code == 200
    managed_token = client.post("/v1/auth/login", json={"username": user_id, "password": "managed-pass"}).json()["access_token"]
    assert "employee" in client.get("/v1/me", headers={"Authorization": f"Bearer {managed_token}"}).json()["roles"]
    assert client.delete(f"/v1/admin/users/{user_id}/roles/employee", headers=headers).status_code == 200
    assert "employee" not in client.get("/v1/me", headers={"Authorization": f"Bearer {managed_token}"}).json()["roles"]


def test_non_admin_cannot_manage_users() -> None:
    client = TestClient(app)
    token = client.post("/v1/auth/login", json={"username": "dave", "password": "dave"}).json()["access_token"]
    response = client.post("/v1/admin/users", headers={"Authorization": f"Bearer {token}"}, json={"user_id": "blocked", "password": "blocked-pass", "roles": []})
    assert response.status_code == 403
