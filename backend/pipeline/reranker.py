"""Cross-encoder re-ranker for RAG retrieval results.

Uses ``sentence-transformers`` CrossEncoder. The model is loaded lazily
and cached in-process (first call takes ~5-10 s to download).

Default model: BAAI/bge-reranker-v2-m3 (Chinese + English, ~568 MB)
"""
from __future__ import annotations

import logging
from functools import lru_cache

logger = logging.getLogger(__name__)

_reranker_available: bool | None = None  # None=not tried, True=loaded, False=failed


def is_reranker_cached(model_name: str = "BAAI/bge-reranker-v2-m3") -> bool:
    """Check if reranker model is already cached on disk."""
    from pathlib import Path
    dir_name = "models--" + model_name.replace("/", "--")
    cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / dir_name
    return cache_dir.is_dir()


@lru_cache(maxsize=4)
def _load_model(model_name: str):
    from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]
    return CrossEncoder(model_name)


def _init_reranker(model_name: str, timeout: float = 20.0, force: bool = False) -> bool:
    """Try to load the reranker model with a timeout. Returns True if loaded.

    Set ``force=True`` to retry after a previous failure (called from the
    download endpoint, not from the search/chat code-path).
    """
    global _reranker_available
    if _reranker_available is not None and not force:
        return _reranker_available
    import threading
    result = [None]

    def _load():
        try:
            result[0] = _load_model(model_name)
        except Exception:
            pass

    t = threading.Thread(target=_load, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if result[0] is not None:
        _reranker_available = True
        logger.info("Reranker model loaded successfully")
    else:
        _reranker_available = False
        logger.warning("Reranker model download timed out (%.0fs) — reranking disabled", timeout)
    return _reranker_available


def rerank(
    query: str,
    chunks: list[dict],
    model_name: str,
    top_n: int | None = None,
) -> list[dict]:
    """Re-rank *chunks* using a cross-encoder model.

    When the model is unavailable (download failed / timed out), returns
    chunks unchanged — the call is a no-op.

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
    global _reranker_available
    if _reranker_available is False:
        return chunks[:top_n] if top_n else chunks
    if not chunks:
        return chunks

    try:
        model = _load_model(model_name)
        _reranker_available = True
    except Exception as exc:
        _reranker_available = False
        logger.warning("Reranker model unavailable: %s — skipping rerank", exc)
        return chunks[:top_n] if top_n else chunks

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
