from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from config import settings
from pipeline.embedder import embed_dense, embed_sparse
from storage.vector_store import hybrid_search

logger = logging.getLogger(__name__)


@dataclass
class RetrievalResult:
    query: str
    results: list[dict]
    expanded: bool = False
    error: str | None = None


def normalize_query(query: str) -> str:
    """Normalize query for better matching across Chinese KB content."""
    normalized = query.strip()
    normalized = re.sub(r'(\d+)T(?=[^a-zA-Z]|$)', r'\1T \1万亿', normalized)
    normalized = re.sub(r'(\d{4})年(\d{1,2})月(\d{1,2})日', r'\1/\2/\3 \1年\2月\3日', normalized)
    return normalized


def diversify_results(results: list[dict], max_per_source: int = 3) -> list[dict]:
    """Prevent a single source from crowding out the rest of the KB."""
    seen_per_source: dict[str, int] = {}
    diversified: list[dict] = []
    remainder: list[dict] = []
    for result in results:
        source_id = result.get("metadata", {}).get("source_id", "")
        if not source_id:
            diversified.append(result)
            continue
        if seen_per_source.get(source_id, 0) < max_per_source:
            diversified.append(result)
            seen_per_source[source_id] = seen_per_source.get(source_id, 0) + 1
        else:
            remainder.append(result)
    return diversified + remainder


async def _run_single_retrieval(
    query: str,
    top_k: int,
    filters: dict[str, Any] | None,
    mode: str,
    qdrant_filter: Any = None,
) -> list[dict]:
    dense_query: list[float] = []
    sparse_indices: list[int] = []
    sparse_values: list[float] = []

    if mode != "bm25":
        try:
            dense_query = (await embed_dense([query]))[0]
        except Exception as exc:
            logger.warning("Dense embedding failed, cannot retrieve: %s", exc)
            return []

    if mode != "semantic":
        try:
            sparse = embed_sparse([query])[0]
            sparse_indices, sparse_values = sparse[0], sparse[1]
        except Exception as exc:
            logger.warning("Sparse embedding failed, using dense-only: %s", exc)

    try:
        if mode == "semantic":
            return await hybrid_search(
                query_dense=dense_query,
                query_sparse_indices=[],
                query_sparse_values=[],
                top_k=top_k,
                filters=filters,
                qdrant_filter=qdrant_filter,
            )
        if mode == "bm25":
            if not sparse_indices:
                return []
            return await hybrid_search(
                query_dense=[],
                query_sparse_indices=sparse_indices,
                query_sparse_values=sparse_values,
                top_k=top_k,
                filters=filters,
                qdrant_filter=qdrant_filter,
            )
        return await hybrid_search(
            query_dense=dense_query,
            query_sparse_indices=sparse_indices,
            query_sparse_values=sparse_values,
            top_k=top_k,
            filters=filters,
            qdrant_filter=qdrant_filter,
        )
    except Exception as exc:
        logger.exception("Hybrid search failed")
        return []


async def _maybe_rerank(query: str, results: list[dict], rerank: bool) -> list[dict]:
    if not rerank or not results or not settings.reranker_enabled:
        return results
    # Pulls from the unified embedding factory; the concrete reranker
    # (LocalCrossEncoderReranker / SiliconFlowRerankerAPI / future
    # Cohere / Jina) is selected by ``settings.reranker_provider`` and
    # cached process-wide. The local impl already offloads model.predict
    # to a worker thread, so we await the protocol method directly
    # instead of doing a sync call inside ``asyncio.to_thread``.
    from pipeline.embeddings import get_reranker
    rr = get_reranker()
    if rr is None:
        return results
    return await rr.rerank(query, results)


async def retrieve_chunks(
    query: str,
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
    mode: str = "hybrid",
    rerank: bool = True,
    diversify: bool = True,
    expand: bool = True,
    fetch_k: int | None = None,
    post_filter: Callable[[dict], bool] | None = None,
    qdrant_filter: Any = None,
) -> RetrievalResult:
    normalized_query = normalize_query(query)
    fetch_limit = max(top_k, fetch_k or top_k)

    def _apply_post_filter(results: list[dict]) -> list[dict]:
        if post_filter is None:
            return results
        return [result for result in results if post_filter(result)]

    if expand and mode == "hybrid":
        try:
            from pipeline.query_expander import expand_query, merge_results, should_expand
        except ImportError:
            should_expand = None
        if should_expand and should_expand(normalized_query):
            sub_queries = expand_query(normalized_query)
            if len(sub_queries) > 1:
                all_results = []
                per_query_top_k = max(3, fetch_limit)
                for sub_query in sub_queries:
                    sub_results = await _run_single_retrieval(
                        query=sub_query,
                        top_k=per_query_top_k,
                        filters=filters,
                        mode="hybrid",
                        qdrant_filter=qdrant_filter,
                    )
                    all_results.append(sub_results)

                results = merge_results(all_results, max_total=max(fetch_limit * 2, top_k))
                results = _apply_post_filter(results)
                results = await _maybe_rerank(normalized_query, results, rerank)
                if diversify:
                    results = diversify_results(results)
                return RetrievalResult(
                    query=normalized_query,
                    results=results[:top_k],
                    expanded=True,
                )

    results = await _run_single_retrieval(
        query=normalized_query,
        top_k=fetch_limit,
        filters=filters,
        mode=mode,
        qdrant_filter=qdrant_filter,
    )
    results = _apply_post_filter(results)
    results = await _maybe_rerank(normalized_query, results, rerank)
    if diversify:
        results = diversify_results(results)
    return RetrievalResult(query=normalized_query, results=results[:top_k], expanded=False)