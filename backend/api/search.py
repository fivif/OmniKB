from __future__ import annotations
import logging
import re

from fastapi import APIRouter, Query

from config import settings
from pipeline.retrieval import retrieve_chunks

router = APIRouter()
logger = logging.getLogger(__name__)


def _highlight(text: str, query: str) -> str:
    """Wrap query terms in <mark> tags (case-insensitive)."""
    terms = [re.escape(t) for t in query.split() if len(t) > 1]
    if not terms:
        return text
    # Cap at 10 terms to prevent ReDoS via pathological alternation regex
    terms = terms[:10]
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
    filters: dict = {}
    if filter_source:
        filters["source_id"] = filter_source
    if filter_type:
        filters["source_type"] = filter_type

    retrieval = await retrieve_chunks(
        query=q,
        top_k=top_k,
        filters=filters or None,
        mode=mode,
        rerank=rerank,
        diversify=True,
        expand=True,
    )
    results = retrieval.results

    for r in results:
        r["highlight"] = _highlight(r["content"][:600], retrieval.query)

    mode_label = f"{mode}+expanded" if retrieval.expanded else mode
    return {"query": retrieval.query, "mode": mode_label, "results": results}
