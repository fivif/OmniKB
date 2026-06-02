"""Factory routing tests.

The factory's job: read settings, build the right concrete class
once, return it process-wide. We mutate ``settings`` per test (the
autouse ``_reset_factory_cache`` fixture in conftest drops the
singletons before each test) and verify the right class + params
come out the other side.
"""
from __future__ import annotations

import pytest

from config import settings
from pipeline.embeddings import (
    clear_caches,
    get_dense_embedder,
    get_reranker,
    get_sparse_embedder,
)
from pipeline.embeddings.dense import OpenAICompatibleDenseEmbedder
from pipeline.embeddings.rerankers import (
    LocalCrossEncoderReranker,
    SiliconFlowRerankerAPI,
)
from pipeline.embeddings.sparse import FastEmbedBM25SparseEmbedder


# ── Dense routing ──────────────────────────────────────────────


def test_dense_siliconflow_defaults(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "siliconflow")
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "siliconflow_base_url", "https://siliconflow/v1")
    monkeypatch.setattr(settings, "siliconflow_api_key", "sf-key")
    monkeypatch.setattr(settings, "embedding_model", "bge-m3")
    monkeypatch.setattr(settings, "embedding_dimensions", 1024)

    e = get_dense_embedder()
    assert isinstance(e, OpenAICompatibleDenseEmbedder)
    assert e.model == "bge-m3"
    assert e.dim == 1024
    assert e._base_url == "https://siliconflow/v1"
    assert e._api_key == "sf-key"


def test_dense_openai_defaults(monkeypatch):
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "embedding_base_url", "")
    monkeypatch.setattr(settings, "embedding_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key", "sk-oai")

    e = get_dense_embedder()
    assert e._base_url == "https://api.openai.com/v1"
    assert e._api_key == "sk-oai"


def test_dense_explicit_base_url_overrides_defaults(monkeypatch):
    """Setting EMBEDDING_BASE_URL should override the provider's default."""
    monkeypatch.setattr(settings, "embedding_provider", "siliconflow")
    monkeypatch.setattr(settings, "embedding_base_url", "https://my-gateway.example.com/v1")
    monkeypatch.setattr(settings, "embedding_api_key", "custom-key")

    e = get_dense_embedder()
    assert e._base_url == "https://my-gateway.example.com/v1"
    assert e._api_key == "custom-key"


def test_dense_unknown_provider_with_explicit_base_url(monkeypatch):
    """Unknown provider + explicit base_url → treat as generic gateway."""
    monkeypatch.setattr(settings, "embedding_provider", "voyage-oai")
    monkeypatch.setattr(settings, "embedding_base_url", "https://api.voyageai.com/v1")
    monkeypatch.setattr(settings, "embedding_api_key", "voyage-key")

    e = get_dense_embedder()
    assert e._base_url == "https://api.voyageai.com/v1"
    assert e._api_key == "voyage-key"


def test_dense_singleton_caching(monkeypatch):
    """Two calls return the same instance — until clear_caches()."""
    monkeypatch.setattr(settings, "embedding_provider", "siliconflow")

    e1 = get_dense_embedder()
    e2 = get_dense_embedder()
    assert e1 is e2

    clear_caches()
    e3 = get_dense_embedder()
    assert e3 is not e1


# ── Sparse routing ─────────────────────────────────────────────


def test_sparse_returns_fastembed_instance():
    s = get_sparse_embedder()
    assert isinstance(s, FastEmbedBM25SparseEmbedder)
    assert get_sparse_embedder() is s  # cached


# ── Reranker routing ──────────────────────────────────────────


def test_reranker_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", False)
    assert get_reranker() is None


def test_reranker_local_provider(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", True)
    monkeypatch.setattr(settings, "reranker_provider", "local")
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-v2-m3")

    r = get_reranker()
    assert isinstance(r, LocalCrossEncoderReranker)
    assert r._model_name == "BAAI/bge-reranker-v2-m3"


def test_reranker_siliconflow_provider(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", True)
    monkeypatch.setattr(settings, "reranker_provider", "siliconflow")
    monkeypatch.setattr(settings, "reranker_api_key", "rr-key")
    monkeypatch.setattr(settings, "siliconflow_base_url", "https://api.siliconflow.cn/v1")
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-v2-m3")

    r = get_reranker()
    assert isinstance(r, SiliconFlowRerankerAPI)
    assert r._api_key == "rr-key"
    assert r._base_url == "https://api.siliconflow.cn/v1"


def test_reranker_siliconflow_falls_back_to_siliconflow_api_key(monkeypatch):
    """Empty reranker_api_key → re-uses siliconflow_api_key (single-key setups)."""
    monkeypatch.setattr(settings, "reranker_enabled", True)
    monkeypatch.setattr(settings, "reranker_provider", "siliconflow")
    monkeypatch.setattr(settings, "reranker_api_key", "")
    monkeypatch.setattr(settings, "siliconflow_api_key", "sf-shared")
    monkeypatch.setattr(settings, "siliconflow_base_url", "https://api.siliconflow.cn/v1")

    r = get_reranker()
    assert r._api_key == "sf-shared"


def test_reranker_unknown_provider_falls_back_to_local(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", True)
    monkeypatch.setattr(settings, "reranker_provider", "cohere-noop")
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-v2-m3")

    r = get_reranker()
    assert isinstance(r, LocalCrossEncoderReranker)


def test_reranker_resolved_sentinel_remembers_disabled(monkeypatch):
    """Once we resolve to None (disabled), don't re-evaluate settings on every call."""
    monkeypatch.setattr(settings, "reranker_enabled", False)
    assert get_reranker() is None

    # Re-enable AFTER first None resolution; without clear_caches the
    # factory should keep returning None (sentinel).
    monkeypatch.setattr(settings, "reranker_enabled", True)
    assert get_reranker() is None  # still None — sentinel held

    clear_caches()
    monkeypatch.setattr(settings, "reranker_provider", "local")
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-v2-m3")
    assert get_reranker() is not None  # re-resolved


# ── Cache invalidation ───────────────────────────────────────


def test_clear_caches_drops_dense_and_reranker(monkeypatch):
    monkeypatch.setattr(settings, "reranker_enabled", True)
    monkeypatch.setattr(settings, "reranker_provider", "local")
    monkeypatch.setattr(settings, "reranker_model", "BAAI/bge-reranker-v2-m3")

    d1 = get_dense_embedder()
    r1 = get_reranker()
    s1 = get_sparse_embedder()

    clear_caches()

    d2 = get_dense_embedder()
    r2 = get_reranker()
    s2 = get_sparse_embedder()

    assert d2 is not d1, "dense embedder must be rebuilt"
    assert r2 is not r1, "reranker must be rebuilt"
    # Sparse explicitly survives clear_caches — see factory.clear_caches docstring.
    assert s2 is s1, "sparse embedder is preserved across clear_caches"
