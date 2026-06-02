"""DuckDuckGo HTML search — the single missing primitive for Deep Research.

The rest of OmniKB's web stack is URL-driven (``agents/web/loop.py``
takes a URL + intent). Deep Research needs the inverse: from a topic
(a wiki page title / summary), produce a ranked list of URLs to
investigate. This module fills that gap.

Why DDG HTML and not Brave / Tavily / Serpapi?

* **No API key.** Karpathy's pattern is for personal KBs; a key-less
  default makes it work for everyone out of the box.
* **No new dependency.** We already have ``httpx`` + ``beautifulsoup4``.
* **No rate limit.** DDG HTML tolerates ~1 query/sec from a single IP
  without complaint, which is well within our use case (3-5 queries
  per page research, manually triggered).

Limitations we accept for v0:

* HTML scraping is brittle — DDG can change layout. The fallback path
  surfaces the raw error rather than papering over it so we notice
  fast.
* Results are HTML-rendered, not as good as the JSON API. We get
  title + URL + snippet which is enough to feed into the URL-driven
  research loop.
* No personalisation / region — single English-language pass for now.

The whole module is ~80 LOC of essentially-procedural code. If we
later want Brave, swap in ``brave_search`` with the same signature.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

import httpx

logger = logging.getLogger(__name__)


_DDG_HTML = "https://html.duckduckgo.com/html/"
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


@dataclass(slots=True)
class SearchResult:
    """One web search hit, normalised."""
    title:   str
    url:     str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


class SearchError(Exception):
    """Raised when the search backend itself failed (network, parsing).

    Plain exception (not a dataclass) — ``dataclass + Exception``
    clashes with ``BaseException.__init__``'s ``*args`` contract on
    Python 3.11+ when slots are involved, so we keep it simple.
    Callers can inspect ``.reason`` / ``.status`` / ``.raw_excerpt``
    to decide whether to retry or give up.
    """
    def __init__(
        self,
        reason: str,
        *,
        status: int | None = None,
        raw_excerpt: str = "",
    ) -> None:
        super().__init__(reason)
        self.reason = reason
        self.status = status
        self.raw_excerpt = raw_excerpt

    def __str__(self) -> str:
        head = f"DDG search failed: {self.reason}"
        return f"{head} (HTTP {self.status})" if self.status else head


# ── Public API ────────────────────────────────────────────────────


async def web_search(
    query: str,
    *,
    limit: int = 10,
    timeout: float = 15.0,
) -> list[SearchResult]:
    """Run a single search query against DuckDuckGo HTML.

    Returns up to ``limit`` :class:`SearchResult` items, deduplicated
    by canonical URL. Raises :class:`SearchError` on network failure
    or unrecognisable response — the caller decides whether to surface
    or swallow.
    """
    query = (query or "").strip()
    if not query:
        return []

    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": _UA, "Accept": "text/html,*/*"},
            timeout=timeout,
            follow_redirects=True,
        ) as client:
            resp = await client.post(_DDG_HTML, data={"q": query})
    except httpx.HTTPError as exc:
        raise SearchError(reason=f"network: {exc}") from exc

    if resp.status_code != 200:
        raise SearchError(
            reason="non-200 from DDG",
            status=resp.status_code,
            raw_excerpt=resp.text[:400],
        )

    try:
        results = _parse_ddg_html(resp.text, limit=limit)
    except Exception as exc:  # noqa: BLE001 — bubble up with context
        raise SearchError(
            reason=f"parse: {exc}",
            status=resp.status_code,
            raw_excerpt=resp.text[:400],
        ) from exc

    logger.info("web_search %r → %d hit(s)", query[:60], len(results))
    return results


# ── Parsing ───────────────────────────────────────────────────────


def _parse_ddg_html(html: str, *, limit: int) -> list[SearchResult]:
    """Extract result rows from a DDG HTML response.

    DDG HTML returns ``<div class="result">`` blocks each with an
    anchor ``a.result__a`` and a snippet ``a.result__snippet``. We're
    deliberately *minimal* with the HTML parsing — narrow CSS selectors
    so layout changes break loudly instead of silently degrading.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    out: list[SearchResult] = []
    seen: set[str] = set()

    for node in soup.select("div.result"):
        a = node.select_one("a.result__a")
        if a is None:
            continue
        href = a.get("href") or ""
        title = a.get_text(strip=True)
        if not href or not title:
            continue

        # DDG wraps results in a redirector — unwrap it so callers get
        # the actual target URL.
        target = _unwrap_ddg_redirect(href)
        if not target or not target.startswith(("http://", "https://")):
            continue

        # Dedupe by canonical (scheme+host+path) so two URLs differing
        # only in tracking params don't both make the cut.
        key = _canonical(target)
        if key in seen:
            continue
        seen.add(key)

        snippet_node = node.select_one("a.result__snippet") or node.select_one(".result__snippet")
        snippet = snippet_node.get_text(" ", strip=True) if snippet_node else ""

        out.append(SearchResult(title=title, url=target, snippet=snippet[:400]))
        if len(out) >= limit:
            break

    return out


def _unwrap_ddg_redirect(href: str) -> str:
    """DDG wraps real URLs in ``/l/?uddg=<encoded>`` — unwrap that."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    # Direct external URL
    if parsed.netloc and not parsed.netloc.endswith("duckduckgo.com"):
        return href
    # Redirector form
    qs = parse_qs(parsed.query)
    for key in ("uddg", "u"):
        if key in qs and qs[key]:
            return unquote(qs[key][0])
    return ""


_CANON_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|mc_eid$)")


def _canonical(url: str) -> str:
    """Best-effort canonicalisation for dedup — scheme + host + path.

    Tracking parameters (utm_*, fbclid, gclid, mc_eid, etc.) are stripped
    from the query string so that the same page with different marketing
    tags maps to a single canonical URL.
    """
    p = urlparse(url)
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path.rstrip("/") or "/"
    # Strip tracking params from query string.
    if p.query:
        params = parse_qs(p.query, keep_blank_values=True)
        cleaned = {k: v for k, v in params.items() if not _CANON_TRACKING.match(k)}
        qs = "&".join(f"{k}={v[0]}" for k, v in cleaned.items()) if cleaned else ""
    else:
        qs = ""
    base = f"{p.scheme}://{host}{path}"
    return f"{base}?{qs}" if qs else base


# ── Self-check ────────────────────────────────────────────────────


async def _self_check() -> None:
    """Live sanity test — only run manually. Hits real DDG."""
    import sys

    res = await web_search("Andrej Karpathy LLM-Wiki", limit=5)
    print(f"got {len(res)} results")
    for r in res:
        print(f"  - {r.title[:60]}  {r.url}")
    assert res, "expected at least one hit for a well-known query"
    sys.stdout.flush()
    print("wiki.web_search self-check OK")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_self_check())
