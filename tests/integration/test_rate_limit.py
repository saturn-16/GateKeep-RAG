import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

pytest.importorskip("sqlalchemy")

from app.api.state import state
from app.config import get_settings
from app.core.security import hash_password
from app.db.models import AuditLog, Tenant, User
from app.main import app

pytestmark = pytest.mark.real_stack


@pytest.mark.skipif(os.getenv("RUN_REAL_STACK") != "1" or os.getenv("PERSISTENCE_BACKEND") != "postgres", reason="requires live PostgreSQL API backend")
def test_login_lockout_and_query_rate_limit_are_audited() -> None:
    settings = get_settings()
    tenant_id = f"rate-{uuid4()}"
    user_id = f"rate-user-{uuid4()}"
    engine = create_engine(settings.database_url.replace("postgresql://", "postgresql+psycopg://", 1))
    with Session(engine) as session:
        session.add(Tenant(id=tenant_id, name=tenant_id))
        session.add(User(id=user_id, tenant_id=tenant_id, password_hash=hash_password("correct"), clearance="internal", active=True, roles=["admin"]))
        session.commit()

    client = TestClient(app)
    for _ in range(settings.login_max_attempts):
        assert client.post("/v1/auth/login", json={"username": user_id, "password": "wrong"}).status_code == 401
    assert client.post("/v1/auth/login", json={"username": user_id, "password": "correct"}).status_code == 429
    with Session(engine) as session:
        assert session.scalar(select(AuditLog.id).where(AuditLog.user_id == user_id, AuditLog.action == "login_failed")) is not None

    query_user_id = f"query-rate-user-{uuid4()}"
    with Session(engine) as session:
        session.add(User(id=query_user_id, tenant_id=tenant_id, password_hash=hash_password("query-password"), clearance="internal", active=True, roles=["admin"]))
        session.commit()
    query_token = client.post("/v1/auth/login", json={"username": query_user_id, "password": "query-password"}).json()["access_token"]
    settings.rate_limit_per_minute = 1
    try:
        headers = {"Authorization": f"Bearer {query_token}"}
        assert client.post("/v1/query", headers=headers, json={"question": "no result"}).status_code == 200
        assert client.post("/v1/query", headers=headers, json={"question": "no result"}).status_code == 429
    finally:
        settings.rate_limit_per_minute = 60
