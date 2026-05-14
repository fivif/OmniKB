from __future__ import annotations
import re
from typing import Any
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def extract_metadata(
    content: str,
    source_type: str,
    url: str | None = None,
) -> dict[str, Any]:
    meta: dict[str, Any] = {
        "source_type": source_type,
        "word_count": len(content.split()),
        "char_count": len(content),
    }

    if url:
        parsed = urlparse(url)
        meta["source_url"] = url
        meta["domain"] = parsed.netloc

    title = _extract_title(content, source_type)
    if title:
        meta["title"] = title

    meta["language"] = _detect_language(content)

    return meta


def _extract_title(content: str, source_type: str) -> str | None:
    if source_type in ("html", "url"):
        soup = BeautifulSoup(content, "html.parser")
        tag = soup.find("title") or soup.find("h1")
        if tag:
            return tag.get_text(strip=True)[:200]

    m = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if m:
        return m.group(1).strip()[:200]

    for line in content.splitlines():
        line = line.strip()
        if line:
            return line[:200]

    return None


def _detect_language(content: str) -> str:
    cjk = sum(1 for c in content if "\u4e00" <= c <= "\u9fff")
    if len(content) > 0 and cjk / len(content) > 0.1:
        return "zh"
    return "en"
