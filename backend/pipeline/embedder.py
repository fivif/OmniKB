from __future__ import annotations
import asyncio
import logging
import os
import random
import time

from openai import AsyncOpenAI
from fastembed import SparseTextEmbedding

from config import settings

logger = logging.getLogger(__name__)

_embed_client: AsyncOpenAI | None = None
_bm25_model: SparseTextEmbedding | None = None

# Semaphore: limits concurrent embedding API calls to avoid RPM 403 on SiliconFlow
_embed_sem: asyncio.Semaphore | None = None

# Sliding-window RPM limiter
_rpm_lock: asyncio.Lock | None = None
_rpm_timestamps: list[float] = []

# Query embedding cache: avoids re-embedding repeated queries
_embed_cache: dict[str, tuple[list[float], float]] = {}
_embed_cache_max = 512
_embed_cache_ttl = 300.0  # 5 minutes


def _get_sem() -> asyncio.Semaphore:
    global _embed_sem
    if _embed_sem is None:
        _embed_sem = asyncio.Semaphore(settings.embedding_concurrency)
    return _embed_sem


async def _rpm_wait() -> None:
    """Proactively throttle to stay under embedding_rpm_limit requests/min.

    Uses a sliding 60-second window. Holds _rpm_lock while checking so that
    concurrent tasks queue up rather than all firing at once.
    """
    if not settings.embedding_rpm_limit:
        return
    global _rpm_lock, _rpm_timestamps
    if _rpm_lock is None:
        _rpm_lock = asyncio.Lock()
    async with _rpm_lock:
        now = time.monotonic()
        # Evict timestamps older than 60 s
        _rpm_timestamps = [t for t in _rpm_timestamps if now - t < 60.0]
        if len(_rpm_timestamps) >= settings.embedding_rpm_limit:
            # Wait until the oldest request falls outside the 60-s window
            wait = 60.0 - (now - _rpm_timestamps[0]) + 0.1
            if wait > 0:
                logger.debug("RPM limit reached (%d/%d), waiting %.1fs",
                             len(_rpm_timestamps), settings.embedding_rpm_limit, wait)
                await asyncio.sleep(wait)
            now = time.monotonic()
            _rpm_timestamps = [t for t in _rpm_timestamps if now - t < 60.0]
        _rpm_timestamps.append(time.monotonic())


def _get_embed_client() -> AsyncOpenAI:
    """Return an OpenAI-compatible client for the configured embedding provider."""
    global _embed_client
    if _embed_client is None:
        if settings.embedding_provider == "siliconflow":
            _embed_client = AsyncOpenAI(
                api_key=settings.siliconflow_api_key,
                base_url=settings.siliconflow_base_url,
            )
        else:
            # fallback: standard OpenAI
            _embed_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _embed_client


def clear_embed_client() -> None:
    """Discard the cached embedding client so the next call rebuilds it.

    Useful after proxy or credential changes at runtime.
    """
    global _embed_client
    if _embed_client is not None:
        try:
            _embed_client.close()
        except Exception:
            pass
        _embed_client = None


_bm25_downloading = False


def _bm25_cache_dir() -> str:
    """Persistent cache directory for fastembed-managed sparse models.

    Resolution order:
    1. ``FASTEMBED_CACHE_PATH`` env var (set by ``main.py`` at startup).
    2. ``settings.fastembed_cache_path`` if non-empty.
    3. ``~/.cache/fastembed`` as a stable user-local default.

    Falling back to fastembed's own default (``tempfile.gettempdir() /
    fastembed_cache``) is intentionally avoided because $TMPDIR is purged
    by macOS launchd and wiped on every Linux container restart, which
    means the BM25 model would re-download on every cold start.
    """
    from pathlib import Path
    env_path = os.environ.get("FASTEMBED_CACHE_PATH", "").strip()
    if env_path:
        return env_path
    cfg_path = (getattr(settings, "fastembed_cache_path", "") or "").strip()
    if cfg_path:
        return cfg_path
    return str(Path.home() / ".cache" / "fastembed")


def _bm25() -> SparseTextEmbedding | None:
    global _bm25_model, _bm25_downloading
    if _bm25_model is not None:
        return _bm25_model if _bm25_model is not False else None
    # Don't block request threads on download — return None, let background task handle it
    if not _bm25_downloading:
        _bm25_downloading = True
        try:
            # If model is cached locally, force offline mode so unreachable HF doesn't kill us
            kwargs = {"cache_dir": _bm25_cache_dir()}
            if is_bm25_cached():
                kwargs["local_files_only"] = True
            _bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25", **kwargs)
            logger.info(
                "BM25 model loaded successfully (cache=%s, offline=%s)",
                kwargs["cache_dir"], kwargs.get("local_files_only", False),
            )
        except Exception as exc:
            logger.warning(
                "BM25 model unavailable (huggingface.co unreachable). "
                "Sparse search disabled — falling back to dense-only. "
                "Configure a proxy in Settings or set HF_ENDPOINT. Error: %s",
                exc,
            )
            _bm25_model = False
    if _bm25_model is False:
        return None
    return _bm25_model


_bm25_download_lock = False  # prevents concurrent _bm25_bg() calls


