"""Reranker implementations: local sentence-transformers + cloud APIs.

Two providers ship today, both satisfying :class:`pipeline.embeddings.protocols.Reranker`:

* :class:`LocalCrossEncoderReranker` — wraps ``sentence-transformers``
  ``CrossEncoder``. Default model ``BAAI/bge-reranker-v2-m3`` (~568 MB,
  Chinese + English). First call downloads, subsequent calls hit the
  in-process LRU cache. Soft-fails to pass-through on download timeout.

* :class:`SiliconFlowRerankerAPI` — calls SiliconFlow's ``/v1/rerank``
  endpoint (a near-clone of Cohere / Jina rerank protocols). Useful
  when you don't want a 600 MB model on disk or want sub-50ms latency
  for large batches. Soft-fails to pass-through on HTTP errors.

Adding a new provider (Cohere, Jina, …) is a 30-line class — copy
the SiliconFlow class and adjust the request / response shape.
"""
from __future__ import annotations

import asyncio
import logging
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


# ── Local cross-encoder ───────────────────────────────────────


@lru_cache(maxsize=4)
def _load_cross_encoder(model_name: str):
    """Process-cached CrossEncoder loader.

    Module-level cache (not instance-level) so multiple ``LocalCrossEncoderReranker``
    constructions for the same model name share the underlying weights — saves
    ~600 MB of RAM on a duplicate ctor.
    """
    from sentence_transformers import CrossEncoder  # type: ignore[import-untyped]
    return CrossEncoder(model_name)


class LocalCrossEncoderReranker:
    """sentence-transformers CrossEncoder reranker (process-local)."""

    def __init__(self, model_name: str) -> None:
        self.name = f"local-cross-encoder:{model_name}"
        self._model_name = model_name
        # ``None`` = not tried, ``True`` = loaded, ``False`` = failed.
        # Identical sentinel discipline to the legacy module global so
        # the back-compat shim can read it 1:1.
        self._available: bool | None = None

    # ── Protocol ──────────────────────────────────────────────

    @property
    def is_available(self) -> bool:
        return self._available is True

    async def rerank(
        self,
        query: str,
        chunks: list[dict],
        top_n: int | None = None,
    ) -> list[dict]:
        if not chunks:
            return chunks
        # Hard-fail short-circuit: a previous load attempt failed and we
        # don't retry on the hot path. The /settings/models/download
        # endpoint can call ``initialize(force=True)`` to retry.
        if self._available is False:
            return chunks[:top_n] if top_n else chunks

        try:
            model = _load_cross_encoder(self._model_name)
            self._available = True
        except Exception as exc:  # noqa: BLE001
            self._available = False
            logger.warning(
                "%s: model unavailable: %s — skipping rerank",
                self.name, exc,
            )
            return chunks[:top_n] if top_n else chunks

        # CrossEncoder.predict is sync + CPU-bound; offload to a thread
        # so the event loop isn't blocked for 100 ms+ on long batches.
        pairs = [(query, c["content"]) for c in chunks]
        scores = await asyncio.to_thread(model.predict, pairs)

        score_list = scores.tolist() if hasattr(scores, "tolist") else list(scores)
        ranked = sorted(zip(score_list, chunks), key=lambda x: x[0], reverse=True)

        out: list[dict] = []
        for score, chunk in ranked:
            c = dict(chunk)
            c["rerank_score"] = round(float(score), 4)
            out.append(c)
        return out[:top_n] if top_n else out

    # ── Legacy hooks (used by shim & /models endpoints) ───────

    def initialize(self, *, timeout_seconds: float = 20.0, force: bool = False) -> bool:
        """Try to load the model with a thread-side timeout. Returns True on success.

        Set ``force=True`` to retry after a previous failure (used by
        the manual-download endpoint, not by the search hot-path).
        """
        if self._available is not None and not force:
            return self._available
        import threading

        result: list[Any] = [None]

        def _load() -> None:
            try:
                result[0] = _load_cross_encoder(self._model_name)
            except Exception:  # noqa: BLE001
                pass

        t = threading.Thread(target=_load, daemon=True)
        t.start()
        t.join(timeout=timeout_seconds)
        if result[0] is not None:
            self._available = True
            logger.info("%s: model loaded successfully", self.name)
        else:
            self._available = False
            logger.warning(
                "%s: model download timed out (%.0fs) — reranking disabled",
                self.name, timeout_seconds,
            )
        return self._available is True

    @staticmethod
    def is_cached(model_name: str = "BAAI/bge-reranker-v2-m3") -> bool:
        """Class-level cache check — reusable from the shim without an instance."""
        from pathlib import Path
        dir_name = "models--" + model_name.replace("/", "--")
        cache_dir = Path.home() / ".cache" / "huggingface" / "hub" / dir_name
        return cache_dir.is_dir()

    def close(self) -> None:
        """No-op: the LRU cache holds the weights process-wide; clearing
        them prematurely would force a re-download on the next request."""
        return


