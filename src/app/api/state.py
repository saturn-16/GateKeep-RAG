from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import uuid

from app.audit.hashchain import AuditRecord, make_record
from app.config import get_settings
from app.core.principal import Principal
from app.core.security import hash_password, verify_password
from app.rag.llm import MockLLM, OllamaLLM
from app.rag.vectorstore.tenant_scoped_retriever import TenantScopedRetriever, VectorChunk
from app.core.permissions import ChunkACL
from app.core.rate_limit import InMemoryRateLimiter


@dataclass(slots=True)
class User:
    user_id: str
    tenant_id: str
    password_hash: str
    roles: frozenset[str]
    clearance: str
    active: bool = True


@dataclass(slots=True)
class ServiceState:
    users: dict[str, User] = field(default_factory=dict)
    audits: list[AuditRecord] = field(default_factory=list)
    document_status: dict[str, dict[str, str]] = field(default_factory=dict)
    retriever: TenantScopedRetriever = field(default_factory=TenantScopedRetriever)
    llm: MockLLM = field(default_factory=MockLLM)
    vector_store: QdrantVectorStore | None = None
    limiter: InMemoryRateLimiter = field(default_factory=InMemoryRateLimiter)

    def audit(self, user: User, action: str, details: dict[str, object]) -> AuditRecord:
        previous = next((record.row_hash for record in reversed(self.audits) if record.tenant_id == user.tenant_id), "")
        record = make_record(str(uuid.uuid4()), user.tenant_id, user.user_id, action, details, previous)
        self.audits.append(record)
        return record


def create_demo_state() -> ServiceState:
    settings = get_settings()
    llm = OllamaLLM(model=settings.llm_model, url=settings.llm_url) if settings.llm_provider == "ollama" else MockLLM()
    users = {
        "alice": User("alice", "acme-corp", hash_password("alice"), frozenset({"admin"}), "restricted"),
        "bob": User("bob", "acme-corp", hash_password("bob"), frozenset({"hr"}), "restricted"),
        "dave": User("dave", "acme-corp", hash_password("dave"), frozenset({"employee"}), "internal"),
        "frank": User("frank", "globex-inc", hash_password("frank"), frozenset({"admin"}), "restricted"),
    }
    chunks = [
        VectorChunk(ChunkACL("acme-corp", "handbook-acme", frozenset({"employee", "hr", "admin"}), sensitivity="internal"), "employee handbook benefits", 1.0, "handbook-acme-doc"),
        VectorChunk(ChunkACL("acme-corp", "salary-acme", frozenset({"hr", "admin"}), sensitivity="restricted"), "salary band engineers acme 120000", 1.0, "salary-acme-doc"),
        VectorChunk(ChunkACL("globex-inc", "salary-globex", frozenset({"hr", "admin"}), sensitivity="restricted"), "salary band engineers globex 90000", 1.0, "salary-globex-doc"),
    ]
    if settings.persistence_backend == "postgres":
        try:
            from app.db.models import Chunk as DbChunk, Document as DbDocument, Tenant as DbTenant, User as DbUser
            from app.db.session import SessionLocal

            with SessionLocal() as session:
                for t_id in ("acme-corp", "globex-inc"):
                    session.merge(DbTenant(id=t_id, name=t_id))
                session.flush()
                for u in users.values():
                    session.merge(DbUser(id=u.user_id, tenant_id=u.tenant_id, password_hash=u.password_hash, clearance=u.clearance, active=u.active, roles=list(u.roles)))
                for chunk in chunks:
                    session.merge(DbDocument(id=chunk.doc_id, tenant_id=chunk.acl.tenant_id, title=chunk.doc_id.title(), status="ready", source="demo", created_by="alice" if chunk.acl.tenant_id == "acme-corp" else "frank"))
                session.flush()
                for chunk in chunks:
                    content_hash = sha256(chunk.text.encode()).hexdigest()
                    session.merge(DbChunk(id=chunk.acl.chunk_id, tenant_id=chunk.acl.tenant_id, document_id=chunk.doc_id, text=chunk.text, content_hash=content_hash, allowed_roles=sorted(chunk.acl.allowed_roles), allowed_users=sorted(chunk.acl.allowed_users), sensitivity=chunk.acl.sensitivity))
                session.commit()
        except Exception:
            pass
    if settings.vector_backend == "qdrant":
        from app.rag.vectorstore.qdrant_store import QdrantVectorStore

        vector_store = QdrantVectorStore(settings)
        vector_store.upsert(chunks)
        return ServiceState(users=users, retriever=TenantScopedRetriever(backend=vector_store), vector_store=vector_store, llm=llm)
    return ServiceState(users=users, retriever=TenantScopedRetriever(chunks), llm=llm)


state = create_demo_state()


def authenticate(username: str, password: str) -> User | None:
    user = state.users.get(username)
    if user and user.active and verify_password(password, user.password_hash):
        return user
    return None


def question_hash(question: str) -> str:
    return sha256(question.encode()).hexdigest()
