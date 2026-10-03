import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

pytest.importorskip("qdrant_client")
pytest.importorskip("sqlalchemy")

from app.main import app
from app.config import get_settings
from app.core.security import hash_password
from app.db.models import Tenant, User

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres", reason="requires live PostgreSQL API backend")
def test_fifty_concurrent_queries_preserve_audit_chain() -> None:
    settings = get_settings()
    tenant_id = f"concurrency-{uuid4()}"
    user_id = f"concurrent-admin-{uuid4()}"
    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with Session(engine) as session:
        session.add(Tenant(id=tenant_id, name=tenant_id))
        session.add(User(id=user_id, tenant_id=tenant_id, password_hash=hash_password("concurrency-password"), clearance="restricted", active=True, roles=["admin"]))
        session.commit()
    client = TestClient(app)
    login = client.post("/v1/auth/login", json={"username": user_id, "password": "concurrency-password"})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    def query(_: int) -> int:
        return client.post("/v1/query", headers=headers, json={"question": "question with no results"}).status_code

    with ThreadPoolExecutor(max_workers=10) as executor:
        statuses = list(executor.map(query, range(50)))
    assert statuses == [200] * 50
    verified = client.get("/v1/audit/verify", headers=headers)
    assert verified.status_code == 200
    assert verified.json()["valid"] is True