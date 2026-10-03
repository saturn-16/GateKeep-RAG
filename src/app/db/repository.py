from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.state import User
from app.audit.hashchain import AuditRecord, make_record
from app.db.models import AuditLog, User as DbUser
from app.core.security import verify_password


def load_user(session: Session, user_id: str) -> User | None:
    record = session.get(DbUser, user_id)
    if record is None:
        return None
    return User(record.id, record.tenant_id, record.password_hash, frozenset(record.roles or []), record.clearance, record.active)


def authenticate_user(session: Session, user_id: str, password: str) -> User | None:
    record = session.get(DbUser, user_id)
    if record is None or not record.active or not verify_password(password, record.password_hash):
        return None
    return User(record.id, record.tenant_id, record.password_hash, frozenset(record.roles or []), record.clearance, record.active)


def append_audit(session: Session, user: User, action: str, details: dict[str, Any]) -> AuditRecord:
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(user.tenant_id))))
    previous = session.scalar(select(AuditLog.row_hash).where(AuditLog.tenant_id == user.tenant_id).order_by(AuditLog.timestamp.desc(), AuditLog.id.desc()).limit(1)) or ""
    record = make_record(str(uuid.uuid4()), user.tenant_id, user.user_id, action, details, previous)
    session.add(AuditLog(id=record.id, tenant_id=record.tenant_id, user_id=record.user_id, action=record.action, details=record.details, timestamp=datetime.fromisoformat(record.timestamp), prev_hash=record.prev_hash, row_hash=record.row_hash))
    session.commit()
    return record


def audit_records(session: Session, tenant_id: str) -> list[AuditLog]:
    return list(session.scalars(select(AuditLog).where(AuditLog.tenant_id == tenant_id).order_by(AuditLog.timestamp, AuditLog.id)))
