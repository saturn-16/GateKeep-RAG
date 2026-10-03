from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient, models

from app.config import Settings
from app.core.permissions import ChunkACL, build_filter
from app.core.principal import Principal
from app.rag.embeddings.factory import get_embedding_provider
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk


class QdrantVectorStore:
    """Qdrant adapter; every search receives and applies a verified Principal filter."""

    def __init__(self, settings: Settings, client: QdrantClient | None = None) -> None:
        self.settings = settings
        self.client = client or QdrantClient(url=settings.qdrant_url)
        self.embedder = get_embedding_provider(settings)
        self.ensure_collection()

    def ensure_collection(self) -> None:
        collections = {item.name for item in self.client.get_collections().collections}
        if self.settings.qdrant_collection not in collections:
            self.client.create_collection(
                collection_name=self.settings.qdrant_collection,
                vectors_config=models.VectorParams(size=self.settings.qdrant_vector_size, distance=models.Distance.COSINE),
            )
        for field_name, schema in (("tenant_id", models.PayloadSchemaType.KEYWORD), ("allowed_roles", models.PayloadSchemaType.KEYWORD), ("allowed_users", models.PayloadSchemaType.KEYWORD), ("sensitivity_level", models.PayloadSchemaType.INTEGER), ("document_status", models.PayloadSchemaType.KEYWORD)):
            self.client.create_payload_index(collection_name=self.settings.qdrant_collection, field_name=field_name, field_schema=schema)

    def upsert(self, chunks: list[VectorChunk]) -> None:
        points = []
        for chunk in chunks:
            point_id = str(uuid5(NAMESPACE_URL, f"{chunk.acl.tenant_id}:{chunk.doc_id}:{chunk.acl.chunk_id}"))
            points.append(models.PointStruct(id=point_id, vector=self.embedder.embed(chunk.text), payload={
                "tenant_id": chunk.acl.tenant_id,
                "chunk_id": chunk.acl.chunk_id,
                "doc_id": chunk.doc_id,
                "document_status": chunk.document_status,
                "text": chunk.text,
                "allowed_roles": sorted(chunk.acl.allowed_roles),
                "allowed_users": sorted(chunk.acl.allowed_users),
                "sensitivity": chunk.acl.sensitivity,
                "sensitivity_level": {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}.get(chunk.acl.sensitivity, 3),
            }))
        if points:
            self.client.upsert(collection_name=self.settings.qdrant_collection, points=points, wait=True)

    def search(self, principal: Principal, query: str, top_k: int) -> list[VectorChunk]:
        filter_spec = build_filter(principal)
        must = [models.FieldCondition(key=condition["key"], **self._condition(condition)) for condition in filter_spec["must"]]
        must.append(models.FieldCondition(key="document_status", match=models.MatchValue(value="ready")))
        should = [models.FieldCondition(key=condition["key"], **self._condition(condition)) for condition in filter_spec.get("should", [])]
        query_filter = models.Filter(
            must=must,
            min_should=models.MinShould(conditions=should, min_count=filter_spec["minimum_should_match"])
            if should and "admin" not in principal.roles else None,
        )
        score_threshold = self.settings.retrieval_score_threshold if self.settings.embedding_provider != "hash" else None
        response = self.client.query_points(
            collection_name=self.settings.qdrant_collection,
            query=self.embedder.embed(query),
            query_filter=query_filter,
            limit=min(top_k, 20),
            score_threshold=score_threshold,
            with_payload=True,
        ).points
        chunks = [self._chunk(point) for point in response if isinstance(point.payload, dict)]
        if self.settings.embedding_provider == "hash":
            query_terms = {term.lower().strip(".,;:!?\"'") for term in query.split() if term}
            if query_terms:
                chunks = [c for c in chunks if query_terms & {t.strip(".,;:!?\"'") for t in c.text.lower().split()}]
        return chunks

    def update_document_acl(self, tenant_id: str, document_id: str, allowed_roles: set[str], allowed_users: set[str], sensitivity: str) -> None:
        self.client.set_payload(collection_name=self.settings.qdrant_collection, payload={"allowed_roles": sorted(allowed_roles), "allowed_users": sorted(allowed_users), "sensitivity": sensitivity, "sensitivity_level": {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}[sensitivity]}, points=models.Filter(must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)), models.FieldCondition(key="doc_id", match=models.MatchValue(value=document_id))]), wait=True)

    def delete_document(self, tenant_id: str, document_id: str) -> None:
        self.client.delete(collection_name=self.settings.qdrant_collection, points_selector=models.FilterSelector(filter=models.Filter(must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id)), models.FieldCondition(key="doc_id", match=models.MatchValue(value=document_id))])), wait=True)

    @staticmethod
    def _condition(condition: dict[str, Any]) -> dict[str, Any]:
        match = condition.get("match")
        if match and "any" in match:
            return {"match": models.MatchAny(any=match["any"])}
        if match and "value" in match:
            return {"match": models.MatchValue(value=match["value"])}
        range_value = condition.get("range", {})
        return {"range": models.Range(lte=range_value.get("lte"))}

    @staticmethod
    def _chunk(point: Any) -> VectorChunk:
        payload = point.payload
        acl = ChunkACL(payload["tenant_id"], payload["chunk_id"], frozenset(payload.get("allowed_roles", [])), frozenset(payload.get("allowed_users", [])), payload.get("sensitivity", "restricted"))
        return VectorChunk(acl, payload.get("text", ""), float(point.score or 0), payload.get("doc_id", ""), payload.get("document_status", "ready"))
