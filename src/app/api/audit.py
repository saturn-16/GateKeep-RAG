from __future__ import annotations

import csv
import io
import json
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.api.dependencies import current_user
from app.api.runtime import get_runtime_db
from app.api.state import User, state
from app.audit.hashchain import AuditRecord, verify_chain
from app.audit.service import write_audit
from app.db.repository import audit_records

router = APIRouter(prefix="/v1/audit", tags=["audit"])


def _record_dict(record: object) -> dict[str, object]:
    if isinstance(record, AuditRecord):
        return asdict(record)
    return {"id": record.id, "tenant_id": record.tenant_id, "user_id": record.user_id, "action": record.action, "details": record.details, "timestamp": record.timestamp.isoformat() if record.timestamp else None, "prev_hash": record.prev_hash, "row_hash": record.row_hash}


def _tenant_records(user: User, db: Session | None) -> list[object]:
    return audit_records(db, user.tenant_id) if db is not None else [record for record in state.audits if record.tenant_id == user.tenant_id]


def _require_auditor(user: User, db: Session | None) -> None:
    if not ({"admin", "auditor"} & user.roles):
        write_audit(state, user, "access_denied", {"resource": "audit"}, db)
        raise HTTPException(status_code=403, detail="admin or auditor role required")


def _audit_read(user: User, db: Session | None, endpoint: str) -> None:
    write_audit(state, user, "audit_read", {"endpoint": endpoint}, db)


@router.get("/logs")
def logs(user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> list[dict[str, object]]:
    _require_auditor(user, db)
    _audit_read(user, db, "logs")
    return [_record_dict(record) for record in _tenant_records(user, db)]


@router.get("/logs/{record_id}")
def log_detail(record_id: str, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, object]:
    _require_auditor(user, db)
    _audit_read(user, db, "log_detail")
    record = next((item for item in _tenant_records(user, db) if item.id == record_id), None)
    if record is None:
        raise HTTPException(status_code=404, detail="audit record not found")
    return _record_dict(record)


@router.get("/export")
def export_logs(format: str = "jsonl", user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> PlainTextResponse:
    _require_auditor(user, db)
    _audit_read(user, db, "export")
    records = [_record_dict(record) for record in _tenant_records(user, db)]
    if format == "jsonl":
        return PlainTextResponse("\n".join(json.dumps(record, default=str) for record in records), media_type="application/jsonl")
    if format == "csv":
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=["id", "tenant_id", "user_id", "action", "details", "timestamp", "prev_hash", "row_hash"])
        writer.writeheader()
        writer.writerows(records)
        return PlainTextResponse(output.getvalue(), media_type="text/csv")
    raise HTTPException(status_code=400, detail="format must be csv or jsonl")


@router.get("/verify")
def verify(user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, object]:
    _require_auditor(user, db)
    _audit_read(user, db, "verify")
    records = _tenant_records(user, db)
    chain = [AuditRecord(item.id, item.tenant_id, item.user_id, item.action, item.details, item.timestamp.isoformat(), item.prev_hash, item.row_hash) for item in records] if db is not None else records
    valid, broken_id = verify_chain(chain)
    return {"valid": valid, "first_broken_id": broken_id}


@router.get("/who-saw/{doc_id}")
def who_saw(doc_id: str, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> list[dict[str, object]]:
    _require_auditor(user, db)
    _audit_read(user, db, "who_saw")
    results = []
    for record in _tenant_records(user, db):
        details = record.details or {}
        if doc_id in details.get("retrieved_doc_ids", []) or details.get("document_id") == doc_id:
            timestamp = record.timestamp.isoformat() if hasattr(record.timestamp, "isoformat") else record.timestamp
            results.append({"user_id": record.user_id, "timestamp": timestamp, "audit_id": record.id})
    return results
