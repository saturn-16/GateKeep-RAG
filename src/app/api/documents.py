import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from app.api.dependencies import current_user
from app.api.state import User, state
from app.core.permissions import ChunkACL
from app.rag.ingestion.chunker import chunk_text
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk
from app.config import get_settings
from app.rag.ingestion.loaders import parse_document, read_upload

router = APIRouter(prefix="/v1/documents", tags=["documents"])


class TextDocument(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=100000)
    allowed_roles: set[str] = Field(min_length=1)
    sensitivity: str = "internal"


@router.post("/text")
def ingest(document: TextDocument, user: User = Depends(current_user)) -> dict[str, object]:
    if not ({"admin", "hr", "finance", "engineering", "legal"} & user.roles):
        raise HTTPException(status_code=403, detail="documents:write permission required")
    if not document.allowed_roles <= {"admin", "hr", "finance", "engineering", "legal", "employee", "viewer"}:
        raise HTTPException(status_code=400, detail="unknown role in ACL")
    chunks = chunk_text(document.text)
    for chunk in chunks:
        state.retriever._chunks.append(VectorChunk(ChunkACL(user.tenant_id, chunk.chunk_id, frozenset(document.allowed_roles), sensitivity=document.sensitivity), chunk.text, 0.5, document.title))
    audit = state.audit(user, "ingest", {"title": document.title, "chunks": len(chunks)})
    return {"status": "ready", "chunks": len(chunks), "audit_id": audit.id}


@router.post("")
async def ingest_file(background_tasks: BackgroundTasks, file: UploadFile = File(...), title: str = Form(...), allowed_roles: str = Form(...), sensitivity: str = Form("internal"), user: User = Depends(current_user)) -> dict[str, str]:
    if not ({"admin", "hr", "finance", "engineering", "legal"} & user.roles):
        raise HTTPException(status_code=403, detail="documents:write permission required")
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
    document_id = f"pending-{uuid.uuid4()}"
    state.document_status[document_id] = {"status": "pending", "title": title}
    background_tasks.add_task(_complete_file_ingest, document_id, user, title, text, roles, sensitivity)
    return {"id": document_id, "status": "pending"}


def _complete_file_ingest(document_id: str, user: User, title: str, text: str, roles: set[str], sensitivity: str) -> None:
    state.document_status[document_id] = {"status": "processing", "title": title}
    chunks = chunk_text(text)
    values = [VectorChunk(ChunkACL(user.tenant_id, f"{document_id}:{chunk.chunk_id}", frozenset(roles), sensitivity=sensitivity), chunk.text, 0.5, document_id) for chunk in chunks]
    if state.vector_store is not None:
        state.vector_store.upsert(values)
    else:
        state.retriever._chunks.extend(values)
    state.document_status[document_id] = {"status": "ready", "title": title, "chunks": str(len(values))}
    state.audit(user, "ingest", {"document_id": document_id, "chunks": len(values), "status": "ready"})


@router.get("/{document_id}")
def document_status(document_id: str, user: User = Depends(current_user)) -> dict[str, str]:
    status = state.document_status.get(document_id)
    if status is None:
        raise HTTPException(status_code=404, detail="document not found")
    return status
