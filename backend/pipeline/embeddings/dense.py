"""OpenAI-compatible dense embedder.

One class, three deployments
----------------------------
Every dense embedding API on the market that matters today (OpenAI,
SiliconFlow, Together, DeepInfra, Voyage's OAI mode, Cohere's OAI mode,
通义 / 智谱 / 月之暗面 / 百炼's OAI mode, vLLM-served local models, …)
speaks the same wire format: ``POST /v1/embeddings`` with
``{model, input}`` and a list of ``{embedding: [...], index, ...}``
in the response. So the abstraction is just ``(api_key, base_url,
model, dim)`` — the previous if-else over ``embedding_provider`` was
artificial.

Behaviour preserved 1:1 from the legacy ``pipeline/embedder.py``:

* Per-query LRU-style cache (TTL 5 min, max 512 entries) keyed on the
  raw query text — chat repeats the same user query several times
  per turn (HyDE expansion, follow-ups), this is the highest-ROI
  cache OmniKB has.
* Concurrency cap via ``embedding_concurrency`` (semaphore).
* Sliding-window RPM limiter (default 10 req/min, configurable).
* Per-batch retry with exponential back-off on 403 / 429 (4 attempts).
* Splits inputs into ``embedding_batch_size`` batches before hitting
  the API.

The cache, semaphore and RPM state are instance attributes so multiple
embedders with different settings don't trample each other's quotas
(future use case: separate embedders for ingest vs. live query).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)


class OpenAICompatibleDenseEmbedder:
    """Dense embedder that speaks OpenAI's ``/v1/embeddings`` wire format."""

    _CACHE_TTL_SECONDS: float = 300.0
    _CACHE_MAX_ENTRIES: int = 512

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None,
        model: str,
        dim: int,
        concurrency: int = 3,
        rpm_limit: int = 10,
        batch_size: int = 32,
        max_retries: int = 4,
    ) -> None:
        # Identity / wiring.
        self.name = f"openai-compat:{model}"
        self.model = model
        self.dim = dim
        self._api_key = api_key
        self._base_url = base_url

        # AsyncOpenAI takes ``base_url=None`` to mean "default
        # api.openai.com" — that's exactly what we want, so pass through.
        self._client: AsyncOpenAI | None = None

        # Throttles / caps. Re-readable for stats.
        self._concurrency = max(1, int(concurrency))
        self._rpm_limit = max(0, int(rpm_limit))
        self._batch_size = max(1, int(batch_size))
        self._max_retries = max(1, int(max_retries))

        # Lazy-built so a never-used embedder costs nothing.
        self._sem: asyncio.Semaphore | None = None
        self._rpm_lock: asyncio.Lock | None = None
        self._rpm_timestamps: list[float] = []

        # Query cache. Mutable + module-visible so legacy callers
        # (api/settings.py clears it after settings changes) keep
        # working through the back-compat shim.
        self.query_cache: dict[str, tuple[list[float], float]] = {}

    # ── lazy resources ────────────────────────────────────────

    def _get_client(self) -> AsyncOpenAI:
        if self._client is None:
            kwargs: dict[str, str] = {"api_key": self._api_key or ""}
            if self._base_url:
                kwargs["base_url"] = self._base_url
            self._client = AsyncOpenAI(**kwargs)
        return self._client

    def _get_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._concurrency)
        return self._sem

    def close(self) -> None:
        """Discard the cached HTTP client. Next ``embed()`` rebuilds it.

        Called by :func:`pipeline.embeddings.factory.clear_caches` after
        a settings change (proxy / API key rotation)."""
        if self._client is not None:
            try:
                self._client.close()
            except Exception:  # noqa: BLE001
                pass
            self._client = None

    # ── public API (Protocol) ─────────────────────────────────

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Cache + batch + concurrency-cap dense embedding."""
        if not texts:
            return []
        now = time.monotonic()

        # 1. Resolve from cache; record misses positionally.
        #    TTL is checked per-entry on lookup — no full-scan eviction needed.
        #    Expired entries are naturally replaced when the slot is reused.
        results: list[list[float]] = []
        miss_idxs: list[int] = []
        miss_texts: list[str] = []
        for i, t in enumerate(texts):
            entry = self.query_cache.get(t)
            if entry is not None and now - entry[1] < self._CACHE_TTL_SECONDS:
                results.append(entry[0])
            else:
                results.append([])  # placeholder
                miss_idxs.append(i)
                miss_texts.append(t)

        if not miss_texts:
            return results

        # 3. Batch the misses. Stays under provider-side input caps and
        #    keeps single-request payload size predictable.
        batches = [
            miss_texts[i:i + self._batch_size]
            for i in range(0, len(miss_texts), self._batch_size)
        ]
        batch_vecs: list[list[float]] = []
        for batch in batches:
            vecs = await self._embed_batch_with_retry(batch)
            batch_vecs.extend(vecs)

        # 4. Splice misses back into ``results`` and update the cache
        #    (bounded — evict oldest entry when full, pushing stale/expired
        #    entries out naturally without a full-scan on every call).
        for j, idx in enumerate(miss_idxs):
            vec = batch_vecs[j]
            results[idx] = vec
            txt = miss_texts[j]
            if len(self.query_cache) >= self._CACHE_MAX_ENTRIES:
                # Python 3.7+ dict preserves insertion order — pop the
                # oldest (first-inserted) entry as a simple LRU eviction.
                self.query_cache.pop(next(iter(self.query_cache)))
            # Also evict any stale entry for the same key before inserting.
            # Stale entries may linger from before the LRU eviction policy.
            if txt in self.query_cache and now - self.query_cache[txt][1] >= self._CACHE_TTL_SECONDS:
                del self.query_cache[txt]
            self.query_cache[txt] = (vec, now)

        return results

    # ── helpers ───────────────────────────────────────────────

    async def _rpm_wait(self) -> None:
        """Sliding-window RPM throttle. No-op when ``rpm_limit == 0``."""
        if not self._rpm_limit:
            return
        if self._rpm_lock is None:
            self._rpm_lock = asyncio.Lock()
        async with self._rpm_lock:
            now = time.monotonic()
            self._rpm_timestamps = [t for t in self._rpm_timestamps if now - t < 60.0]
            if len(self._rpm_timestamps) >= self._rpm_limit:
                wait = 60.0 - (now - self._rpm_timestamps[0]) + 0.1
                if wait > 0:
                    logger.debug(
                        "%s: RPM limit reached (%d/%d), waiting %.1fs",
                        self.name, len(self._rpm_timestamps), self._rpm_limit, wait,
                    )
                    await asyncio.sleep(wait)
                now = time.monotonic()
                self._rpm_timestamps = [t for t in self._rpm_timestamps if now - t < 60.0]
            self._rpm_timestamps.append(time.monotonic())

    async def _embed_batch_with_retry(self, texts: list[str]) -> list[list[float]]:
        """One batch with semaphore + exponential back-off on 403 / 429."""
        sem = self._get_sem()
        client = self._get_client()
        for attempt in range(self._max_retries):
            await self._rpm_wait()
            async with sem:
                try:
                    resp = await client.embeddings.create(
                        model=self.model,
                        input=texts,
                    )
                    return [item.embedding for item in resp.data]
                except Exception as exc:  # noqa: BLE001
                    status = getattr(getattr(exc, "response", None), "status_code", None)
                    if status in (403, 429) and attempt < self._max_retries - 1:
                        wait = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            "%s: rate-limited (%s), retry %d/%d in %.1fs",
                            self.name, status, attempt + 1, self._max_retries - 1, wait,
                        )
                        await asyncio.sleep(wait)
                    else:
                        raise
        raise RuntimeError("OpenAICompatibleDenseEmbedder._embed_batch_with_retry: unreachable")
