"""Backward-compat shim — delegates to ``pipeline.embeddings`` factory.

The real implementations live in :mod:`pipeline.embeddings.rerankers`.
This module preserves the legacy public API:

* :func:`rerank` — sync facade. Internally awaits the async rerank
  protocol method on a private event loop when called outside one.
* :func:`is_reranker_cached` — disk-cache probe (local cross-encoder).
* :func:`_init_reranker` — manual download / retry trigger.
* Module attr ``_reranker_available`` — read by
  ``/settings/models/status``. Resolved live against the factory
  instance via PEP 562 ``__getattr__``.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from pipeline.embeddings.factory import get_reranker
from pipeline.embeddings.rerankers import LocalCrossEncoderReranker

logger = logging.getLogger(__name__)


def is_reranker_cached(model_name: str = "BAAI/bge-reranker-v2-m3") -> bool:
    """Check if the cross-encoder reranker model is already cached on disk."""
    return LocalCrossEncoderReranker.is_cached(model_name)


def _init_reranker(model_name: str, timeout: float = 20.0, force: bool = False) -> bool:
    """Try to load the (local) reranker model with a timeout.

    Set ``force=True`` to retry after a previous failure (called from
    ``/settings/models/download``). The factory must currently be
    routing to a local reranker for this to do work — if it's pointed
    at a cloud API, the call is a no-op (cloud rerankers have nothing
    to download).
    """
    rr = get_reranker()
    if rr is None:
        logger.debug("_init_reranker: reranker disabled in settings")
        return False
    if isinstance(rr, LocalCrossEncoderReranker):
        return rr.initialize(timeout_seconds=timeout, force=force)
    # Cloud reranker — nothing to download / preload.
    return rr.is_available


def rerank(
    query: str,
    chunks: list[dict],
    model_name: str,
    top_n: int | None = None,
) -> list[dict]:
    """Re-rank *chunks* using the configured reranker provider.

    Synchronous facade for the async :class:`Reranker.rerank`. Most
    callers (``pipeline.retrieval.rerank``) are already inside an
    event loop, but this function is sync to preserve the legacy
    contract. We dispatch through :func:`asyncio.run` only when no
    loop is running; otherwise we raise so the caller knows to await
    directly.

    The ``model_name`` argument is kept for API stability but is
    actually controlled by ``settings.reranker_model`` — passing a
    different value here logs a one-shot warning and is otherwise
    ignored. (Switching models at request time would require
    rebuilding the cross-encoder, which is too expensive to do per
    call.)

    Returns chunks with a ``rerank_score`` key added, sorted desc.
    Soft-fails to pass-through when the reranker is unavailable.
    """
    rr = get_reranker()
    if rr is None:
        return chunks[:top_n] if top_n else chunks

    if model_name and model_name != getattr(rr, "_model_name", None) \
            and model_name != getattr(rr, "_model", None):
        # Log once per process — see legacy comment block.
        _warn_model_override_once(model_name, rr.name)

    # Dispatch the async call. We accept being called from inside or
    # outside an event loop:
    #   - Outside (rare; offline scripts): use asyncio.run.
    #   - Inside (the hot path, FastAPI request handler): we can't
    #     re-enter the loop, so we tell the caller to switch.
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(rr.rerank(query, chunks, top_n))
    raise RuntimeError(
        "rerank() called from inside an event loop — use "
        "`await get_reranker().rerank(query, chunks, top_n)` instead. "
        "Legacy sync facade is for offline scripts only."
    )


# ── Legacy module-level globals (read-only proxy via PEP 562) ─


_warned_model_overrides: set[str] = set()


def _warn_model_override_once(requested: str, actual: str) -> None:
    if requested in _warned_model_overrides:
        return
    _warned_model_overrides.add(requested)
    logger.warning(
        "rerank() ignored model_name=%r — using %r from settings. "
        "Set RERANKER_MODEL=%r to switch.",
        requested, actual, requested,
    )


def __getattr__(name: str) -> Any:
    if name == "_reranker_available":
        rr = get_reranker()
        if rr is None:
            return False
        # Local reranker tracks ``_available`` (None|True|False).
        # Cloud reranker tracks ``_available`` (bool). Both share the
        # name — return as-is so the status endpoint's None|True|False
        # discriminator keeps working.
        return getattr(rr, "_available", rr.is_available)
    raise AttributeError(f"module 'pipeline.reranker' has no attribute {name!r}")