def is_bm25_cached() -> bool:
    """Check if BM25 model is already cached on disk (no download needed).

    Checks the SAME directory fastembed actually writes to — getting this
    wrong (e.g. checking ``~/.cache/huggingface/hub`` instead) silently
    re-downloads the model on every restart because the cache hit always
    misses, then the freshly downloaded copy lands in $TMPDIR and gets
    wiped again by the OS.
    """
    from pathlib import Path
    root = Path(_bm25_cache_dir())
    if not root.is_dir():
        return False
    # fastembed lays out repos as ``models--<org>--<name>/`` inside cache_dir
    target = root / "models--Qdrant--bm25"
    if target.is_dir():
        # Require at least one entry under the snapshot directory so a
        # half-aborted download doesn't masquerade as a cached model.
        try:
            return any(target.rglob("*"))
        except Exception:
            return True
    # Fallback heuristic: a sibling Qdrant/bm25 directory (older layouts)
    try:
        for child in root.iterdir():
            n = child.name.lower()
            if "qdrant" in n and "bm25" in n and child.is_dir():
                return True
    except Exception:
        pass
    return False


def _bm25_bg() -> None:
    """Download BM25 model synchronously (called from the download endpoint)."""
    global _bm25_model, _bm25_downloading, _bm25_download_lock
    import threading

    # Guard against concurrent calls
    if _bm25_download_lock:
        return
    _bm25_download_lock = True

    try:
        result = [None]

        def _download():
            try:
                result[0] = SparseTextEmbedding(
                    model_name="Qdrant/bm25",
                    cache_dir=_bm25_cache_dir(),
                )
            except Exception:
                pass

        t = threading.Thread(target=_download, daemon=True)
        t.start()
        t.join(timeout=15.0)
        # Only update if _bm25() didn't already load it concurrently
        if _bm25_model is not None and _bm25_model is not False:
            return  # already loaded by _bm25()
        if result[0] is not None:
            _bm25_model = result[0]
            _bm25_downloading = True
            logger.info("BM25 model loaded successfully (background)")
        else:
            _bm25_model = False
            _bm25_downloading = False
            logger.warning("BM25 download timed out (15s) — sparse search disabled")
    finally:
        _bm25_download_lock = False


async def embed_dense(texts: list[str]) -> list[list[float]]:
    """Generate dense embeddings via the configured provider, with query cache.

    Internally splits *texts* into batches of ``embedding_batch_size`` and
    enforces ``embedding_concurrency`` to avoid RPM 403 on SiliconFlow.
    Each batch retries up to 4 times with exponential back-off on 403/429.
    """
    global _embed_cache
    now = time.monotonic()

    # Prune expired entries
    _embed_cache = {
        k: v for k, v in _embed_cache.items()
        if now - v[1] < _embed_cache_ttl
    }

    # Check cache
    results: list[list[float]] = []
    miss_idxs: list[int] = []
    miss_texts: list[str] = []
    for i, t in enumerate(texts):
        entry = _embed_cache.get(t)
        if entry is not None and now - entry[1] < _embed_cache_ttl:
            results.append(entry[0])
        else:
            results.append([])  # placeholder
            miss_idxs.append(i)
            miss_texts.append(t)

    if not miss_texts:
        return results

    # Embed cache misses in batches
    batch_size = settings.embedding_batch_size
    batches = [miss_texts[i:i + batch_size] for i in range(0, len(miss_texts), batch_size)]
    batch_vecs: list[list[float]] = []
    for batch in batches:
        vecs = await _embed_batch_with_retry(batch)
        batch_vecs.extend(vecs)

    # Fill results and update cache
    for j, idx in enumerate(miss_idxs):
        vec = batch_vecs[j]
        results[idx] = vec
        txt = miss_texts[j]
        if len(_embed_cache) < _embed_cache_max:
            _embed_cache[txt] = (vec, now)

    return results


async def _embed_batch_with_retry(
    texts: list[str],
    max_retries: int = 4,
) -> list[list[float]]:
    """Embed one batch with semaphore + exponential back-off on 403/429."""
    sem = _get_sem()
    client = _get_embed_client()
    for attempt in range(max_retries):
        await _rpm_wait()
        async with sem:
            try:
                resp = await client.embeddings.create(
                    model=settings.embedding_model,
                    input=texts,
                )
                return [item.embedding for item in resp.data]
            except Exception as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status in (403, 429) and attempt < max_retries - 1:
                    wait = (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(
                        "Embedding rate-limited (%s), retry %d/%d in %.1fs",
                        status, attempt + 1, max_retries - 1, wait,
                    )
                    await asyncio.sleep(wait)
                else:
                    raise
    raise RuntimeError("embed_batch: unreachable")


def embed_sparse(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    """Generate BM25 sparse embeddings via FastEmbed.

    Returns list of (indices, values) tuples.
    When BM25 is unavailable, returns empty sparse vectors (dense-only fallback).
    """
    model = _bm25()
    if model is None:
        return [([], []) for _ in texts]
    results: list[tuple[list[int], list[float]]] = []
    for emb in model.embed(texts):
        results.append((emb.indices.tolist(), emb.values.tolist()))
    return results
