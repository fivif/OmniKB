"""HTTP fetch tools — fast static fetch, parallel batch, and link extraction.

Ported from the legacy smart_fetcher.py with cleaner separation. These wrap
httpx + scrapling and output cleaned plain text suitable for LLM consumption.
"""
from __future__ import annotations

import asyncio
import json
import re
from urllib.parse import urljoin, urlparse

from langchain_core.tools import tool

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def _clean_html_text(html: str) -> tuple[str, str]:
    """Return (title, body_text) cleaned of nav/footer noise."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    body = re.sub(r"\n{3,}", "\n\n", soup.get_text(separator="\n", strip=True))
    return title, body


@tool
async def http_get(url: str) -> str:
    """Fetch a URL via fast static HTTP (no JavaScript). Returns up to 20K chars.

    Auto-detects content type:
      - PDF: extracted via pdfplumber (first 80 pages, up to 20K chars)
      - JSON / XML: returned raw
      - HTML: cleaned (script/nav/footer stripped) with title prepended

    Prefer this tool for: REST APIs (GitHub, arxiv, PyPI...), simple HTML pages, PDFs.
    """
    import httpx

    try:
        from agents.web_agent import _scrapling_static
        doc = await _scrapling_static(url)
        return doc.content[:20000]
    except Exception:
        pass

    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, timeout=25, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    ct = resp.headers.get("content-type", "").lower()

    if "pdf" in ct or url.lower().endswith(".pdf"):
        try:
            import io, pdfplumber
            pages = []
            with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
                for page in pdf.pages[:80]:
                    t = page.extract_text()
                    if t:
                        pages.append(t)
            return "\n\n".join(pages)[:20000] if pages else "[PDF: no text extracted]"
        except Exception as exc:
            return f"[PDF extraction failed: {exc}]"

    body = resp.text
    if "json" in ct or body.lstrip().startswith(("{", "[")):
        return body[:20000]
    if "xml" in ct or body.lstrip().startswith("<?xml"):
        return body[:20000]

    title, text = _clean_html_text(body)
    return (f"# {title}\n\n{text}" if title else text)[:20000]


@tool
async def http_get_batch(urls: list) -> str:
    """Fetch multiple URLs in parallel (max 15). Each result truncated to 8K chars.
    Output: each result prefixed with [URL] and separated by '\n\n---\n\n'.
    """
    import httpx

    if len(urls) > 15:
        urls = urls[:15]

    async def _fetch_one(u: str) -> str:
        try:
            async with httpx.AsyncClient(
                headers={"User-Agent": _UA}, timeout=20, follow_redirects=True
            ) as client:
                resp = await client.get(u)
                resp.raise_for_status()
            ct = resp.headers.get("content-type", "").lower()
            body = resp.text
            if "json" in ct or body.lstrip().startswith(("{", "[")):
                return f"[{u}]\n{body[:8000]}"
            if "xml" in ct or body.lstrip().startswith("<?xml"):
                return f"[{u}]\n{body[:8000]}"
            _, text = _clean_html_text(body)
            return f"[{u}]\n{text[:8000]}"
        except Exception as exc:
            return f"[{u}]\n[fetch error: {exc}]"

    results = await asyncio.gather(*[_fetch_one(u) for u in urls])
    return "\n\n---\n\n".join(results)


@tool
async def get_links(url: str, max_links: int = 40) -> str:
    """Extract internal hyperlinks from a page. Returns JSON array of {url, text}.
    Same-domain only. Use to discover sub-pages before bulk-fetching them.
    """
    import httpx
    from bs4 import BeautifulSoup

    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, timeout=20, follow_redirects=True
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()

    base = urlparse(url)
    soup = BeautifulSoup(resp.text, "html.parser")
    seen: set[str] = set()
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "javascript:")):
            continue
        full = urljoin(url, href)
        p = urlparse(full)
        if p.netloc != base.netloc:
            continue
        clean = p._replace(fragment="").geturl()
        if clean in seen:
            continue
        seen.add(clean)
        text = a.get_text(strip=True)[:80]
        links.append({"url": clean, "text": text})
        if len(links) >= max_links:
            break

    return json.dumps(links, ensure_ascii=False)


@tool
async def browser_get_text(url: str, scroll: bool = False) -> str:
    """Fetch a JS-rendered page through the long-lived patchright browser.
    Use when http_get returns thin content for an SPA / JS-heavy page.
    Set scroll=True for lazy-loaded pages.
    """
    from agents.web.tools.browser import patchright_fetch
    doc = await patchright_fetch(url, stealth=True, scroll=scroll)
    return doc.content[:20000]
