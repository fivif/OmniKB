"""Backward-compat shim — delegates to ``pipeline.embeddings`` factory.

The real implementations live in :mod:`pipeline.embeddings.dense` and
:mod:`pipeline.embeddings.sparse`. This module preserves the legacy
public API so 20+ call sites (chat / search / scenarios / mcp / wiki
/ agent_core skill memory) keep working unchanged, AND so
``api/settings.py`` — which reaches into module-level globals for
the ``/settings/models/status`` endpoint — keeps rendering correct
state for the BM25 download UI.

Public surface preserved:

* :func:`embed_dense` / :func:`embed_sparse` — async/sync embed APIs
* :func:`clear_embed_client` — drops the cached HTTP client
* :func:`is_bm25_cached` — disk-cache probe
* :func:`_bm25_bg` — manual background download (called via executor)
* Module attrs ``_embed_cache``, ``_embed_client``, ``_bm25_model``,
  ``_bm25_downloading``, ``_bm25_download_lock`` — read by
  ``/settings/models/status``. Resolved live against the factory
  instance via :pep:`562` module ``__getattr__``.
"""
from __future__ import annotations

from pipeline.embeddings.factory import (
    clear_caches as _factory_clear_caches,
    get_dense_embedder,
    get_sparse_embedder,
)


# ── Dense ─────────────────────────────────────────────────────


async def embed_dense(texts: list[str]) -> list[list[float]]:
    """RAG removed — returns empty vectors."""
    return [[] for _ in texts]


def clear_embed_client() -> None:
    """Discard the cached embedding client so the next call rebuilds it.

    Useful after proxy or credential changes at runtime. Internally
    delegates to :func:`pipeline.embeddings.factory.clear_caches`,
    which also drops the reranker (whose API key may have rotated
    along with the embedder's).
    """
    _factory_clear_caches()


# ── Sparse ────────────────────────────────────────────────────


def embed_sparse(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    """RAG removed — returns empty sparse vectors."""
    return [([], []) for _ in texts]


def is_bm25_cached() -> bool:
    """Check if the BM25 model is already cached on disk (no download needed)."""
    return get_sparse_embedder().is_cached()


def _bm25_bg() -> None:
    """Download BM25 model synchronously (called from the download endpoint)."""
    get_sparse_embedder().background_download()


# ── Legacy module-level globals (read-only proxy via PEP 562) ─


def __getattr__(name: str):
    """Resolve legacy module attrs against the live factory instance.

    ``api/settings.py`` reads ``_embed_cache`` / ``_bm25_model`` / etc.
    directly from the module namespace for the model-status endpoint.
    Routing through PEP 562 keeps those reads coherent with the
    embedder's actual state without any reassignment dance in callers.
    """
    if name == "_embed_cache":
        # Returns the live cache dict — ``.clear()`` from api/settings.py
        # mutates the same dict the embedder reads on the next call.
        return get_dense_embedder().query_cache
    if name == "_embed_client":
        return get_dense_embedder()._client  # noqa: SLF001 — back-compat probe
    if name == "_bm25_model":
        return get_sparse_embedder()._model  # noqa: SLF001
    if name == "_bm25_downloading":
        return get_sparse_embedder()._downloading  # noqa: SLF001
    if name == "_bm25_download_lock":
        return get_sparse_embedder()._download_lock  # noqa: SLF001
    raise AttributeError(f"module 'pipeline.embedder' has no attribute {name!r}")
