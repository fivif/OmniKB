"""WebAgent — fetch and crawl web pages.

Layer 1: scrapling static Fetcher (if installed)
Layer 2: scrapling PlayWrightFetcher (dynamic SPA / stealth anti-bot, if installed)
Fallback: httpx + BeautifulSoup

Site crawl: BFS with robots.txt compliance and concurrency limiter.
Cookie injection supported for authenticated pages.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from agents.doc_agent import RawDocument, parse_url_content

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}

# Cookie dict type: {name: value} or list of {name, value, domain, path}
CookieJar = dict[str, str] | list[dict]


# ── Single-page fetch ─────────────────────────────────────────

async def fetch_url(
    url: str,
    mode: str = "auto",
    cookies: CookieJar | None = None,
) -> RawDocument:
    """Fetch a single URL and return a :class:`RawDocument`.

    Parameters
    ----------
    mode:
        ``'auto'`` / ``'static'`` — scrapling Fetcher, fallback httpx.
        ``'dynamic'`` — scrapling PlayWrightFetcher, fallback httpx.
        ``'stealth'`` — scrapling PlayWrightFetcher with anti-bot stealth
        (Cloudflare, JS-heavy). Falls back to httpx.
        ``'agent_browser'`` — Layer 3-A: agent-browser CLI (native Rust/CDP).
        Best for interactive, SPA, or scroll-to-load pages.
        Falls back to httpx on failure.
        ``'jshook'`` — Layer 3-B: jshookmcp (@jshookmcp/jshook) CDP browser.
        Best for advanced anti-bot, network interception, JS-heavy reverse.
        Requires Node.js. Falls back to httpx on failure.
    cookies:
        Optional cookies to inject. Dict ``{name: value}`` or list of
        Playwright cookie objects ``{name, value, domain, path}``.
    """
    if mode in ("auto", "static"):
        try:
            return await _scrapling_static(url, cookies=cookies)
        except Exception as e:
            logger.debug("scrapling static failed for %s: %s", url, e)
    elif mode == "dynamic":
        try:
            return await _scrapling_dynamic(url, cookies=cookies)
        except Exception as e:
            logger.debug("scrapling dynamic failed for %s: %s", url, e)
    elif mode == "stealth":
        try:
            return await _scrapling_stealth(url, cookies=cookies)
        except Exception as e:
            logger.debug("scrapling stealth failed for %s: %s", url, e)
    elif mode == "agent_browser":
        try:
            return await _agent_browser_fetch(url, cookies=cookies)
        except Exception as e:
            logger.debug("agent_browser failed for %s: %s", url, e)
    elif mode == "jshook":
        try:
            return await _jshook_fetch(url, cookies=cookies)
        except Exception as e:
            logger.debug("jshook failed for %s: %s", url, e)
    return await _httpx_fetch(url, cookies=cookies)


async def _scrapling_static(url: str, cookies: CookieJar | None = None) -> RawDocument:
    from scrapling.fetchers import Fetcher  # type: ignore[import-untyped]

    def _sync():
        fetcher = Fetcher(auto_match=False)
        extra = {}
        if cookies and isinstance(cookies, dict):
            extra["cookies"] = cookies
        page = fetcher.get(url, headers=_HEADERS, timeout=30, **extra)
        return getattr(page, "html_content", str(page))

    html = await asyncio.to_thread(_sync)
    return RawDocument(
        content=_clean_html(html),
        metadata={"file_type": "url", "source_url": url},
    )


async def _scrapling_dynamic(url: str, cookies: CookieJar | None = None) -> RawDocument:
    from scrapling.fetchers import PlayWrightFetcher  # type: ignore[import-untyped]

    fetcher = PlayWrightFetcher(auto_match=False)
    pw_cookies = _normalize_cookies(url, cookies)
    page = await fetcher.async_get(
        url,
        headless=True,
        timeout=60_000,
        network_idle=True,
        **({"cookies": pw_cookies} if pw_cookies else {}),
    )
    html = getattr(page, "html_content", str(page))
    return RawDocument(
        content=_clean_html(html),
        metadata={"file_type": "url", "source_url": url},
    )


async def _scrapling_stealth(url: str, cookies: CookieJar | None = None) -> RawDocument:
    """PlayWrightFetcher with stealth/fingerprint options for anti-bot sites."""
    from scrapling.fetchers import PlayWrightFetcher  # type: ignore[import-untyped]

    fetcher = PlayWrightFetcher(auto_match=False)
    pw_cookies = _normalize_cookies(url, cookies)
    page = await fetcher.async_get(
        url,
        headless=True,
        timeout=90_000,
        network_idle=True,
        stealth=True,
        humanize=True,
        **({"cookies": pw_cookies} if pw_cookies else {}),
    )
    html = getattr(page, "html_content", str(page))
    return RawDocument(
        content=_clean_html(html),
        metadata={"file_type": "url", "source_url": url, "fetch_mode": "stealth"},
    )


async def _httpx_fetch(url: str, cookies: CookieJar | None = None) -> RawDocument:
    httpx_cookies = cookies if isinstance(cookies, dict) else None
    async with httpx.AsyncClient(
        follow_redirects=True, timeout=30, headers=_HEADERS,
        cookies=httpx_cookies or {},
    ) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return parse_url_content(resp.text, url)


async def _agent_browser_fetch(url: str, cookies: CookieJar | None = None) -> RawDocument:
    """Layer 3-A: agent-browser CLI — handles interactive/SPA/JS-heavy pages.

    Uses the agent-browser daemon (persistent across commands).  Each command
    runs in an isolated session so parallel calls don't interfere.
    """
    ab = shutil.which("agent-browser")
    if not ab:
        raise RuntimeError("agent-browser not installed (npm install -g agent-browser)")

    # Unique session per task to allow parallel fetches
    task = asyncio.current_task()
    session = f"omnigkb-{id(task) if task else 'default'}"
    env = {**os.environ, "AGENT_BROWSER_SESSION": session}

    try:
        from utils.agent_bus import emit as _emit
    except ImportError:
        def _emit(*a, **kw): pass  # type: ignore

    async def _run(*args: str, timeout: float = 30.0) -> tuple[str, int]:
        proc = await asyncio.create_subprocess_exec(
            ab, *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return stdout.decode("utf-8", errors="replace"), proc.returncode or 0

    text = ""
    _emit(f"正在打开页面：{url}", kind="progress", agent="agent_browser")
    try:
        await _run("open", url, timeout=30.0)

        # Inject cookies (dict form only; list form requires Playwright-style handling)
        if cookies and isinstance(cookies, dict):
            for name, value in cookies.items():
                await _run("cookies", "set", name, value, timeout=10.0)

        # Wait for full network idle
        _emit("等待网络空闲…", kind="progress", agent="agent_browser")
        await _run("wait", "--load", "networkidle", timeout=30.0)

        # Prefer plain text (no HTML noise)
        _emit("提取页面文本…", kind="progress", agent="agent_browser")
        text, code = await _run("get", "text", "body", timeout=20.0)
        if code != 0 or not text.strip():
            html, _ = await _run("get", "html", "body", timeout=20.0)
            if html.strip():
                text = _clean_html(html)
    finally:
        try:
            proc = await asyncio.create_subprocess_exec(
                ab, "close", env=env,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except Exception:
            pass

    if not text.strip():
        _emit(f"获取内容为空：{url}", kind="error", agent="agent_browser")
        raise RuntimeError(f"agent-browser returned empty content for {url}")

    _emit(f"✅ 获取完成，{len(text.strip())} 字符", kind="success", agent="agent_browser")
    return RawDocument(
        content=text.strip(),
        metadata={"file_type": "url", "source_url": url, "fetch_mode": "agent_browser"},
    )


async def _jshook_fetch(url: str, cookies: CookieJar | None = None) -> RawDocument:
    """Layer 3-B: jshookmcp (@jshookmcp/jshook) — CDP-level browser control.

    Best for sites with advanced anti-bot measures, complex CDP interactions,
    or when network-level interception is needed.
    Requires Node.js / npx; the server is downloaded on first use via npx -y.
    """
    from agents.jshook_client import JsHookMcpClient  # lazy import

    try:
        from utils.agent_bus import emit as _emit
    except ImportError:
        def _emit(*a, **kw): pass  # type: ignore

    simple_cookies: dict | None = None
    if cookies and isinstance(cookies, dict):
        simple_cookies = cookies

    _emit(f"启动 jshookmcp 服务…", kind="progress", agent="jshook")
    async with JsHookMcpClient(profile="workflow") as client:
        _emit(f"导航至：{url}", kind="progress", agent="jshook")
        text = await client.fetch_page(url, cookies=simple_cookies)

    if not text.strip():
        _emit(f"获取内容为空：{url}", kind="error", agent="jshook")
        raise RuntimeError(f"jshookmcp returned empty content for {url}")

    # If the result is raw HTML, clean it
    if text.lstrip().startswith(("<html", "<!doctype", "<HTML", "<!DOCTYPE")):
        text = _clean_html(text)

    _emit(f"✅ 获取完成，{len(text.strip())} 字符", kind="success", agent="jshook")
    return RawDocument(
        content=text.strip(),
        metadata={"file_type": "url", "source_url": url, "fetch_mode": "jshook"},
    )


# ── BFS site crawl ────────────────────────────────────────────

async def crawl_site(
    start_url: str,
    max_pages: int = 50,
    max_depth: int = 3,
    mode: str = "auto",
    log_cb=None,
    cookies: CookieJar | None = None,
) -> list[RawDocument]:
    """BFS crawl starting from *start_url*.

    Respects robots.txt, stays within the same domain, limits concurrency
    to 5 simultaneous fetches.

    Parameters
    ----------
    log_cb:
        Optional async callable(msg: str) for streaming progress logs.
    cookies:
        Optional session cookies for authenticated crawls.

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
                # Use fetch_url for stealth/dynamic modes; plain httpx for auto/static (faster)
                if mode in ("stealth", "dynamic"):
                    doc = await fetch_url(url, mode=mode, cookies=cookies)
                    html_for_links: str | None = None  # can't re-extract links without raw html
                else:
                    httpx_cookies = cookies if isinstance(cookies, dict) else None
                    async with httpx.AsyncClient(
                        follow_redirects=True, timeout=20, headers=_HEADERS,
                        cookies=httpx_cookies or {},
                    ) as client:
                        resp = await client.get(url)

                    if not resp.is_success:
                        await _log(f"⚠️ HTTP {resp.status_code}，跳过：{url}")
                        continue

                    ct = resp.headers.get("content-type", "")
                    if "html" not in ct and "text" not in ct:
                        await _log(f"⏭️ 非HTML内容({ct[:30]})，跳过：{url}")
                        continue

                    html_for_links = resp.text
                    doc = parse_url_content(html_for_links, url)

                content_len = len(doc.content.strip())
                if content_len > 100:
                    results.append(doc)
                    await _log(f"✅ 已抓取（{content_len}字）[{len(results)}/{max_pages}]：{url}")
                else:
                    await _log(f"⏭️ 内容过短({content_len}字)，跳过：{url}")

                if depth < max_depth and html_for_links is not None:
                    # 用当前页 url 作为基准解析相对链接
                    for link in _extract_links(html_for_links, url):
                        if link not in visited:
                            queue.append((link, depth + 1))
            except Exception as exc:
                await _log(f"❌ 抓取失败：{url} — {exc}")
                logger.debug("crawl_site error for %s: %s", url, exc, exc_info=True)
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


def _normalize_cookies(url: str, cookies: CookieJar | None) -> list[dict] | None:
    """Convert a simple {name: value} dict to Playwright cookie list."""
    if not cookies:
        return None
    if isinstance(cookies, list):
        return cookies  # already in Playwright format
    parsed = urlparse(url)
    domain = parsed.netloc
    return [
        {"name": k, "value": v, "domain": domain, "path": "/"}
        for k, v in cookies.items()
    ]
