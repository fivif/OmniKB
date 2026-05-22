"""Wiki page retriever — tokenized scoring over title + summary + tags.

This is the **L2 retrieval** path: chat / MCP routes hit it BEFORE
falling back to the L1 RAG chunks. Two design constraints:

1. **No new dependencies.** Embeddings, BM25 libraries, and rerankers
   already live in the L1 path. The L2 layer is supposed to be cheap
   and serve <500 pages — a hand-rolled scorer is the right tool.
2. **Bilingual-by-default.** OmniKB's user base is split between
   English and Chinese sources. We tokenise English by word and CJK
   by bigram so a query like ``"Karpathy 的 LLM-Wiki"`` matches both
   ``Andrej Karpathy`` (entity page) and ``LLM-Wiki`` (concept page).

Scoring sketch (per page):
    title_match  × 4.0
  + summary_match × 2.0
  + tag_match    × 3.0
  + body_match   × 1.0   (cheap substring count, capped)
  + recency_boost (newer pages slightly preferred)

The output is intentionally a small list — the chat agent then
decides whether to call ``read_wiki_page`` for the full body. We
don't return bodies here to keep tool responses bounded.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from storage.metadata_db import list_wiki_pages

logger = logging.getLogger(__name__)


# ── Tokenisation ────────────────────────────────────────────────────


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "of", "to", "in", "on", "for", "and", "or",
    "is", "are", "was", "were", "with", "by", "from", "this", "that",
    "what", "why", "how", "when", "which", "who",
    # Chinese particles often crash specificity for free
    "的", "了", "是", "和", "或", "在", "对", "为", "与", "及",
})


def _tokenize(text: str) -> list[str]:
    """Tokenise ``text`` into a list of lower-case tokens.

    English: word-split, drop stopwords + tokens shorter than 2 chars.
    CJK: bigram every contiguous run of Chinese / Japanese / Korean
         characters. e.g. ``知识库`` → ``知识`` + ``识库``.

    Tokens from both passes are merged. Order doesn't matter — we
    score on the resulting set.
    """
    tokens: list[str] = []
    text = text or ""
    for m in _WORD_RE.finditer(text):
        tok = m.group(0).lower()
        if len(tok) < 2 or tok in _STOPWORDS:
            continue
        tokens.append(tok)
    for m in _CJK_RE.finditer(text):
        run = m.group(0)
        if len(run) == 1:
            # Single CJK character between non-CJK tokens (e.g. "X 的 Y").
            # Pass it through the stopword filter — most single-char hits
            # are particles ("的", "了", "是") and would only add noise.
            if run in _STOPWORDS:
                continue
            tokens.append(run)
            continue
        for i in range(len(run) - 1):
            bg = run[i : i + 2]
            if bg in _STOPWORDS:
                continue
            tokens.append(bg)
    return tokens


# ── Public API ──────────────────────────────────────────────────────


@dataclass(slots=True)
class WikiHit:
    """One scored wiki page result."""
    page_id:    str
    page_type:  str
    title:      str
    slug:       str
    summary:    str
    tags:       list[str]
    score:      float
    matched:    list[str]    # which query tokens matched (for debug + UI)
    file_path:  str

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id":   self.page_id,
            "page_type": self.page_type,
            "title":     self.title,
            "slug":      self.slug,
            "summary":   self.summary,
            "tags":      self.tags,
            "score":     round(self.score, 4),
            "matched":   self.matched,
            "file_path": self.file_path,
        }


async def search_wiki_pages(
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.5,
    page_types: list[str] | None = None,
) -> list[WikiHit]:
    """Score every wiki page against ``query`` and return the top hits.

    Implementation note: we pull all pages with one DB query (caller is
    expected to keep wikis < ~hundreds of pages — beyond that we'd
    swap in a proper FTS index). For each page we re-use cached token
    sets across calls within the same coroutine — but the function is
    stateless across calls, which is fine because tokenisation is
    cheap (microseconds per page).
    """
    q_tokens = set(_tokenize(query))
    if not q_tokens:
        return []

    # Pull all candidate pages. ``list_wiki_pages`` returns rows newest
    # first; we read up to a hard cap so a runaway DB doesn't OOM us.
    pages = await list_wiki_pages(limit=2000)
    if page_types:
        wanted = set(page_types)
        pages = [p for p in pages if p.get("page_type") in wanted]
    if not pages:
        return []

    hits: list[WikiHit] = []
    for page in pages:
        score, matched = _score_page(page, q_tokens)
        if score < min_score:
            continue
        hits.append(WikiHit(
            page_id=page["id"],
            page_type=page["page_type"],
            title=page["title"],
            slug=page["slug"],
            summary=page.get("summary") or "",
            tags=list((page.get("frontmatter") or {}).get("tags") or []),
            score=score,
            matched=matched,
            file_path=page["file_path"],
        ))

    hits.sort(key=lambda h: h.score, reverse=True)
    return hits[:max(1, int(top_k))]


def _score_page(page: dict[str, Any], q_tokens: set[str]) -> tuple[float, list[str]]:
    """Compute score + matched-token list for one page row."""
    title_tokens   = set(_tokenize(page.get("title") or ""))
    summary_tokens = set(_tokenize(page.get("summary") or ""))
    fm = page.get("frontmatter") or {}
    tag_tokens: set[str] = set()
    for t in (fm.get("tags") or []):
        tag_tokens.update(_tokenize(str(t)))
    for a in (fm.get("aliases") or []):
        tag_tokens.update(_tokenize(str(a)))

    title_match   = q_tokens & title_tokens
    summary_match = q_tokens & summary_tokens
    tag_match     = q_tokens & tag_tokens

    score = (
        4.0 * len(title_match)
      + 2.0 * len(summary_match)
      + 3.0 * len(tag_match)
    )
    # Exact whole-string slug / title boost — the LLM often just types
    # the title directly when it knows what it wants.
    qlower = " ".join(sorted(q_tokens))
    if page.get("slug") and page["slug"] in qlower:
        score += 5.0
    matched = sorted(title_match | summary_match | tag_match)
    return score, matched


# ── Body reader ─────────────────────────────────────────────────────


async def read_page_body(
    page_id: str,
    *,
    data_dir: str | Path,
    max_chars: int = 8000,
) -> tuple[dict | None, str | None]:
    """Return ``(page_row, body_text)`` for a given wiki page id.

    Returns ``(None, None)`` if the page is unknown. Body is read off
    disk and capped at ``max_chars`` to keep tool responses bounded
    when an LLM accidentally asks for a 200KB page. The cap is
    deliberately generous (~2k tokens) — chat tools typically pass
    8000 here so the agent gets the whole page.
    """
    from storage.metadata_db import get_wiki_page
    row = await get_wiki_page(page_id)
    if row is None:
        return None, None
    body: str | None = None
    try:
        p = Path(data_dir).expanduser() / row["file_path"]
        if p.is_file():
            body = p.read_text(encoding="utf-8")[:max_chars]
    except OSError as exc:
        logger.debug("read_page_body: %s read failed: %s", page_id, exc)
        body = None
    return row, body


# ── Self-check ─────────────────────────────────────────────────────


def _self_check() -> None:
    """Run synthetic tokenisation tests (sync, no DB)."""
    en = _tokenize("Andrej Karpathy describes the LLM-Wiki pattern.")
    assert "karpathy" in en and "llm-wiki" in en, en
    assert "the" not in en   # stopword filtered

    cn = _tokenize("知识库的检索路径")
    assert "知识" in cn and "识库" in cn, cn
    assert "的" not in cn    # stopword filtered

    mixed = _tokenize("Karpathy 的 LLM-Wiki 模式")
    assert "karpathy" in mixed and "llm-wiki" in mixed
    assert "的" not in mixed
    assert "模式" in mixed

    print("wiki.retriever self-check OK")


if __name__ == "__main__":
    _self_check()
