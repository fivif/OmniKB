from __future__ import annotations
import asyncio
import logging
import random

from openai import AsyncOpenAI
from fastembed import SparseTextEmbedding

from config import settings

logger = logging.getLogger(__name__)

_embed_client: AsyncOpenAI | None = None
_bm25_model: SparseTextEmbedding | None = None

# Semaphore: limits concurrent embedding API calls to avoid RPM 403 on SiliconFlow
_embed_sem: asyncio.Semaphore | None = None


def _get_sem() -> asyncio.Semaphore:
    global _embed_sem
    if _embed_sem is None:
        _embed_sem = asyncio.Semaphore(settings.embedding_concurrency)
    return _embed_sem


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


def _bm25() -> SparseTextEmbedding:
    global _bm25_model
    if _bm25_model is None:
        _bm25_model = SparseTextEmbedding(model_name="Qdrant/bm25")
    return _bm25_model


async def embed_dense(texts: list[str]) -> list[list[float]]:
    """Generate dense embeddings via the configured provider.

    Internally splits *texts* into batches of ``embedding_batch_size`` and
    enforces ``embedding_concurrency`` to avoid RPM 403 on SiliconFlow.
    Each batch retries up to 4 times with exponential back-off on 403/429.
    """
    batch_size = settings.embedding_batch_size
    batches = [texts[i:i + batch_size] for i in range(0, len(texts), batch_size)]
    results: list[list[float]] = []
    for batch in batches:
        vecs = await _embed_batch_with_retry(batch)
        results.extend(vecs)
    return results


async def _embed_batch_with_retry(
    texts: list[str],
    max_retries: int = 4,
) -> list[list[float]]:
    """Embed one batch with semaphore + exponential back-off on 403/429."""
    sem = _get_sem()
    client = _get_embed_client()
    for attempt in range(max_retries):
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
    """
    model = _bm25()
    results: list[tuple[list[int], list[float]]] = []
    for emb in model.embed(texts):
        results.append((emb.indices.tolist(), emb.values.tolist()))
    return results
