"""Tests for sparse + reranker implementations.

We avoid touching real fastembed / sentence-transformers downloads
in CI by:

* For sparse: forcing the load path to fail and verifying the
  soft-fail returns empty tuples.
* For local reranker: setting the internal sentinel so it short-circuits
  to pass-through, then verifying the score injection path with a
  monkey-patched ``_load_cross_encoder``.
* For SiliconFlow API reranker: monkey-patching the imported ``httpx``
  module so we control HTTP responses without network.
"""
from __future__ import annotations

import pytest

from pipeline.embeddings.protocols import Reranker, SparseEmbedder
from pipeline.embeddings.rerankers import (
    LocalCrossEncoderReranker,
    SiliconFlowRerankerAPI,
)
from pipeline.embeddings.sparse import FastEmbedBM25SparseEmbedder


# ── Sparse ──────────────────────────────────────────────────────


def test_sparse_satisfies_protocol():
    s = FastEmbedBM25SparseEmbedder()
    assert isinstance(s, SparseEmbedder)
    assert s.name == "fastembed:bm25"


def test_sparse_soft_fails_when_model_unavailable(monkeypatch):
    """If the model load raises, embed() returns empty tuples (one per text)."""
    s = FastEmbedBM25SparseEmbedder()

    def boom(self):
        raise RuntimeError("network down")

    monkeypatch.setattr(FastEmbedBM25SparseEmbedder, "_try_load", boom)
    out = s.embed(["a", "b", "c"])
    assert out == [([], []), ([], []), ([], [])]
    # Once marked unavailable, subsequent calls don't retry — keeps
    # the request hot path fast.
    assert s._model is False
    assert s.is_available is False


def test_sparse_returns_real_vectors_when_loaded(monkeypatch):
    """When the underlying model returns sparse vectors, we forward them."""

    class _Emb:
        def __init__(self, idx, vals):
            class _Arr:
                def __init__(self, lst):
                    self._lst = lst

                def tolist(self):
                    return self._lst

            self.indices = _Arr(idx)
            self.values = _Arr(vals)

    class _Model:
        def embed(self, texts):
            for i, _t in enumerate(texts):
                yield _Emb([i, i + 1], [0.5, 0.25])

    s = FastEmbedBM25SparseEmbedder()
    s._model = _Model()  # bypass the lazy-load path

    out = s.embed(["one", "two"])
    assert out == [([0, 1], [0.5, 0.25]), ([1, 2], [0.5, 0.25])]
    assert s.is_available is True


# ── Local reranker ──────────────────────────────────────────────


def test_local_reranker_satisfies_protocol():
    r = LocalCrossEncoderReranker("BAAI/bge-reranker-v2-m3")
    assert isinstance(r, Reranker)
    assert r.name.startswith("local-cross-encoder:")


@pytest.mark.asyncio
async def test_local_reranker_soft_fails_when_unavailable():
    r = LocalCrossEncoderReranker("BAAI/bge-reranker-v2-m3")
    r._available = False  # simulate previous load failure
    chunks = [{"content": f"c-{i}"} for i in range(3)]
    out = await r.rerank("q", chunks, top_n=2)
    # Pass-through, sliced to top_n; original chunks not mutated.
    assert out == chunks[:2]
    assert "rerank_score" not in chunks[0]


@pytest.mark.asyncio
async def test_local_reranker_sorts_by_predicted_score(monkeypatch):
    """When the model loads, chunks must come out sorted desc by predict()."""

    class _FakeModel:
        def predict(self, pairs):
            # Score = -len(content) so longer content sinks lower; lets us
            # assert the ordering deterministically.
            return [-len(c) for _q, c in pairs]

    monkeypatch.setattr(
        "pipeline.embeddings.rerankers._load_cross_encoder",
        lambda name: _FakeModel(),
    )
    r = LocalCrossEncoderReranker("BAAI/bge-reranker-v2-m3")
    r._available = None  # force fresh load via patched fn

    chunks = [
        {"content": "longer content"},
        {"content": "x"},
        {"content": "medium"},
    ]
    out = await r.rerank("q", chunks)

    # "x" has the highest score (-1) → first.
    assert [c["content"] for c in out] == ["x", "medium", "longer content"]
    assert all("rerank_score" in c for c in out)
    assert out[0]["rerank_score"] > out[-1]["rerank_score"]


