from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.api.dependencies import current_user, principal
from app.api.state import User, question_hash, state
from app.core.principal import Principal
from app.rag.generation.output_guard import guard_output
from app.rag.generation.prompt import build_prompt

router = APIRouter(prefix="/v1", tags=["query"])


class QueryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    top_k: int = Field(default=5, ge=1, le=20)
    conversation_id: str | None = Field(default=None, max_length=100)


@router.get("/me")
def me(user: User = Depends(current_user)) -> dict[str, object]:
    return {"user_id": user.user_id, "tenant_id": user.tenant_id, "roles": sorted(user.roles), "clearance": user.clearance}


@router.post("/query")
def query(request: QueryRequest, user: User = Depends(current_user), identity: Principal = Depends(principal)) -> dict[str, object]:
    chunks = state.retriever.search(identity, request.question, request.top_k)
    prompt = build_prompt(identity, chunks, request.question)
    answer = guard_output(state.llm.answer(prompt), {chunk.acl.chunk_id for chunk in chunks})
    audit = state.audit(user, "query", {"question_hash": question_hash(request.question), "retrieved_chunk_ids": [chunk.acl.chunk_id for chunk in chunks], "num_returned": len(chunks)})
    return {"answer": answer, "citations": [{"chunk_id": chunk.acl.chunk_id, "doc_id": chunk.doc_id} for chunk in chunks], "audit_id": audit.id}
