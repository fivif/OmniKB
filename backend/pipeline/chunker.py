from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any

from langchain_text_splitters import RecursiveCharacterTextSplitter

CHUNK_SIZE = 800
CHUNK_OVERLAP = 160

_MD_SEPARATORS = [
    "\n## ", "\n### ", "\n#### ", "\n##### ",
    "\n\n", "\n", " ", "",
]


@dataclass
class TextChunk:
    content: str
    chunk_index: int
    metadata: dict[str, Any]


def chunk_text(
    text: str,
    source_id: str,
    base_metadata: dict[str, Any] | None = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> list[TextChunk]:
    meta = base_metadata or {}
    is_markdown = bool(re.search(r"^#{1,6} ", text, re.MULTILINE))

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=_MD_SEPARATORS if is_markdown else None,
        keep_separator=True,
    )

    splits = splitter.split_text(text)

    return [
        TextChunk(
            content=s.strip(),
            chunk_index=i,
            metadata={**meta, "source_id": source_id},
        )
        for i, s in enumerate(splits)
        if s.strip()
    ]