@pytest.mark.asyncio
async def test_local_reranker_empty_chunks_returns_empty():
    r = LocalCrossEncoderReranker("BAAI/bge-reranker-v2-m3")
    assert await r.rerank("q", []) == []


# ── SiliconFlow API reranker ────────────────────────────────────


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class _FakeAsyncClient:
    """Drop-in replacement for httpx.AsyncClient used in tests."""

    def __init__(self, response):
        self._response = response
        self.posts: list[tuple[str, dict, dict]] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, *, headers, json):
        self.posts.append((url, headers, json))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def _patch_httpx(monkeypatch, response_or_exc):
    """Make ``import httpx`` inside the reranker resolve to a fake client."""
    import sys
    import types

    fake_httpx = types.SimpleNamespace()
    captured = {"client": None}

    def AsyncClient(timeout=None):  # noqa: N802 — match httpx API
        client = _FakeAsyncClient(response_or_exc)
        captured["client"] = client
        return client

    fake_httpx.AsyncClient = AsyncClient
    monkeypatch.setitem(sys.modules, "httpx", fake_httpx)
    return captured


def _build_api_reranker(**overrides):
    defaults = dict(
        api_key="sk-test",
        base_url="https://api.siliconflow.cn/v1",
        model="BAAI/bge-reranker-v2-m3",
    )
    defaults.update(overrides)
    return SiliconFlowRerankerAPI(**defaults)


def test_siliconflow_reranker_satisfies_protocol():
    r = _build_api_reranker()
    assert isinstance(r, Reranker)
    assert r.is_available


@pytest.mark.asyncio
async def test_siliconflow_reranker_happy_path(monkeypatch):
    payload = {"results": [
        {"index": 2, "relevance_score": 0.95},
        {"index": 0, "relevance_score": 0.75},
        {"index": 1, "relevance_score": 0.25},
    ]}
    captured = _patch_httpx(monkeypatch, _FakeResponse(payload))

    r = _build_api_reranker()
    chunks = [{"content": f"c-{i}"} for i in range(3)]
    out = await r.rerank("q", chunks)

    # Sorted desc by relevance_score.
    assert [c["content"] for c in out] == ["c-2", "c-0", "c-1"]
    assert out[0]["rerank_score"] == 0.95
    assert out[-1]["rerank_score"] == 0.25
    # API was called once with the right shape.
    posts = captured["client"].posts
    assert len(posts) == 1
    url, headers, body = posts[0]
    assert url == "https://api.siliconflow.cn/v1/rerank"
    assert headers["Authorization"] == "Bearer sk-test"
    assert body["model"] == "BAAI/bge-reranker-v2-m3"
    assert body["query"] == "q"
    assert body["documents"] == ["c-0", "c-1", "c-2"]


@pytest.mark.asyncio
async def test_siliconflow_reranker_soft_fails_on_http_error(monkeypatch):
    """Network glitch → return chunks unchanged, mark unavailable for next call."""
    _patch_httpx(monkeypatch, RuntimeError("connection refused"))

    r = _build_api_reranker()
    chunks = [{"content": f"c-{i}"} for i in range(3)]
    out = await r.rerank("q", chunks, top_n=2)

    # Returned unchanged (no rerank_score injected) and sliced to top_n.
    assert out == chunks[:2]
    assert r.is_available is False


@pytest.mark.asyncio
async def test_siliconflow_reranker_missing_api_key_short_circuits(monkeypatch):
    """An empty api_key is a configuration error — disable, don't crash."""
    captured = _patch_httpx(monkeypatch, _FakeResponse({}))  # never reached

    r = _build_api_reranker(api_key="")
    chunks = [{"content": "x"}]
    out = await r.rerank("q", chunks)
    assert out == chunks
    assert r.is_available is False
    # No HTTP call attempted.
    assert captured["client"] is None


@pytest.mark.asyncio
async def test_siliconflow_reranker_top_n_slicing(monkeypatch):
    payload = {"results": [
        {"index": 0, "relevance_score": 0.9},
        {"index": 1, "relevance_score": 0.5},
        {"index": 2, "relevance_score": 0.1},
    ]}
    _patch_httpx(monkeypatch, _FakeResponse(payload))

    r = _build_api_reranker()
    chunks = [{"content": f"c-{i}"} for i in range(3)]
    out = await r.rerank("q", chunks, top_n=2)
    assert len(out) == 2
    assert [c["content"] for c in out] == ["c-0", "c-1"]
