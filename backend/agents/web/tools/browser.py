"""Browser fetch via patchright (stealth-patched Playwright) using PlaywrightPool.

Replaces the old agent-browser CLI subprocess. Same return type (RawDocument);
falls back to a clear error if PlaywrightPool is unavailable so callers can
escalate to httpx or jshook.
"""
from __future__ import annotations
import logging
import re
from urllib.parse import urlparse

from agents.doc_agent import RawDocument
from agents.web import pool as _pool_mod

logger = logging.getLogger(__name__)


def _emit(msg: str, kind: str = "progress") -> None:
    try:
        from utils.agent_bus import emit
        emit(msg, kind=kind, agent="agent_browser")
    except Exception:
        pass


def _normalize_cookies(url: str, cookies):
    if not cookies:
        return None
    if isinstance(cookies, list):
        return cookies
    domain = urlparse(url).netloc
    return [{"name": k, "value": v, "domain": domain, "path": "/"} for k, v in cookies.items()]


def _clean_text(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def patchright_fetch(
    url: str,
    cookies=None,
    stealth: bool = True,
    scroll: bool = False,
    timeout_ms: int = 60_000,
) -> RawDocument:
    """Fetch *url* via the long-lived PlaywrightPool browser.

    Parameters
    ----------
    cookies:
        Dict ``{name: value}`` or Playwright cookie list.
    stealth:
        Inject minimal anti-detection script before navigation.
    scroll:
        Scroll to bottom + 1.5s wait (for lazy-loaded SPAs).
    """
    pool = _pool_mod.PLAYWRIGHT_POOL
    if pool is None or not pool.available:
        raise RuntimeError("PlaywrightPool unavailable -- install patchright/playwright or set PLAYWRIGHT_POOL_SIZE>0")

    _emit(f"打开页面：{url[:100]}")
    pw_cookies = _normalize_cookies(url, cookies)

    async with pool.new_context() as ctx:
        if pw_cookies:
            try:
                await ctx.add_cookies(pw_cookies)
            except Exception as exc:
                logger.debug("add_cookies non-fatal: %s", exc)
        page = await ctx.new_page()
        if stealth:
            try:
                await page.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
                )
            except Exception:
                pass

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                await page.wait_for_load_state("networkidle", timeout=15_000)
            except Exception:
                pass
            if scroll:
                _emit("滚动加载…")
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)
            _emit("提取页面文本…")
            text = await page.inner_text("body")
            html = await page.content()
        finally:
            try:
                await page.close()
            except Exception:
                pass

    text = _clean_text(text)
    if not text:
        _emit(f"获取内容为空：{url}", kind="error")
        raise RuntimeError(f"patchright_fetch returned empty content for {url}")

    _emit(f"完成，{len(text)} 字符", kind="success")
    return RawDocument(
        content=text,
        metadata={
            "file_type": "url",
            "source_url": url,
            "fetch_mode": "patchright",
            "html_for_links": html,
        },
    )
