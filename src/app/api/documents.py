import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.dependencies import current_user
from app.api.runtime import get_runtime_db
from app.api.state import User, state
from app.audit.service import write_audit
from app.core.principal import CLEARANCE_LEVELS
from app.core.permissions import ChunkACL
from app.rag.ingestion.chunker import chunk_text
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk
from app.config import get_settings
from app.rag.ingestion.loaders import parse_document, read_upload
from sqlalchemy.orm import Session
from sqlalchemy import delete, select
from app.db.models import Chunk, Document

router = APIRouter(prefix="/v1/documents", tags=["documents"])


class TextDocument(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100000)
    allowed_roles: set[str] = Field(min_length=1)
    sensitivity: str = "internal"


class ACLUpdate(BaseModel):
    allowed_roles: set[str]
    allowed_users: set[str] = set()
    sensitivity: str = "internal"


WRITE_ROLES = {"admin", "hr", "finance", "engineering", "legal"}
KNOWN_ROLES = WRITE_ROLES | {"employee", "viewer", "auditor"}


def _require_write(user: User) -> None:
    if not (WRITE_ROLES & user.roles):
        raise HTTPException(status_code=403, detail="documents:write permission required")


def _validate_acl(user: User, update: ACLUpdate) -> None:
    if update.sensitivity not in CLEARANCE_LEVELS or not update.allowed_roles <= KNOWN_ROLES:
        raise HTTPException(status_code=400, detail="invalid ACL")
    if CLEARANCE_LEVELS[update.sensitivity] > CLEARANCE_LEVELS.get(user.clearance, -1):
        raise HTTPException(status_code=403, detail="cannot grant above own clearance")
    if "admin" not in user.roles and not update.allowed_roles <= user.roles:
        raise HTTPException(status_code=403, detail="cannot grant roles outside own authority")


@router.post("/text")
def ingest(document: TextDocument, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, object]:
    _require_write(user)
    if not document.allowed_roles <= {"admin", "hr", "finance", "engineering", "legal", "employee", "viewer"}:
        raise HTTPException(status_code=400, detail="unknown role in ACL")
    chunks = chunk_text(document.text)
    document_id = str(uuid.uuid4())
    chunk_data = [(chunk, str(uuid.uuid4())) for chunk in chunks]
    values = [
        VectorChunk(
            ChunkACL(user.tenant_id, chunk_id, frozenset(document.allowed_roles), sensitivity=document.sensitivity),
            chunk.text,
            0.5,
            document_id,
            "ready",
        )
        for chunk, chunk_id in chunk_data
    ]
    if db is None:
        state.retriever._chunks.extend(values)
        state.document_status[document_id] = {"status": "ready", "title": document.title, "tenant_id": user.tenant_id, "chunks": str(len(chunks))}
        audit = write_audit(state, user, "ingest", {"document_id": document_id, "title": document.title, "chunks": len(chunks)}, db)
        return {"id": document_id, "status": "ready", "chunks": len(chunks), "audit_id": audit.id}
    record = Document(id=document_id, tenant_id=user.tenant_id, title=document.title, status="processing", source="text", created_by=user.user_id)
    db.add(record)
    db.commit()
    try:
        if state.vector_store is not None:
            state.vector_store.upsert(values)
        for (chunk, chunk_id), value in zip(chunk_data, values):
            db.add(Chunk(id=chunk_id, tenant_id=user.tenant_id, document_id=document_id, text=chunk.text, content_hash=chunk.content_hash, allowed_roles=sorted(document.allowed_roles), allowed_users=[], sensitivity=document.sensitivity, page=chunk.page))
        record.status = "ready"
        audit = write_audit(state, user, "ingest", {"document_id": document_id, "title": document.title, "chunks": len(chunks)}, db)
        db.commit()
        return {"id": document_id, "status": "ready", "chunks": len(chunks), "audit_id": audit.id}
    except Exception as exc:
        db.rollback()
        record = db.get(Document, document_id)
        if record is not None:
            record.status = "failed"
            record.error = str(exc)
            db.commit()
        raise HTTPException(status_code=503, detail="document ingestion failed") from exc


