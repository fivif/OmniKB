from __future__ import annotations
import asyncio
import logging
import re

from fastapi import APIRouter, Query

from config import settings
from pipeline.embedder import embed_dense, embed_sparse
from storage.vector_store import hybrid_search

router = APIRouter()
logger = logging.getLogger(__name__)


def _diversify(results: list[dict], max_per_source: int = 3) -> list[dict]:
    """Diversify search results so no single source dominates.

    Keeps the highest-scoring results but caps at max_per_source per source_id,
    then appends remaining results (from already-represented sources) at the end
    so total count is preserved.
    """
    seen = {}
    diversified = []
    remainder = []
    for r in results:
        sid = r.get("metadata", {}).get("source_id", "")
        if sid and sid not in seen:
            diversified.append(r)
            seen[sid] = 1
        elif sid and seen[sid] < max_per_source:
            diversified.append(r)
            seen[sid] += 1
        else:
            remainder.append(r)
    return diversified + remainder


def _normalize_query(q: str) -> str:
    """Normalize query for better matching: number formats, date formats, synonyms."""
    q = q.strip()
    # Number abbreviations: 2T -> keep both forms
    q = re.sub(r'(\d+)T(?=[^a-zA-Z]|$)', r'\1T \1万亿', q)
    # Date formats: 2025年1月15日 -> add ISO form
    q = re.sub(r'(\d{4})年(\d{1,2})月(\d{1,2})日', r'\1/\2/\3 \1年\2月\3日', q)
    return q


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
    rerank: bool = Query(True, description="Apply cross-encoder re-ranking (requires RERANKER_ENABLED=true)"),
):
    q = _normalize_query(q)

    filters: dict = {}
    if filter_source:
        filters["source_id"] = filter_source
    if filter_type:
        filters["source_type"] = filter_type

    # Broad query expansion
    try:
        from pipeline.query_expander import should_expand, expand_query
        if should_expand(q):
            sub_queries = expand_query(q)
            if len(sub_queries) > 1:
                all_results = []
                for sq in sub_queries:
                    dense_vec = (await embed_dense([sq]))[0]
                    sparse = embed_sparse([sq])[0]
                    sq_results = await hybrid_search(
                        query_dense=dense_vec,
                        query_sparse_indices=sparse[0],
                        query_sparse_values=sparse[1],
                        top_k=max(3, top_k),
                        filters=filters or None,
                    )
                    all_results.append(sq_results)
                from pipeline.query_expander import merge_results
                results = merge_results(all_results, max_total=top_k * 2)

                # Re-rank expanded results
                if rerank and results and settings.reranker_enabled:
                    from pipeline.reranker import rerank as do_rerank
                    results = await asyncio.to_thread(
                        do_rerank, q, results, settings.reranker_model
                    )

                results = _diversify(results, max_per_source=3)
                for r in results:
                    r["highlight"] = _highlight(r["content"][:600], q)
                return {"query": q, "mode": f"{mode}+expanded", "results": results}
    except ImportError:
        pass

    try:
        dense_vec = (await embed_dense([q]))[0]
    except Exception as exc:
        logger.warning("Dense embedding failed, cannot search: %s", exc)
        return {"query": q, "mode": mode, "results": []}

    try:
        sparse = embed_sparse([q])[0]
    except Exception as exc:
        logger.warning("Sparse embedding failed, using dense-only: %s", exc)
        sparse = ([], [])

    try:
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
                query_dense=[],
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
    except Exception as exc:
        logger.warning("Hybrid search failed: %s", exc)
        return {"query": q, "mode": mode, "results": []}

    # Optional re-rank
    if rerank and results and settings.reranker_enabled:
        from pipeline.reranker import rerank as do_rerank
        results = await asyncio.to_thread(
            do_rerank, q, results, settings.reranker_model
        )

    # Diversify: ensure coverage across sources
    results = _diversify(results)

    for r in results:
        r["highlight"] = _highlight(r["content"][:600], q)

    return {"query": q, "mode": mode, "results": results}
