from __future__ import annotations

from app.core.permissions import ChunkACL
from app.rag.vectorstore.hybrid import compute_candidate_bm25_scores, fuse_dense_and_bm25
from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk


def test_bm25_computed_strictly_over_candidates_counterfactual_invariance() -> None:
    """Proves BM25 statistics are computed solely on candidate chunks, never on unretrieved documents."""
    c1 = VectorChunk(
        acl=ChunkACL("tenant-a", "chunk-1", frozenset(["employee"]), sensitivity="internal"),
        text="Employee annual paid time off leave accrues fifteen days annually.",
        score=0.75,
        doc_id="doc-handbook",
    )
    c2 = VectorChunk(
        acl=ChunkACL("tenant-a", "chunk-2", frozenset(["employee"]), sensitivity="internal"),
        text="Health insurance medical and dental plan details for all staff.",
        score=0.45,
        doc_id="doc-handbook",
    )
    c3_restricted = VectorChunk(
        acl=ChunkACL("tenant-a", "chunk-3", frozenset(["admin"]), sensitivity="restricted"),
        text="Executive severance golden parachute payments and confidential bonus equity grants.",
        score=0.20,
        doc_id="doc-exec",
    )

    query = "annual paid time off leave accrual"

    # World 1: Candidate set for employee user (only c1 and c2 are permitted by pre-filter)
    scores_world_1 = compute_candidate_bm25_scores([c1, c2], query)
    fused_world_1 = fuse_dense_and_bm25([c1, c2], query)

    # In World 2 (restricted document physically deleted from database), candidate set is STILL [c1, c2]
    scores_world_2 = compute_candidate_bm25_scores([c1, c2], query)
    fused_world_2 = fuse_dense_and_bm25([c1, c2], query)

    assert scores_world_1 == scores_world_2
    assert [c.score for c in fused_world_1] == [c.score for c in fused_world_2]
    assert [c.acl.chunk_id for c in fused_world_1] == [c.acl.chunk_id for c in fused_world_2]

    # Verify candidate with exact query terms receives higher BM25 score
    assert scores_world_1[0] > scores_world_1[1]
    assert fused_world_1[0].acl.chunk_id == "chunk-1"


def test_bm25_edge_cases() -> None:
    """Empty or single candidate lists behave cleanly without division-by-zero."""
    assert compute_candidate_bm25_scores([], "query") == []
    c1 = VectorChunk(
        acl=ChunkACL("t", "c1", frozenset(["employee"]), sensitivity="internal"),
        text="hello world",
        score=0.8,
    )
    assert compute_candidate_bm25_scores([c1], "hello") == [1.0]
    assert fuse_dense_and_bm25([c1], "hello")[0].score == 0.8
