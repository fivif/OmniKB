"""Pluggable embedding factory.

Public surface:

* Protocols (for type-hints / Protocol-aware tests):
  :class:`DenseEmbedder`, :class:`SparseEmbedder`, :class:`Reranker`

* Factory:
  :func:`get_dense_embedder`, :func:`get_sparse_embedder`,
  :func:`get_reranker`, :func:`clear_caches`

The legacy module-level functions ``embed_dense`` / ``embed_sparse``
in :mod:`pipeline.embedder` and ``rerank`` in :mod:`pipeline.reranker`
are kept as thin shims that delegate here, so existing call sites
(chat, search, scenarios, MCP, wiki, agent_core skill memory, …)
continue to work without modification.
"""
from .factory import (
    clear_caches,
    get_dense_embedder,
    get_reranker,
    get_sparse_embedder,
)
from .protocols import DenseEmbedder, Reranker, SparseEmbedder

__all__ = [
    "DenseEmbedder",
    "SparseEmbedder",
    "Reranker",
    "get_dense_embedder",
    "get_sparse_embedder",
    "get_reranker",
    "clear_caches",
]
