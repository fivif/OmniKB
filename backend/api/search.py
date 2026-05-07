from __future__ import annotations
import asyncio
import re

from fastapi import APIRouter, Query

from config import settings
from pipeline.embedder import embed_dense, embed_sparse
from storage.vector_store import hybrid_search

router = APIRouter()


def _highlight(text: str, query: str) -> str:
    """Wrap query terms in <mark> tags (case-insensitive)."""
    terms = [re.escape(t) for t in query.split() if len(t) > 1]
    if not terms:
        return text
    pattern = re.compile("|".join(terms), re.IGNORECASE)
    return pattern.sub(lambda m: f"<mark>{m.group()}</mark>", text)


@router.get("")
async def search(
    q: str = Query(..., description="Search query"),
    top_k: int = Query(10, ge=1, le=50),
    mode: str = Query("hybrid", pattern="^(hybrid|semantic|bm25)$"),
    filter_source: str | None = Query(None),
    filter_type: str | None = Query(None),
    rerank: bool = Query(False, description="Apply cross-encoder re-ranking (requires RERANKER_ENABLED=true)"),
):
    filters: dict = {}
    if filter_source:
        filters["source_id"] = filter_source
    if filter_type:
        filters["source_type"] = filter_type

    dense_vec = (await embed_dense([q]))[0]
    sparse = embed_sparse([q])[0]

    if mode == "semantic":
        results = await hybrid_search(
            query_dense=dense_vec,
            query_sparse_indices=[],
            query_sparse_values=[],
            top_k=top_k,
            filters=filters or None,
        )
    elif mode == "bm25":
        results = await hybrid_search(
            query_dense=[0.0] * 1536,
            query_sparse_indices=sparse[0],
            query_sparse_values=sparse[1],
            top_k=top_k,
            filters=filters or None,
        )
    else:
        results = await hybrid_search(
            query_dense=dense_vec,
            query_sparse_indices=sparse[0],
            query_sparse_values=sparse[1],
            top_k=top_k,
            filters=filters or None,
        )

    # Optional re-rank
    if rerank and results and settings.reranker_enabled:
        from pipeline.reranker import rerank as do_rerank
        results = await asyncio.to_thread(
            do_rerank, q, results, settings.reranker_model
        )

    for r in results:
        r["highlight"] = _highlight(r["content"][:600], q)

    return {"query": q, "mode": mode, "results": results}
