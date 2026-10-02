from dataclasses import dataclass
from typing import Protocol

from app.core.permissions import ChunkACL, build_filter, can_access
from app.core.principal import Principal


@dataclass(frozen=True, slots=True)
class VectorChunk:
    acl: ChunkACL
    text: str
    score: float = 0.0
    doc_id: str = ""


class TenantContextRequired(RuntimeError):
    """Raised when retrieval is attempted without a verified principal."""


class VectorBackend(Protocol):
    def search(self, principal: Principal, query: str, top_k: int) -> list[VectorChunk]:
        ...


class TenantScopedRetriever:
    """Tenant-required boundary around either Qdrant or an in-memory test double."""

    def __init__(self, chunks: list[VectorChunk] | None = None, backend: VectorBackend | None = None) -> None:
        self._chunks = chunks or []
        self._backend = backend

    def search(self, principal: Principal | None, query: str, top_k: int = 5) -> list[VectorChunk]:
        if principal is None or not principal.tenant_id:
            raise TenantContextRequired("verified tenant context is required")
        if self._backend is not None:
            return self._backend.search(principal, query, min(top_k, 20))
        query_terms = {term.lower() for term in query.split() if term}
        filtered = [
            chunk for chunk in self._chunks
            if can_access(principal, chunk.acl)
        ]
        verified = [
            chunk for chunk in filtered
            if chunk.acl.tenant_id == principal.tenant_id
            and (not query_terms or query_terms & set(chunk.text.lower().split()))
        ]
        return sorted(verified, key=lambda chunk: chunk.score, reverse=True)[: min(top_k, 20)]

    def filter_for(self, principal: Principal) -> dict[str, object]:
        return build_filter(principal)