@router.post("")
async def ingest_file(background_tasks: BackgroundTasks, file: UploadFile = File(...), title: str = Form(...), allowed_roles: str = Form(...), sensitivity: str = Form("internal"), user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, str]:
    _require_write(user)
    try:
        data = await read_upload(file, get_settings().upload_max_bytes)
        text = parse_document(file.filename or title, file.content_type, data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not text:
        raise HTTPException(status_code=400, detail="document contains no extractable text")
    roles = {role.strip() for role in allowed_roles.split(",") if role.strip()}
    if not roles or not roles <= {"admin", "hr", "finance", "engineering", "legal", "employee", "viewer"}:
        raise HTTPException(status_code=400, detail="unknown or empty ACL role")
    document_id = str(uuid.uuid4())
    state.document_status[document_id] = {"status": "pending", "title": title, "tenant_id": user.tenant_id}
    if db is not None:
        db.add(Document(id=document_id, tenant_id=user.tenant_id, title=title, status="pending", source=file.filename or title, created_by=user.user_id))
        db.commit()
    background_tasks.add_task(_complete_file_ingest, document_id, user, title, text, roles, sensitivity)
    return {"id": document_id, "status": "pending"}


@router.patch("/{document_id}/acl")
def update_acl(document_id: str, update: ACLUpdate, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, object]:
    _require_write(user)
    _validate_acl(user, update)
    if db is None:
        matches = [chunk for chunk in state.retriever._chunks if chunk.doc_id == document_id and chunk.acl.tenant_id == user.tenant_id]
        if not matches:
            raise HTTPException(status_code=404, detail="document not found")
        state.retriever._chunks = [VectorChunk(ChunkACL(item.acl.tenant_id, item.acl.chunk_id, frozenset(update.allowed_roles), frozenset(update.allowed_users), update.sensitivity), item.text, item.score, item.doc_id) if item in matches else item for item in state.retriever._chunks]
        audit = write_audit(state, user, "acl_update", {"document_id": document_id, "allowed_roles": sorted(update.allowed_roles)}, db)
        return {"id": document_id, "status": "ready", "audit_id": audit.id}
    document = db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == user.tenant_id))
    chunks = list(db.scalars(select(Chunk).where(Chunk.document_id == document_id, Chunk.tenant_id == user.tenant_id)))
    if document is None or not chunks:
        raise HTTPException(status_code=404, detail="document not found")
    old = chunks[0]
    try:
        if state.vector_store is not None:
            state.vector_store.update_document_acl(user.tenant_id, document_id, update.allowed_roles, update.allowed_users, update.sensitivity)
        for chunk in chunks:
            chunk.allowed_roles = sorted(update.allowed_roles)
            chunk.allowed_users = sorted(update.allowed_users)
            chunk.sensitivity = update.sensitivity
        document.repair_required = False
        document.error = None
        audit = write_audit(state, user, "acl_update", {"document_id": document_id, "allowed_roles": sorted(update.allowed_roles)}, db)
        db.commit()
        return {"id": document_id, "status": "ready", "audit_id": audit.id}
    except Exception as exc:
        db.rollback()
        repair = db.get(Document, document_id)
        if repair is not None:
            repair.repair_required = True
            repair.error = str(exc)
            db.commit()
        raise HTTPException(status_code=503, detail="document ACL update requires repair") from exc


