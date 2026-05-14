"""Connection pools for web agent — bind to FastAPI lifespan for reuse."""
from __future__ import annotations
import asyncio
import logging
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class JsHookPool:
    """Reusable jshookmcp connection pool. Each slot = one long-lived JsHookMcpClient."""

    def __init__(self, size: int = 2, profile: str = "workflow"):
        self._size = size
        self._profile = profile
        self._available: asyncio.Queue | None = None
        self._all: list = []
        self._started = False

    # Domains whose tools the langchain agent can call directly (jshook__<name>).
    # These map to the ALLOWED_PREFIXES in jshook_dynamic.py:
    #   page_, network_, stealth_, browser_, cdp_
    _AUTO_DOMAINS = ("page", "network", "stealth", "browser", "cdp")

    async def start(self) -> None:
        from agents.jshook_client import JsHookMcpClient
        self._available = asyncio.Queue()
        for i in range(self._size):
            try:
                c = JsHookMcpClient(profile=self._profile)
                await c.start()
                # Pre-activate common domains so langchain tools (jshook__page_evaluate
                # etc.) are callable without the agent manually running search→activate→call.
                for domain in self._AUTO_DOMAINS:
                    try:
                        await c.activate_domain(domain)
                    except Exception:
                        pass
                self._all.append(c)
                await self._available.put(c)
            except Exception as exc:
                logger.warning("JsHookPool slot %d failed: %s", i, exc)
        self._started = True
        logger.info("JsHookPool started: %d/%d slots", len(self._all), self._size)

    async def stop(self) -> None:
        if self._available is not None:
            while not self._available.empty():
                try:
                    self._available.get_nowait()
                except Exception:
                    break
        for c in self._all:
            try:
                await c.close()
            except Exception as exc:
                logger.debug("JsHookPool close: %s", exc)
        self._all.clear()
        self._started = False

    @asynccontextmanager
    async def acquire(self, timeout: float = 30.0):
        if not self._started or self._available is None:
            raise RuntimeError("JsHookPool not started")
        client = await asyncio.wait_for(self._available.get(), timeout=timeout)
        try:
            if client._proc is None or client._proc.returncode is not None:
                logger.info("JsHookPool: dead slot, restarting")
                try:
                    await client.close()
                except Exception:
                    pass
                from agents.jshook_client import JsHookMcpClient
                client = JsHookMcpClient(profile=self._profile)
                await client.start()
                for domain in self._AUTO_DOMAINS:
                    try:
                        await client.activate_domain(domain)
                    except Exception:
                        pass
                self._all.append(client)
            yield client
        finally:
            await self._available.put(client)

    @property
    def available(self) -> bool:
        return self._started and bool(self._all)


class PlaywrightPool:
    """Reusable Chromium browsers via patchright (or playwright fallback)."""

    def __init__(self, size: int = 1):
        self._size = size
        self._sem = asyncio.Semaphore(max(1, size))
        self._pw = None
        self._browsers: list = []
        self._started = False

    async def start(self) -> None:
        if self._size <= 0:
            logger.info("PlaywrightPool disabled (size=0)")
            return
        try:
            from patchright.async_api import async_playwright
        except ImportError:
            try:
                from playwright.async_api import async_playwright
                logger.warning("patchright missing, using playwright (no stealth)")
            except ImportError:
                logger.warning("Neither patchright nor playwright available; PlaywrightPool disabled")
                return
        try:
            self._pw = await async_playwright().start()
            for _ in range(self._size):
                browser = await self._pw.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                self._browsers.append(browser)
            self._started = True
            logger.info("PlaywrightPool started: %d browsers", len(self._browsers))
        except Exception as exc:
            logger.warning("PlaywrightPool start failed: %s", exc)
            await self._cleanup()

    async def _cleanup(self) -> None:
        for b in self._browsers:
            try:
                await b.close()
            except Exception:
                pass
        self._browsers.clear()
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None

    async def stop(self) -> None:
        await self._cleanup()
        self._started = False

    @asynccontextmanager
    async def new_context(self, **context_kwargs):
        if not self._started or not self._browsers:
            raise RuntimeError("PlaywrightPool not started")
        async with self._sem:
            browser = self._browsers.pop(0)
            try:
                ctx = await browser.new_context(**context_kwargs)
                try:
                    yield ctx
                finally:
                    try:
                        await ctx.close()
                    except Exception:
                        pass
            finally:
                self._browsers.append(browser)

    @property
    def available(self) -> bool:
        return self._started and bool(self._browsers)

# ── Module-level registry (set by main.py lifespan) ────────────
# Allows non-request-scoped modules (e.g. agents.web_agent) to access pools
# without depending on FastAPI app state.
JSHOOK_POOL: "JsHookPool | None" = None
PLAYWRIGHT_POOL: "PlaywrightPool | None" = None


def get_jshook_pool() -> "JsHookPool | None":
    return JSHOOK_POOL


def get_playwright_pool() -> "PlaywrightPool | None":
    return PLAYWRIGHT_POOL
