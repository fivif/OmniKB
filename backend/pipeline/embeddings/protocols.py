"""Protocol definitions for OmniKB's three embedding flavours.

All three are pluggable through the :mod:`pipeline.embeddings.factory`
module — settings determine which concrete class the factory hands
out. Adding a new provider means adding a class that satisfies one
of these Protocols and a branch in :func:`factory.get_*_embedder`,
NOT touching the call sites (chat, search, scenarios, mcp, wiki,
agent_core skill memory, …).

Why three Protocols instead of one
----------------------------------
The three workloads have fundamentally different shapes:

* **Dense** is async (REST round-trip), per-query batched, returns
  fixed-dimension float vectors. Cache hits matter a lot (chat repeats
  the same user query across turns) so the protocol owns its query
  cache.
* **Sparse** is sync (CPU-local fastembed BM25), returns variable-length
  ``(indices, values)`` tuples, MAY be unavailable when the model
  download fails — implementations soft-fail with empty vectors so
  retrieval gracefully falls back to dense-only.
* **Reranker** is async (mix of HTTP and local sentence-transformers),
  takes a query plus candidate dicts, returns the same dicts sorted
  with an injected ``rerank_score`` field. Soft-fails by passing
  through unchanged when unavailable.

A single uber-protocol would have to admit None / Optional fields for
features that don't apply, which is the abstraction equivalent of
saying nothing.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DenseEmbedder(Protocol):
    """Async dense vector embedder (OpenAI / SiliconFlow / any gateway).

    Implementations MUST:

    * return one fixed-dimension float vector per input text;
    * raise on hard provider errors so the caller can decide whether
      to surface or swallow (see ``api/scenarios.py`` agent search
      catching a soft-fail vs. ``mcp_server.tools`` returning ``[]``);
    * own their own batching / retry / rate-limiting — the Protocol
      keeps the public surface small.
    """

    name: str
    """Stable identifier for logs / metrics, e.g. ``"openai-compat:bge-m3"``."""

    dim: int
    """Output dimensionality. Must match the Qdrant collection that
    will receive the vectors — re-creating the collection is currently
    the only way to change ``dim`` safely."""

    model: str
    """Provider-specific model identifier passed in the API request."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed *texts*. Returns one vector per input, in the same order."""
        ...

    def close(self) -> None:
        """Release HTTP / network resources (used by ``clear_caches()``).
        Implementations that hold no resources may no-op."""
        ...


@runtime_checkable
class SparseEmbedder(Protocol):
    """Sync sparse vector embedder (BM25-style, fastembed today).

    Soft-fail contract:
        When :attr:`is_available` is False, :meth:`embed` returns
        empty ``([], [])`` tuples instead of raising. This lets
        retrieval fall back to dense-only without try/except in every
        call site (chat, search, scenarios, MCP, …).
    """

    name: str

    def embed(self, texts: list[str]) -> list[tuple[list[int], list[float]]]:
        """Return ``(indices, values)`` per text. Empty tuples when unavailable."""
        ...

    @property
    def is_available(self) -> bool:
        """True once the underlying model is loaded successfully."""
        ...


@runtime_checkable
class Reranker(Protocol):
    """Cross-encoder reranker (local sentence-transformers OR cloud API).

    Soft-fail contract:
        When :attr:`is_available` is False, :meth:`rerank` returns the
        input chunks unchanged (sliced to ``top_n`` if provided). The
        caller never has to know whether the reranker is up.
    """

    name: str

    async def rerank(
        self,
        query: str,
        chunks: list[dict],
        top_n: int | None = None,
    ) -> list[dict]:
        """Re-sort *chunks* by relevance to *query*.

        Returns a new list of dicts (originals not mutated). Each
        returned dict has a ``rerank_score`` key added — useful for
        UI / debugging even when scores are unitless across providers.
        """
        ...

    @property
    def is_available(self) -> bool:
        """True once the model / API is confirmed reachable."""
        ...
