from __future__ import annotations
from openai import AsyncOpenAI
from fastembed import SparseTextEmbedding

from config import settings

_embed_client: AsyncOpenAI | None = None
_bm25_model: SparseTextEmbedding | None = None


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
    """Generate dense embeddings via the configured provider (batched)."""
    resp = await _get_embed_client().embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    return [item.embedding for item in resp.data]


def embed_sparse(texts: list[str]) -> list[tuple[list[int], list[float]]]:
    """Generate BM25 sparse embeddings via FastEmbed.

    Returns list of (indices, values) tuples.
    """
    model = _bm25()
    results: list[tuple[list[int], list[float]]] = []
    for emb in model.embed(texts):
        results.append((emb.indices.tolist(), emb.values.tolist()))
    return results
