import pytest

from app.core.permissions import ChunkACL
from app.core.principal import Principal
from app.rag.vectorstore.tenant_scoped_retriever import TenantContextRequired, TenantScopedRetriever, VectorChunk


def test_retrieval_never_crosses_tenants() -> None:
    retriever = TenantScopedRetriever([
        VectorChunk(ChunkACL("acme", "a", frozenset({"employee"}), sensitivity="internal"), "salary band", 1.0),
        VectorChunk(ChunkACL("globex", "g", frozenset({"employee"}), sensitivity="internal"), "salary band", 2.0),
    ])
    user = Principal("dave", "acme", frozenset({"employee"}), "internal")
    results = retriever.search(user, "salary band")
    assert [result.acl.chunk_id for result in results] == ["a"]


def test_retrieval_requires_tenant_context() -> None:
    with pytest.raises(TenantContextRequired):
        TenantScopedRetriever().search(None, "anything")
