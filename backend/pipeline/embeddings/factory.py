"""Factory for the three embedder Protocols.

Single source of truth for "which provider does OmniKB use right now".
Settings drive everything; instances are process-cached so the cost
of provider selection logic is paid once per backend lifetime.

Resolution rules
----------------
**Dense:**
    The provider field (``embedding_provider``) chooses sane defaults
    for ``base_url`` + ``api_key``. Explicit ``embedding_base_url`` /
    ``embedding_api_key`` always win, so any OpenAI-compatible gateway
    works without code changes:

    .. code-block:: text

        EMBEDDING_PROVIDER=siliconflow              # → defaults: SF base_url + SF key
        EMBEDDING_PROVIDER=openai                   # → defaults: api.openai.com + OAI key
        EMBEDDING_BASE_URL=https://other.gw/v1      # overrides whichever default
        EMBEDDING_API_KEY=sk-...                    # overrides whichever default

**Sparse:**
    Single implementation today (fastembed BM25). The factory exists
    so the call site doesn't import ``fastembed`` directly — making
    "swap to a different sparse model" a one-class change.

**Reranker:**
    Disabled when ``reranker_enabled=False`` (factory returns ``None``;
    callers MUST handle ``None`` — :func:`pipeline.retrieval.rerank` does).
    Otherwise switches on ``reranker_provider``:

    * ``"local"`` (default) — sentence-transformers CrossEncoder
    * ``"siliconflow"`` — SiliconFlow ``/v1/rerank`` API

    ``reranker_api_key`` falls back to ``siliconflow_api_key`` when empty
    so users with one SF key don't have to duplicate it.

Cache invalidation
------------------
Call :func:`clear_caches` after any settings change that would affect
provider routing. ``api/settings.py`` already does this on the
``POST /settings`` path; tests can call it to reset state between
isolated runs.
"""
from __future__ import annotations

import logging

from .protocols import DenseEmbedder, Reranker, SparseEmbedder

logger = logging.getLogger(__name__)


# Process-cached singletons. Reset by ``clear_caches()``.
_dense: DenseEmbedder | None = None
_sparse: SparseEmbedder | None = None
_reranker: Reranker | None = None
# Sentinel for "factory ran for the reranker, returned None because
# disabled by config" — distinct from "haven't tried yet". Avoids
# rebuilding the reranker (and re-checking settings) on every call.
_reranker_resolved: bool = False


# ── Dense ────────────────────────────────────────────────────


def get_dense_embedder() -> DenseEmbedder:
    """Process-cached dense embedder for the configured provider."""
    global _dense
    if _dense is not None:
        return _dense

    from config import settings
    from .dense import OpenAICompatibleDenseEmbedder

    # Resolve credentials. Explicit overrides always win over
    # provider-specific defaults; this is the single line that lets
    # OmniKB talk to ANY OpenAI-compatible embedding gateway.
    provider = (settings.embedding_provider or "").strip().lower()
    explicit_base = (settings.embedding_base_url or "").strip()
    explicit_key = (settings.embedding_api_key or "").strip()

    if provider == "siliconflow":
        base_url = explicit_base or settings.siliconflow_base_url
        api_key = explicit_key or settings.siliconflow_api_key
    elif provider == "openai":
        base_url = explicit_base or "https://api.openai.com/v1"
        api_key = explicit_key or settings.openai_api_key
    else:
        # Unknown provider but explicit base_url given — treat as a
        # generic OpenAI-compatible gateway.
        if explicit_base:
            base_url = explicit_base
            api_key = explicit_key or settings.openai_api_key
        else:
            logger.warning(
                "embedding_provider=%r is unknown and no embedding_base_url set; "
                "falling back to OpenAI defaults", provider,
            )
            base_url = "https://api.openai.com/v1"
            api_key = explicit_key or settings.openai_api_key

    _dense = OpenAICompatibleDenseEmbedder(
        api_key=api_key,
        base_url=base_url,
        model=settings.embedding_model,
        dim=settings.embedding_dimensions,
        concurrency=settings.embedding_concurrency,
        rpm_limit=settings.embedding_rpm_limit,
        batch_size=settings.embedding_batch_size,
    )
    logger.info(
        "Dense embedder initialised: %s (base_url=%s, dim=%d)",
        _dense.name, base_url, _dense.dim,
    )
    return _dense


# ── Sparse ───────────────────────────────────────────────────


def get_sparse_embedder() -> SparseEmbedder:
    """Process-cached sparse embedder. Always returns an instance —
    its ``embed()`` soft-fails when the model can't load."""
    global _sparse
    if _sparse is not None:
        return _sparse

    from config import settings
    from .sparse import FastEmbedBM25SparseEmbedder

    _sparse = FastEmbedBM25SparseEmbedder(
        fastembed_cache_path=getattr(settings, "fastembed_cache_path", "") or "",
    )
    return _sparse


# ── Reranker ─────────────────────────────────────────────────


def get_reranker() -> Reranker | None:
    """Process-cached reranker, or ``None`` when disabled by settings.

    Callers MUST tolerate ``None`` and skip the rerank step — the only
    real cost of doing so is RAG quality, not correctness.
    """
    global _reranker, _reranker_resolved
    if _reranker_resolved:
        return _reranker

    from config import settings

    if not settings.reranker_enabled:
        _reranker_resolved = True
        return None

    provider = (getattr(settings, "reranker_provider", "") or "local").strip().lower()
    try:
        if provider == "local":
            from .rerankers import LocalCrossEncoderReranker
            _reranker = LocalCrossEncoderReranker(settings.reranker_model)
        elif provider == "siliconflow":
            from .rerankers import SiliconFlowRerankerAPI
            api_key = (
                (getattr(settings, "reranker_api_key", "") or "").strip()
                or settings.siliconflow_api_key
            )
            _reranker = SiliconFlowRerankerAPI(
                api_key=api_key,
                base_url=settings.siliconflow_base_url,
                model=settings.reranker_model,
            )
        else:
            logger.warning(
                "Unknown reranker_provider=%r; falling back to local", provider,
            )
            from .rerankers import LocalCrossEncoderReranker
            _reranker = LocalCrossEncoderReranker(settings.reranker_model)
    except Exception as exc:  # noqa: BLE001
        # Reranker is non-critical — log loudly and serve None so RAG
        # keeps working without it.
        logger.warning(
            "Reranker construction failed (%s) — disabled for this process: %s",
            provider, exc,
        )
        _reranker = None

    _reranker_resolved = True
    if _reranker is not None:
        logger.info("Reranker initialised: %s", _reranker.name)
    return _reranker


# ── Cache management ─────────────────────────────────────────


def clear_caches() -> None:
    """Drop all cached embedder / reranker instances.

    Called from ``api/settings.py`` after credentials / proxy changes
    so the next request rebuilds clients with the new config.
    """
    global _dense, _sparse, _reranker, _reranker_resolved
    if _dense is not None:
        try:
            _dense.close()
        except Exception:  # noqa: BLE001
            pass
    _dense = None
    # Sparse embedder holds an in-memory model — we keep it alive
    # across credential changes because the model isn't credentialed,
    # and tearing it down would force a re-download on the next call.
    # _sparse stays.
    if _reranker is not None:
        try:
            _reranker.close()
        except Exception:  # noqa: BLE001
            pass
    _reranker = None
    _reranker_resolved = False
