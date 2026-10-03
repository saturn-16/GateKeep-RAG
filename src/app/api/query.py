from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import current_user, principal
from app.api.runtime import get_runtime_db
from app.api.state import User, question_hash, state
from app.audit.service import write_audit
from app.core.principal import Principal
from app.core.permissions import ChunkACL, can_access
from app.db.models import Chunk, Document
from app.rag.generation.output_guard import guard_output
from app.rag.generation.prompt import build_prompt
from sqlalchemy import select
from sqlalchemy.orm import Session

router = APIRouter(prefix="/v1", tags=["query"])


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: str | None = Field(default=None, max_length=100)


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, object]:
    return {"user_id": user.user_id, "tenant_id": user.tenant_id, "roles": sorted(user.roles), "clearance": user.clearance}


@router.post("/query")
def query(request: QueryRequest, user: User = Depends(current_user), identity: Principal = Depends(principal), db: Session | None = Depends(get_runtime_db)) -> dict[str, object]:
    chunks = state.retriever.search(identity, request.question, request.top_k)
    if db is not None and chunks:
        source_chunks = {record.id: record for record in db.scalars(select(Chunk).where(Chunk.id.in_([chunk.acl.chunk_id for chunk in chunks])))}
        verified = []
        for chunk in chunks:
            source = source_chunks.get(chunk.acl.chunk_id)
            acl = ChunkACL(source.tenant_id, source.id, frozenset(source.allowed_roles or []), frozenset(source.allowed_users or []), source.sensitivity) if source else chunk.acl
            document = db.get(Document, source.document_id) if source else None
            if source is None or document is None or document.status != "ready" or not can_access(identity, acl):
                write_audit(state, user, "security_alert", {"chunk_id": chunk.acl.chunk_id, "reason": "post_retrieval_acl_mismatch"}, db)
                continue
            verified.append(chunk)
        chunks = verified
    else:
        chunks = [chunk for chunk in chunks if can_access(identity, chunk.acl)]
    prompt = build_prompt(identity, chunks, request.question)
    answer = guard_output(state.llm.answer(prompt), {chunk.acl.chunk_id for chunk in chunks})
    audit = write_audit(state, user, "query", {"question_hash": question_hash(request.question), "retrieved_chunk_ids": [chunk.acl.chunk_id for chunk in chunks], "retrieved_doc_ids": [chunk.doc_id for chunk in chunks], "num_returned": len(chunks)}, db)
    return {"answer": answer, "citations": [{"chunk_id": chunk.acl.chunk_id, "doc_id": chunk.doc_id} for chunk in chunks], "audit_id": audit.id}
