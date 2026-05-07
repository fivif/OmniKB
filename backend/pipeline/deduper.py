from __future__ import annotations
import hashlib

from storage.metadata_db import check_content_hash_exists


def compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


async def filter_duplicates(chunks: list[dict]) -> list[dict]:
    """Remove chunks whose content hash already exists in the DB."""
    unique: list[dict] = []
    for chunk in chunks:
        h = compute_hash(chunk["content"])
        chunk.setdefault("metadata", {})["content_hash"] = h
        if not await check_content_hash_exists(h):
            unique.append(chunk)
    return unique
