from __future__ import annotations

import math
import re
from typing import Sequence

from app.rag.vectorstore.tenant_scoped_retriever import VectorChunk


def tokenize_query(text: str) -> list[str]:
    """Extracts lowercase alphabetic/numeric tokens of length >= 2."""
    return [t.lower() for t in re.findall(r"\w+", text) if len(t) >= 2]


def compute_candidate_bm25_scores(
    candidates: Sequence[VectorChunk],
    query: str,
    k1: float = 1.2,
    b: float = 0.75,
) -> list[float]:
    """Computes Okapi BM25 scores strictly over the candidate chunk set.

    No global/corpus-wide statistics are ever used. Document frequencies,
    average document length, and term frequencies are evaluated solely
    within the already-filtered candidate set for the principal.
    """
    n = len(candidates)
    if n == 0:
        return []
    if n == 1:
        return [1.0]

    query_terms = tokenize_query(query)
    if not query_terms:
        return [0.0] * n

    doc_tokens = [tokenize_query(c.text) for c in candidates]
    doc_lens = [len(tokens) for tokens in doc_tokens]
    avgdl = (sum(doc_lens) / n) if n > 0 else 1.0

    # Document frequency strictly over the permitted candidate set
    dfs: dict[str, int] = {}
    for tokens in doc_tokens:
        seen = set(tokens)
        for term in query_terms:
            if term in seen:
                dfs[term] = dfs.get(term, 0) + 1

    scores: list[float] = []
    for i, tokens in enumerate(doc_tokens):
        score = 0.0
        d_len = doc_lens[i]
        tf_dict: dict[str, int] = {}
        for token in tokens:
            tf_dict[token] = tf_dict.get(token, 0) + 1

        for term in query_terms:
            df = dfs.get(term, 0)
            if df == 0:
                continue
            # Robertson-Spärck Jones IDF with smoothing
            idf = math.log(1.0 + (n - df + 0.5) / (df + 0.5))
            tf = tf_dict.get(term, 0)
            denom = tf + k1 * (1.0 - b + b * (d_len / avgdl)) if avgdl > 0 else 1.0
            score += idf * (tf * (k1 + 1.0) / denom)
        scores.append(score)

    return scores


def fuse_dense_and_bm25(
    candidates: list[VectorChunk],
    query: str,
    dense_weight: float = 0.7,
    bm25_weight: float = 0.3,
) -> list[VectorChunk]:
    """Fuses dense similarity scores with candidate-isolated BM25 scores."""
    if len(candidates) <= 1:
        return candidates

    bm25_scores = compute_candidate_bm25_scores(candidates, query)
    max_bm25 = max(bm25_scores) if bm25_scores else 0.0
    min_bm25 = min(bm25_scores) if bm25_scores else 0.0

    fused: list[VectorChunk] = []
    for c, bm25 in zip(candidates, bm25_scores):
        if max_bm25 > min_bm25:
            norm_bm25 = (bm25 - min_bm25) / (max_bm25 - min_bm25)
        else:
            norm_bm25 = 1.0 if max_bm25 > 0 else 0.0
        fused_score = (dense_weight * c.score) + (bm25_weight * norm_bm25)
        fused.append(
            VectorChunk(
                acl=c.acl,
                text=c.text,
                score=round(fused_score, 4),
                doc_id=c.doc_id,
                document_status=c.document_status,
            )
        )

    return sorted(fused, key=lambda x: x.score, reverse=True)
