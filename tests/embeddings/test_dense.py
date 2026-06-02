"""Tests for OpenAICompatibleDenseEmbedder.

We mock ``AsyncOpenAI.embeddings.create`` so no real HTTP traffic is
involved. The class under test owns batching, caching, semaphore and
RPM throttling; we verify each invariant independently.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from pipeline.embeddings.dense import OpenAICompatibleDenseEmbedder
from pipeline.embeddings.protocols import DenseEmbedder


def _stub_resp(vectors: list[list[float]]):
    """Mimic the AsyncOpenAI embeddings.create response shape."""
    class _Item:
        def __init__(self, embedding):
            self.embedding = embedding

    class _Resp:
        def __init__(self, vecs):
            self.data = [_Item(v) for v in vecs]

    return _Resp(vectors)


def _build_embedder(**overrides) -> OpenAICompatibleDenseEmbedder:
    defaults = dict(
        api_key="test-key",
        base_url="https://x.example.com/v1",
        model="bge-m3",
        dim=4,
        concurrency=2,
        rpm_limit=0,  # disable RPM in unit tests by default
        batch_size=2,
    )
    defaults.update(overrides)
    return OpenAICompatibleDenseEmbedder(**defaults)


def _patch_client(embedder, fake_create):
    """Stuff a fake AsyncOpenAI into the embedder's client slot."""
    class _FakeEmbeddings:
        def __init__(self):
            self.create = fake_create

    class _FakeClient:
        def __init__(self):
            self.embeddings = _FakeEmbeddings()

        def close(self):
            pass

    embedder._client = _FakeClient()


# ── Tests ───────────────────────────────────────────────────────


def test_satisfies_protocol():
    """Runtime Protocol check — guards against accidental signature drift."""
    e = _build_embedder()
    assert isinstance(e, DenseEmbedder)
    assert e.name.startswith("openai-compat:")
    assert e.dim == 4


@pytest.mark.asyncio
async def test_embed_returns_one_vector_per_input():
    e = _build_embedder()
    calls: list[list[str]] = []

    async def fake_create(*, model, input):
        calls.append(list(input))
        return _stub_resp([[0.1, 0.2, 0.3, 0.4]] * len(input))

    _patch_client(e, fake_create)

    out = await e.embed(["one", "two", "three"])
    assert len(out) == 3
    assert all(len(v) == 4 for v in out)


@pytest.mark.asyncio
async def test_batch_splitting_respects_batch_size():
    """5 inputs with batch_size=2 → exactly 3 calls (2+2+1)."""
    e = _build_embedder(batch_size=2)
    seen_batches: list[int] = []

    async def fake_create(*, model, input):
        seen_batches.append(len(input))
        return _stub_resp([[0.0] * 4] * len(input))

    _patch_client(e, fake_create)

    await e.embed([f"q-{i}" for i in range(5)])
    assert seen_batches == [2, 2, 1]


@pytest.mark.asyncio
async def test_query_cache_hit_avoids_second_api_call():
    e = _build_embedder()
    call_count = {"n": 0}

    async def fake_create(*, model, input):
        call_count["n"] += 1
        return _stub_resp([[0.1] * 4 for _ in input])

    _patch_client(e, fake_create)

    await e.embed(["repeat"])
    assert call_count["n"] == 1
    await e.embed(["repeat"])  # cached
    assert call_count["n"] == 1
    await e.embed(["repeat", "fresh"])  # one miss → one call with just the miss
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_retry_on_429_then_success():
    """A first-call 429 must be retried with back-off; back-off is monkey-patched
    to zero so the test runs fast."""
    e = _build_embedder(max_retries=3)
    attempts = {"n": 0}

    class _RateLimitErr(Exception):
        def __init__(self):
            super().__init__("429")

            class _Resp:
                status_code = 429
            self.response = _Resp()

    async def fake_create(*, model, input):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _RateLimitErr()
        return _stub_resp([[0.1] * 4 for _ in input])

    _patch_client(e, fake_create)

    async def fast_sleep(d):
        pass

    with patch("pipeline.embeddings.dense.asyncio.sleep", fast_sleep):
        out = await e.embed(["q"])

    assert attempts["n"] == 2
    assert out and out[0] == [0.1] * 4


@pytest.mark.asyncio
async def test_non_retryable_exception_propagates():
    """A 500 (or anything non-403/429) must NOT be silently retried — caller
    decides what to do."""
    e = _build_embedder(max_retries=3)

    class _ServerErr(Exception):
        pass

    async def fake_create(*, model, input):
        raise _ServerErr("boom")

    _patch_client(e, fake_create)

    with pytest.raises(_ServerErr):
        await e.embed(["q"])


@pytest.mark.asyncio
async def test_close_drops_client():
    e = _build_embedder()
    e._client = type("Stub", (), {"close": lambda self: None})()
    e.close()
    assert e._client is None


@pytest.mark.asyncio
async def test_empty_input_returns_empty_list_no_api_call():
    e = _build_embedder()

    async def fake_create(*, model, input):  # noqa: ARG001
        raise AssertionError("must not be called for empty input")

    _patch_client(e, fake_create)
    assert await e.embed([]) == []
