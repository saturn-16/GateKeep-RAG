from __future__ import annotations

from sqlalchemy.orm import Session

from app.api.state import ServiceState, User
from app.audit.hashchain import AuditRecord
from app.db.repository import append_audit


def write_audit(state: ServiceState, user: User, action: str, details: dict[str, object], db: Session | None = None) -> AuditRecord:
    if db is not None:
        return append_audit(db, user, action, details)
    return state.audit(user, action, details)
