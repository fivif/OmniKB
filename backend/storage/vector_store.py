from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
    PointStruct,
    SparseVector,
    Filter,
    FieldCondition,
    MatchValue,
    Prefetch,
    FusionQuery,
    Fusion,
    FilterSelector,
)

from config import settings

DENSE_DIM = settings.embedding_dimensions  # BGE-M3=1024, text-embedding-3-small=1536
DENSE_VECTOR = "dense"
SPARSE_VECTOR = "sparse"


@dataclass
class ChunkDoc:
    id: str
    content: str
    dense_vector: list[float]
    sparse_indices: list[int]
    sparse_values: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


_client: AsyncQdrantClient | None = None


def _make_client() -> AsyncQdrantClient:
    mode = settings.qdrant_mode.lower()
    if mode == "memory":
        return AsyncQdrantClient(location=":memory:")
    if mode == "local":
        import os
        os.makedirs(settings.qdrant_local_path, exist_ok=True)
        return AsyncQdrantClient(path=settings.qdrant_local_path)
    # default: remote
    return AsyncQdrantClient(url=settings.qdrant_url)


def get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        _client = _make_client()
    return _client


async def init_vector_store() -> None:
    """Create Qdrant collection with dense + sparse vectors if it doesn't exist."""
    global _client
    _client = _make_client()

    collections = await _client.get_collections()
    existing = {c.name for c in collections.collections}

    if settings.qdrant_collection not in existing:
        await _client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config={
                DENSE_VECTOR: VectorParams(
                    size=DENSE_DIM,
                    distance=Distance.COSINE,
                )
            },
            sparse_vectors_config={
                SPARSE_VECTOR: SparseVectorParams(
                    index=SparseIndexParams(on_disk=False)
                )
            },
        )


async def upsert_chunks(chunks: list[ChunkDoc]) -> None:
    client = get_client()
    points = [
        PointStruct(
            id=chunk.id,
            vector={
                DENSE_VECTOR: chunk.dense_vector,
                SPARSE_VECTOR: SparseVector(
                    indices=chunk.sparse_indices,
                    values=chunk.sparse_values,
                ),
            },
            payload={"content": chunk.content, **chunk.metadata},
        )
        for chunk in chunks
    ]
    await client.upsert(collection_name=settings.qdrant_collection, points=points)


async def hybrid_search(
    query_dense: list[float],
    query_sparse_indices: list[int],
    query_sparse_values: list[float],
    top_k: int = 10,
    filters: dict[str, Any] | None = None,
) -> list[dict]:
    client = get_client()

    qdrant_filter: Filter | None = None
    if filters:
        conditions = [
            FieldCondition(key=k, match=MatchValue(value=v))
            for k, v in filters.items()
            if v is not None
        ]
        if conditions:
            qdrant_filter = Filter(must=conditions)

    prefetches: list[Prefetch] = []

    if query_dense and any(v != 0.0 for v in query_dense):
        prefetches.append(
            Prefetch(
                query=query_dense,
                using=DENSE_VECTOR,
                limit=top_k * 2,
                filter=qdrant_filter,
            )
        )

    if query_sparse_indices:
        prefetches.append(
            Prefetch(
                query=SparseVector(
                    indices=query_sparse_indices,
                    values=query_sparse_values,
                ),
                using=SPARSE_VECTOR,
                limit=top_k * 2,
                filter=qdrant_filter,
            )
        )

    if not prefetches:
        return []

    results = await client.query_points(
        collection_name=settings.qdrant_collection,
        prefetch=prefetches,
        query=FusionQuery(fusion=Fusion.RRF),
        limit=top_k,
        with_payload=True,
    )

    return [
        {
            "id": str(point.id),
            "score": point.score,
            "content": point.payload.get("content", ""),
            "metadata": {k: v for k, v in point.payload.items() if k != "content"},
        }
        for point in results.points
    ]


async def delete_by_source_id(source_id: str) -> None:
    client = get_client()
    await client.delete(
        collection_name=settings.qdrant_collection,
        points_selector=FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(
                        key="source_id",
                        match=MatchValue(value=source_id),
                    )
                ]
            )
        ),
    )
