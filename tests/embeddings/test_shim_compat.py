"""Backward-compat shim tests.

Verifies the legacy ``pipeline.embedder`` and ``pipeline.reranker``
public APIs still work the way 20+ existing call sites expect:

* Module-level ``embed_dense`` / ``embed_sparse`` / ``rerank`` keep
  their signatures.
* The PEP 562 ``__getattr__`` proxies expose live state (``_embed_cache``,
  ``_bm25_model``, ``_reranker_available``, …) so ``api/settings.py``'s
  model-status endpoint keeps rendering correct UI.
"""
from __future__ import annotations

import pytest


# ── Public API surface ─────────────────────────────────────────


def test_embedder_module_exports_legacy_api():
    """The known callers import these names — make sure they exist."""
    from pipeline.embedder import (  # noqa: F401
        embed_dense,
        embed_sparse,
        clear_embed_client,
        is_bm25_cached,
        _bm25_bg,
    )


def test_reranker_module_exports_legacy_api():
    from pipeline.reranker import (  # noqa: F401
        rerank,
        is_reranker_cached,
        _init_reranker,
    )


# ── Live module-attr proxying ─────────────────────────────────


def test_embed_cache_proxy_returns_live_dict(monkeypatch):
    """``_embed_cache.clear()`` from api/settings.py must reach the live cache."""
    import pipeline.embedder as e

    cache = e._embed_cache  # PEP 562 dispatch
    assert isinstance(cache, dict)

    # Mutating the returned dict must be visible to the embedder instance.
    cache["seed"] = ([0.1, 0.2], 0.0)
    from pipeline.embeddings import get_dense_embedder
    assert get_dense_embedder().query_cache.get("seed") == ([0.1, 0.2], 0.0)

    # And ``.clear()`` from the legacy code path drops the entries.
    e._embed_cache.clear()
    assert "seed" not in get_dense_embedder().query_cache


def test_bm25_globals_proxy_match_factory_state():
    import pipeline.embedder as e
    from pipeline.embeddings import get_sparse_embedder

    s = get_sparse_embedder()
    # Untriggered: both views report None / False.
    assert e._bm25_model is None
    assert e._bm25_downloading is False
    assert e._bm25_download_lock is False
    assert s._model is None

    # Simulate a successful load — proxy should reflect immediately.
    s._model = "FAKE-MODEL"
    s._downloading = True
    try:
        assert e._bm25_model == "FAKE-MODEL"
        assert e._bm25_downloading is True
    finally:
        s._model = None
        s._downloading = False


def test_unknown_attr_raises():
    """Module __getattr__ must NOT silently swallow typos."""
    import pipeline.embedder as e
    with pytest.raises(AttributeError):
        _ = e._not_a_real_attr


def test_reranker_available_proxy(monkeypatch):
    """Reflects the local reranker's tri-state availability flag."""
    from config import settings
    monkeypatch.setattr(settings, "reranker_enabled", True)
    monkeypatch.setattr(settings, "reranker_provider", "local")
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-v2-m3")

    import pipeline.reranker as r
    from pipeline.embeddings import get_reranker

    rr = get_reranker()
    rr._available = None
    assert r._reranker_available is None

    rr._available = True
    assert r._reranker_available is True

    rr._available = False
    assert r._reranker_available is False


def test_reranker_available_when_disabled(monkeypatch):
    """When reranker is disabled, the legacy global must report False
    (legacy callers used False to mean 'don't render the badge')."""
    from config import settings
    monkeypatch.setattr(settings, "reranker_enabled", False)

    import pipeline.reranker as r
    assert r._reranker_available is False
