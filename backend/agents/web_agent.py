"""WebAgent — fetch web pages.

Layer 1: scrapling static Fetcher (if installed)
Layer 2: scrapling PlayWrightFetcher (dynamic SPA / stealth anti-bot, if installed)
Fallback: httpx + BeautifulSoup

Cookie injection supported for authenticated pages.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from urllib.parse import urlparse

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
    intent: str = "",
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
    intent:
        Free-text description of what the user wants to collect, used by the
        LLM judge to evaluate page relevance. Empty = general / accept all.
    """
    # ── Smart mode: agentic loop via agents.web.loop.run_agent ──────────
    # Cookies are currently not threaded through the new agent path; if the
    # caller really needs auth we fall back to the static path below.
    if mode == "smart" and not cookies:
        try:
            from agents.web.loop import run_agent as _smart_run_agent
            doc = await _smart_run_agent(url=url, intent=intent, task_id=None)
            return await _apply_quality_gates(doc, url, intent)
        except ContentTooShortError as exc:
            # Agent finished but didn't extract anything useful. Don't fail
            # the whole ingest — fall through to the layer-1/2/3 fetchers.
            logger.warning(
                "smart agent produced no usable content for %s (%s); "
                "falling back to static fetch",
                url, exc,
            )
            mode = "auto"
        except ValueError as exc:
            # LLM judge rejected the smart-mode output. The user picked
            # smart mode because they want a best-effort result — give the
            # cheaper fetchers a chance before giving up entirely.
            # The final layer's quality gate will catch real spam.
            logger.warning(
                "smart agent output rejected by LLM judge (%s) — "
                "retrying via static/dynamic fetchers",
                exc,
            )
            mode = "auto"
        except Exception as exc:
            logger.warning(
                "web/loop.run_agent crashed for %s: %s — falling back to static",
                url, exc,
            )
            mode = "auto"
    elif mode == "smart" and cookies:
        logger.info(
            "smart mode + cookies not yet supported in unified path; using stealth fallback for %s",
            url,
        )
        mode = "stealth"

    doc = None
    if mode in ("auto", "static"):
        try:
            doc = await _scrapling_static(url, cookies=cookies)
        except Exception as e:
            logger.debug("scrapling static failed for %s: %s", url, e)
    elif mode == "dynamic":
        try:
            doc = await _scrapling_dynamic(url, cookies=cookies)
        except Exception as e:
            logger.debug("scrapling dynamic failed for %s: %s", url, e)
    elif mode == "stealth":
        try:
            doc = await _scrapling_stealth(url, cookies=cookies)
        except Exception as e:
            logger.debug("scrapling stealth failed for %s: %s", url, e)
    elif mode == "agent_browser":
        try:
            doc = await _agent_browser_fetch(url, cookies=cookies)
        except Exception as e:
            logger.debug("agent_browser failed for %s: %s", url, e)
    elif mode == "jshook":
        try:
            doc = await _jshook_fetch(url, cookies=cookies)
        except Exception as e:
            logger.debug("jshook failed for %s: %s", url, e)

    if doc is None:
        doc = await _httpx_fetch(url, cookies=cookies)

    return await _apply_quality_gates(doc, url, intent)


class ContentTooShortError(ValueError):
    """Fetched document has no usable body.

    Subclass of ``ValueError`` so callers that only `except ValueError` still
    catch it, but a dedicated type lets smart-mode distinguish recoverable
    length failures from terminal LLM-judge rejections.
    """


async def _apply_quality_gates(doc: RawDocument, url: str, intent: str) -> RawDocument:
    """Run LLM quality judge on a fetched document.

    Raises:
        ContentTooShortError: body is empty / below the minimum-length gate.
            Smart mode treats this as recoverable and falls back to static.
        ValueError: LLM judge rejected the page. Terminal — respect verdict.
    """
    stripped = doc.content.strip()
    if len(stripped) < 100:
        raise ContentTooShortError(
            f"Content too short ({len(stripped)} chars) — {url}"
        )

    from config import settings as _cfg
    if not _cfg.web_judge_enabled:
        return doc

    from agents.web_judge import judge_page
    verdict = await judge_page(url, stripped, intent=intent)
    logger.info("web_judge [%d/10] %s — %s", verdict.score, url, verdict.reason)
    doc.metadata["judge_score"] = verdict.score
    doc.metadata["judge_reason"] = verdict.reason
    if verdict.summary:
        doc.metadata["llm_summary"] = verdict.summary
    if not verdict.keep or verdict.score < _cfg.web_judge_min_score:
        raise ValueError(
            f"Page rejected by LLM judge (score={verdict.score}/10): {verdict.reason}"
        )
    return doc


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
    """Layer 3-A: fetch via patchright (stealth Playwright) using long-lived PlaywrightPool.

    Replaces the old agent-browser CLI subprocess. The 'agent_browser' mode name
    is preserved for backward compatibility with existing API callers / MCP clients.
    Raises on failure so fetch_url() can fall back to httpx.
    """
    from agents.web.tools.browser import patchright_fetch
    return await patchright_fetch(url, cookies=cookies, stealth=True, scroll=True)

async def _jshook_fetch(url: str, cookies: CookieJar | None = None) -> RawDocument:
    """Layer 3-B: fetch via jshookmcp using the long-lived JsHookPool.

    Falls back to per-call JsHookMcpClient when pool is unavailable (e.g. during
    standalone tests outside FastAPI lifespan).
    """
    try:
        from utils.agent_bus import emit as _emit
    except ImportError:
        def _emit(*a, **kw): pass

    simple_cookies: dict | None = None
    if cookies and isinstance(cookies, dict):
        simple_cookies = cookies

    from agents.web import pool as _pool_mod
    pool = _pool_mod.JSHOOK_POOL

    if pool is not None and pool.available:
        _emit(f"通过连接池获取 jshookmcp 实例…", kind="progress", agent="jshook")
        async with pool.acquire() as client:
            _emit(f"导航至：{url}", kind="progress", agent="jshook")
            text = await client.fetch_page(url, cookies=simple_cookies)
    else:
        from agents.jshook_client import JsHookMcpClient
        _emit(f"启动 jshookmcp 服务（未启用连接池）…", kind="progress", agent="jshook")
        async with JsHookMcpClient(profile="workflow") as client:
            _emit(f"导航至：{url}", kind="progress", agent="jshook")
            text = await client.fetch_page(url, cookies=simple_cookies)

    if not text.strip():
        _emit(f"获取内容为空：{url}", kind="error", agent="jshook")
        raise RuntimeError(f"jshookmcp returned empty content for {url}")

    if text.lstrip().startswith(("<html", "<!doctype", "<HTML", "<!DOCTYPE")):
        text = _clean_html(text)

    _emit(f"获取完成，{len(text.strip())} 字符", kind="success", agent="jshook")
    return RawDocument(
        content=text.strip(),
        metadata={"file_type": "url", "source_url": url, "fetch_mode": "jshook"},
    )

# ── Helpers ───────────────────────────────────────────────────

def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    return re.sub(r"\n{3,}", "\n\n", text)


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
