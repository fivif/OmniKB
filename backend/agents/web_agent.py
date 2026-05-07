"""WebAgent — fetch and crawl web pages.

Layer 1: scrapling static Fetcher (if installed)
Layer 2: scrapling PlayWrightFetcher (dynamic SPA, if installed)
Fallback: httpx + BeautifulSoup

Site crawl: BFS with robots.txt compliance and concurrency limiter.
"""
from __future__ import annotations

import asyncio
import re
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from agents.doc_agent import RawDocument, parse_url_content

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


# ── Single-page fetch ─────────────────────────────────────────

async def fetch_url(url: str, mode: str = "auto") -> RawDocument:
    """Fetch a single URL and return a :class:`RawDocument`.

    Parameters
    ----------
    mode:
        ``'auto'`` or ``'static'`` — try scrapling Fetcher, fallback httpx.
        ``'dynamic'`` — try scrapling PlayWrightFetcher, fallback httpx.
    """
    if mode in ("auto", "static"):
        try:
            return await _scrapling_static(url)
        except Exception:
            pass
    elif mode == "dynamic":
        try:
            return await _scrapling_dynamic(url)
        except Exception:
            pass
    return await _httpx_fetch(url)


async def _scrapling_static(url: str) -> RawDocument:
    from scrapling.fetchers import Fetcher  # type: ignore[import-untyped]

    def _sync():
        fetcher = Fetcher(auto_match=False)
        page = fetcher.get(url, headers=_HEADERS, timeout=30)
        return getattr(page, "html_content", str(page))

    html = await asyncio.to_thread(_sync)
    return RawDocument(
        content=_clean_html(html),
        metadata={"file_type": "url", "source_url": url},
    )


async def _scrapling_dynamic(url: str) -> RawDocument:
    from scrapling.fetchers import PlayWrightFetcher  # type: ignore[import-untyped]

    fetcher = PlayWrightFetcher(auto_match=False)
    page = await fetcher.async_get(url, headless=True, timeout=60_000)
    html = getattr(page, "html_content", str(page))
    return RawDocument(
        content=_clean_html(html),
        metadata={"file_type": "url", "source_url": url},
    )


async def _httpx_fetch(url: str) -> RawDocument:
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=30, headers=_HEADERS
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return parse_url_content(resp.text, url)


# ── BFS site crawl ────────────────────────────────────────────

async def crawl_site(
    start_url: str,
    max_pages: int = 50,
    max_depth: int = 3,
    mode: str = "auto",
    log_cb=None,
) -> list[RawDocument]:
    """BFS crawl starting from *start_url*.

    Respects robots.txt, stays within the same domain, limits concurrency
    to 5 simultaneous fetches.

    Parameters
    ----------
    log_cb:
        Optional async callable(msg: str) for streaming progress logs.

    Returns
    -------
    list[RawDocument]
        One entry per successfully fetched page (content > 100 chars).
    """
    async def _log(msg: str):
        if log_cb:
            await log_cb(msg)

    can_fetch = _build_robots_checker(start_url)
    visited: set[str] = set()
    queue: list[tuple[str, int]] = [(start_url, 0)]
    results: list[RawDocument] = []
    sem = asyncio.Semaphore(5)

    while queue and len(results) < max_pages:
        url, depth = queue.pop(0)
        if url in visited or depth > max_depth:
            continue
        if not can_fetch(url):
            await _log(f"⛔ robots.txt 禁止：{url}")
            continue
        visited.add(url)

        async with sem:
            try:
                async with httpx.AsyncClient(
                    follow_redirects=True, timeout=20, headers=_HEADERS
                ) as client:
                    resp = await client.get(url)

                if not resp.is_success:
                    await _log(f"⚠️ HTTP {resp.status_code}，跳过：{url}")
                    continue

                ct = resp.headers.get("content-type", "")
                if "html" not in ct and "text" not in ct:
                    await _log(f"⏭️ 非HTML内容({ct[:30]})，跳过：{url}")
                    continue

                html = resp.text
                doc = parse_url_content(html, url)
                content_len = len(doc.content.strip())
                if content_len > 100:
                    results.append(doc)
                    await _log(f"✅ 已抓取（{content_len}字）[{len(results)}/{max_pages}]：{url}")
                else:
                    await _log(f"⏭️ 内容过短({content_len}字)，跳过：{url}")

                if depth < max_depth:
                    # 用当前页 url 作为基准解析相对链接
                    for link in _extract_links(html, url):
                        if link not in visited:
                            queue.append((link, depth + 1))
            except Exception as exc:
                await _log(f"❌ 抓取失败：{url} — {exc}")
                continue

    await _log(f"🏁 爬取结束，共获取 {len(results)} 页")
    return results


# ── Helpers ───────────────────────────────────────────────────

def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


def _extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].split("#")[0].strip()
        if not href:
            continue
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme in ("http", "https") and _same_domain(full, base_url):
            links.append(full)
    return list(dict.fromkeys(links))  # preserve order, dedupe


def _same_domain(url: str, base_url: str) -> bool:
    return urlparse(url).netloc == urlparse(base_url).netloc


def _build_robots_checker(start_url: str):
    """Return a callable(url) -> bool that checks robots.txt allowance."""
    parsed = urlparse(start_url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = RobotFileParser(robots_url)
    try:
        import urllib.request
        with urllib.request.urlopen(robots_url, timeout=5) as f:
            rp.parse(f.read().decode("utf-8", errors="ignore").splitlines())
    except Exception:
        pass  # no robots.txt → allow all

    def can_fetch(url: str) -> bool:
        return rp.can_fetch("*", url)

    return can_fetch
