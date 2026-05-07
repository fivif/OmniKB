"""Cross-encoder re-ranker for RAG retrieval results.

Uses ``sentence-transformers`` CrossEncoder. The model is loaded lazily
and cached in-process (first call takes ~5-10 s to download).

Default model: BAAI/bge-reranker-v2-m3 (Chinese + English, ~568 MB)
"""
from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=4)
def _load_model(model_name: str):
    from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]
    return CrossEncoder(model_name)


def rerank(
    query: str,
    chunks: list[dict],
    model_name: str,
    top_n: int | None = None,
) -> list[dict]:
    """Re-rank *chunks* using a cross-encoder model.

    Parameters
    ----------
    query:
        The user's original query.
    chunks:
        List of chunk dicts with at least a ``content`` key.
    model_name:
        HuggingFace model ID, e.g. ``BAAI/bge-reranker-v2-m3``.
    top_n:
        Return only the top-*n* results. ``None`` returns all.

    Returns
    -------
    list[dict]
        Same dicts, sorted by ``rerank_score`` descending, with the
        ``rerank_score`` key added to each entry.
    """
    if not chunks:
        return chunks

    model = _load_model(model_name)
    pairs = [(query, c["content"]) for c in chunks]
    scores = model.predict(pairs)

    # scores may be a numpy array — convert to plain floats
    score_list = scores.tolist() if hasattr(scores, "tolist") else list(scores)

    ranked = sorted(
        zip(score_list, chunks),
        key=lambda x: x[0],
        reverse=True,
    )

    result = []
    for score, chunk in ranked:
        c = dict(chunk)
        c["rerank_score"] = round(float(score), 4)
        result.append(c)

    return result[:top_n] if top_n else result