@router.delete("/{document_id}")
def delete_document(document_id: str, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, object]:
    _require_write(user)
    if db is None:
        before = len(state.retriever._chunks)
        state.retriever._chunks = [item for item in state.retriever._chunks if not (item.doc_id == document_id and item.acl.tenant_id == user.tenant_id)]
        if len(state.retriever._chunks) == before:
            raise HTTPException(status_code=404, detail="document not found")
        audit = write_audit(state, user, "delete", {"document_id": document_id}, db)
        return {"id": document_id, "status": "deleted", "audit_id": audit.id}
    document = db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == user.tenant_id))
    if document is None:
        raise HTTPException(status_code=404, detail="document not found")
    try:
        if state.vector_store is not None:
            state.vector_store.delete_document(user.tenant_id, document_id)
        db.execute(delete(Chunk).where(Chunk.document_id == document_id, Chunk.tenant_id == user.tenant_id))
        db.delete(document)
        audit = write_audit(state, user, "delete", {"document_id": document_id}, db)
        db.commit()
        return {"id": document_id, "status": "deleted", "audit_id": audit.id}
    except Exception as exc:
        db.rollback()
        repair = db.get(Document, document_id)
        if repair is not None:
            repair.repair_required = True
            repair.error = str(exc)
            db.commit()
        raise HTTPException(status_code=503, detail="document delete requires repair") from exc


def _complete_file_ingest(document_id: str, user: User, title: str, text: str, roles: set[str], sensitivity: str) -> None:
    state.document_status[document_id] = {"status": "processing", "title": title, "tenant_id": user.tenant_id}
    chunks = chunk_text(text)
    chunk_data = [(chunk, str(uuid.uuid4())) for chunk in chunks]
    values = [
        VectorChunk(
            ChunkACL(user.tenant_id, chunk_id, frozenset(roles), sensitivity=sensitivity),
            chunk.text,
            0.5,
            document_id,
            "ready",
        )
        for chunk, chunk_id in chunk_data
    ]
    from app.config import get_settings
    from app.db.session import SessionLocal
    session = SessionLocal() if get_settings().persistence_backend == "postgres" else None
    try:
        if session is not None:
            record = session.get(Document, document_id)
            if record is not None:
                record.status = "processing"
                session.commit()
        if state.vector_store is not None:
            state.vector_store.upsert(values)
        else:
            state.retriever._chunks.extend(values)
        if session is not None:
            for (chunk, chunk_id), value in zip(chunk_data, values):
                session.add(Chunk(id=chunk_id, tenant_id=user.tenant_id, document_id=document_id, text=chunk.text, content_hash=chunk.content_hash, allowed_roles=sorted(roles), allowed_users=[], sensitivity=sensitivity, page=chunk.page))
            record = session.get(Document, document_id)
            if record is not None:
                record.status = "ready"
            write_audit(state, user, "ingest", {"document_id": document_id, "chunks": len(values), "status": "ready"}, session)
            session.commit()
        else:
            write_audit(state, user, "ingest", {"document_id": document_id, "chunks": len(values), "status": "ready"})
        state.document_status[document_id] = {"status": "ready", "title": title, "chunks": str(len(values)), "tenant_id": user.tenant_id}
    except Exception as exc:
        if session is not None:
            session.rollback()
            record = session.get(Document, document_id)
            if record is not None:
                record.status = "failed"
                record.error = str(exc)
                session.commit()
        state.document_status[document_id] = {"status": "failed", "title": title, "tenant_id": user.tenant_id}
    finally:
        if session is not None:
            session.close()


@router.get("/{document_id}")
def document_status(document_id: str, user: User = Depends(current_user), db: Session | None = Depends(get_runtime_db)) -> dict[str, str]:
    if db is not None:
        doc = db.scalar(select(Document).where(Document.id == document_id, Document.tenant_id == user.tenant_id))
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        return {"id": doc.id, "status": doc.status, "title": doc.title}
    status = state.document_status.get(document_id)
    if status is None or (status.get("tenant_id") and status["tenant_id"] != user.tenant_id):
        raise HTTPException(status_code=404, detail="document not found")
    return {"id": document_id, "status": status.get("status", "ready"), "title": status.get("title", "")}