# ── SiliconFlow rerank API ───────────────────────────────────


class SiliconFlowRerankerAPI:
    """Reranker backed by SiliconFlow's ``/v1/rerank`` endpoint.

    SiliconFlow's protocol mirrors Cohere / Jina rerank closely:

    .. code-block:: text

        POST {base_url}/rerank
        Authorization: Bearer {api_key}
        {
          "model": "BAAI/bge-reranker-v2-m3",
          "query": "...",
          "documents": ["doc 1", "doc 2", ...],
          "top_n": 10,
          "return_documents": false
        }

    Response:

    .. code-block:: json

        {
          "results": [
            {"index": 3, "relevance_score": 0.987},
            {"index": 0, "relevance_score": 0.412},
            ...
          ]
        }

    Soft-fails to pass-through on any HTTP error so search keeps working
    if the rerank API is briefly unreachable. ``rerank_score`` on the
    returned dicts is the provider's ``relevance_score`` rounded to 4
    decimals — comparable across calls to the SAME provider, but NOT
    comparable to local cross-encoder scores (different score scales).
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.name = f"siliconflow-rerank:{model}"
        self._api_key = api_key
        # Strip trailing slash so ``"/rerank"`` join is predictable.
        self._base_url = (base_url or "").rstrip("/")
        self._model = model
        self._timeout = timeout_seconds
        # Trust-on-first-use: marked available, flips to False after a
        # confirmed remote failure. Lets first-call latency stay low.
        self._available: bool = True
        # Process-cached httpx client — lazy-init so setups that never
        # use the cloud reranker pay zero import cost.
        self._client: Any = None

    @property
    def is_available(self) -> bool:
        return self._available

    def _get_client(self):
        """Lazy-init the process-cached httpx AsyncClient."""
        if self._client is None:
            import httpx
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def rerank(
        self,
        query: str,
        chunks: list[dict],
        top_n: int | None = None,
    ) -> list[dict]:
        if not chunks:
            return chunks
        if not self._available:
            return chunks[:top_n] if top_n else chunks
        if not self._api_key:
            logger.warning("%s: missing api_key — disabling and passing through", self.name)
            self._available = False
            return chunks[:top_n] if top_n else chunks

        # Lazy-import httpx so the module load stays cheap for setups
        # that never use the cloud reranker.
        try:
            import httpx
        except ImportError:
            logger.warning(
                "%s: httpx not installed — install httpx to use cloud rerankers",
                self.name,
            )
            self._available = False
            return chunks[:top_n] if top_n else chunks

        documents = [c.get("content", "") for c in chunks]
        url = f"{self._base_url}/rerank"
        payload: dict[str, Any] = {
            "model": self._model,
            "query": query,
            "documents": documents,
            # Always request all results — we'll slice locally so the
            # ``rerank_score`` is preserved for every input.
            "return_documents": False,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        try:
            client = self._get_client()
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:  # noqa: BLE001
            # Don't permanently disable on a single hiccup — flip the
            # flag so the next call also passes through, but the next
            # successful initialize() / settings change can revive us.
            logger.warning(
                "%s: rerank API failed (%s) — passing through chunks",
                self.name, exc,
            )
            self._available = False
            return chunks[:top_n] if top_n else chunks

        # Build (index → score) lookup; missing indices keep rank 0
        # so they slot to the bottom but aren't dropped.
        scores: dict[int, float] = {}
        for r in data.get("results") or []:
            idx = r.get("index")
            score = r.get("relevance_score")
            if isinstance(idx, int) and isinstance(score, (int, float)):
                scores[idx] = float(score)

        ranked: list[tuple[float, dict]] = []
        for i, c in enumerate(chunks):
            score = scores.get(i, 0.0)
            new_c = dict(c)
            new_c["rerank_score"] = round(score, 4)
            ranked.append((score, new_c))

        ranked.sort(key=lambda x: x[0], reverse=True)
        out = [c for _, c in ranked]
        return out[:top_n] if top_n else out

    def close(self) -> None:
        """Shut down the cached httpx client if one was created."""
        if self._client is not None:
            try:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._client.aclose())
                except RuntimeError:
                    # No running event loop — close synchronously if possible.
                    pass
            except Exception:  # noqa: BLE001
                pass
            self._client = None
